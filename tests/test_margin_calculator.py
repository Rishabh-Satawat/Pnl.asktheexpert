"""Tests for SEBIMarginCalculator (Audit Metric Secondary). TR-6.1, TR-6.2."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.margin_calculator import SEBIMarginCalculator


@pytest.fixture
def calc():
    return SEBIMarginCalculator()


def _load_golden():
    p = Path(__file__).resolve().parent / "fixtures" / "golden_margin_examples.csv"
    return pd.read_csv(p)


_REQUIRED_KEYS = {
    "notional_value",
    "span_margin",
    "exposure_margin",
    "total_margin_required",
    "audit_net_capital_blocked_secondary",
    "margin_methodology_string",
}


def test_tr_6_1_four_archetypes_required_keys(calc):
    """TR-6.1: All 4 golden archetypes return dicts with required keys."""
    df = _load_golden()
    for _, row in df.iterrows():
        archetype = row["archetype"]
        is_spread = str(row["is_spread"]).lower() == "true"

        if row["option_type"] == "FUT":
            result = calc.calculate_futures_margin(
                underlying=row["underlying"],
                underlying_price=float(row["underlying_price"]),
                qty=int(row["qty"]),
                lot_size=int(row["lot_size"]),
                lots=int(row["lots"]),
                exchange=row["exchange"],
            )
        else:
            spread_max = float(row["spread_max_loss_per_unit"]) if pd.notna(row.get("spread_max_loss_per_unit")) else None
            spread_net = float(row["spread_net_premium_flow_per_unit"]) if pd.notna(row.get("spread_net_premium_flow_per_unit")) else None
            # Convention: positive premium = buyer pays; negative = seller receives
            ppp = float(row["premium_per_point"])
            if str(row.get("side", "")).upper() == "SELL" and not is_spread:
                ppp = -ppp
            result = calc.calculate_option_margin(
                underlying=row["underlying"],
                underlying_price=float(row["underlying_price"]),
                option_type=row["option_type"],
                strike=float(row["strike"]),
                premium_per_point=ppp,
                qty=int(row["qty"]),
                lot_size=int(row["lot_size"]),
                lots=int(row["lots"]),
                exchange=row["exchange"],
                is_spread=is_spread,
                spread_max_loss_per_unit=spread_max,
                spread_net_premium_flow_per_unit=spread_net,
            )

        missing = _REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Archetype {archetype} missing keys: {missing}"

        audit = result["audit_net_capital_blocked_secondary"]
        low = float(row["expected_audit_min"])
        high = float(row["expected_audit_max"])
        assert low <= audit <= high, (
            f"Archetype {archetype}: audit_net={audit:.2f} outside [{low:.2f}, {high:.2f}]"
        )

        print(f"  [PASS] {archetype}: audit_net_capital_blocked_secondary = {audit:.2f} in [{low:.2f}, {high:.2f}]")


def test_tr_6_2_long_option_only_premium(calc):
    """TR-6.2: Long NIFTY ATM CE -- audit = premium only = 6250."""
    result = calc.calculate_option_margin(
        underlying="NIFTY",
        underlying_price=25000.0,
        option_type="CE",
        strike=25000.0,
        premium_per_point=250.0,
        qty=25,
        lot_size=25,
        lots=1,
        exchange="NSE",
    )
    assert result["audit_net_capital_blocked_secondary"] == pytest.approx(6250.0, abs=0.01), (
        f"Long option audit should be premium only = 250*25 = 6250, got {result['audit_net_capital_blocked_secondary']}"
    )
    meth = result["margin_methodology_string"]
    assert "Long option: only premium blocked for audit metric" in meth, (
        f"Methodology must contain long option badge. Got: {meth}"
    )
    assert "Audit Metric (Secondary)" in meth, (
        f"Methodology must contain Audit Metric (Secondary). Got: {meth}"
    )
    print(f"  [PASS] Long NIFTY ATM CE: audit = {result['audit_net_capital_blocked_secondary']:.2f}")


def test_tr_6_3_spread_max_debit_max_loss(calc):
    """TR-6.3: SENSEX Bull Call Spread -- audit = max(debit, max_loss) = max(2000, 10000) = 10000."""
    result = calc.calculate_option_margin(
        underlying="SENSEX",
        underlying_price=80000.0,
        option_type="CE",
        strike=80000.0,
        premium_per_point=300.0,
        qty=20,
        lot_size=20,
        lots=1,
        exchange="BSE",
        is_spread=True,
        spread_max_loss_per_unit=500.0,
        spread_net_premium_flow_per_unit=-100.0,
    )
    # debit_cost = abs(-100) * 20 = 2000
    # max_loss_total = 500 * 20 = 10000
    # audit = max(2000, 10000) = 10000
    expected = max(abs(-100.0) * 20, 500.0 * 20)
    assert result["audit_net_capital_blocked_secondary"] == pytest.approx(expected, abs=0.01), (
        f"Spread audit should be max(debit={abs(-100.0)*20}, max_loss={500.0*20}) = {expected}, "
        f"got {result['audit_net_capital_blocked_secondary']}"
    )
    meth = result["margin_methodology_string"]
    assert "Spread" in meth
    assert "Audit Metric (Secondary)" in meth
    assert "SEBI SPAN+Exposure framework" in meth
    print(f"  [PASS] SENSEX Bull Call Spread: audit = {result['audit_net_capital_blocked_secondary']:.2f}")


def test_tr_6_4_auto_estimate_price(calc):
    """TR-6.4: Auto-estimate NIFTY price in reference band 24000-26000."""
    price, meth = calc.auto_estimate_underlying_price(
        strike=25000.0,
        premium=250.0,
        option_type="CE",
        underlying="NIFTY",
    )
    assert 24000.0 <= price <= 26000.0, (
        f"NIFTY estimated price {price} outside reference band [24000, 26000]"
    )
    assert "Estimated" in meth, f"Methodology must contain 'Estimated'. Got: {meth}"
    print(f"  [PASS] NIFTY auto-estimate: price = {price:.0f}, methodology = {meth}")


def test_tr_6_5_futures_margin_keys(calc):
    """TR-6.5: SENSEX Future has positive audit margin and correct methodology badges."""
    result = calc.calculate_futures_margin(
        underlying="SENSEX",
        underlying_price=80000.0,
        qty=20,
        lot_size=20,
        lots=1,
        exchange="BSE",
    )
    assert result["audit_net_capital_blocked_secondary"] > 0, (
        f"Futures audit margin must be > 0, got {result['audit_net_capital_blocked_secondary']}"
    )
    meth = result["margin_methodology_string"]
    assert "Future" in meth, f"Methodology must contain 'Future'. Got: {meth}"
    assert "SEBI" in meth, f"Methodology must contain 'SEBI'. Got: {meth}"
    assert "Audit Metric (Secondary)" in meth, f"Methodology must contain 'Audit Metric (Secondary)'. Got: {meth}"
    print(f"  [PASS] SENSEX Future: audit = {result['audit_net_capital_blocked_secondary']:.2f}")
