"""Explainable diagnostics computed only from the trades and summaries we have."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _pipeline_frame(pipeline_result: Any, result_key: str, stage_key: str) -> pd.DataFrame:
    frame = getattr(pipeline_result, result_key, None)
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return frame.copy()
    for stage in getattr(pipeline_result, "per_stage", []) or []:
        frame = getattr(stage, "dataframes", {}).get(stage_key)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            return frame.copy()
    return pd.DataFrame()


def _finite_float(value: Any) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def diagnose_pipeline(pipeline_result: Any) -> dict[str, Any]:
    """Return descriptive trade metrics, strategy attribution, and review flags.

    The calculations intentionally do not estimate Greeks, market correlation,
    or execution slippage: those require quote/market data not stored by this app.
    """
    matched = _pipeline_frame(pipeline_result, "matched_trades_df", "matched_df")
    strategies = getattr(pipeline_result, "strategy_runs_df", None)
    strategies = strategies.copy() if isinstance(strategies, pd.DataFrame) else pd.DataFrame()
    open_legs = pd.DataFrame()
    for stage in getattr(pipeline_result, "per_stage", []) or []:
        candidate = getattr(stage, "dataframes", {}).get("open_legs_df")
        if isinstance(candidate, pd.DataFrame) and not candidate.empty:
            open_legs = candidate.copy()
            break

    summary = getattr(pipeline_result, "daily_summary_df", None)
    summary = summary if isinstance(summary, dict) else {}
    gross_total = _finite_float(summary.get("total_gross_pnl", strategies.get("booked_gross_pnl", pd.Series(dtype=float)).sum()))
    net_total = _finite_float(summary.get("total_net_pnl", strategies.get("net_pnl", pd.Series(dtype=float)).sum()))
    charges_total = _finite_float(summary.get("total_allocated_charges", strategies.get("allocated_charges_total", pd.Series(dtype=float)).sum()))

    gross = pd.to_numeric(matched.get("gross_pnl", pd.Series(dtype=float)), errors="coerce").dropna()
    winners = gross[gross > 0]
    losers = gross[gross < 0]
    trade_count = int(gross.size)
    gross_profit = float(winners.sum())
    gross_loss = float(losers.sum())
    profit_factor = gross_profit / abs(gross_loss) if gross_loss else (float("inf") if gross_profit else None)
    metrics = {
        "closed_trades": trade_count,
        "win_rate_pct": float((winners.size / trade_count) * 100) if trade_count else None,
        "average_win": float(winners.mean()) if not winners.empty else None,
        "average_loss": float(losers.mean()) if not losers.empty else None,
        "profit_factor": profit_factor,
        "expectancy_per_trade": float(gross.mean()) if trade_count else None,
        "gross_pnl": gross_total,
        "net_pnl": net_total,
        "charges": charges_total,
        "cost_drag_pct": (abs(charges_total) / abs(gross_total) * 100) if gross_total else None,
        "unmatched_legs": len(open_legs),
    }

    attribution = pd.DataFrame()
    if not strategies.empty:
        columns = [c for c in (
            "strategy_run_id", "strategy_name", "underlying_segment",
            "booked_gross_pnl", "allocated_charges_total", "net_pnl", "net_roi_pct",
        ) if c in strategies.columns]
        attribution = strategies[columns].copy()
        if not matched.empty and "strategy_run_id" in matched.columns and "gross_pnl" in matched.columns:
            trade_rows = matched.copy()
            trade_rows["gross_pnl"] = pd.to_numeric(trade_rows["gross_pnl"], errors="coerce")
            stats = trade_rows.groupby("strategy_run_id").agg(
                closed_trades=("gross_pnl", "count"),
                winning_trades=("gross_pnl", lambda values: int((values > 0).sum())),
                average_trade_gross=("gross_pnl", "mean"),
            ).reset_index()
            stats["win_rate_pct"] = (stats["winning_trades"] / stats["closed_trades"] * 100).round(2)
            attribution = attribution.merge(stats, on="strategy_run_id", how="left")

    findings: list[dict[str, str]] = []
    if metrics["unmatched_legs"]:
        findings.append({"level": "Review", "title": "Open or unmatched executions", "detail": f"{metrics['unmatched_legs']} execution leg(s) did not form a closed match. Check symbols, dates, sides, quantities, and strategy assignment."})
    if trade_count and trade_count < 20:
        findings.append({"level": "Context", "title": "Small sample", "detail": f"Only {trade_count} closed trade(s) are available; win rate and expectancy can move substantially with a few trades."})
    if gross_total > 0 and net_total <= 0:
        findings.append({"level": "Alert", "title": "Costs erased gross gains", "detail": f"Gross P&L is positive, while net P&L is ₹{net_total:,.2f}. Reconcile realized charges and review turnover/position sizing."})
    elif metrics["cost_drag_pct"] is not None and metrics["cost_drag_pct"] >= 25:
        findings.append({"level": "Review", "title": "High cost drag", "detail": f"Charges are {metrics['cost_drag_pct']:.1f}% of the absolute gross P&L for this batch."})
    if net_total < 0:
        findings.append({"level": "Review", "title": "Negative net result", "detail": "Review the losing trades and strategy attribution before treating this batch as representative."})
    if not findings:
        findings.append({"level": "Info", "title": "No rule-based flags", "detail": "The available accounting data did not trigger a diagnostic flag. This is descriptive analysis, not a forecast."})

    return {"metrics": metrics, "strategy_attribution": attribution, "findings": findings}
