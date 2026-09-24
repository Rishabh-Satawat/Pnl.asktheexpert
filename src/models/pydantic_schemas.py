from __future__ import annotations

import re
import uuid
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any, Literal

from pydantic import (
    BaseModel, Field, field_validator, ConfigDict,
    ValidationError, model_validator,
)


_SIDE_RE = re.compile(r"^(BUY|SELL)$", re.IGNORECASE)
_OPTION_TYPE_RE = re.compile(r"^(CE|PE|FUT)$", re.IGNORECASE)
_RUPEE_SCALE = Decimal("0.01")


def _round_inr(v: float | int | Decimal | None) -> float | None:
    if v is None:
        return None
    try:
        return float(Decimal(str(v)).quantize(_RUPEE_SCALE))
    except Exception:
        return float(v)


class SourceScreenTypeEnum(str, Enum):
    TRADETRON_STRATEGY_CARD = "TRADETRON_STRATEGY_CARD"
    ZERODHA_KITE_POSITIONS = "ZERODHA_KITE_POSITIONS"
    ZERODHA_VIRTUAL_CONTRACT_NOTE = "ZERODHA_VIRTUAL_CONTRACT_NOTE"
    MANUAL_CSV = "MANUAL_CSV"
    UNKNOWN = "UNKNOWN"


class ProcessingStatusEnum(str, Enum):
    PENDING = "PENDING"
    PARSED = "PARSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    PERSISTED = "PERSISTED"
    FAILED = "FAILED"


class DeploymentStatusEnum(str, Enum):
    LIVE_AUTO = "LIVE_AUTO"
    EXITED = "EXITED"
    PARTIAL = "PARTIAL"
    OTHER = "OTHER"


class ChargeSourceEnum(str, Enum):
    REALIZED_VIRTUAL_CONTRACT_NOTE = "REALIZED_VIRTUAL_CONTRACT_NOTE"
    FORMULA_COMPUTED = "FORMULA_COMPUTED"


class OptionTypeEnum(str, Enum):
    CE = "CE"
    PE = "PE"
    FUT = "FUT"


class SideEnum(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class _BaseRupeeModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="ignore")

    @field_validator("*", mode="after")
    @classmethod
    def _numerics_non_negative_where_applicable(cls, v: Any, info):
        non_neg_fields = {
            "brokerage", "exchange_turnover_fee", "stt", "sebi_turnover_charges",
            "stamp_duty", "gst", "ipft", "slippage", "total_charges",
            "execution_price", "gross_premium", "strike_price",
            "capital_deployed_allocated", "lot_size", "lots", "quantity",
            "brokerage_per_order_inr", "stt_option_sell_premium_pct",
            "span_margin_pct", "exposure_margin_pct", "peak_equity",
        }
        if info.field_name in non_neg_fields and isinstance(v, (int, float, Decimal)):
            if v < 0:
                raise ValueError(f"{info.field_name} must be non-negative")
        return v


class RawSourceFile(_BaseRupeeModel):
    id: Optional[int] = None
    sha256_hash: str = Field(min_length=8, max_length=64)
    screen_type: SourceScreenTypeEnum = SourceScreenTypeEnum.UNKNOWN
    upload_filename: str = Field(min_length=1, max_length=255)
    upload_timestamp: datetime = Field(default_factory=datetime.utcnow)
    file_size_bytes: Optional[int] = Field(default=None, ge=0)
    processing_status: ProcessingStatusEnum = ProcessingStatusEnum.PENDING
    overall_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    broker_identified: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    structured_json_response: Optional[Dict[str, Any]] = None
    visible_underlying_levels: Optional[Dict[str, float]] = None
    visible_margin_hud: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    extra_metadata: Optional[Dict[str, Any]] = None


class LegGreek(BaseModel):
    leg_label: Optional[str] = None
    instrument_symbol: Optional[str] = None
    option_type: Optional[OptionTypeEnum] = None
    delta: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv_pct: Optional[float] = None
    ltp: Optional[float] = None


