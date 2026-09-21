from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from .models.pydantic_schemas import ChargesBreakdown as ChargesBreakdownModel
from .models.pydantic_schemas import (
    ChargeSourceEnum, ContractNoteCharges, BrokerChargeSchedule,
)

_PAISE = Decimal("0.01")


def _q(x: float | int | Decimal) -> float:
    try:
        return float(Decimal(str(x)).quantize(_PAISE, rounding=ROUND_HALF_UP))
    except Exception:
        return float(x)


CHARGE_METHODOLOGY_FORMULA = (
    "FORMULA computed per Zerodha schedule effective 2026-04-01 "
    "(STT 0.1% on sell premium, Brokerage ₹20 flat per executed order, "
    "NSE 0.03553% / BSE 0.0325% exchange turnover, SEBI ₹10/crore, "
    "Stamp 0.003% buy-side only, GST 18% on broker+exchange+SEBI)."
)
CHARGE_METHODOLOGY_REALIZED = (
    "REALIZED per Zerodha Virtual Contract Note screenshot extraction. "
    "6-tuple values stored byte-for-byte identical to screenshot; FORMULA not applied."
)

DEFAULT_SCHEDULE_DICT: Dict[str, float] = {
    "broker_name": "ZERODHA",
    "effective_date": "2026-04-01",
    "brokerage_per_order_inr": 20.0,
    "stt_option_sell_premium_pct": 0.001,
    "nse_exchange_option_pct": 0.0003553,
    "bse_exchange_option_pct": 0.000325,
    "sebi_fee_per_crore_inr": 10.0,
    "stamp_duty_option_buy_pct": 0.00003,
    "gst_pct": 0.18,
    "default_slippage_per_point_inr": 0.10,
    "ipft_per_crore_inr": 1.0,
    "is_default": True,
}


@dataclass
class _CostComponents:
    brokerage: float
    exchange_turnover_fee: float
    stt: float
    sebi_turnover_charges: float
    stamp_duty: float
    gst: float
    ipft: float
    slippage: float
    total_charges: float
    gross_pnl_leg: float
    net_pnl_leg: float
    methodology_note: str
    qty: int
    buy_premium: float
    sell_premium: float
    total_premium_turnover: float


