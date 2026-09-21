from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cost_calculator import (
    FOCostCalculator, allocate_charges_to_strategies,
    CHARGE_METHODOLOGY_REALIZED, CHARGE_METHODOLOGY_FORMULA,
)
from src.models.pydantic_schemas import (
    ContractNoteCharges, ChargeSourceEnum,
)


@pytest.fixture
def calc():
    return FOCostCalculator()


def _read_golden_fixture():
    p = Path(__file__).resolve().parent / "fixtures" / "golden_cost_calculator.csv"
    df = pd.read_csv(p)
    return df[df["fixture_name"] == "AC1_SENSEX_BULL_CALL_LEG"].iloc[0]


class TestCostCalculatorGoldenFixture:
    def test_sensex_bull_call_leg_roundtrip(self, calc):
        """AC-1 / TR-3.1: Golden Fixture (Critical STT=2.40 NOT 3.60 test — proves new 0.1% rate vs superseded 0.15%)."""
        g = _read_golden_fixture()
        res = calc.calculate_option_roundtrip_costs_formula(
            buy_price=float(g.buy_price),
            sell_price=float(g.sell_price),
            lot_size=int(g.lot_size),
            lots=int(g.lots),
            exchange=str(g.exchange),
            slippage_per_point=float(g.slippage_per_point),
        )
        ch = res["charges"]
        qty = int(g.lot_size) * int(g.lots)

        print("\n=== AC-1 Golden Fixture SENSEX 20x BSE buy-INR-100 sell-INR-120 ===")
        print(f"  qty                 = {qty}")
        print(f"  buy_premium         = {res['buy_premium']:.2f}")
        print(f"  sell_premium        = {res['sell_premium']:.2f}")
        print(f"  total_turnover      = {res['total_premium_turnover']:.2f}")
        print(f"  brokerage           = {ch['brokerage']:.2f}  (expected {g.brokerage_expected:.2f})")
        print(f"  stt                 = {ch['stt']:.2f}  (expected {g.stt_expected:.2f}) -- THIS IS THE SUPERSEDE TEST: 0.1% = 2.40, NOT old 0.15% = 3.60")
        print(f"  stamp_duty          = {ch['stamp_duty']:.2f}  (expected {g.stamp_expected:.2f})")
        print(f"  exchange_turnover   = {ch['exchange_turnover_fee']:.2f}")
        print(f"  sebi_turnover       = {ch['sebi_turnover_charges']:.2f}")
        print(f"  gst                 = {ch['gst']:.2f}")
        print(f"  ipft                = {ch['ipft']:.2f}")
        print(f"  slippage            = {ch['slippage']:.2f}  (expected {g.slippage_expected:.2f})")
        print(f"  total_charges       = {ch['total_charges']:.2f}  (expect [{g.total_charges_lower:.2f} .. {g.total_charges_upper:.2f}])")
        print(f"  gross_pnl_leg       = {res['pnl']['gross_pnl_leg']:.2f}")
        print(f"  net_pnl_leg         = {res['pnl']['net_pnl_leg']:.2f}")

        # Explicit hand-arithmetic assertions
        assert ch["brokerage"] == pytest.approx(40.0, abs=0.005), (
            "1 round-trip leg = 2 orders x INR-20 flat per order = INR-40 (Zerodha flat discount brokerage)"
        )
        # SUPERSEDE TEST: STT must be 2.40 (0.1% of 2400), NOT 3.60 (superseded 0.15% draft)
        hand_stt = (qty * float(g.sell_price)) * 0.001
        assert hand_stt == pytest.approx(2.40, abs=0.005)
        assert ch["stt"] == pytest.approx(2.40, abs=0.005), (
            f"STT is the critical spec update. Expected 0.1%x sell_premium={hand_stt:.2f}=2.40. "
            f"Got {ch['stt']:.4f}. If this is ~3.60 then the superseded 0.15% STT draft was not removed."
        )
        hand_stamp = (qty * float(g.buy_price)) * 3e-5  # buy-premium only
        assert hand_stamp == pytest.approx(0.06, abs=0.005)
        assert ch["stamp_duty"] == pytest.approx(0.06, abs=0.005)
        hand_slippage = 0.10 * qty * 2  # entry + exit
        assert hand_slippage == pytest.approx(4.00, abs=0.005)
        assert ch["slippage"] == pytest.approx(4.00, abs=0.005)

        # +/- INR 0.05 tolerance window on total (NFR-1)
        assert float(g.total_charges_lower) - 0.05 <= ch["total_charges"] <= float(g.total_charges_upper) + 0.05, (
            f"total_charges {ch['total_charges']:.4f} outside hand-calc [{g.total_charges_lower}, {g.total_charges_upper}] +/-0.05 window"
        )
        # Methodology tag correct
        assert "FORMULA computed per Zerodha" in res["methodology_note"]
        assert "STT 0.1%" in res["methodology_note"]

    def test_nifty_nse_25_lot_buy_150_sell_180(self, calc):
        """NIFTY NSE test: buy=150 sell=180 lot_size=25 -> gross=750; stt=25*180*0.001=4.50."""
        res = calc.calculate_option_roundtrip_costs_formula(
            buy_price=150.0, sell_price=180.0, lot_size=25, lots=1, exchange="NSE",
        )
        ch = res["charges"]
        assert res["pnl"]["gross_pnl_leg"] == pytest.approx((180-150)*25, abs=0.01), "gross=points*qty"
        assert ch["brokerage"] == pytest.approx(40.0, abs=0.005)
        assert ch["stt"] == pytest.approx(25 * 180 * 0.001, abs=0.005), "STT 0.1% on sell premium"
        # NSE exchange rate != BSE rate → must be different values
        sensex = calc.calculate_option_roundtrip_costs_formula(
            buy_price=150.0, sell_price=180.0, lot_size=25, lots=1, exchange="BSE",
        )
        assert (
            abs(ch["exchange_turnover_fee"] - sensex["charges"]["exchange_turnover_fee"]) > 0.001
        ), "NSE 0.03553% vs BSE 0.0325% → different exchange fee values expected (differentiation test)"

    def test_two_leg_spread_brokerage_sum_80(self, calc):
        """2-leg spread brokerage sum = 4 orders x INR-20 = INR-80; calculate_two_leg_spread_total_costs validates same."""
        leg1 = calc.calculate_option_roundtrip_costs_formula(
            buy_price=50.0, sell_price=75.0, lot_size=20, lots=1, exchange="BSE", slippage_per_point=0.0,
        )
        leg2 = calc.calculate_option_roundtrip_costs_formula(
            buy_price=25.0, sell_price=15.0, lot_size=20, lots=1, exchange="BSE", slippage_per_point=0.0,
        )
        total_brokerage = leg1["charges"]["brokerage"] + leg2["charges"]["brokerage"]
        assert total_brokerage == pytest.approx(80.0, abs=0.005), (
            "2 legs x 2 sides x INR-20/order = INR-80 total FORMULA spread brokerage"
        )
        combined = calc.calculate_two_leg_spread_total_costs(leg1, leg2)
        assert combined["line_items_2leg_sum"]["brokerage"] == pytest.approx(80.0, abs=0.005)

    def test_realized_contract_note_overrides_formula_exact(self, calc):
        """AC-2 / TR-3.2: Realized values from screenshot stored EXACT byte-for-byte; not formula-derived; charge_source tag correct."""
        cn = ContractNoteCharges(
            brokerage_amount=60.00,
            exchange_turnover_fee_amount=5.25,
            securities_transaction_tax_stt=3.10,
            sebi_turnover_charges=0.05,
            stamp_duty=0.10,
            gst=12.30,
            total_charges_grand_total=80.80,
        )
        model = calc.from_realized_contract_note(
            strategy_run_id=42, report_date=date(2026,9,3), realized=cn,
        )
        assert model.charge_source == ChargeSourceEnum.REALIZED_VIRTUAL_CONTRACT_NOTE.value, (
            "charge_source must be REALIZED not FORMULA"
        )
        # All 6 values + total stored exact (2dp zero tolerance on realized byte-for-byte)
        assert model.brokerage == 60.00, f"realized brokerage override lost: {model.brokerage}"
        assert model.exchange_turnover_fee == 5.25
        assert model.stt == 3.10
        assert model.sebi_turnover_charges == 0.05
        assert model.stamp_duty == 0.10
        assert model.gst == 12.30
        assert model.total_charges == 80.80, f"realized total override lost: {model.total_charges}"
        assert "REALIZED per Zerodha" in (model.methodology_note or "")
        assert "Reconciliation: PASS" in (model.methodology_note or "")

    def test_bse_vs_nse_differentiation_explicit(self, calc):
        """Same inputs → NSE fee != BSE fee by correct rates (0.03553% vs 0.0325%)."""
        common_kwargs = dict(buy_price=200.0, sell_price=220.0, lot_size=15, lots=1, slippage_per_point=0.0)
        nse = calc.calculate_option_roundtrip_costs_formula(**common_kwargs, exchange="NSE")
        bse = calc.calculate_option_roundtrip_costs_formula(**common_kwargs, exchange="BSE")
        turnover = nse["total_premium_turnover"]
        hand_nse = 0.0003553 * turnover
        hand_bse = 0.000325 * turnover
        assert nse["charges"]["exchange_turnover_fee"] == pytest.approx(hand_nse, abs=0.005)
        assert bse["charges"]["exchange_turnover_fee"] == pytest.approx(hand_bse, abs=0.005)
        assert nse["charges"]["exchange_turnover_fee"] > bse["charges"]["exchange_turnover_fee"]


