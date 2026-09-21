"""Pipeline Orchestrator: 9 observable stages for daily P&L processing."""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    stage_name: str
    status: str  # SUCCESS, WARNING, FAIL
    row_counts: Dict[str, int] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    dataframes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    per_stage: List[StageResult] = field(default_factory=list)
    all_passed: bool = False
    daily_summary_df: Any = None
    strategy_runs_df: Any = None
    charges_df: Any = None
    equity_curve_append_df: Any = None
    report_ready: bool = False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class DailyPipelineOrchestrator:
    """9-stage daily P&L pipeline orchestrator."""

    def __init__(
        self,
        db_engine=None,
        session_factory=None,
        gemini_api_key: Optional[str] = None,
        dhan_client_id: Optional[str] = None,
        dhan_access_token: Optional[str] = None,
    ):
        self.db_engine = db_engine
        self.session_factory = session_factory
        self.gemini_api_key = gemini_api_key
        self.dhan_client_id = dhan_client_id
        self.dhan_access_token = dhan_access_token

        # Lazy-create helper instances
        from .market_knowledge import MarketKnowledge
        from .trade_matcher import TradeMatcher
        from .cost_calculator import FOCostCalculator
        from .margin_calculator import SEBIMarginCalculator

        self.market_knowledge = MarketKnowledge(session_or_engine=db_engine)
        self.trade_matcher = TradeMatcher(market_knowledge=self.market_knowledge)
        self.cost_calculator = FOCostCalculator()
        self.margin_calculator = SEBIMarginCalculator(market_knowledge=self.market_knowledge)

        # Gemini parser (optional)
        self.gemini_parser = None
        try:
            from .gemini_parser import GeminiScreenshotParser
            self.gemini_parser = GeminiScreenshotParser(api_key=gemini_api_key)
        except Exception:
            pass

        # Dhan provider (optional)
        self.dhan_provider = None
        try:
            from .dhan_integration import DhanDataProvider
            self.dhan_provider = DhanDataProvider(
                client_id=dhan_client_id, access_token=dhan_access_token,
            )
        except Exception:
            pass

    # ======================================================================
    # Stage 1: Ingest sources
    # ======================================================================
    def stage_1_ingest_sources(
        self,
        upload_paths: Optional[List[str]] = None,
        manual_csv_df: Optional[pd.DataFrame] = None,
        contract_note_realized_override: Optional[Dict[str, float]] = None,
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            files_ingested = 0
            duplicates_skipped = 0
            raw_rows: List[Dict[str, Any]] = []

            paths = upload_paths or []
            for fpath in paths:
                sha = self._sha256_file(fpath)
                # Dedupe check
                if self.session_factory is not None:
                    try:
                        from .db.schema import RawSourceFile
                        sess = self.session_factory()
                        try:
                            existing = sess.query(RawSourceFile).filter(
                                RawSourceFile.sha256_hash == sha,
                            ).first()
                            if existing is not None:
                                duplicates_skipped += 1
                                continue
                        finally:
                            sess.close()
                    except Exception:
                        pass

                source_type = self._classify_source_type(fpath)
                raw_rows.append({
                    "file_path": fpath,
                    "sha256_hash": sha,
                    "source_type": source_type,
                    "upload_filename": os.path.basename(fpath),
                })
                files_ingested += 1

            if manual_csv_df is not None:
                raw_rows.append({
                    "file_path": None,
                    "sha256_hash": None,
                    "source_type": "MANUAL_CSV",
                    "upload_filename": "manual_csv",
                    "manual_csv_df": manual_csv_df,
                })
                files_ingested += 1

            if contract_note_realized_override is not None:
                raw_rows.append({
                    "file_path": None,
                    "sha256_hash": None,
                    "source_type": "CONTRACT_NOTE_OVERRIDE",
                    "upload_filename": "contract_note_override",
                    "contract_note_charges": contract_note_realized_override,
                })

            raw_sources_df = pd.DataFrame(raw_rows) if raw_rows else pd.DataFrame()
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_1_ingest_sources",
                status="SUCCESS",
                row_counts={"files_ingested": files_ingested, "duplicates_skipped": duplicates_skipped},
                elapsed_ms=elapsed,
                dataframes={"raw_sources_df": raw_sources_df},
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_1_ingest_sources",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Stage 2: Gemini multimodal parse
    # ======================================================================
    def stage_2_gemini_multimodal_parse(
        self,
        raw_sources: Any,
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            strategy_cards: List[Dict[str, Any]] = []
            kite_positions: List[Dict[str, Any]] = []
            contract_note_charges: Optional[Dict[str, float]] = None
            warnings_list: List[str] = []

            if isinstance(raw_sources, pd.DataFrame):
                rows = raw_sources.to_dict("records")
            elif isinstance(raw_sources, list):
                rows = raw_sources
            else:
                rows = []

            for row in rows:
                src_type = row.get("source_type", "")
                if src_type == "MANUAL_CSV":
                    csv_df = row.get("manual_csv_df")
                    if csv_df is not None:
                        strategy_cards.extend(csv_df.to_dict("records"))
                    continue
                if src_type == "CONTRACT_NOTE_OVERRIDE":
                    contract_note_charges = row.get("contract_note_charges")
                    continue
                fpath = row.get("file_path")
                if fpath is None:
                    continue
                if self.gemini_parser is None:
                    warnings_list.append(
                        "GeminiScreenshotParser unavailable. Use Manual CSV fallback."
                    )
                    continue
                try:
                    parsed = self.gemini_parser.parse_image(fpath)
                    cards = parsed.get("strategy_cards", [])
                    strategy_cards.extend(cards)
                    kpos = parsed.get("kite_positions", [])
                    kite_positions.extend(kpos)
                    cn = parsed.get("contract_note_charges")
                    if cn is not None:
                        contract_note_charges = cn
                except Exception as parse_err:
                    err_name = type(parse_err).__name__
                    if err_name == "DependenciesMissingError":
                        warnings_list.append(
                            "Gemini dependencies missing. Use Manual CSV fallback."
                        )
                    else:
                        warnings_list.append(f"Parse error for {fpath}: {parse_err}")

            strategy_cards_df = pd.DataFrame(strategy_cards) if strategy_cards else pd.DataFrame()
            kite_positions_df = pd.DataFrame(kite_positions) if kite_positions else pd.DataFrame()

            status = "WARNING" if warnings_list else "SUCCESS"
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_2_gemini_multimodal_parse",
                status=status,
                row_counts={
                    "strategy_cards": len(strategy_cards),
                    "kite_positions": len(kite_positions),
                },
                elapsed_ms=elapsed,
                warnings=warnings_list,
                dataframes={
                    "strategy_cards_df": strategy_cards_df,
                    "kite_positions_df": kite_positions_df,
                    "contract_note_charges": contract_note_charges,
                },
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_2_gemini_multimodal_parse",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Stage 3: Review staging (mandatory checkpoint)
    # ======================================================================
    def stage_3_review_staging(
        self,
        parse_result: StageResult,
        operator_edits_df: Optional[pd.DataFrame] = None,
        operator_approve_flag: bool = False,
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            if not operator_approve_flag:
                elapsed = (time.perf_counter() - t0) * 1000.0
                return StageResult(
                    stage_name="stage_3_review_staging",
                    status="WARNING",
                    elapsed_ms=elapsed,
                    warnings=[
                        "Operator review required. Set operator_approve_flag=True "
                        "after reviewing staged data."
                    ],
                )

            # Merge operator edits with parsed data
            dfs = dict(parse_result.dataframes)
            if operator_edits_df is not None and not operator_edits_df.empty:
                strategy_cards_df = dfs.get("strategy_cards_df", pd.DataFrame())
                if not strategy_cards_df.empty:
                    # Overlay edits by index or strategy_run_id
                    for col in operator_edits_df.columns:
                        if col in strategy_cards_df.columns:
                            strategy_cards_df[col] = operator_edits_df[col]
                    dfs["strategy_cards_df"] = strategy_cards_df

            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_3_review_staging",
                status="SUCCESS",
                elapsed_ms=elapsed,
                dataframes=dfs,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_3_review_staging",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Stage 4: Classify symbols
    # ======================================================================
    def stage_4_classify_symbols(
        self,
        approved_dfs: Dict[str, Any],
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            from .symbol_parser import parse_indian_symbol, SymbolParseError

            trade_exec_df = approved_dfs.get("trade_executions_df")
            if trade_exec_df is None:
                trade_exec_df = approved_dfs.get("strategy_cards_df", pd.DataFrame())

            if trade_exec_df.empty:
                elapsed = (time.perf_counter() - t0) * 1000.0
                return StageResult(
                    stage_name="stage_4_classify_symbols",
                    status="SUCCESS",
                    row_counts={"trade_executions": 0},
                    elapsed_ms=elapsed,
                    dataframes={"trade_executions_df": trade_exec_df},
                )

            warns: List[str] = []
            segments: List[str] = []
            lot_sizes: List[Optional[int]] = []
            exchanges: List[Optional[str]] = []
            underlyings: List[Optional[str]] = []
            option_types: List[Optional[str]] = []

            sym_col = None
            for candidate in ["vendor_symbol", "symbol", "instrument_symbol", "Instrument"]:
                if candidate in trade_exec_df.columns:
                    sym_col = candidate
                    break

            if sym_col is None:
                # No symbol column found, add empty classification columns
                trade_exec_df = trade_exec_df.copy()
                trade_exec_df["segment"] = "UNKNOWN"
                trade_exec_df["lot_size"] = 0
                trade_exec_df["exchange"] = None
                trade_exec_df["underlying"] = None
                trade_exec_df["option_type"] = None
                elapsed = (time.perf_counter() - t0) * 1000.0
                return StageResult(
                    stage_name="stage_4_classify_symbols",
                    status="WARNING",
                    row_counts={"trade_executions": len(trade_exec_df)},
                    elapsed_ms=elapsed,
                    warnings=["No symbol column found in trade executions"],
                    dataframes={"trade_executions_df": trade_exec_df},
                )

            for _, row in trade_exec_df.iterrows():
                sym = str(row[sym_col]) if pd.notna(row[sym_col]) else ""
                seg = self.market_knowledge.get_segment_for_symbol(sym)
                segments.append(seg)
                try:
                    parsed = parse_indian_symbol(sym, self.market_knowledge)
                    underlyings.append(parsed.get("underlying"))
                    option_types.append(parsed.get("option_type"))
                    lot = self.market_knowledge.get_lot_size(
                        parsed.get("underlying", ""),
                    )
                    lot_sizes.append(lot)
                    exchanges.append(
                        self.market_knowledge.get_exchange(
                            parsed.get("underlying", ""),
                        )
                    )
                except SymbolParseError as e:
                    underlyings.append(None)
                    option_types.append(None)
                    lot_sizes.append(None)
                    exchanges.append(None)
                    warns.append(f"Symbol parse warning: {sym}: {e}")

            trade_exec_df = trade_exec_df.copy()
            trade_exec_df["segment"] = segments
            trade_exec_df["lot_size_lookup"] = lot_sizes
            trade_exec_df["exchange"] = exchanges
            trade_exec_df["underlying"] = underlyings
            trade_exec_df["option_type"] = option_types

            status = "WARNING" if warns else "SUCCESS"
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_4_classify_symbols",
                status=status,
                row_counts={"trade_executions": len(trade_exec_df)},
                elapsed_ms=elapsed,
                warnings=warns,
                dataframes={"trade_executions_df": trade_exec_df},
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_4_classify_symbols",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Stage 5: FIFO match
    # ======================================================================
    def stage_5_fifo_match(
        self,
        trade_executions_df: pd.DataFrame,
        strategy_run_ids: Optional[List[int]] = None,
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            if trade_executions_df.empty:
                elapsed = (time.perf_counter() - t0) * 1000.0
                return StageResult(
                    stage_name="stage_5_fifo_match",
                    status="SUCCESS",
                    row_counts={"matched": 0, "open_legs": 0},
                    elapsed_ms=elapsed,
                    dataframes={
                        "matched_df": pd.DataFrame(),
                        "open_legs_df": pd.DataFrame(),
                    },
                )

            normalized = self.trade_matcher.parse_and_normalize_executions(
                trade_executions_df,
            )
            matched_df, open_legs_df = self.trade_matcher.match_trades_fifo(normalized)

            warns: List[str] = []
            if not open_legs_df.empty:
                warns.append(
                    f"{len(open_legs_df)} open legs remain unmatched"
                )

            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_5_fifo_match",
                status="SUCCESS",
                row_counts={
                    "matched": len(matched_df),
                    "open_legs": len(open_legs_df),
                },
                elapsed_ms=elapsed,
                warnings=warns,
                dataframes={
                    "matched_df": matched_df,
                    "open_legs_df": open_legs_df,
                },
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_5_fifo_match",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Stage 6: Compute charges
    # ======================================================================
    def stage_6_compute_charges(
        self,
        matched_df: pd.DataFrame,
        strategies_df: pd.DataFrame,
        contract_note_charges: Optional[Dict[str, float]] = None,
        schedule: Optional[Dict[str, Any]] = None,
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            if schedule is not None:
                self.cost_calculator = __import__(
                    "src.cost_calculator", fromlist=["FOCostCalculator"]
                ).FOCostCalculator(schedule=schedule)

            charges_rows: List[Dict[str, Any]] = []
            warns: List[str] = []

            if contract_note_charges is not None:
                # REALIZED mode: allocate aggregate charges to strategies
                mode = "REALIZED"
                from .cost_calculator import allocate_charges_to_strategies
                strat_rows = strategies_df.to_dict("records") if not strategies_df.empty else []
                if strat_rows:
                    try:
                        allocated = allocate_charges_to_strategies(
                            strat_rows, contract_note_charges,
                        )
                        for srid, cb in allocated.items():
                            charges_rows.append(cb.model_dump())
                    except Exception as alloc_err:
                        warns.append(f"Charge allocation error: {alloc_err}")
            else:
                # FORMULA mode: compute per matched leg
                mode = "FORMULA"
                if not matched_df.empty:
                    for _, row in matched_df.iterrows():
                        buy_price = float(row.get("entry_price", 0))
                        sell_price = float(row.get("exit_price", 0))
                        side = row.get("side", "LONG")
                        if side == "SHORT":
                            buy_price, sell_price = sell_price, buy_price
                        lot_size = int(row.get("lot_size", 0)) or int(row.get("quantity", 1))
                        lots = int(row.get("lots", 1))
                        seg = str(row.get("segment", ""))
                        exchange = "BSE" if seg == "SENSEX" else "NSE"
                        result = self.cost_calculator.calculate_option_roundtrip_costs_formula(
                            buy_price=buy_price,
                            sell_price=sell_price,
                            lot_size=lot_size,
                            lots=lots,
                            exchange=exchange,
                        )
                        charges = result["charges"]
                        charges["strategy_run_id"] = row.get("strategy_run_id")
                        charges["mode"] = mode
                        charges_rows.append(charges)

            charges_df = pd.DataFrame(charges_rows) if charges_rows else pd.DataFrame()
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_6_compute_charges",
                status="SUCCESS",
                row_counts={"charges_rows": len(charges_rows)},
                elapsed_ms=elapsed,
                warnings=warns,
                dataframes={"charges_df": charges_df},
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_6_compute_charges",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Stage 7: Compute summary
    # ======================================================================
    def stage_7_compute_summary(
        self,
        strategies_df: pd.DataFrame,
        matched_df: pd.DataFrame,
        charges_df: pd.DataFrame,
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            from .strategy_aggregator import (
                aggregate_strategy_runs,
                compute_portfolio_day_summary,
            )

            # Merge charges into strategies_df
            strat = strategies_df.copy()
            if not charges_df.empty and "strategy_run_id" in charges_df.columns and "total_charges" in charges_df.columns:
                charges_agg = (
                    charges_df.groupby("strategy_run_id", as_index=False)["total_charges"]
                    .sum()
                    .rename(columns={"total_charges": "allocated_charges_total"})
                )
                if "allocated_charges_total" in strat.columns:
                    strat = strat.drop(columns=["allocated_charges_total"])
                strat = strat.merge(charges_agg, on="strategy_run_id", how="left")
                strat["allocated_charges_total"] = strat["allocated_charges_total"].fillna(0.0)
            elif "allocated_charges_total" not in strat.columns:
                strat["allocated_charges_total"] = 0.0

            strategy_runs_df = aggregate_strategy_runs(matched_df, strat)
            daily_summary_dict = compute_portfolio_day_summary(strategy_runs_df)

            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_7_compute_summary",
                status="SUCCESS",
                row_counts={"strategy_runs": len(strategy_runs_df)},
                elapsed_ms=elapsed,
                dataframes={
                    "strategy_runs_df": strategy_runs_df,
                    "daily_summary_dict": daily_summary_dict,
                },
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_7_compute_summary",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Stage 8: Persist — SQLite (local buffer) + Supabase (primary cloud store)
    # ======================================================================
    def stage_8_persist_sqlite(
        self,
        session_or_engine,
        tables_dict: Dict[str, Any],
        report_date: date,
    ) -> StageResult:
        t0 = time.perf_counter()
        supabase_result: Dict[str, Any] = {}
        sqlite_errors: List[str] = []
        warns: List[str] = []

        # ── Supabase dual-write (primary) ──────────────────────────────────
        try:
            from .supabase_store import get_supabase_store
            sb = get_supabase_store()
            if sb.is_connected:
                strategy_runs_df = tables_dict.get("strategy_runs_df")
                daily_summary_dict = tables_dict.get("daily_summary_dict")
                charges_df = tables_dict.get("charges_df")

                supabase_result = sb.upsert_daily_batch(
                    report_date=report_date,
                    daily_summary=daily_summary_dict if isinstance(daily_summary_dict, dict) else None,
                    strategy_runs=(
                        strategy_runs_df.to_dict("records")
                        if strategy_runs_df is not None and not strategy_runs_df.empty
                        else None
                    ),
                    charges=(
                        charges_df.to_dict("records")
                        if charges_df is not None and not charges_df.empty
                        else None
                    ),
                    trade_executions=(
                        tables_dict.get("matched_trades_df", pd.DataFrame()).to_dict("records")
                        if tables_dict.get("matched_trades_df") is not None and not tables_dict.get("matched_trades_df", pd.DataFrame()).empty
                        else None
                    ),
                )
            else:
                warns.append(
                    "Supabase not configured — set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY "
                    "for cloud persistence. Continuing with SQLite-only."
                )
        except Exception as sb_exc:
            warns.append(f"Supabase write warning (non-blocking): {sb_exc}")

        # ── SQLite local persist (buffer / fallback) ───────────────────────
        try:
            if session_or_engine is None:
                elapsed = (time.perf_counter() - t0) * 1000.0
                return StageResult(
                    stage_name="stage_8_persist_sqlite",
                    status="WARNING",
                    elapsed_ms=elapsed,
                    warnings=warns + ["No database engine provided; SQLite persistence skipped."],
                    dataframes={"supabase_result": supabase_result},
                )

            from sqlalchemy.orm import sessionmaker as sa_sessionmaker, Session
            from sqlalchemy.engine import Engine
            from .db.schema import (
                StrategyRun, DailySummary, ChargesBreakdown as CBModel,
                TradeExecution,
            )

            if isinstance(session_or_engine, Engine):
                SessionLocal = sa_sessionmaker(
                    bind=session_or_engine, autoflush=False,
                    autocommit=False, future=True,
                )
            else:
                SessionLocal = session_or_engine

            row_counts: Dict[str, int] = {}
            sess = SessionLocal()
            try:
                # Strategy runs
                strat_runs_df = tables_dict.get("strategy_runs_df")
                if strat_runs_df is not None and not strat_runs_df.empty:
                    for _, row in strat_runs_df.iterrows():
                        sr = StrategyRun(
                            strategy_run_uuid=str(uuid.uuid4()),
                            report_date=report_date,
                            strategy_name=str(row.get("strategy_name", "unknown")),
                            deployment_status=str(row.get("deployment_status", "EXITED")),
                            multiplier_x=int(row.get("multiplier", 1)),
                            counter_int=int(row.get("counter", 0)) if pd.notna(row.get("counter")) else None,
                            capital_deployed_allocated=float(row.get("capital_deployed_allocated", 0)),
                            booked_gross_pnl=float(row.get("booked_gross_pnl", 0)),
                            allocated_charges_total=float(row.get("allocated_charges_total", 0)),
                            net_pnl=float(row.get("net_pnl", 0)),
                            net_roi_pct=float(row.get("net_roi_pct", 0)) if pd.notna(row.get("net_roi_pct")) else None,
                            underlying_segment=str(row.get("underlying_segment", "")) if pd.notna(row.get("underlying_segment")) else None,
                        )
                        sess.add(sr)
                    row_counts["strategy_runs"] = len(strat_runs_df)

                # Daily summary
                summary_dict = tables_dict.get("daily_summary_dict")
                if summary_dict is not None:
                    ds = DailySummary(
                        report_date=report_date,
                        total_trades_executed=int(summary_dict.get("total_trades_executed", 0)),
                        total_strategy_runs=int(summary_dict.get("total_strategy_runs", 0)),
                        win_count=int(summary_dict.get("win_count", 0)),
                        loss_count=int(summary_dict.get("loss_count", 0)),
                        total_capital_deployed_peak=float(summary_dict.get("peak_capital_deployed", 0)),
                        total_gross_pnl=float(summary_dict.get("total_gross_pnl", 0)),
                        total_transaction_cost_drag=float(summary_dict.get("total_allocated_charges", 0)),
                        total_net_pnl=float(summary_dict.get("total_net_pnl", 0)),
                        portfolio_day_net_roi_pct=float(summary_dict.get("portfolio_day_roi_pct", 0)) if not pd.isna(summary_dict.get("portfolio_day_roi_pct", 0)) else None,
                    )
                    sess.add(ds)
                    row_counts["daily_summaries"] = 1

                # Charges
                charges_df = tables_dict.get("charges_df")
                if charges_df is not None and not charges_df.empty:
                    for _, row in charges_df.iterrows():
                        cb = CBModel(
                            strategy_run_id=int(row.get("strategy_run_id", 0)),
                            report_date=report_date,
                            charge_source=str(row.get("charge_source", "FORMULA_COMPUTED")),
                            brokerage=float(row.get("brokerage", 0)),
                            exchange_turnover_fee=float(row.get("exchange_turnover_fee", 0)),
                            stt=float(row.get("stt", 0)),
                            sebi_turnover_charges=float(row.get("sebi_turnover_charges", 0)),
                            stamp_duty=float(row.get("stamp_duty", 0)),
                            gst=float(row.get("gst", 0)),
                            total_charges=float(row.get("total_charges", 0)),
                        )
                        sess.add(cb)
                    row_counts["charges_breakdown"] = len(charges_df)

                sess.commit()
            except Exception as db_err:
                sess.rollback()
                sqlite_errors.append(f"SQLite persist error (ROLLBACK): {db_err}")
            finally:
                sess.close()

        except Exception as exc:
            sqlite_errors.append(str(exc))

        elapsed = (time.perf_counter() - t0) * 1000.0
        all_errors = sqlite_errors
        status = "FAIL" if all_errors else (
            "WARNING" if warns else "SUCCESS"
        )
        combined_counts: Dict[str, int] = {}
        try:
            combined_counts.update(row_counts)
        except NameError:
            pass
        combined_counts.update({k: v for k, v in supabase_result.items() if isinstance(v, int)})

        return StageResult(
            stage_name="stage_8_persist_sqlite",
            status=status,
            row_counts=combined_counts,
            elapsed_ms=elapsed,
            warnings=warns,
            errors=all_errors,
            dataframes={"supabase_result": supabase_result},
        )

    # ======================================================================
    # Stage 9: Rebuild equity curve
    # ======================================================================
    def stage_9_rebuild_equity_curve(
        self,
        session_or_engine,
        report_date: date,
        extend_from_date: Optional[date] = None,
    ) -> StageResult:
        t0 = time.perf_counter()
        try:
            if session_or_engine is None:
                elapsed = (time.perf_counter() - t0) * 1000.0
                return StageResult(
                    stage_name="stage_9_rebuild_equity_curve",
                    status="WARNING",
                    elapsed_ms=elapsed,
                    warnings=["No database engine provided; equity curve rebuild skipped."],
                )

            from sqlalchemy.orm import sessionmaker as sa_sessionmaker
            from sqlalchemy.engine import Engine
            from .db.schema import DailySummary, EquityCurve

            if isinstance(session_or_engine, Engine):
                SessionLocal = sa_sessionmaker(
                    bind=session_or_engine, autoflush=False,
                    autocommit=False, future=True,
                )
            else:
                SessionLocal = session_or_engine

            sess = SessionLocal()
            try:
                start_date = extend_from_date or report_date
                summaries = (
                    sess.query(DailySummary)
                    .filter(DailySummary.report_date >= start_date)
                    .order_by(DailySummary.report_date.asc())
                    .all()
                )

                # Get prior cumulative from day before start_date
                prior_cumulative = 0.0
                prior_peak = 0.0
                prior_row = (
                    sess.query(EquityCurve)
                    .filter(EquityCurve.report_date < start_date)
                    .order_by(EquityCurve.report_date.desc())
                    .first()
                )
                if prior_row is not None:
                    prior_cumulative = float(prior_row.cumulative_net_pnl)
                    prior_peak = float(prior_row.peak_equity)

                # Also gather win counts for rolling 30d
                thirty_days_ago = start_date - timedelta(days=30)
                recent_summaries = (
                    sess.query(DailySummary)
                    .filter(DailySummary.report_date >= thirty_days_ago)
                    .order_by(DailySummary.report_date.asc())
                    .all()
                )
                # Build lookups
                win_total_30d: Dict[date, int] = {}
                loss_total_30d: Dict[date, int] = {}
                for s in recent_summaries:
                    win_total_30d[s.report_date] = s.win_count
                    loss_total_30d[s.report_date] = s.loss_count

                cumulative = prior_cumulative
                peak_equity = prior_peak
                rows_upserted = 0
                equity_rows: List[Dict[str, Any]] = []

                for summary in summaries:
                    daily_net = float(summary.total_net_pnl)
                    cumulative += daily_net
                    if cumulative > peak_equity:
                        peak_equity = cumulative
                    drawdown_pct = 0.0
                    if peak_equity > 0:
                        drawdown_pct = ((peak_equity - cumulative) / peak_equity) * 100.0

                    # Rolling 30d win rate
                    d30_start = summary.report_date - timedelta(days=30)
                    wins_30 = sum(
                        v for k, v in win_total_30d.items()
                        if d30_start <= k <= summary.report_date
                    )
                    losses_30 = sum(
                        v for k, v in loss_total_30d.items()
                        if d30_start <= k <= summary.report_date
                    )
                    total_30 = wins_30 + losses_30
                    win_rate_30d = (wins_30 / total_30 * 100.0) if total_30 > 0 else None

                    # Upsert
                    existing = (
                        sess.query(EquityCurve)
                        .filter(EquityCurve.report_date == summary.report_date)
                        .first()
                    )
                    if existing is not None:
                        existing.daily_net_pnl = daily_net
                        existing.cumulative_net_pnl = cumulative
                        existing.peak_equity = peak_equity
                        existing.drawdown_pct = drawdown_pct
                        existing.running_win_rate_30d = win_rate_30d
                        existing.updated_at = datetime.utcnow()
                    else:
                        ec = EquityCurve(
                            report_date=summary.report_date,
                            daily_net_pnl=daily_net,
                            cumulative_net_pnl=cumulative,
                            peak_equity=peak_equity,
                            drawdown_pct=drawdown_pct,
                            running_win_rate_30d=win_rate_30d,
                        )
                        sess.add(ec)
                    equity_rows.append({
                        "report_date": summary.report_date,
                        "daily_net_pnl": daily_net,
                        "cumulative_net_pnl": cumulative,
                        "peak_equity": peak_equity,
                        "drawdown_pct": drawdown_pct,
                        "running_win_rate_30d": win_rate_30d,
                    })
                    rows_upserted += 1

                sess.commit()
                # Push to Supabase
                try:
                    from .supabase_store import get_supabase_store
                    sb = get_supabase_store()
                    if sb.is_connected and equity_rows:
                        sb.upsert_equity_curve(equity_rows)
                except Exception as sb_exc:
                    # non-blocking
                    pass
            except Exception as db_err:
                sess.rollback()
                elapsed = (time.perf_counter() - t0) * 1000.0
                return StageResult(
                    stage_name="stage_9_rebuild_equity_curve",
                    status="FAIL",
                    elapsed_ms=elapsed,
                    errors=[f"Equity curve rebuild error: {db_err}"],
                )
            finally:
                sess.close()

            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_9_rebuild_equity_curve",
                status="SUCCESS",
                row_counts={"equity_curve_rows_upserted": rows_upserted},
                elapsed_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return StageResult(
                stage_name="stage_9_rebuild_equity_curve",
                status="FAIL",
                elapsed_ms=elapsed,
                errors=[str(exc)],
            )

    # ======================================================================
    # Main pipeline methods
    # ======================================================================
    def run_entire_pipeline(
        self,
        report_date: date,
        uploads: Optional[List[str]] = None,
        manual_csv_df: Optional[pd.DataFrame] = None,
        contract_note_override: Optional[Dict[str, float]] = None,
        operator_approve_flag: bool = False,
    ) -> PipelineResult:
        result = PipelineResult()

        # Stage 1
        s1 = self.stage_1_ingest_sources(
            upload_paths=uploads,
            manual_csv_df=manual_csv_df,
            contract_note_realized_override=contract_note_override,
        )
        result.per_stage.append(s1)
        if s1.status == "FAIL":
            return result

        # Stage 2
        raw_sources = s1.dataframes.get("raw_sources_df", pd.DataFrame())
        s2 = self.stage_2_gemini_multimodal_parse(raw_sources)
        result.per_stage.append(s2)
        if s2.status == "FAIL":
            return result

        # Stage 3
        s3 = self.stage_3_review_staging(
            s2, operator_approve_flag=operator_approve_flag,
        )
        result.per_stage.append(s3)
        if s3.status == "FAIL" or (s3.status == "WARNING" and not operator_approve_flag):
            return result

        # Stage 4
        s4 = self.stage_4_classify_symbols(s3.dataframes)
        result.per_stage.append(s4)
        if s4.status == "FAIL":
            return result

        # Stage 5
        trade_exec_df = s4.dataframes.get("trade_executions_df", pd.DataFrame())
        s5 = self.stage_5_fifo_match(trade_exec_df)
        result.per_stage.append(s5)
        if s5.status == "FAIL":
            return result

        # Stage 6
        matched_df = s5.dataframes.get("matched_df", pd.DataFrame())
        # Build strategies_df from stage 3/4 data
        strategies_df = s3.dataframes.get("strategy_cards_df", pd.DataFrame())
        cn_charges = s2.dataframes.get("contract_note_charges")
        if contract_note_override is not None:
            cn_charges = contract_note_override
        s6 = self.stage_6_compute_charges(
            matched_df, strategies_df, contract_note_charges=cn_charges,
        )
        result.per_stage.append(s6)
        if s6.status == "FAIL":
            return result

        # Stage 7
        charges_df = s6.dataframes.get("charges_df", pd.DataFrame())
        s7 = self.stage_7_compute_summary(strategies_df, matched_df, charges_df)
        result.per_stage.append(s7)
        if s7.status == "FAIL":
            return result

        result.strategy_runs_df = s7.dataframes.get("strategy_runs_df")
        result.charges_df = charges_df
        result.daily_summary_df = s7.dataframes.get("daily_summary_dict")

        # Stage 8
        engine = self.db_engine
        session_factory = self.session_factory
        tables = {
            "strategy_runs_df": result.strategy_runs_df,
            "daily_summary_dict": result.daily_summary_df,
            "charges_df": result.charges_df,
        }
        s8 = self.stage_8_persist_sqlite(
            session_factory or engine, tables, report_date,
        )
        result.per_stage.append(s8)

        # Stage 9
        s9 = self.stage_9_rebuild_equity_curve(
            session_factory or engine, report_date,
        )
        result.per_stage.append(s9)

        result.all_passed = all(
            s.status in ("SUCCESS", "WARNING") for s in result.per_stage
        )
        result.report_ready = result.all_passed
        return result

    def rerun_historical(
        self,
        from_date: date,
        to_date: date,
        session_or_engine=None,
    ) -> PipelineResult:
        """Re-run stages 4-9 for each date in range (historical rebuild)."""
        result = PipelineResult()
        engine = session_or_engine or self.db_engine

        if engine is None:
            result.per_stage.append(StageResult(
                stage_name="rerun_historical",
                status="WARNING",
                warnings=["No database engine provided; historical rerun skipped."],
            ))
            return result

        from sqlalchemy.orm import sessionmaker as sa_sessionmaker
        from sqlalchemy.engine import Engine
        from .db.schema import DailySummary

        if isinstance(engine, Engine):
            SessionLocal = sa_sessionmaker(
                bind=engine, autoflush=False, autocommit=False, future=True,
            )
        else:
            SessionLocal = engine

        current = from_date
        while current <= to_date:
            # For historical rebuild, query existing data and reprocess stages 7-9
            try:
                sess = SessionLocal()
                try:
                    summary = sess.query(DailySummary).filter(
                        DailySummary.report_date == current,
                    ).first()
                    if summary is not None:
                        # Rebuild equity curve for this date
                        s9 = self.stage_9_rebuild_equity_curve(
                            SessionLocal, current, extend_from_date=from_date,
                        )
                        result.per_stage.append(s9)
                finally:
                    sess.close()
            except Exception as exc:
                result.per_stage.append(StageResult(
                    stage_name=f"rerun_{current.isoformat()}",
                    status="FAIL",
                    errors=[str(exc)],
                ))
            current += timedelta(days=1)

        result.all_passed = all(
            s.status in ("SUCCESS", "WARNING") for s in result.per_stage
        )
        return result

    # ======================================================================
    # Helpers
    # ======================================================================
    @staticmethod
    def _sha256_file(filepath: str) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _classify_source_type(filepath: str) -> str:
        fname = os.path.basename(filepath).lower()
        if "tradetron" in fname or "strategy" in fname:
            return "TRADETRON_STRATEGY_CARD"
        if "kite" in fname or "position" in fname:
            return "ZERODHA_KITE_POSITIONS"
        if "contract" in fname or "charge" in fname:
            return "ZERODHA_VIRTUAL_CONTRACT_NOTE"
        if fname.endswith(".csv"):
            return "MANUAL_CSV"
        return "UNKNOWN"
