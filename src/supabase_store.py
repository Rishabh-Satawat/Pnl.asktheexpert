"""
Supabase primary persistence store — dual-write hybrid pattern.

Architecture:
- Supabase (PostgreSQL) is the PRIMARY durable store for all reporting tables
  (daily_summaries, strategy_runs, equity_curve, charges_breakdown, trade_executions).
- SQLite remains the LOCAL buffer for intraday staging and large binary blobs
  (raw_source_files with OCR JSON).
- All writes go to Supabase first; SQLite is a fallback/local mirror.
- Reads for the Historical Dashboard and Audit pages come from Supabase.
- If Supabase credentials are absent, the store silently falls back to SQLite-only.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_supabase_client():
    """
    Return an initialised supabase-py client, or None if credentials are missing.
    Credentials are resolved in priority order:
      1. Streamlit st.secrets (production / Streamlit Cloud)
      2. Environment variables (local .env loaded by dotenv)
    """
    url: Optional[str] = None
    key: Optional[str] = None

    # Try Streamlit secrets first (available in deployed app)
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase", {}).get("url")
        key = (
            st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
            or st.secrets.get("SUPABASE_KEY")
            or st.secrets.get("supabase", {}).get("service_role_key")
            or st.secrets.get("supabase", {}).get("key")
        )
    except Exception:
        pass

    # Fall back to environment variables
    if not url:
        url = os.environ.get("SUPABASE_URL", "")
    if not key:
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY", "")

    if not url or not key:
        return None

    try:
        from supabase import create_client
        client = create_client(url, key)
        return client
    except Exception as exc:
        logger.warning("Failed to create Supabase client: %s", exc)
        return None


def _to_json_safe(value: Any) -> Any:
    """Convert Python dicts/lists to JSON strings for Supabase JSONB columns."""
    if isinstance(value, (dict, list)):
        return value  # supabase-py sends these as JSON automatically
    return value


def _date_str(d: Any) -> Optional[str]:
    if isinstance(d, date):
        return d.isoformat()
    if isinstance(d, str):
        return d
    return None


class SupabaseStore:
    """
    Thin repository wrapping supabase-py for all reporting tables.
    All public methods degrade gracefully (return empty results / log warning)
    when Supabase is unavailable — the app never crashes due to connectivity issues.
    """

    def __init__(self):
        self._client = _get_supabase_client()
        if self._client is None:
            logger.info(
                "SupabaseStore: no credentials found. "
                "Set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY to enable cloud persistence."
            )

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    # UPSERT helpers
    # ------------------------------------------------------------------

    def upsert_daily_summary(self, summary: Dict[str, Any]) -> bool:
        """Insert or replace a daily_summaries row. Returns True on success."""
        if not self.is_connected:
            return False
        try:
            row = {
                "report_date": _date_str(summary.get("report_date")),
                "total_trades_executed": int(summary.get("total_trades_executed", 0)),
                "total_strategy_runs": int(summary.get("total_strategy_runs", 0)),
                "win_count": int(summary.get("win_count", 0)),
                "loss_count": int(summary.get("loss_count", 0)),
                "total_capital_deployed_peak": float(summary.get("total_capital_deployed_peak", 0)),
                "total_gross_pnl": float(summary.get("total_gross_pnl", 0)),
                "total_transaction_cost_drag": float(summary.get("total_transaction_cost_drag", 0)),
                "total_net_pnl": float(summary.get("total_net_pnl", 0)),
                "portfolio_day_net_roi_pct": (
                    float(summary["portfolio_day_net_roi_pct"])
                    if summary.get("portfolio_day_net_roi_pct") is not None
                    else None
                ),
                "segment_breakdown": _to_json_safe(summary.get("segment_breakdown")),
                "strategy_breakdown": _to_json_safe(summary.get("strategy_breakdown")),
                "report_hash": summary.get("report_hash"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._client.table("daily_summaries").upsert(row, on_conflict="report_date").execute()
            return True
        except Exception as exc:
            logger.error("SupabaseStore.upsert_daily_summary failed: %s", exc)
            return False

    def upsert_strategy_runs(self, runs: List[Dict[str, Any]], report_date: Any) -> int:
        """Bulk upsert strategy_runs rows. Returns count of rows sent."""
        if not self.is_connected or not runs:
            return 0
        try:
            rows = []
            for r in runs:
                rows.append({
                    "strategy_run_uuid": r.get("strategy_run_uuid"),
                    "report_date": _date_str(report_date),
                    "strategy_name": str(r.get("strategy_name", "")),
                    "deployment_status": str(r.get("deployment_status", "EXITED")),
                    "multiplier_x": int(r.get("multiplier_x", r.get("multiplier", 1))),
                    "counter_int": r.get("counter_int") or r.get("counter"),
                    "capital_deployed_allocated": float(r.get("capital_deployed_allocated", 0)),
                    "booked_gross_pnl": float(r.get("booked_gross_pnl", 0)),
                    "allocated_charges_total": float(r.get("allocated_charges_total", 0)),
                    "net_pnl": float(r.get("net_pnl", 0)),
                    "net_roi_pct": (
                        float(r["net_roi_pct"]) if r.get("net_roi_pct") is not None else None
                    ),
                    "underlying_segment": r.get("underlying_segment"),
                    "entry_timestamp_ist": r.get("entry_timestamp_ist"),
                    "exit_timestamp_ist": r.get("exit_timestamp_ist"),
                    "legs_greeks": _to_json_safe(r.get("legs_greeks")),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            self._client.table("strategy_runs").upsert(rows, on_conflict="strategy_run_uuid").execute()
            return len(rows)
        except Exception as exc:
            logger.error("SupabaseStore.upsert_strategy_runs failed: %s", exc)
            return 0

    def upsert_charges_breakdown(self, charges: List[Dict[str, Any]], report_date: Any) -> int:
        """Bulk upsert charges_breakdown rows."""
        if not self.is_connected or not charges:
            return 0
        try:
            import uuid
            rows = []
            for c in charges:
                rows.append({
                    "id": str(c.get("id", uuid.uuid4())),
                    "strategy_run_uuid": c.get("strategy_run_uuid") or c.get("strategy_run_id"),
                    "report_date": _date_str(report_date),
                    "charge_source": str(c.get("charge_source", "FORMULA_COMPUTED")),
                    "brokerage": float(c.get("brokerage", 0)),
                    "exchange_turnover_fee": float(c.get("exchange_turnover_fee", 0)),
                    "stt": float(c.get("stt", 0)),
                    "sebi_turnover_charges": float(c.get("sebi_turnover_charges", 0)),
                    "stamp_duty": float(c.get("stamp_duty", 0)),
                    "gst": float(c.get("gst", 0)),
                    "ipft": float(c.get("ipft", 0)),
                    "total_charges": float(c.get("total_charges", 0)),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            self._client.table("charges_breakdown").upsert(rows, on_conflict="id").execute()
            return len(rows)
        except Exception as exc:
            logger.error("SupabaseStore.upsert_charges_breakdown failed: %s", exc)
            return 0

    def upsert_trade_executions(self, executions: List[Dict[str, Any]], report_date: Any) -> int:
        """Bulk upsert trade_executions rows."""
        if not self.is_connected or not executions:
            return 0
        try:
            rows = []
            for e in executions:
                rows.append({
                    "execution_uuid": e.get("execution_uuid"),
                    "strategy_run_uuid": e.get("strategy_run_uuid"),
                    "report_date": _date_str(report_date),
                    "vendor_symbol": e.get("vendor_symbol"),
                    "underlying": e.get("underlying"),
                    "segment": e.get("segment"),
                    "exchange": e.get("exchange"),
                    "expiry_date": _date_str(e.get("expiry_date")),
                    "strike_price": float(e["strike_price"]) if e.get("strike_price") else None,
                    "option_type": e.get("option_type"),
                    "side": e.get("side"),
                    "lots": int(e.get("lots", 1)),
                    "lot_size": int(e.get("lot_size", 0)),
                    "quantity": int(e.get("quantity", 0)),
                    "execution_price": float(e.get("execution_price", 0)),
                    "matched_pair_id": e.get("matched_pair_id"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            self._client.table("trade_executions").upsert(rows, on_conflict="execution_uuid").execute()
            return len(rows)
        except Exception as exc:
            logger.error("SupabaseStore.upsert_trade_executions failed: %s", exc)
            return 0

    def upsert_equity_curve(self, points: List[Dict[str, Any]]) -> int:
        """Bulk upsert equity_curve rows (primary key: report_date)."""
        if not self.is_connected or not points:
            return 0
        try:
            rows = []
            for p in points:
                rows.append({
                    "report_date": _date_str(p.get("report_date")),
                    "daily_net_pnl": float(p.get("daily_net_pnl", 0)),
                    "cumulative_net_pnl": float(p.get("cumulative_net_pnl", 0)),
                    "daily_net_roi_pct": p.get("daily_net_roi_pct"),
                    "cumulative_net_roi_pct": p.get("cumulative_net_roi_pct"),
                    "peak_equity": float(p.get("peak_equity", 0)),
                    "drawdown_pct": float(p.get("drawdown_pct", 0)),
                    "running_win_rate_30d": p.get("running_win_rate_30d"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            self._client.table("equity_curve").upsert(rows, on_conflict="report_date").execute()
            return len(rows)
        except Exception as exc:
            logger.error("SupabaseStore.upsert_equity_curve failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # READ helpers — used by Historical Dashboard and Audit pages
    # ------------------------------------------------------------------

    def get_daily_summaries(
        self, start_date: Any = None, end_date: Any = None, limit: int = 365
    ) -> List[Dict[str, Any]]:
        """Fetch daily_summaries rows sorted by date ascending."""
        if not self.is_connected:
            return []
        try:
            q = self._client.table("daily_summaries").select("*")
            if start_date:
                q = q.gte("report_date", _date_str(start_date))
            if end_date:
                q = q.lte("report_date", _date_str(end_date))
            q = q.order("report_date", desc=False).limit(limit)
            resp = q.execute()
            return resp.data or []
        except Exception as exc:
            logger.error("SupabaseStore.get_daily_summaries failed: %s", exc)
            return []

    def get_strategy_runs(
        self, start_date: Any = None, end_date: Any = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Fetch strategy_runs rows."""
        if not self.is_connected:
            return []
        try:
            q = self._client.table("strategy_runs").select("*")
            if start_date:
                q = q.gte("report_date", _date_str(start_date))
            if end_date:
                q = q.lte("report_date", _date_str(end_date))
            q = q.order("report_date", desc=False).limit(limit)
            resp = q.execute()
            return resp.data or []
        except Exception as exc:
            logger.error("SupabaseStore.get_strategy_runs failed: %s", exc)
            return []

    def get_equity_curve(
        self, start_date: Any = None, end_date: Any = None, limit: int = 730
    ) -> List[Dict[str, Any]]:
        """Fetch equity_curve rows."""
        if not self.is_connected:
            return []
        try:
            q = self._client.table("equity_curve").select("*")
            if start_date:
                q = q.gte("report_date", _date_str(start_date))
            if end_date:
                q = q.lte("report_date", _date_str(end_date))
            q = q.order("report_date", desc=False).limit(limit)
            resp = q.execute()
            return resp.data or []
        except Exception as exc:
            logger.error("SupabaseStore.get_equity_curve failed: %s", exc)
            return []

    def get_charges_breakdown(
        self, start_date: Any = None, end_date: Any = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Fetch charges_breakdown rows."""
        if not self.is_connected:
            return []
        try:
            q = self._client.table("charges_breakdown").select("*")
            if start_date:
                q = q.gte("report_date", _date_str(start_date))
            if end_date:
                q = q.lte("report_date", _date_str(end_date))
            q = q.order("report_date", desc=False).limit(limit)
            resp = q.execute()
            return resp.data or []
        except Exception as exc:
            logger.error("SupabaseStore.get_charges_breakdown failed: %s", exc)
            return []

    def get_trade_executions(
        self, start_date: Any = None, end_date: Any = None, limit: int = 5000
    ) -> List[Dict[str, Any]]:
        """Fetch trade_executions rows."""
        if not self.is_connected:
            return []
        try:
            q = self._client.table("trade_executions").select("*")
            if start_date:
                q = q.gte("report_date", _date_str(start_date))
            if end_date:
                q = q.lte("report_date", _date_str(end_date))
            q = q.order("report_date", desc=False).limit(limit)
            resp = q.execute()
            return resp.data or []
        except Exception as exc:
            logger.error("SupabaseStore.get_trade_executions failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Convenience: full daily batch upsert (called from pipeline stage 8)
    # ------------------------------------------------------------------

    def upsert_daily_batch(
        self,
        report_date: Any,
        daily_summary: Optional[Dict[str, Any]] = None,
        strategy_runs: Optional[List[Dict[str, Any]]] = None,
        charges: Optional[List[Dict[str, Any]]] = None,
        trade_executions: Optional[List[Dict[str, Any]]] = None,
        equity_curve_points: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Single-call batch writer. All sub-writes are independent (no cross-table FK enforcement
        in Supabase by default). Returns a dict of {table: count_written}.
        """
        results: Dict[str, Any] = {"supabase_connected": self.is_connected}
        if not self.is_connected:
            return results

        if daily_summary:
            daily_summary.setdefault("report_date", report_date)
            ok = self.upsert_daily_summary(daily_summary)
            results["daily_summaries"] = 1 if ok else 0

        if strategy_runs:
            n = self.upsert_strategy_runs(strategy_runs, report_date)
            results["strategy_runs"] = n

        if charges:
            n = self.upsert_charges_breakdown(charges, report_date)
            results["charges_breakdown"] = n

        if trade_executions:
            n = self.upsert_trade_executions(trade_executions, report_date)
            results["trade_executions"] = n

        if equity_curve_points:
            n = self.upsert_equity_curve(equity_curve_points)
            results["equity_curve"] = n

        return results


# Module-level singleton (created lazily to avoid import-time credential errors)
_store: Optional[SupabaseStore] = None


def get_supabase_store() -> SupabaseStore:
    """Return the module-level SupabaseStore singleton."""
    global _store
    if _store is None:
        _store = SupabaseStore()
    return _store