class StrategyRun(_BaseRupeeModel):
    id: Optional[int] = None
    strategy_run_uuid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    report_date: date
    strategy_name: str = Field(min_length=1, max_length=255)
    deployment_status: DeploymentStatusEnum = DeploymentStatusEnum.LIVE_AUTO
    multiplier_x: int = Field(default=1, ge=1)
    counter_int: Optional[int] = Field(default=None, ge=0)
    capital_deployed_allocated: float = Field(ge=0.0)
    entry_timestamp_ist: Optional[datetime] = None
    exit_timestamp_ist: Optional[datetime] = None
    underlying_segment: Optional[str] = None
    legs_greeks: Optional[List[LegGreek]] = None
    booked_gross_pnl: float = Field(default=0.0)
    allocated_charges_total: float = Field(default=0.0)
    net_pnl: float = Field(default=0.0)
    net_roi_pct: Optional[float] = None
    operational_notes: Optional[str] = None
    capital_provenance_tag: Optional[str] = None
    source_file_id: Optional[int] = None
    parsing_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    manually_edited: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def _roi_consistency(self):
        if self.capital_deployed_allocated and self.capital_deployed_allocated > 0:
            if self.net_roi_pct is None:
                self.net_roi_pct = round((self.net_pnl / self.capital_deployed_allocated) * 100.0, 4)
        return self


class TradeExecution(_BaseRupeeModel):
    id: Optional[int] = None
    execution_uuid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strategy_run_id: int
    report_date: date
    vendor_symbol: str = Field(min_length=1, max_length=120)
    underlying: Optional[str] = None
    segment: Optional[str] = None
    exchange: Optional[str] = None
    expiry_date: Optional[date] = None
    strike_price: Optional[float] = None
    option_type: Optional[OptionTypeEnum] = None
    instrument_type: Optional[str] = None
    side: SideEnum
    lots: int = Field(default=1, ge=1)
    lot_size: int = Field(default=0, ge=0)
    quantity: int = Field(ge=1)
    execution_price: float = Field(gt=0)
    gross_premium: Optional[float] = Field(default=None, ge=0.0)
    product_type: Optional[Literal["MIS", "NRML", "CNC"]] = None
    ltp_at_extract: Optional[float] = None
    individual_leg_pnl: Optional[float] = None
    execution_timestamp_ist: Optional[datetime] = None
    matched_pair_id: Optional[str] = None
    is_entry_leg: Optional[bool] = None
    parsing_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    manually_edited: bool = False
    source_file_id: Optional[int] = None
    extra_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("side", mode="before")
    @classmethod
    def _normalize_side(cls, v):
        if isinstance(v, str):
            up = v.strip().upper()
            if up in {"BUY", "LONG", "B"}:
                return "BUY"
            if up in {"SELL", "SHORT", "S"}:
                return "SELL"
        return v

    @field_validator("option_type", mode="before")
    @classmethod
    def _normalize_opt(cls, v):
        if isinstance(v, str):
            up = v.strip().upper()
            if up in {"CE", "CALL", "CALLS"}:
                return "CE"
            if up in {"PE", "PUT", "PUTS"}:
                return "PE"
            if up in {"FUT", "FUTURE", "FUTURES"}:
                return "FUT"
        return v

    @model_validator(mode="after")
    def _consistent_qty(self):
        if self.lot_size and self.lots:
            expected = self.lot_size * self.lots
            if self.quantity <= 0:
                self.quantity = expected
        if self.gross_premium is None and self.execution_price and self.quantity:
            self.gross_premium = round(self.execution_price * self.quantity, 2)
        return self


