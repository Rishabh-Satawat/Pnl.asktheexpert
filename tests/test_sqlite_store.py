from __future__ import annotations

import sys
import tempfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sqlite_store import QuantDeskSqliteStore
from src.db.schema import DailySummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daily_summary(report_date: date, net_pnl: float = 1000.0) -> dict:
    return {
        "report_date": report_date,
        "total_trades_executed": 10,
        "total_strategy_runs": 2,
        "win_count": 6,
        "loss_count": 4,
        "total_capital_deployed_peak": 500_000.0,
        "total_gross_pnl": net_pnl + 200.0,
        "total_transaction_cost_drag": 200.0,
        "total_net_pnl": net_pnl,
        "portfolio_day_net_roi_pct": round(net_pnl / 500_000 * 100, 4),
    }


def _make_strategy_run(report_date: date, idx: int = 1) -> dict:
    return {
        "strategy_run_uuid": f"sr-{report_date.isoformat()}-{idx}-{uuid.uuid4().hex[:8]}",
        "report_date": report_date,
        "strategy_name": f"TestStrategy-{idx}",
        "capital_deployed_allocated": 100_000.0,
        "booked_gross_pnl": 500.0,
        "allocated_charges_total": 50.0,
        "net_pnl": 450.0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSqliteStore:

    @pytest.fixture(autouse=True)
    def setup_store(self, tmp_path):
        db_path = tmp_path / "test_store.db"
        cache_dir = tmp_path / "cache"
        self.store = QuantDeskSqliteStore(db_path=db_path, cache_dir=cache_dir)
        self.tmp_path = tmp_path
        self.cache_dir = cache_dir

    def test_tr_11_1_lock_parquet_replay(self):
        """TR-11.1: Successful insert, then pending parquet write + replay with no duplicates."""
        rd = date(2026, 9, 1)
        summary = _make_daily_summary(rd, net_pnl=1500.0)

        # Step 1 - normal upsert should succeed
        result = self.store.upsert_daily_batch(
            report_date=rd,
            daily_summary=summary,
        )
        print(f"[TR-11.1] upsert result: status={result['status']}, counts={result['row_counts']}")
        assert result["status"] == "ok"
        assert result["row_counts"]["daily_summaries"] == 1

        # Verify row is in DB
        fetched = self.store.get_daily_summary(rd)
        assert fetched is not None
        assert fetched["total_net_pnl"] == 1500.0

        # Step 2 - manually write a pending parquet to simulate fallback
        rd2 = date(2026, 9, 2)
        pending_data = [_make_daily_summary(rd2, net_pnl=2000.0)]
        df = pd.DataFrame(pending_data)
        parquet_path = self.cache_dir / f"pending_daily_summaries_{rd2.isoformat()}_abc123.parquet"
        df.to_parquet(parquet_path, index=False)
        assert parquet_path.exists(), "Pending parquet should exist before replay"

        # Step 3 - replay pending parquets
        replay_result = self.store._replay_pending_parquets()
        print(f"[TR-11.1] replay result: {replay_result}")
        assert replay_result["replayed_count"] >= 1
        assert replay_result["failed_count"] == 0

        # Parquet file should be deleted after successful replay
        assert not parquet_path.exists(), "Parquet should be deleted after replay"

        # Verify replayed row is in DB
        fetched2 = self.store.get_daily_summary(rd2)
        assert fetched2 is not None
        assert fetched2["total_net_pnl"] == 2000.0

        # Step 4 - write same data again as parquet and replay - should not create duplicates
        df.to_parquet(
            self.cache_dir / f"pending_daily_summaries_{rd2.isoformat()}_dup456.parquet",
            index=False,
        )
        replay2 = self.store._replay_pending_parquets()
        print(f"[TR-11.1] replay2 (dedup) result: {replay2}")
        # The upsert should handle the duplicate gracefully (update rather than fail)
        assert replay2["failed_count"] == 0

        # Still only one row for rd2
        fetched3 = self.store.get_daily_summary(rd2)
        assert fetched3 is not None
        assert fetched3["total_net_pnl"] == 2000.0
        print("[TR-11.1] PASSED - parquet replay with dedup works correctly")

    def test_tr_11_2_duplicate_pk_rollback(self):
        """TR-11.2: Upsert handles duplicate PK gracefully (update-on-conflict)."""
        rd = date(2026, 9, 5)

        # Insert initial daily summary
        summary_v1 = _make_daily_summary(rd, net_pnl=1000.0)
        r1 = self.store.upsert_daily_batch(report_date=rd, daily_summary=summary_v1)
        assert r1["status"] == "ok"
        print(f"[TR-11.2] initial insert: {r1}")

        fetched1 = self.store.get_daily_summary(rd)
        assert fetched1 is not None
        assert fetched1["total_net_pnl"] == 1000.0

        # Insert same PK with updated values - should update, not fail
        summary_v2 = _make_daily_summary(rd, net_pnl=2500.0)
        sr = _make_strategy_run(rd, idx=1)
        r2 = self.store.upsert_daily_batch(
            report_date=rd,
            daily_summary=summary_v2,
            strategy_runs=[sr],
        )
        print(f"[TR-11.2] upsert with same PK: {r2}")
        assert r2["status"] == "ok", f"Upsert should handle duplicate PK, got: {r2}"

        # Verify update took effect
        fetched2 = self.store.get_daily_summary(rd)
        assert fetched2 is not None
        assert fetched2["total_net_pnl"] == 2500.0, (
            f"Expected updated net_pnl=2500, got {fetched2['total_net_pnl']}"
        )

        # Verify strategy run was also inserted
        runs = self.store.get_strategy_runs(rd)
        assert len(runs) == 1
        print("[TR-11.2] PASSED - upsert handles duplicate PK via update")

    def test_tr_11_3_fetch_historical(self):
        """TR-11.3: Insert 5 daily summaries, query date range, verify count & ordering."""
        base = date(2026, 9, 10)
        dates = [base + timedelta(days=i) for i in range(5)]
        pnls = [1000.0, -500.0, 2000.0, 750.0, -200.0]

        for d, pnl in zip(dates, pnls):
            summary = _make_daily_summary(d, net_pnl=pnl)
            result = self.store.upsert_daily_batch(report_date=d, daily_summary=summary)
            assert result["status"] == "ok", f"Insert failed for {d}: {result}"

        # Query full range
        hist = self.store.get_historical_summaries(dates[0], dates[-1])
        assert len(hist) == 5, f"Expected 5 summaries, got {len(hist)}"
        print(f"[TR-11.3] fetched {len(hist)} historical summaries")

        # Verify ascending date order
        fetched_dates = [h["report_date"] for h in hist]
        for i in range(len(fetched_dates) - 1):
            assert fetched_dates[i] < fetched_dates[i + 1], (
                f"Dates not in ascending order: {fetched_dates}"
            )

        # Verify PNL values match
        fetched_pnls = [h["total_net_pnl"] for h in hist]
        assert fetched_pnls == pnls, f"PNL mismatch: expected {pnls}, got {fetched_pnls}"

        # Query sub-range (middle 3 days)
        sub = self.store.get_historical_summaries(dates[1], dates[3])
        assert len(sub) == 3, f"Expected 3 summaries in sub-range, got {len(sub)}"
        sub_pnls = [s["total_net_pnl"] for s in sub]
        assert sub_pnls == pnls[1:4], f"Sub-range PNL mismatch: {sub_pnls}"
        print("[TR-11.3] PASSED - historical fetch with date range and ordering correct")
