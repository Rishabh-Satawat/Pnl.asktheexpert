from __future__ import annotations

import hashlib
import json
import math
import numbers
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.db.engine import init_db
from src.db.schema import (
    Base,
    ChargesBreakdown,
    DailySummary,
    EquityCurve,
    RawSourceFile,
    StrategyRun,
    TradeExecution,
)


_MODEL_MAP = {
    "raw_source_files": RawSourceFile,
    "strategy_runs": StrategyRun,
    "trade_executions": TradeExecution,
    "charges_breakdown": ChargesBreakdown,
    "daily_summaries": DailySummary,
}

_SQLITE_INTEGER_COLUMNS = {
    "win_count", "loss_count", "total_trades_executed", "total_strategy_runs",
    "multiplier_x", "quantity", "lot_size", "strategy_run_id", "id",
    "counter_int", "counter", "lots", "running_trade_count", "file_size_bytes",
    "source_file_id", "expiry_weekday_number",
}


def sanitize_for_sqlite(record: dict) -> dict:
    """Normalize pandas/numpy missing values before passing records to SQLite.

    Missing auto-increment primary keys are left as ``None`` so SQLite can
    allocate them. Other integer fields use zero for missing/invalid values;
    non-finite floating point values use zero, while nullable non-numeric
    values remain SQL NULL.
    """
    sanitized = {}
    for key, value in record.items():
        try:
            missing_value = pd.isna(value)
            is_missing = bool(missing_value) if pd.api.types.is_scalar(missing_value) else False
        except (TypeError, ValueError):
            is_missing = False

        if key in _SQLITE_INTEGER_COLUMNS:
            if key == "id" and is_missing:
                sanitized[key] = None
                continue
            try:
                value_number = float(value)
                sanitized[key] = 0 if is_missing or not math.isfinite(value_number) else int(round(value_number))
            except (ValueError, TypeError, OverflowError):
                sanitized[key] = 0
            continue

        if is_missing:
            if isinstance(value, numbers.Number) and not isinstance(value, bool):
                sanitized[key] = 0.0
            else:
                sanitized[key] = None
            continue

        # Convert numpy scalar wrappers to their Python equivalents for SQLite.
        if hasattr(value, "item") and callable(value.item):
            try:
                value = value.item()
            except (ValueError, TypeError):
                pass
        sanitized[key] = value
    return sanitized


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy model instance to a plain dict."""
    d = {}
    for c in row.__table__.columns:
        val = getattr(row, c.name)
        if isinstance(val, (date, datetime)):
            val = val.isoformat()
        d[c.name] = val
    return d


class QuantDeskSqliteStore:
    """Repository-pattern store backed by SQLite via SQLAlchemy."""

    def __init__(
        self,
        db_path: str | Path = "data/quant_desk.db",
        cache_dir: str | Path = "data/cache",
    ) -> None:
        self.db_path = Path(db_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.engine, self.SessionLocal = init_db(
            db_path=self.db_path, create_tables=True, seed=False
        )

    # ------------------------------------------------------------------
    # upsert_daily_batch
    # ------------------------------------------------------------------
    def upsert_daily_batch(
        self,
        report_date: date,
        raw_sources: list[dict] | None = None,
        trade_executions: list[dict] | None = None,
        strategy_runs: list[dict] | None = None,
        charges_breakdowns: list[dict] | None = None,
        daily_summary: dict | None = None,
    ) -> dict:
        row_counts: dict[str, int] = {}
        errors: list[str] = []
        data_dict: dict[str, list[dict]] = {}

        if raw_sources:
            data_dict["raw_source_files"] = raw_sources
        if strategy_runs:
            data_dict["strategy_runs"] = strategy_runs
        if trade_executions:
            data_dict["trade_executions"] = trade_executions
        if charges_breakdowns:
            data_dict["charges_breakdown"] = charges_breakdowns
        if daily_summary:
            data_dict["daily_summaries"] = [daily_summary]

        try:
            with self.SessionLocal.begin() as session:
                for table_name, rows in data_dict.items():
                    model_cls = _MODEL_MAP[table_name]
                    count = self._upsert_rows(session, model_cls, rows)
                    row_counts[table_name] = count
            return {"status": "ok", "row_counts": row_counts, "errors": errors}
        except Exception as exc:
            errors.append(str(exc))
            self._write_pending_parquet(data_dict, report_date)
            return {"status": "fallback_parquet", "row_counts": {}, "errors": errors}

    def _upsert_rows(self, session: Session, model_cls, rows: list[dict]) -> int:
        """Insert-or-update rows using merge (session-level upsert)."""
        count = 0
        pk_cols = [c.name for c in model_cls.__table__.primary_key.columns]
        for row_data in rows:
            clean = {
                k: v for k, v in row_data.items()
                if k in {c.name for c in model_cls.__table__.columns}
            }
            clean = sanitize_for_sqlite(clean)
            # Convert date strings to date objects for Date columns
            for col in model_cls.__table__.columns:
                if col.name in clean and clean[col.name] is not None:
                    from sqlalchemy import Date as SADate, DateTime as SADateTime
                    if isinstance(col.type, SADate) and isinstance(clean[col.name], str):
                        clean[col.name] = date.fromisoformat(clean[col.name])
                    elif isinstance(col.type, SADateTime) and isinstance(clean[col.name], str):
                        clean[col.name] = datetime.fromisoformat(clean[col.name])

            # Check if row with same PK exists
            pk_filter = {}
            has_pk = True
            for pk_col in pk_cols:
                if pk_col in clean and clean[pk_col] is not None:
                    pk_filter[pk_col] = clean[pk_col]
                else:
                    has_pk = False
                    break

            if has_pk and pk_filter:
                existing = session.query(model_cls).filter(
                    *[getattr(model_cls, k) == v for k, v in pk_filter.items()]
                ).one_or_none()
                if existing:
                    for k, v in clean.items():
                        if k not in pk_cols:
                            setattr(existing, k, v)
                    count += 1
                    continue

            obj = model_cls(**clean)
            session.add(obj)
            count += 1
        session.flush()
        return count

    # ------------------------------------------------------------------
    # rebuild_equity_curve
    # ------------------------------------------------------------------
    def rebuild_equity_curve(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict]:
        with self.SessionLocal() as session:
            q = session.query(DailySummary).order_by(DailySummary.report_date)
            if from_date:
                q = q.filter(DailySummary.report_date >= from_date)
            if to_date:
                q = q.filter(DailySummary.report_date <= to_date)
            summaries = q.all()

        if not summaries:
            return []

        curve_rows: list[dict] = []
        cumulative = 0.0
        peak = 0.0
        running_trade_count = 0
        recent_wins: list[bool] = []

        for s in summaries:
            daily_pnl = s.total_net_pnl or 0.0
            cumulative += daily_pnl
            if cumulative > peak:
                peak = cumulative
            drawdown_pct = ((peak - cumulative) / peak * 100.0) if peak > 0 else 0.0

            running_trade_count += (s.total_trades_executed or 0)
            win_c = s.win_count or 0
            loss_c = s.loss_count or 0
            recent_wins.extend([True] * win_c + [False] * loss_c)
            # Keep last 30 days of win/loss records
            if len(recent_wins) > 200:
                recent_wins = recent_wins[-200:]
            last_30 = recent_wins[-30:] if recent_wins else []
            win_rate_30d = (sum(last_30) / len(last_30) * 100.0) if last_30 else None

            curve_rows.append({
                "report_date": s.report_date,
                "daily_net_pnl": daily_pnl,
                "cumulative_net_pnl": cumulative,
                "daily_net_roi_pct": s.portfolio_day_net_roi_pct,
                "cumulative_net_roi_pct": None,
                "peak_equity": peak,
                "drawdown_pct": round(drawdown_pct, 4),
                "running_capital_base": s.total_capital_deployed_peak,
                "running_trade_count": running_trade_count,
                "running_win_rate_30d": round(win_rate_30d, 2) if win_rate_30d is not None else None,
            })

        # Upsert equity_curve rows
        try:
            with self.SessionLocal.begin() as session:
                for row in curve_rows:
                    self._upsert_rows(session, EquityCurve, [row])
        except Exception:
            pass

        return [
            {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in r.items()}
            for r in curve_rows
        ]

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def get_daily_summary(self, report_date: date) -> dict | None:
        with self.SessionLocal() as session:
            row = session.query(DailySummary).filter(
                DailySummary.report_date == report_date
            ).one_or_none()
            if row is None:
                return None
            return _row_to_dict(row)

    def get_strategy_runs(self, report_date: date) -> list[dict]:
        with self.SessionLocal() as session:
            rows = session.query(StrategyRun).filter(
                StrategyRun.report_date == report_date
            ).all()
            return [_row_to_dict(r) for r in rows]

    def get_trade_executions(self, report_date: date) -> list[dict]:
        with self.SessionLocal() as session:
            rows = session.query(TradeExecution).filter(
                TradeExecution.report_date == report_date
            ).all()
            return [_row_to_dict(r) for r in rows]

    def get_equity_curve(self, from_date: date, to_date: date) -> list[dict]:
        with self.SessionLocal() as session:
            rows = session.query(EquityCurve).filter(
                and_(
                    EquityCurve.report_date >= from_date,
                    EquityCurve.report_date <= to_date,
                )
            ).order_by(EquityCurve.report_date).all()
            return [_row_to_dict(r) for r in rows]

    def get_historical_summaries(self, from_date: date, to_date: date) -> list[dict]:
        with self.SessionLocal() as session:
            rows = session.query(DailySummary).filter(
                and_(
                    DailySummary.report_date >= from_date,
                    DailySummary.report_date <= to_date,
                )
            ).order_by(DailySummary.report_date).all()
            return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Parquet fallback / replay
    # ------------------------------------------------------------------
    def _write_pending_parquet(self, data_dict: dict, report_date: date) -> list[Path]:
        """Write each table's data to a pending parquet file in cache_dir."""
        written: list[Path] = []
        date_str = report_date.isoformat()
        for table_name, rows in data_dict.items():
            if not rows:
                continue
            uid = uuid.uuid4().hex[:12]
            filename = f"pending_{table_name}_{date_str}_{uid}.parquet"
            path = self.cache_dir / filename
            df = pd.DataFrame(rows)
            df.to_parquet(path, index=False)
            written.append(path)
        return written

    def _replay_pending_parquets(self) -> dict:
        """Scan cache_dir for pending parquet files and replay them into the DB."""
        replayed_count = 0
        failed_count = 0
        seen_hashes: set[str] = set()

        parquet_files = sorted(self.cache_dir.glob("pending_*.parquet"))
        for pf in parquet_files:
            try:
                # Parse table name from filename: pending_{table}_{date}_{uuid}.parquet
                parts = pf.stem.split("_", 2)  # ['pending', rest...]
                # The table name may contain underscores, so we need smarter parsing
                # Format: pending_{table_name}_{date}_{uuid}.parquet
                stem = pf.stem  # e.g. pending_raw_source_files_2026-09-01_abc123
                # Remove 'pending_' prefix
                rest = stem[len("pending_"):]
                # Find the table name by matching known table names
                table_name = None
                for known in _MODEL_MAP:
                    if rest.startswith(known + "_"):
                        table_name = known
                        break
                if table_name is None:
                    failed_count += 1
                    continue

                model_cls = _MODEL_MAP[table_name]
                df = pd.read_parquet(pf)
                rows = df.to_dict(orient="records")

                # Deduplicate by content hash
                unique_rows = []
                for row in rows:
                    h = self._compute_content_hash(row)
                    if h in seen_hashes:
                        continue
                    seen_hashes.add(h)
                    unique_rows.append(row)

                if unique_rows:
                    with self.SessionLocal.begin() as session:
                        self._upsert_rows(session, model_cls, unique_rows)

                # Success - delete the parquet file
                pf.unlink()
                replayed_count += len(unique_rows)
            except Exception:
                failed_count += 1

        return {"replayed_count": replayed_count, "failed_count": failed_count}

    def _compute_content_hash(self, row_dict: dict) -> str:
        """SHA-256 of sorted key-value pairs for dedupe."""
        items = sorted(row_dict.items(), key=lambda x: str(x[0]))
        raw = json.dumps(items, default=str, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
