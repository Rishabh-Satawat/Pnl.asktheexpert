from __future__ import annotations

import pandas as pd

from src.pnl_pipeline import StageResult
from src.trade_matcher import TradeMatcher


def test_normalization_makes_negative_quantities_positive_without_changing_side():
    rows = pd.DataFrame([
        {
            "vendor_symbol": "OPTIDX_BANKNIFTY_24SEP2026_PE_50000",
            "segment": "BANKNIFTY",
            "exchange": "BSE",
            "trade_date": "2026-09-24",
            "execution_time": "09:30:00",
            "side": "SELL",
            "quantity": -30,
            "price": 100.0,
        }
    ])

    normalized = TradeMatcher().parse_and_normalize_executions(rows)

    assert normalized.loc[0, "quantity"] == 30
    assert normalized.loc[0, "side"] == "SELL"
    assert normalized.loc[0, "exchange"] == "NSE"


def test_normalization_assigns_bse_to_sensex():
    rows = pd.DataFrame([
        {
            "vendor_symbol": "OPTIDX_SENSEX_24SEP2026_PE_73800",
            "segment": "SENSEX",
            "exchange": "NSE",
            "trade_date": "2026-09-24",
            "execution_time": "09:30:00",
            "side": "BUY",
            "quantity": 20,
            "price": 100.0,
        }
    ])

    normalized = TradeMatcher().parse_and_normalize_executions(rows)

    assert normalized.loc[0, "exchange"] == "BSE"


def test_stage_result_exposes_backward_compatible_error_message():
    result = StageResult(stage_name="example", status="FAIL", errors=["first", "second"])

    assert result.error_message == "first; second"
    assert StageResult(stage_name="ok", status="SUCCESS").error_message == ""
