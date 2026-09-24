"""Small, deterministic portfolio analytics helpers shared by UI and tests."""
from __future__ import annotations

from typing import Any

import pandas as pd


def equity_and_drawdown(daily_pnl: pd.Series, base_capital: float) -> pd.DataFrame:
    """Build equity and peak-to-trough drawdown against account capital.

    ``base_capital`` is the account equity at the start of the selected period.
    It must be positive; we reject invalid inputs instead of reporting misleading
    percentages against cumulative profit.
    """
    if base_capital <= 0:
        raise ValueError("Base capital must be greater than zero")
    pnl = pd.to_numeric(daily_pnl, errors="coerce").fillna(0.0).astype(float)
    cumulative = pnl.cumsum()
    equity = float(base_capital) + cumulative
    peak = equity.cummax().clip(lower=float(base_capital))
    drawdown = ((peak - equity) / peak) * 100.0
    return pd.DataFrame({
        "daily_net_pnl": pnl,
        "cumulative_net_pnl": cumulative,
        "equity": equity,
        "peak_equity": peak,
        "drawdown_pct": drawdown.clip(lower=0.0),
    }, index=daily_pnl.index)


def format_chart_dates(frame: pd.DataFrame, date_column: str = "report_date") -> pd.Series:
    """Return stable human-readable chart dates without timestamp artifacts."""
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    return dates.dt.strftime("%d %b %Y")


def number_or(value: Any, fallback: float = 0.0) -> float:
    """Convert nullable/NaN values to finite floats for display and math."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if pd.notna(result) else fallback