class ChargesBreakdown(_BaseRupeeModel):
    id: Optional[int] = None
    strategy_run_id: int
    report_date: date
    trade_match_key: Optional[str] = None
    charge_source: ChargeSourceEnum = ChargeSourceEnum.FORMULA_COMPUTED
    brokerage: float = 0.0
    exchange_turnover_fee: float = 0.0
    stt: float = 0.0
    sebi_turnover_charges: float = 0.0
    stamp_duty: float = 0.0
    gst: float = 0.0
    ipft: float = 0.0
    slippage: float = 0.0
    total_charges: float = 0.0
    methodology_note: Optional[str] = None
    allocation_method: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def _total_matches(self):
        if self.total_charges == 0.0 and any(
            getattr(self, k) for k in [
                "brokerage", "exchange_turnover_fee", "stt", "sebi_turnover_charges",
                "stamp_duty", "gst", "ipft", "slippage",
            ]
        ):
            self.total_charges = round(
                self.brokerage + self.exchange_turnover_fee + self.stt +
                self.sebi_turnover_charges + self.stamp_duty + self.gst +
                self.ipft + self.slippage, 2
            )
        return self


class MatchedTradePair(_BaseRupeeModel):
    match_pair_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trade_date: date
    segment: Optional[str] = None
    underlying: Optional[str] = None
    vendor_symbol: Optional[str] = None
    option_type: Optional[OptionTypeEnum] = None
    expiry_date: Optional[date] = None
    strike_price: Optional[float] = None
    lots: int = Field(default=1, ge=1)
    quantity: int = Field(ge=1)
    lot_size: int = Field(default=0, ge=0)
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    side: Literal["LONG", "SHORT"] = "LONG"
    points_pnl: float = 0.0
    gross_pnl: float = 0.0
    holding_duration_minutes: Optional[float] = None
    match_method: str = "FIFO"
    exec_ids_entry: Optional[List[int]] = None
    exec_ids_exit: Optional[List[int]] = None
    strategy_run_id: Optional[int] = None

    @model_validator(mode="after")
    def _consistent_pnl(self):
        if self.side == "LONG":
            self.points_pnl = round(self.exit_price - self.entry_price, 2)
        else:
            self.points_pnl = round(self.entry_price - self.exit_price, 2)
        if self.gross_pnl == 0 and self.points_pnl and self.quantity:
            self.gross_pnl = round(self.points_pnl * self.quantity, 2)
        return self


class DailySummary(_BaseRupeeModel):
    report_date: date
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_trades_executed: int = 0
    total_strategy_runs: int = 0
    win_count: int = 0
    loss_count: int = 0
    total_capital_deployed_peak: float = 0.0
    peak_margin_audit_metric_secondary: Optional[float] = None
    total_gross_pnl: float = 0.0
    total_transaction_cost_drag: float = 0.0
    total_transaction_cost_drag_pct_of_gross: Optional[float] = None
    total_net_pnl: float = 0.0
    portfolio_day_net_roi_pct: Optional[float] = None
    segment_breakdown: Optional[Dict[str, Any]] = None
    strategy_breakdown: Optional[Dict[str, Any]] = None
    report_hash: Optional[str] = None
    disclaimer_version_tag: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def _roi_consistency(self):
        if self.total_gross_pnl != 0 and self.total_transaction_cost_drag == 0:
            self.total_transaction_cost_drag = round(
                max(self.total_gross_pnl, 0.0) - max(self.total_net_pnl, 0.0)
                if self.total_net_pnl < self.total_gross_pnl
                else 0.0, 2
            )
        if self.total_capital_deployed_peak and self.total_capital_deployed_peak > 0 and self.portfolio_day_net_roi_pct is None:
            self.portfolio_day_net_roi_pct = round(
                (self.total_net_pnl / self.total_capital_deployed_peak) * 100.0, 4
            )
        return self


