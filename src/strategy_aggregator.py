"""Aggregate matched trades into strategy-level P&L and ROI metrics."""
from __future__ import annotations

import warnings
from typing import Any, Dict

import pandas as pd


def aggregate_strategy_runs(
    matched_df: pd.DataFrame,
    strategy_metadata_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate matched trades into strategy-level P&L and ROI metrics.

    strategy_metadata_df columns: strategy_run_id, strategy_name, deployment_status,
        multiplier, counter, capital_deployed_allocated, entry_ts, exit_ts,
        allocated_charges_total.

    Returns DataFrame with per-strategy summary including net_pnl and net_roi_pct.
    """
    # Sum gross_pnl per strategy_run_id from matched trades
    if matched_df.empty:
        gross_by_strat = pd.DataFrame(columns=["strategy_run_id", "booked_gross_pnl"])
    else:
        gross_by_strat = (
            matched_df.groupby("strategy_run_id", as_index=False)["gross_pnl"]
            .sum()
            .rename(columns={"gross_pnl": "booked_gross_pnl"})
        )

    # Merge with metadata
    result = strategy_metadata_df.copy()
    result = result.merge(gross_by_strat, on="strategy_run_id", how="left")
    result["booked_gross_pnl"] = result["booked_gross_pnl"].fillna(0.0)

    # Ensure allocated_charges_total exists
    if "allocated_charges_total" not in result.columns:
        result["allocated_charges_total"] = 0.0
    result["allocated_charges_total"] = result["allocated_charges_total"].fillna(0.0)

    # Derive underlying_segment from matched_df if available
    if not matched_df.empty and "segment" in matched_df.columns:
        seg_by_strat = (
            matched_df.groupby("strategy_run_id", as_index=False)["segment"]
            .first()
            .rename(columns={"segment": "underlying_segment"})
        )
        result = result.merge(seg_by_strat, on="strategy_run_id", how="left")
    elif "underlying_segment" not in result.columns:
        result["underlying_segment"] = None

    # Compute net_pnl and ROI
    result["net_pnl"] = result["booked_gross_pnl"] - result["allocated_charges_total"]

    def _compute_roi(row: Any) -> float:
        cap = row["capital_deployed_allocated"]
        if pd.isna(cap) or cap == 0:
            warnings.warn(
                f"Strategy {row.get('strategy_run_id', '?')}: "
                f"capital_deployed_allocated is {cap}; ROI set to NaN.",
                UserWarning,
                stacklevel=2,
            )
            return float("nan")
        return (row["net_pnl"] / cap) * 100.0

    result["net_roi_pct"] = result.apply(_compute_roi, axis=1)

    # Ensure output column order
    out_cols = [
        "strategy_run_id", "strategy_name", "deployment_status",
        "strategy_run_uuid",
        "multiplier", "counter", "capital_deployed_allocated",
        "entry_ts", "exit_ts", "underlying_segment",
        "booked_gross_pnl", "allocated_charges_total",
        "net_pnl", "net_roi_pct",
    ]
    for c in out_cols:
        if c not in result.columns:
            result[c] = None
    return result[out_cols]


def compute_portfolio_day_summary(strategy_runs_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute portfolio-level day summary.

    Returns dict with: total_gross_pnl, total_allocated_charges, total_net_pnl,
    peak_capital_deployed, portfolio_day_roi_pct, win_count, loss_count, flat_count
    """
    total_gross_pnl = float(strategy_runs_df["booked_gross_pnl"].sum())
    total_allocated_charges = float(strategy_runs_df["allocated_charges_total"].sum())
    total_net_pnl = float(strategy_runs_df["net_pnl"].sum())
    peak_capital_deployed = float(strategy_runs_df["capital_deployed_allocated"].sum())

    if peak_capital_deployed == 0:
        portfolio_day_roi_pct = float("nan")
    else:
        portfolio_day_roi_pct = (total_net_pnl / peak_capital_deployed) * 100.0

    win_count = int((strategy_runs_df["net_pnl"] > 0).sum())
    loss_count = int((strategy_runs_df["net_pnl"] < 0).sum())
    flat_count = int((strategy_runs_df["net_pnl"] == 0).sum())

    return {
        "total_gross_pnl": total_gross_pnl,
        "total_allocated_charges": total_allocated_charges,
        "total_net_pnl": total_net_pnl,
        "peak_capital_deployed": peak_capital_deployed,
        "portfolio_day_roi_pct": portfolio_day_roi_pct,
        "win_count": win_count,
        "loss_count": loss_count,
        "flat_count": flat_count,
    }