class TestChargeAllocation:
    def test_allocate_proportional_total_matches_aggregate(self, calc):
        """TR-3.3: Σ per-strategy allocated total_charges == aggregate input total (0.001 INR tolerance)."""
        # Synthetic: 3 strategies with varied premium_turnover
        strategies = [
            {"strategy_run_id": 1, "premium_turnover": 100_000.0},
            {"strategy_run_id": 2, "premium_turnover": 200_000.0},
            {"strategy_run_id": 3, "premium_turnover": 150_000.0},
        ]
        # Numbers derived from a SENSEX day:
        aggregate = {
            "brokerage": 240.0,
            "exchange_turnover_fee": 12.80,
            "stt": 24.60,
            "sebi_turnover_charges": 0.45,
            "stamp_duty": 1.20,
            "gst": 45.60,
            "ipft": 0.05,
            "slippage": 20.00,
            "total_charges": 344.70,
            "charge_source": ChargeSourceEnum.FORMULA_COMPUTED.value,
        }
        allocated = allocate_charges_to_strategies(
            strategy_run_rows=strategies,
            aggregate_charges=aggregate,
            method="PROPORTIONAL_PREMIUM_TURNOVER",
            report_date=date(2026,9,3),
        )
        assert set(allocated.keys()) == {1,2,3}
        total_back = sum(a.total_charges for a in allocated.values())
        assert total_back == pytest.approx(aggregate["total_charges"], abs=0.001), (
            f"Allocation grand total mismatch: Σ={total_back:.4f} vs input={aggregate['total_charges']:.4f}"
        )
        # Weights proportional: strategy 2 has highest turnover → largest absolute charges share
        sorted_by_share = sorted(allocated.values(), key=lambda a: a.total_charges)
        assert sorted_by_share[2].strategy_run_id == 2, "strategy 2 has highest premium → largest allocation"
        assert sorted_by_share[0].strategy_run_id == 1, "strategy 1 lowest premium → smallest"
        # Source tag propagated
        for a in allocated.values():
            assert a.charge_source == ChargeSourceEnum.FORMULA_COMPUTED.value
            assert a.allocation_method == "PROPORTIONAL_PREMIUM_TURNOVER"