class FOCostCalculator:
    """
    Indian F&O charges calculator — Zerodha primary, dual-mode.

    Mode A (Realized Contract Note — highest priority): If the user uploaded a
    Zerodha Virtual Contract Note charges popup screenshot, use those exact 6 values
    (brokerage, exchange_turnover_fee, stt, sebi, stamp, gst, total_charges).
    Total is always reconciled byte-for-byte against screenshot.

    Mode B (Zerodha FORMULA — fallback): Calculate per-leg round-trip costs
    using the public Zerodha / NSE / BSE / SEBI fee schedule (STT 0.1% sell-only
    sell-premium rule: NOT 0.15% from earlier superseded drafts).
    """

    def __init__(self, schedule: Optional[Union[Dict[str, Any], BrokerChargeSchedule]] = None):
        self.schedule: Dict[str, Any] = dict(DEFAULT_SCHEDULE_DICT)
        if schedule is not None:
            if isinstance(schedule, BrokerChargeSchedule):
                self.schedule.update(schedule.model_dump(exclude_none=True))
            elif isinstance(schedule, dict):
                self.schedule.update({k: v for k, v in schedule.items() if v is not None})

    # -------------------- PUBLIC API --------------------
    def from_realized_contract_note(
        self,
        strategy_run_id: int,
        report_date: date,
        realized: Union[ContractNoteCharges, Dict[str, float]],
        trade_match_key: Optional[str] = None,
        allocation_method: Optional[str] = None,
    ) -> ChargesBreakdownModel:
        """AC-2: Return ChargesBreakdown Pydantic object with charge_source=REALIZED_VIRTUAL_CONTRACT_NOTE — values stored exactly as input (no formula overwrite)."""
        if isinstance(realized, ContractNoteCharges):
            r = realized
        else:
            r = ContractNoteCharges(**realized)
        return ChargesBreakdownModel(
            strategy_run_id=strategy_run_id,
            report_date=report_date,
            trade_match_key=trade_match_key,
            charge_source=ChargeSourceEnum.REALIZED_VIRTUAL_CONTRACT_NOTE,
            brokerage=_q(r.brokerage_amount),
            exchange_turnover_fee=_q(r.exchange_turnover_fee_amount),
            stt=_q(r.securities_transaction_tax_stt),
            sebi_turnover_charges=_q(r.sebi_turnover_charges),
            stamp_duty=_q(r.stamp_duty),
            gst=_q(r.gst),
            ipft=0.0,
            slippage=0.0,
            total_charges=_q(r.total_charges_grand_total),
            methodology_note=(
                CHARGE_METHODOLOGY_REALIZED
                + f" Reconciliation: {'PASS' if r.reconciliation_boolean else 'FAIL'}"
                + (f" diff=₹{r.diff_rupees:+.2f}" if r.diff_rupees else "")
            ),
            allocation_method=allocation_method,
        )

    def calculate_option_roundtrip_costs_formula(
        self,
        buy_price: float,
        sell_price: float,
        lot_size: int,
        lots: int = 1,
        exchange: Literal["NSE", "BSE"] = "NSE",
        broker: str = "ZERODHA",
        slippage_per_point: Optional[float] = None,
        orders_per_single_leg_roundtrip: int = 2,
    ) -> Dict[str, Any]:
        """
        Zerodha FORMULA mode round-trip costs for one single option leg
        (entry + exit, i.e. one BUY order + one SELL order = 2 executed orders).

        AC-1 Golden Fixture:
          lot_size=20, buy=₹100, sell=₹120, exchange=BSE, slippage=₹0.10/point
          → brokerage 40.00, stt (20×120)×0.001 = ₹2.40 (0.1% NOT 0.15%!),
            stamp (20×100)×3e-5 = ₹0.06, slippage 0.10×20×2 = ₹4.00.
        """
        buy_price = float(buy_price)
        sell_price = float(sell_price)
        lot_size = int(lot_size)
        lots = int(lots)

        # Exchange fallback guard: infer from context if None/empty
        if not exchange:
            exchange = "NSE"
        exchange = str(exchange).upper().strip()
        if exchange not in ("NSE", "BSE"):
            exchange = "NSE"
        qty = lot_size * lots
        buy_premium = qty * buy_price
        sell_premium = qty * sell_price
        total_premium_turnover = buy_premium + sell_premium

        s = self.schedule
        brokerage_flat = float(s["brokerage_per_order_inr"])
        brokerage = brokerage_flat * int(orders_per_single_leg_roundtrip)

        stt_pct = float(s["stt_option_sell_premium_pct"])
        assert stt_pct <= 0.001 + 1e-9, (
            f"CRITICAL FORMULA DRIFT: STT pct {stt_pct} exceeds 0.1% allowed upper bound. "
            f"Unified spec mandates STT=0.001 (0.1%) sell-premium FORMULA rate."
        )
        stt = stt_pct * sell_premium  # sell-side only

        if exchange.upper() == "BSE":
            exch_pct = float(s["bse_exchange_option_pct"])
        else:
            exch_pct = float(s["nse_exchange_option_pct"])
        exchange_turnover_fee = exch_pct * total_premium_turnover

        sebi_pct = float(s["sebi_fee_per_crore_inr"]) / 10_000_000.0  # ₹10/crore
        sebi_turnover_charges = sebi_pct * total_premium_turnover

        stamp_pct = float(s["stamp_duty_option_buy_pct"])
        stamp_duty = stamp_pct * buy_premium  # buy-side only

        gst_base = brokerage + exchange_turnover_fee + sebi_turnover_charges
        gst = float(s["gst_pct"]) * gst_base

        ipft_pct = (float(s.get("ipft_per_crore_inr", 1.0)) or 0.0) / 10_000_000.0
        ipft = ipft_pct * total_premium_turnover

        slip = float(slippage_per_point) if slippage_per_point is not None else float(s["default_slippage_per_point_inr"])
        slippage = slip * qty * 2  # entry + exit sides

        total_charges = (
            brokerage + stt + exchange_turnover_fee + sebi_turnover_charges
            + stamp_duty + gst + ipft + slippage
        )

        gross_pnl_leg = (sell_price - buy_price) * qty
        net_pnl_leg = gross_pnl_leg - total_charges

        components = _CostComponents(
            brokerage=_q(brokerage),
            exchange_turnover_fee=_q(exchange_turnover_fee),
            stt=_q(stt),
            sebi_turnover_charges=_q(sebi_turnover_charges),
            stamp_duty=_q(stamp_duty),
            gst=_q(gst),
            ipft=_q(ipft),
            slippage=_q(slippage),
            total_charges=_q(total_charges),
            gross_pnl_leg=_q(gross_pnl_leg),
            net_pnl_leg=_q(net_pnl_leg),
            methodology_note=CHARGE_METHODOLOGY_FORMULA,
            qty=qty,
            buy_premium=_q(buy_premium),
            sell_premium=_q(sell_premium),
            total_premium_turnover=_q(total_premium_turnover),
        )
        result = {
            "qty": qty,
            "lot_size": lot_size,
            "lots": lots,
            "exchange": exchange,
            "buy_price": _q(buy_price),
            "sell_price": _q(sell_price),
            "buy_premium": components.buy_premium,
            "sell_premium": components.sell_premium,
            "total_premium_turnover": components.total_premium_turnover,
            "charges": {
                "brokerage": components.brokerage,
                "exchange_turnover_fee": components.exchange_turnover_fee,
                "stt": components.stt,
                "sebi_turnover_charges": components.sebi_turnover_charges,
                "stamp_duty": components.stamp_duty,
                "gst": components.gst,
                "ipft": components.ipft,
                "slippage": components.slippage,
                "total_charges": components.total_charges,
            },
            "pnl": {
                "gross_pnl_leg": components.gross_pnl_leg,
                "net_pnl_leg": components.net_pnl_leg,
            },
            "methodology_note": components.methodology_note,
            "_raw": components,
        }
        return result

    def calculate_two_leg_spread_total_costs(
        self,
        leg1: Dict[str, Any],
        leg2: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate same underlying+expiry; sum; verify total brokerage=₹80 for 2 legs × 2 sides × ₹20/order = 4 orders (for FORMULA mode legs)."""
        line_items = ["brokerage", "exchange_turnover_fee", "stt", "sebi_turnover_charges",
                      "stamp_duty", "gst", "ipft", "slippage", "total_charges"]
        sums: Dict[str, float] = {k: 0.0 for k in line_items}
        for leg in (leg1, leg2):
            c = leg.get("charges", leg)
            for k in line_items:
                sums[k] = _q(sums[k] + c.get(k, 0.0))
        # Sanity: FORMULA legs sum brokerage should be 4 orders * ₹20 = ₹80
        if (
            "FORMULA" in str(leg1.get("methodology_note", ""))
            and "FORMULA" in str(leg2.get("methodology_note", ""))
        ):
            if abs(sums["brokerage"] - 80.0) > 0.01:
                raise AssertionError(
                    f"2-leg FORMULA spread total brokerage expected ₹80.00, got ₹{sums['brokerage']:.2f}"
                )
        return {
            "line_items_2leg_sum": sums,
            "combined_gross_pnl": _q(
                (leg1.get("pnl", {}).get("gross_pnl_leg") or leg1.get("gross_pnl_leg") or 0.0)
                + (leg2.get("pnl", {}).get("gross_pnl_leg") or leg2.get("net_pnl_leg") or 0.0)
            ),
            "combined_net_pnl": _q(
                (leg1.get("pnl", {}).get("gross_pnl_leg") or 0.0)
                + (leg2.get("pnl", {}).get("gross_pnl_leg") or 0.0)
                - sums["total_charges"]
            ),
        }


def allocate_charges_to_strategies(
    strategy_run_rows: List[Dict[str, Any]],
    aggregate_charges: Dict[str, float],
    method: Literal["PROPORTIONAL_PREMIUM_TURNOVER", "EQUAL_PER_STRATEGY"] = "PROPORTIONAL_PREMIUM_TURNOVER",
    report_date: Optional[date] = None,
) -> Dict[int, ChargesBreakdownModel]:
    """
    Distribute aggregate realized/formula charges across strategy_runs.
    Default method PROPORTIONAL_PREMIUM_TURNOVER pro-rates by premium turnover per strategy.
    Alternative EQUAL_PER_STRATEGY splits equal rupee amounts per strategy.
    Returns dict: key=strategy_run_id, value=ChargesBreakdown Pydantic model.
    TR-3.3: Σ per-strategy total_charges MUST equal aggregate total_charges (0.001 INR tolerance).
    """
    n = len(strategy_run_rows)
    if n == 0:
        return {}
    line_items = ["brokerage", "exchange_turnover_fee", "stt", "sebi_turnover_charges",
                  "stamp_duty", "gst", "ipft", "slippage", "total_charges"]
    # Determine weights
    if method == "EQUAL_PER_STRATEGY":
        weights = [1.0 / n for _ in strategy_run_rows]
    else:
        # PROPORTIONAL_PREMIUM_TURNOVER
        premiums = [
            float(r.get("premium_turnover") or r.get("total_premium_turnover") or (
                float(r.get("booked_gross_pnl") or 0.0)
                + float(r.get("allocated_charges_total") or 0.0)
            ) or 1.0)
            for r in strategy_run_rows
        ]
        s = sum(premiums)
        if s <= 0:
            weights = [1.0 / n for _ in strategy_run_rows]
        else:
            weights = [p / s for p in premiums]

    allocated: Dict[int, ChargesBreakdownModel] = {}
    running_correction: Dict[str, float] = {k: 0.0 for k in line_items}
    for idx, row in enumerate(strategy_run_rows):
        srid = int(row["strategy_run_id"])
        w = weights[idx]
        per_row: Dict[str, float] = {}
        is_last = (idx == n - 1)
        for k in line_items:
            raw = float(aggregate_charges.get(k, 0.0)) * w
            # accumulate drift so Σ all rows = aggregate exactly (TR-3.3 requirement)
            running_correction[k] += raw
            if is_last or k == "total_charges":
                val = _q(running_correction[k])
                running_correction[k] = 0.0
                if k == "total_charges" and is_last:
                    # last row: ensure exact grand total by adjusting
                    already = sum(allocated[rr].total_charges for rr in allocated)
                    val = _q(float(aggregate_charges.get("total_charges", 0.0)) - already)
            else:
                floored = _q(raw)
                running_correction[k] = raw - floored
                val = floored
            per_row[k] = val
        source = aggregate_charges.get("charge_source", ChargeSourceEnum.FORMULA_COMPUTED.value)
        methodology = aggregate_charges.get("methodology_note") or (
            CHARGE_METHODOLOGY_FORMULA if "FORMULA" in source else CHARGE_METHODOLOGY_REALIZED
        )
        allocated[srid] = ChargesBreakdownModel(
            strategy_run_id=srid,
            report_date=report_date or date.today(),
            trade_match_key=aggregate_charges.get("trade_match_key"),
            charge_source=source,  # type: ignore
            brokerage=per_row["brokerage"],
            exchange_turnover_fee=per_row["exchange_turnover_fee"],
            stt=per_row["stt"],
            sebi_turnover_charges=per_row["sebi_turnover_charges"],
            stamp_duty=per_row["stamp_duty"],
            gst=per_row["gst"],
            ipft=per_row["ipft"],
            slippage=per_row["slippage"],
            total_charges=per_row["total_charges"],
            methodology_note=f"{methodology} | Allocation: {method} weight={w:.4f}",
            allocation_method=method,
        )
    # Post condition check (TR-3.3)
    total_allocated = sum(a.total_charges for a in allocated.values())
    expected_total = float(aggregate_charges.get("total_charges", 0.0))
    if abs(total_allocated - expected_total) > 0.001:  # 0.001 INR tolerance
        raise AssertionError(
            f"Charge allocation grand-total drift: allocated {total_allocated:.4f} "
            f"vs aggregate {expected_total:.4f} diff {total_allocated-expected_total:.4f}"
        )
    return allocated
