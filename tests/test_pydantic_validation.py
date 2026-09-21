from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from src.models.pydantic_schemas import (
    TradeExecution, StrategyRun, ChargesBreakdown, ContractNoteCharges,
    OptionTypeEnum, SideEnum,
)


def test_trade_execution_invalid_option_type_raises():
    """TR-1.4: Malformed TradeExecution with option_type='XX' raises ValidationError."""
    with pytest.raises(ValidationError) as ei:
        TradeExecution(
            strategy_run_id=1, report_date=date(2026,9,3),
            vendor_symbol="NIFTY2692424000XX", side="BUY", lots=1, lot_size=25,
            quantity=25, execution_price=150.0, option_type="XX",
        )
    assert "XX" in str(ei.value).lower() or "enum" in str(ei.value).lower() or "validation" in str(ei.value).lower()


def test_negative_execution_price_fails_validator():
    """TR-1.4: Negative execution_price fails non-negative-price validator."""
    with pytest.raises(ValidationError):
        TradeExecution(
            strategy_run_id=1, report_date=date(2026,9,3),
            vendor_symbol="BANKNIFTY26925120000PE", side="SELL", lots=1, lot_size=15,
            quantity=15, execution_price=-5.0, option_type="PE",
        )


def test_negative_capital_deployed_fails():
    with pytest.raises(ValidationError):
        StrategyRun(
            report_date=date(2026,9,3), strategy_name="Bad",
            capital_deployed_allocated=-10.0,
        )


def test_negative_brokerage_fails_non_negative():
    with pytest.raises(ValidationError):
        ChargesBreakdown(
            strategy_run_id=1, report_date=date(2026,9,3),
            brokerage=-5.0, total_charges=10.0,
        )


def test_side_normalization_and_gross_premium_auto():
    te = TradeExecution(
        strategy_run_id=42, report_date=date(2026,9,3),
        vendor_symbol="SENSEX2692277300CE", side="long", lots=1, lot_size=20,
        quantity=20, execution_price=100.0, option_type="CALL",
    )
    assert te.side == SideEnum.BUY
    assert te.option_type == OptionTypeEnum.CE
    assert te.gross_premium == pytest.approx(2000.0, abs=0.01)


def test_contract_note_auto_reconciles_correctly():
    cn = ContractNoteCharges(
        brokerage_amount=40.0,
        exchange_turnover_fee_amount=3.12,
        securities_transaction_tax_stt=2.40,
        sebi_turnover_charges=0.01,
        stamp_duty=0.06,
        gst=7.77,
        total_charges_grand_total=40.0+3.12+2.40+0.01+0.06+7.77,
    )
    assert cn.reconciliation_boolean is True
    assert abs(cn.diff_rupees) < 0.01


def test_contract_note_detects_mismatch():
    cn = ContractNoteCharges(
        brokerage_amount=10.0, exchange_turnover_fee_amount=1.0,
        securities_transaction_tax_stt=1.0, sebi_turnover_charges=0.0,
        stamp_duty=0.0, gst=0.0,
        total_charges_grand_total=100.0,
    )
    assert cn.reconciliation_boolean is False
    assert cn.diff_rupees > 10.0