class EquityCurvePoint(_BaseRupeeModel):
    report_date: date
    daily_net_pnl: float = 0.0
    cumulative_net_pnl: float = 0.0
    daily_net_roi_pct: Optional[float] = None
    cumulative_net_roi_pct: Optional[float] = None
    peak_equity: float = 0.0
    drawdown_pct: Optional[float] = None
    running_capital_base: Optional[float] = None
    running_trade_count: Optional[int] = None
    running_win_rate_30d: Optional[float] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ContractNoteCharges(_BaseRupeeModel):
    brokerage_amount: float = Field(ge=0.0)
    exchange_turnover_fee_amount: float = Field(ge=0.0)
    securities_transaction_tax_stt: float = Field(ge=0.0)
    sebi_turnover_charges: float = Field(ge=0.0)
    stamp_duty: float = Field(ge=0.0)
    gst: float = Field(ge=0.0)
    total_charges_grand_total: float = Field(ge=0.0)
    reconciliation_boolean: bool = True
    diff_rupees: float = 0.0

    @model_validator(mode="after")
    def _reconcile(self):
        s = (
            self.brokerage_amount + self.exchange_turnover_fee_amount +
            self.securities_transaction_tax_stt + self.sebi_turnover_charges +
            self.stamp_duty + self.gst
        )
        self.diff_rupees = round(self.total_charges_grand_total - s, 2)
        self.reconciliation_boolean = abs(self.diff_rupees) < 0.01
        return self


class GeminiParseEnvelope(_BaseRupeeModel):
    screen_type: SourceScreenTypeEnum = SourceScreenTypeEnum.UNKNOWN
    broker_identified: Optional[str] = "ZERODHA"
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    visible_underlying_levels: Dict[str, float] = Field(default_factory=dict)
    visible_margin_hud: Optional[Dict[str, Any]] = None
    strategy_cards: Optional[List[Dict[str, Any]]] = None
    kite_positions: Optional[List[Dict[str, Any]]] = None
    contract_note_charges: Optional[ContractNoteCharges] = None
    execution_rows: Optional[List[Dict[str, Any]]] = None
    processing_status: ProcessingStatusEnum = ProcessingStatusEnum.PENDING


class MarketKnowledge(_BaseRupeeModel):
    id: Optional[int] = None
    underlying: str = Field(min_length=1, max_length=40)
    exchange: Literal["NSE", "BSE", "OTHER"] = "NSE"
    instrument_type: str = Field(min_length=1, max_length=20)
    lot_size: int = Field(ge=1)
    strike_interval: Optional[float] = None
    weekly_expiry_available: bool = False
    expiry_weekday_number: Optional[int] = Field(default=None, ge=0, le=6)
    span_margin_pct: float = 0.0
    exposure_margin_pct: float = 0.0
    effective_date: date
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None
    is_current: bool = False
    notes: Optional[str] = None


class BrokerChargeSchedule(_BaseRupeeModel):
    id: Optional[int] = None
    broker_name: str = "ZERODHA"
    effective_date: date
    brokerage_per_order_inr: float = 20.0
    stt_option_sell_premium_pct: float = 0.0015
    nse_exchange_option_pct: float = 0.0003553
    bse_exchange_option_pct: float = 0.000325
    sebi_fee_per_crore_inr: float = 10.0
    stamp_duty_option_buy_pct: float = 0.00003
    gst_pct: float = 0.18
    default_slippage_per_point_inr: float = 0.10
    ipft_per_crore_inr: float = 1.0
    is_default: bool = False
    notes: Optional[str] = None

    @property
    def sebi_pct(self) -> float:
        return self.sebi_fee_per_crore_inr / 10_000_000.0

    @property
    def ipft_pct(self) -> float:
        return (self.ipft_per_crore_inr or 0.0) / 10_000_000.0

    @field_validator("stt_option_sell_premium_pct")
    @classmethod
    def _stt_0_1_only(cls, v):
        if not 0.0 <= v <= 0.01:
            raise ValueError("STT pct out of realistic band [0, 0.01]")
        return v
