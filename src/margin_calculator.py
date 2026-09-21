from __future__ import annotations

from typing import Optional, Dict, Any, Tuple

from .market_knowledge import MarketKnowledge


# Reference price bands for 2026 (used by auto_estimate_underlying_price)
_REFERENCE_BANDS: Dict[str, Tuple[float, float]] = {
    "NIFTY": (24000.0, 26000.0),
    "BANKNIFTY": (50000.0, 55000.0),
    "SENSEX": (75000.0, 85000.0),
    "FINNIFTY": (22000.0, 25000.0),
    "MIDCPNIFTY": (9000.0, 11000.0),
}


class SEBIMarginCalculator:
    """Audit metric only. Founder report ROI denominator remains Capital Deployed from Tradetron card / operator review.

    Implements SEBI SPAN+Exposure margin framework for Indian F&O index derivatives.
    All margin figures produced here are *secondary audit metrics* and are never used
    as the primary ROI denominator.
    """

    def __init__(self, market_knowledge: Optional[MarketKnowledge] = None):
        self._mk = market_knowledge if market_knowledge is not None else MarketKnowledge()

    # ------------------------------------------------------------------
    # 1. Position architecture classification
    # ------------------------------------------------------------------
    def classify_position_architecture(
        self,
        side: str,
        option_type: str,
        strategy_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Classify a position into one of the canonical margin architectures."""
        if strategy_context and strategy_context.get("is_spread"):
            net_premium = strategy_context.get("net_premium_flow", 0.0)
            if net_premium < 0:
                return "DEBIT_SPREAD"
            return "CREDIT_SPREAD"

        if option_type == "FUT":
            return "FUTURE"

        if side == "BUY" and option_type in ("CE", "PE"):
            return "LONG_OPTION"

        if side == "SELL" and option_type in ("CE", "PE"):
            return "SHORT_OPTION"

        return "NAKED"

    # ------------------------------------------------------------------
    # 2. Option margin calculation
    # ------------------------------------------------------------------
    def calculate_option_margin(
        self,
        underlying: str,
        underlying_price: float,
        option_type: str,
        strike: float,
        premium_per_point: float,
        qty: int,
        lot_size: int,
        lots: int,
        exchange: str = "NSE",
        is_spread: bool = False,
        spread_max_loss_per_unit: Optional[float] = None,
        spread_net_premium_flow_per_unit: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Calculate option margin under SEBI SPAN+Exposure framework (Audit Metric Secondary)."""
        params = self._mk.get_margin_params(underlying)
        span_pct = params["span_margin_pct"]
        exposure_pct = params["exposure_margin_pct"]

        notional_value = underlying_price * qty
        span_margin = notional_value * span_pct
        exposure_margin = max(notional_value * exposure_pct, 100000.0 * lots)
        total_margin_required = span_margin + exposure_margin
        premium_paid_received = premium_per_point * qty

        price_badge = "Real/Provided"

        if is_spread:
            # --- SPREAD ---
            debit_cost = 0.0
            if spread_net_premium_flow_per_unit is not None and spread_net_premium_flow_per_unit < 0:
                debit_cost = abs(spread_net_premium_flow_per_unit) * qty
            max_loss_total = 0.0
            if spread_max_loss_per_unit is not None:
                max_loss_total = spread_max_loss_per_unit * qty
            audit_net = max(debit_cost, max_loss_total)
            methodology = (
                f"Spread: SPAN benefit applied. Margin = max(debit paid, max loss). "
                f"Audit Metric (Secondary) | SEBI SPAN+Exposure framework | "
                f"Underlying price: {price_badge}"
            )
        elif premium_per_point > 0:
            # --- LONG OPTION (buyer pays premium) ---
            audit_net = premium_paid_received
            methodology = (
                f"Long option: only premium blocked for audit metric. "
                f"Audit Metric (Secondary) | SEBI SPAN+Exposure framework | "
                f"Underlying price: {price_badge}"
            )
        else:
            # --- SHORT OPTION (seller receives premium) ---
            audit_net = max(total_margin_required - abs(premium_paid_received), abs(premium_paid_received))
            methodology = (
                f"Short option: SPAN+Exposure margin required, reduced by premium received. "
                f"Audit Metric (Secondary) | SEBI SPAN+Exposure framework | "
                f"Underlying price: {price_badge}"
            )

        return {
            "notional_value": notional_value,
            "span_margin": span_margin,
            "exposure_margin": exposure_margin,
            "total_margin_required": total_margin_required,
            "premium_paid_received": premium_paid_received,
            "audit_net_capital_blocked_secondary": audit_net,
            "margin_methodology_string": methodology,
        }

    # ------------------------------------------------------------------
    # 3. Futures margin calculation
    # ------------------------------------------------------------------
    def calculate_futures_margin(
        self,
        underlying: str,
        underlying_price: float,
        qty: int,
        lot_size: int,
        lots: int,
        exchange: str = "NSE",
    ) -> Dict[str, Any]:
        """Calculate futures margin under SEBI SPAN+Exposure framework (Audit Metric Secondary)."""
        params = self._mk.get_margin_params(underlying)
        span_pct = params["span_margin_pct"]
        exposure_pct = params["exposure_margin_pct"]

        notional_value = underlying_price * qty
        span_margin = notional_value * span_pct
        exposure_margin = notional_value * exposure_pct
        total_margin_required = span_margin + exposure_margin

        methodology = (
            f"Future: Full SPAN+Exposure margin required. "
            f"Audit Metric (Secondary) | SEBI SPAN+Exposure framework | "
            f"Underlying price: Real/Provided"
        )

        return {
            "notional_value": notional_value,
            "span_margin": span_margin,
            "exposure_margin": exposure_margin,
            "total_margin_required": total_margin_required,
            "audit_net_capital_blocked_secondary": total_margin_required,
            "margin_methodology_string": methodology,
        }

    # ------------------------------------------------------------------
    # 4. Auto-estimate underlying price
    # ------------------------------------------------------------------
    def auto_estimate_underlying_price(
        self,
        strike: float,
        premium: float,
        option_type: str,
        underlying: str,
        moneyness_context: Optional[str] = None,
    ) -> Tuple[float, str]:
        """Estimate the underlying price when not directly available.

        Returns (estimated_price, methodology_string).
        """
        u = underlying.upper().strip()

        if u in _REFERENCE_BANDS:
            low, high = _REFERENCE_BANDS[u]
            midpoint = (low + high) / 2.0
            methodology = (
                f"Estimated: {u} reference band [{low:.0f}-{high:.0f}], midpoint {midpoint:.0f} used. "
                f"Audit Metric (Secondary) | SEBI SPAN+Exposure framework"
            )
            return (midpoint, methodology)

        # Fallback: use strike as proxy
        estimated = strike
        methodology = (
            f"Estimated: No reference band for {u}; strike {strike:.0f} used as proxy. "
            f"Audit Metric (Secondary) | SEBI SPAN+Exposure framework"
        )
        return (estimated, methodology)
