from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics import equity_and_drawdown, format_chart_dates


def test_drawdown_uses_account_equity_not_cumulative_profit():
    result = equity_and_drawdown(pd.Series([-500.0]), 300_000.0)
    assert result.iloc[0]["equity"] == 299_500.0
    assert result.iloc[0]["drawdown_pct"] == pytest.approx(0.1666667, rel=1e-5)


def test_drawdown_recovers_from_prior_account_equity_peak():
    result = equity_and_drawdown(pd.Series([1_000.0, -500.0]), 300_000.0)
    assert result.iloc[1]["drawdown_pct"] == pytest.approx(500 / 301_000 * 100)


def test_drawdown_rejects_nonpositive_account_base():
    with pytest.raises(ValueError):
        equity_and_drawdown(pd.Series([-500.0]), 0)


def test_chart_date_labels_have_no_time_component():
    frame = pd.DataFrame({"report_date": ["2026-09-22T23:59:59.999600"]})
    assert format_chart_dates(frame).iloc[0] == "22 Sep 2026"
