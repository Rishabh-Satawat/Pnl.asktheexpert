"""Tests for Pipeline Orchestrator (Task 9) - 4 tests."""
from __future__ import annotations

import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pnl_pipeline import DailyPipelineOrchestrator, StageResult, PipelineResult
from src.db.engine import init_db
from src.db.schema import (
    Base, DailySummary, EquityCurve, StrategyRun,
    ChargesBreakdown as CBModel, TradeExecution,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _make_synthetic_executions(
    report_dt: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create 10 synthetic matched trade pairs across 3 segments.

    Returns (trade_executions_df, strategy_metadata_df).
    Segments: SENSEX (strat 1, 4 trades), BANKNIFTY (strat 2, 3 trades), NIFTY (strat 3, 3 trades).
    """
    base_ts = datetime(report_dt.year, report_dt.month, report_dt.day, 9, 30, 0)
    rows = []
    # Strategy 1 - SENSEX (lot_size=20), 4 round-trips
    sensex_trades = [
        ("SENSEX2692277300CE", 100.0, 120.0),
        ("SENSEX26922077200PE", 80.0, 95.0),
        ("SENSEX26922077400CE", 110.0, 105.0),
        ("SENSEX26922077100PE", 90.0, 115.0),
    ]
    for i, (sym, buy_px, sell_px) in enumerate(sensex_trades):
        ts_buy = base_ts + timedelta(minutes=i * 10)
        ts_sell = ts_buy + timedelta(minutes=5)
        rows.append({
            "vendor_symbol": sym, "side": "BUY", "quantity": 20,
            "execution_price": buy_px, "lot_size": 20,
            "execution_timestamp": ts_buy, "trade_date": report_dt,
            "strategy_run_id": 1, "execution_id": str(uuid.uuid4()),
        })
        rows.append({
            "vendor_symbol": sym, "side": "SELL", "quantity": 20,
            "execution_price": sell_px, "lot_size": 20,
            "execution_timestamp": ts_sell, "trade_date": report_dt,
            "strategy_run_id": 1, "execution_id": str(uuid.uuid4()),
        })

    # Strategy 2 - BANKNIFTY (lot_size=15), 3 round-trips
    bn_trades = [
        ("BANKNIFTY2692252000CE", 200.0, 230.0),
        ("BANKNIFTY2692251500PE", 150.0, 145.0),
        ("BANKNIFTY2692252500CE", 180.0, 210.0),
    ]
    for i, (sym, buy_px, sell_px) in enumerate(bn_trades):
        ts_buy = base_ts + timedelta(minutes=50 + i * 10)
        ts_sell = ts_buy + timedelta(minutes=5)
        rows.append({
            "vendor_symbol": sym, "side": "BUY", "quantity": 15,
            "execution_price": buy_px, "lot_size": 15,
            "execution_timestamp": ts_buy, "trade_date": report_dt,
            "strategy_run_id": 2, "execution_id": str(uuid.uuid4()),
        })
        rows.append({
            "vendor_symbol": sym, "side": "SELL", "quantity": 15,
            "execution_price": sell_px, "lot_size": 15,
            "execution_timestamp": ts_sell, "trade_date": report_dt,
            "strategy_run_id": 2, "execution_id": str(uuid.uuid4()),
        })

    # Strategy 3 - NIFTY (lot_size=25), 3 round-trips
    nifty_trades = [
        ("NIFTY2692224000CE", 300.0, 320.0),
        ("NIFTY2692224500PE", 250.0, 270.0),
        ("NIFTY2692223500CE", 280.0, 310.0),
    ]
    for i, (sym, buy_px, sell_px) in enumerate(nifty_trades):
        ts_buy = base_ts + timedelta(minutes=80 + i * 10)
        ts_sell = ts_buy + timedelta(minutes=5)
        rows.append({
            "vendor_symbol": sym, "side": "BUY", "quantity": 25,
            "execution_price": buy_px, "lot_size": 25,
            "execution_timestamp": ts_buy, "trade_date": report_dt,
            "strategy_run_id": 3, "execution_id": str(uuid.uuid4()),
        })
        rows.append({
            "vendor_symbol": sym, "side": "SELL", "quantity": 25,
            "execution_price": sell_px, "lot_size": 25,
            "execution_timestamp": ts_sell, "trade_date": report_dt,
            "strategy_run_id": 3, "execution_id": str(uuid.uuid4()),
        })

    trade_exec_df = pd.DataFrame(rows)

    strategy_meta_df = pd.DataFrame([
        {
            "strategy_run_id": 1, "strategy_name": "SENSEX Iron Condor",
            "deployment_status": "EXITED", "multiplier": 1, "counter": 1,
            "capital_deployed_allocated": 200000.0,
            "entry_ts": None, "exit_ts": None,
        },
        {
            "strategy_run_id": 2, "strategy_name": "BANKNIFTY Straddle",
            "deployment_status": "EXITED", "multiplier": 1, "counter": 2,
            "capital_deployed_allocated": 150000.0,
            "entry_ts": None, "exit_ts": None,
        },
        {
            "strategy_run_id": 3, "strategy_name": "NIFTY Bull Spread",
            "deployment_status": "EXITED", "multiplier": 1, "counter": 3,
            "capital_deployed_allocated": 180000.0,
            "entry_ts": None, "exit_ts": None,
        },
    ])

    return trade_exec_df, strategy_meta_df


# -----------------------------------------------------------------------
# TR-9.1: Synthetic end-to-end arithmetic
# -----------------------------------------------------------------------

def test_tr_9_1_synthetic_e2e_arithmetic():
    """Inject synthetic data into stages 4-9, verify gross totals and net=gross-charges."""
    report_dt = date(2026, 9, 22)
    trade_exec_df, strategy_meta_df = _make_synthetic_executions(report_dt)

    orch = DailyPipelineOrchestrator()

    # Stage 4: classify symbols
    s4 = orch.stage_4_classify_symbols({"trade_executions_df": trade_exec_df})
    assert s4.status in ("SUCCESS", "WARNING"), f"Stage 4 failed: {s4.errors}"
    classified_df = s4.dataframes["trade_executions_df"]

    # Stage 5: FIFO match
    s5 = orch.stage_5_fifo_match(classified_df)
    assert s5.status == "SUCCESS", f"Stage 5 failed: {s5.errors}"
    matched_df = s5.dataframes["matched_df"]
    assert len(matched_df) == 10, f"Expected 10 matched pairs, got {len(matched_df)}"

    # Verify segment gross totals by arithmetic
    # SENSEX: (120-100)*20 + (95-80)*20 + (105-110)*20 + (115-90)*20
    #       = 400 + 300 + (-100) + 500 = 1100
    sensex_gross = matched_df[matched_df["segment"] == "SENSEX"]["gross_pnl"].sum()
    assert abs(sensex_gross - 1100.0) < 0.01, (
        f"SENSEX gross expected 1100.0, got {sensex_gross}"
    )

    # BANKNIFTY: (230-200)*15 + (145-150)*15 + (210-180)*15
    #          = 450 + (-75) + 450 = 825
    bn_gross = matched_df[matched_df["segment"] == "BANKNIFTY"]["gross_pnl"].sum()
    assert abs(bn_gross - 825.0) < 0.01, (
        f"BANKNIFTY gross expected 825.0, got {bn_gross}"
    )

    # NIFTY: (320-300)*25 + (270-250)*25 + (310-280)*25
    #       = 500 + 500 + 750 = 1750
    nifty_gross = matched_df[matched_df["segment"] == "NIFTY"]["gross_pnl"].sum()
    assert abs(nifty_gross - 1750.0) < 0.01, (
        f"NIFTY gross expected 1750.0, got {nifty_gross}"
    )

    # Stage 6: compute charges (FORMULA mode)
    s6 = orch.stage_6_compute_charges(matched_df, strategy_meta_df)
    assert s6.status == "SUCCESS", f"Stage 6 failed: {s6.errors}"
    charges_df = s6.dataframes["charges_df"]
    assert not charges_df.empty, "Charges DF should not be empty"
    total_charges = float(charges_df["total_charges"].sum())
    assert total_charges > 0, "Total charges must be positive"

    # Stage 7: compute summary
    s7 = orch.stage_7_compute_summary(strategy_meta_df, matched_df, charges_df)
    assert s7.status == "SUCCESS", f"Stage 7 failed: {s7.errors}"
    summary = s7.dataframes["daily_summary_dict"]
    strat_runs_df = s7.dataframes["strategy_runs_df"]

    total_gross = summary["total_gross_pnl"]
    total_net = summary["total_net_pnl"]
    total_alloc_charges = summary["total_allocated_charges"]

    # total_gross should equal sum of segment grosses
    expected_total_gross = 1100.0 + 825.0 + 1750.0  # = 3675.0
    assert abs(total_gross - expected_total_gross) < 0.01, (
        f"Total gross expected {expected_total_gross}, got {total_gross}"
    )

    # Net = Gross - Charges
    assert abs(total_net - (total_gross - total_alloc_charges)) < 0.02, (
        f"Net P&L mismatch: net={total_net}, gross={total_gross}, "
        f"charges={total_alloc_charges}"
    )

    print("[TR-9.1] PASS: Synthetic E2E arithmetic verified")
    print(f"  Total gross: {total_gross:.2f}")
    print(f"  Total charges: {total_alloc_charges:.2f}")
    print(f"  Total net: {total_net:.2f}")


# -----------------------------------------------------------------------
# TR-9.2: Equity rebuild shift
# -----------------------------------------------------------------------

def test_tr_9_2_equity_rebuild_shift():
    """Seed 5 daily summaries, build equity curve, alter Wednesday, verify +500 shift."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = Path(tmpdir) / "test_equity.db"
        engine, SessionLocal = init_db(db_path, create_tables=True, seed=True)

        # Mon-Fri dates (2026-09-21 is Monday)
        dates = [date(2026, 9, 21) + timedelta(days=i) for i in range(5)]
        pnl_values = [1000.0, -500.0, 800.0, 200.0, -300.0]  # Mon-Fri

        # Seed daily summaries
        sess = SessionLocal()
        try:
            for d, pnl in zip(dates, pnl_values):
                ds = DailySummary(
                    report_date=d,
                    total_trades_executed=5,
                    total_strategy_runs=2,
                    win_count=1 if pnl > 0 else 0,
                    loss_count=1 if pnl < 0 else 0,
                    total_capital_deployed_peak=200000.0,
                    total_gross_pnl=pnl + 100.0,
                    total_transaction_cost_drag=100.0,
                    total_net_pnl=pnl,
                )
                sess.add(ds)
            sess.commit()
        finally:
            sess.close()

        # Build initial equity curve
        orch = DailyPipelineOrchestrator(db_engine=engine, session_factory=SessionLocal)
        s9 = orch.stage_9_rebuild_equity_curve(SessionLocal, dates[-1], extend_from_date=dates[0])
        assert s9.status == "SUCCESS", f"Initial equity build failed: {s9.errors}"

        # Read initial equity curve
        sess = SessionLocal()
        try:
            initial_curves = sess.query(EquityCurve).order_by(EquityCurve.report_date).all()
            initial_cumulatives = {ec.report_date: ec.cumulative_net_pnl for ec in initial_curves}
        finally:
            sess.close()

        # Verify initial cumulative: Mon=1000, Tue=500, Wed=1300, Thu=1500, Fri=1200
        expected_initial = {
            dates[0]: 1000.0,
            dates[1]: 500.0,
            dates[2]: 1300.0,
            dates[3]: 1500.0,
            dates[4]: 1200.0,
        }
        for d, exp in expected_initial.items():
            actual = initial_cumulatives.get(d, None)
            assert actual is not None, f"Missing equity curve for {d}"
            assert abs(actual - exp) < 0.01, (
                f"Initial cumulative for {d}: expected {exp}, got {actual}"
            )

        # Alter Wednesday net_pnl by +500 (from 800 to 1300)
        sess = SessionLocal()
        try:
            wed_summary = sess.query(DailySummary).filter(
                DailySummary.report_date == dates[2],
            ).first()
            wed_summary.total_net_pnl = 1300.0
            wed_summary.total_gross_pnl = 1400.0
            sess.commit()
        finally:
            sess.close()

        # Rebuild equity curve from Wednesday onward
        s9b = orch.stage_9_rebuild_equity_curve(
            SessionLocal, dates[-1], extend_from_date=dates[2],
        )
        assert s9b.status == "SUCCESS", f"Rebuild equity failed: {s9b.errors}"

        # Verify shifted cumulative: Wed-Fri should all be +500 vs initial
        sess = SessionLocal()
        try:
            rebuilt_curves = sess.query(EquityCurve).order_by(EquityCurve.report_date).all()
            rebuilt_cumulatives = {ec.report_date: ec.cumulative_net_pnl for ec in rebuilt_curves}
        finally:
            sess.close()

        for d_idx in [2, 3, 4]:  # Wed, Thu, Fri
            d = dates[d_idx]
            old_val = initial_cumulatives[d]
            new_val = rebuilt_cumulatives.get(d, None)
            assert new_val is not None, f"Missing rebuilt equity curve for {d}"
            shift = new_val - old_val
            assert abs(shift - 500.0) < 0.01, (
                f"Equity shift for {d}: expected +500.0, got {shift:.2f} "
                f"(old={old_val:.2f}, new={new_val:.2f})"
            )

        print("[TR-9.2] PASS: Equity rebuild shift verified (+500 on Wed/Thu/Fri)")
    finally:
        engine.dispose()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# -----------------------------------------------------------------------
# TR-9.3: Stage result observability
# -----------------------------------------------------------------------

def test_tr_9_3_stage_result_observability():
    """Run a synthetic pipeline and assert every StageResult has required observability fields."""
    report_dt = date(2026, 9, 22)
    trade_exec_df, strategy_meta_df = _make_synthetic_executions(report_dt)

    orch = DailyPipelineOrchestrator()

    stages: list[StageResult] = []

    # Run stages 4-7 (no DB needed)
    s4 = orch.stage_4_classify_symbols({"trade_executions_df": trade_exec_df})
    stages.append(s4)

    s5 = orch.stage_5_fifo_match(s4.dataframes["trade_executions_df"])
    stages.append(s5)

    matched_df = s5.dataframes["matched_df"]
    s6 = orch.stage_6_compute_charges(matched_df, strategy_meta_df)
    stages.append(s6)

    charges_df = s6.dataframes["charges_df"]
    s7 = orch.stage_7_compute_summary(strategy_meta_df, matched_df, charges_df)
    stages.append(s7)

    # Stages 8-9 without DB -> WARNING
    s8 = orch.stage_8_persist_sqlite(None, {}, report_dt)
    stages.append(s8)

    s9 = orch.stage_9_rebuild_equity_curve(None, report_dt)
    stages.append(s9)

    # Also test stages 1-3
    s1 = orch.stage_1_ingest_sources()
    stages.append(s1)

    s2 = orch.stage_2_gemini_multimodal_parse([])
    stages.append(s2)

    s3 = orch.stage_3_review_staging(s2, operator_approve_flag=False)
    stages.append(s3)

    valid_statuses = {"SUCCESS", "WARNING", "FAIL"}

    print("\n[TR-9.3] Stage Result Observability Summary:")
    print("-" * 70)
    for sr in stages:
        assert sr.stage_name, "stage_name must be non-empty"
        assert sr.status in valid_statuses, (
            f"Invalid status '{sr.status}' for stage {sr.stage_name}"
        )
        assert sr.elapsed_ms >= 0, (
            f"elapsed_ms must be >= 0 for stage {sr.stage_name}"
        )
        assert isinstance(sr.row_counts, dict), (
            f"row_counts must be dict for stage {sr.stage_name}"
        )
        assert isinstance(sr.warnings, list), (
            f"warnings must be list for stage {sr.stage_name}"
        )
        assert isinstance(sr.errors, list), (
            f"errors must be list for stage {sr.stage_name}"
        )
        print(
            f"  {sr.stage_name:40s} | {sr.status:8s} | "
            f"elapsed={sr.elapsed_ms:8.2f}ms | rows={sr.row_counts}"
        )

    print("-" * 70)
    print(f"[TR-9.3] PASS: All {len(stages)} stage results have valid observability fields")


# -----------------------------------------------------------------------
# TR-9.4: Rollback on SQL error
# -----------------------------------------------------------------------

def test_tr_9_4_same_date_persist_updates_without_duplicate_pk():
    """Saving a second run for one report date updates its daily summary safely."""
    tmpdir = tempfile.mkdtemp()
    try:
        db_path = Path(tmpdir) / "test_rollback.db"
        engine, SessionLocal = init_db(db_path, create_tables=True, seed=True)

        orch = DailyPipelineOrchestrator(db_engine=engine, session_factory=SessionLocal)
        report_dt = date(2026, 9, 22)

        # First: insert a DailySummary to create a PK conflict later
        sess = SessionLocal()
        try:
            ds = DailySummary(
                report_date=report_dt,
                total_trades_executed=0,
                total_strategy_runs=0,
                win_count=0,
                loss_count=0,
                total_capital_deployed_peak=0.0,
                total_gross_pnl=0.0,
                total_transaction_cost_drag=0.0,
                total_net_pnl=0.0,
            )
            sess.add(ds)
            sess.commit()
        finally:
            sess.close()

        # Persist another result for the same date; it must upsert the summary.
        tables = {
            "strategy_runs_df": pd.DataFrame([{
                "strategy_name": "Test Strat",
                "deployment_status": "EXITED",
                "multiplier": 1,
                "counter": 1,
                "capital_deployed_allocated": 100000.0,
                "booked_gross_pnl": 500.0,
                "allocated_charges_total": 50.0,
                "net_pnl": 450.0,
                "net_roi_pct": 0.45,
            }]),
            "daily_summary_dict": {
                "total_trades_executed": 5,
                "total_strategy_runs": 1,
                "win_count": 1,
                "loss_count": 0,
                "peak_capital_deployed": 100000.0,
                "total_gross_pnl": 500.0,
                "total_allocated_charges": 50.0,
                "total_net_pnl": 450.0,
                "portfolio_day_roi_pct": 0.45,
            },
            "trade_executions_df": pd.DataFrame([{
                "strategy_run_id": 0, "vendor_symbol": "SENSEX2692277300PE",
                "trade_date": report_dt, "execution_time": "09:30:00",
                "side": "SELL", "quantity": 20, "price": 51.0,
                "segment": "SENSEX", "exchange": "BSE", "lot_size_lookup": 20,
            }]),
        }

        s8 = orch.stage_8_persist_sqlite(SessionLocal, tables, report_dt)
        assert s8.status in ("SUCCESS", "WARNING"), (
            f"Expected stage 8 to upsert the date, got {s8.status}: {s8.errors}"
        )
        second_save = orch.stage_8_persist_sqlite(SessionLocal, tables, report_dt)
        assert second_save.status in ("SUCCESS", "WARNING"), second_save.errors

        # Repeating the same save must be idempotent and retain the raw leg.
        sess = SessionLocal()
        try:
            strat_count = sess.query(StrategyRun).count()
            assert strat_count == 1, f"Expected the strategy run to persist, got {strat_count}"
            assert sess.query(TradeExecution).filter_by(report_date=report_dt).count() == 1
            saved_summary = sess.query(DailySummary).filter_by(report_date=report_dt).one()
            assert saved_summary.total_net_pnl == pytest.approx(450.0)
        finally:
            sess.close()

        print("[TR-9.4] PASS: Same-date upsert and execution persistence verified")
    finally:
        engine.dispose()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
