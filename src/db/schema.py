from __future__ import annotations

import enum
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, Boolean,
    Text, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SourceScreenType(str, enum.Enum):
    TRADETRON_STRATEGY_CARD = "TRADETRON_STRATEGY_CARD"
    ZERODHA_KITE_POSITIONS = "ZERODHA_KITE_POSITIONS"
    ZERODHA_VIRTUAL_CONTRACT_NOTE = "ZERODHA_VIRTUAL_CONTRACT_NOTE"
    MANUAL_CSV = "MANUAL_CSV"
    UNKNOWN = "UNKNOWN"


class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PARSED = "PARSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    PERSISTED = "PERSISTED"
    FAILED = "FAILED"


class DeploymentStatus(str, enum.Enum):
    LIVE_AUTO = "LIVE_AUTO"
    EXITED = "EXITED"
    PARTIAL = "PARTIAL"
    OTHER = "OTHER"


class ChargeSource(str, enum.Enum):
    REALIZED_VIRTUAL_CONTRACT_NOTE = "REALIZED_VIRTUAL_CONTRACT_NOTE"
    FORMULA_COMPUTED = "FORMULA_COMPUTED"


class OptionType(str, enum.Enum):
    CE = "CE"
    PE = "PE"
    FUT = "FUT"


class SideType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class RawSourceFile(Base):
    __tablename__ = "raw_source_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sha256_hash = Column(String(64), unique=True, nullable=False, index=True)
    screen_type = Column(String(40), nullable=False, default=SourceScreenType.UNKNOWN.value)
    upload_filename = Column(String(255), nullable=False)
    upload_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    file_size_bytes = Column(Integer, nullable=True)
    processing_status = Column(String(30), nullable=False, default=ProcessingStatus.PENDING.value)
    overall_confidence = Column(Float, nullable=True)
    broker_identified = Column(String(40), nullable=True)
    ocr_raw_text = Column(Text, nullable=True)
    structured_json_response = Column(JSON, nullable=True)
    visible_underlying_levels = Column(JSON, nullable=True)
    visible_margin_hud = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    extra_metadata = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_rsf_screen_type", "screen_type"),
        Index("ix_rsf_status", "processing_status"),
        Index("ix_rsf_upload_ts", "upload_timestamp"),
    )


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_run_uuid = Column(String(36), unique=True, nullable=False, index=True)
    report_date = Column(Date, nullable=False, index=True)
    strategy_name = Column(String(255), nullable=False)
    deployment_status = Column(String(20), nullable=False, default=DeploymentStatus.LIVE_AUTO.value)
    multiplier_x = Column(Integer, nullable=False, default=1)
    counter_int = Column(Integer, nullable=True)
    capital_deployed_allocated = Column(Float, nullable=False)
    entry_timestamp_ist = Column(DateTime, nullable=True)
    exit_timestamp_ist = Column(DateTime, nullable=True)
    underlying_segment = Column(String(40), nullable=True)
    legs_greeks = Column(JSON, nullable=True)
    booked_gross_pnl = Column(Float, nullable=False, default=0.0)
    allocated_charges_total = Column(Float, nullable=False, default=0.0)
    net_pnl = Column(Float, nullable=False, default=0.0)
    net_roi_pct = Column(Float, nullable=True)
    operational_notes = Column(Text, nullable=True)
    capital_provenance_tag = Column(String(120), nullable=True)
    source_file_id = Column(Integer, ForeignKey("raw_source_files.id"), nullable=True)
    parsing_confidence = Column(Float, nullable=True)
    manually_edited = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    trade_executions = relationship("TradeExecution", back_populates="strategy_run", cascade="all, delete-orphan")
    charges_breakdowns = relationship("ChargesBreakdown", back_populates="strategy_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sr_report_date", "report_date"),
        Index("ix_sr_segment", "underlying_segment"),
    )


class TradeExecution(Base):
    __tablename__ = "trade_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_uuid = Column(String(36), unique=True, nullable=False, index=True)
    strategy_run_id = Column(Integer, ForeignKey("strategy_runs.id"), nullable=False, index=True)
    report_date = Column(Date, nullable=False, index=True)
    vendor_symbol = Column(String(120), nullable=False)
    underlying = Column(String(40), nullable=True)
    segment = Column(String(40), nullable=True)
    exchange = Column(String(10), nullable=True)
    expiry_date = Column(Date, nullable=True)
    strike_price = Column(Float, nullable=True)
    option_type = Column(String(5), nullable=True)
    instrument_type = Column(String(20), nullable=True)
    side = Column(String(10), nullable=False)
    lots = Column(Integer, nullable=False, default=1)
    lot_size = Column(Integer, nullable=False, default=0)
    quantity = Column(Integer, nullable=False)
    execution_price = Column(Float, nullable=False)
    gross_premium = Column(Float, nullable=True)
    product_type = Column(String(10), nullable=True)
    ltp_at_extract = Column(Float, nullable=True)
    individual_leg_pnl = Column(Float, nullable=True)
    execution_timestamp_ist = Column(DateTime, nullable=True)
    matched_pair_id = Column(String(36), nullable=True, index=True)
    is_entry_leg = Column(Boolean, nullable=True)
    parsing_confidence = Column(Float, nullable=True)
    manually_edited = Column(Boolean, nullable=False, default=False)
    source_file_id = Column(Integer, ForeignKey("raw_source_files.id"), nullable=True)
    extra_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    strategy_run = relationship("StrategyRun", back_populates="trade_executions")

    __table_args__ = (
        Index("ix_te_report_date_symbol", "report_date", "vendor_symbol"),
        Index("ix_te_strategy_id", "strategy_run_id"),
        Index("ix_te_matched_pair", "matched_pair_id"),
    )


class ChargesBreakdown(Base):
    __tablename__ = "charges_breakdown"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_run_id = Column(Integer, ForeignKey("strategy_runs.id"), nullable=False, index=True)
    report_date = Column(Date, nullable=False, index=True)
    trade_match_key = Column(String(80), nullable=True)
    charge_source = Column(String(40), nullable=False, default=ChargeSource.FORMULA_COMPUTED.value)
    brokerage = Column(Float, nullable=False, default=0.0)
    exchange_turnover_fee = Column(Float, nullable=False, default=0.0)
    stt = Column(Float, nullable=False, default=0.0)
    sebi_turnover_charges = Column(Float, nullable=False, default=0.0)
    stamp_duty = Column(Float, nullable=False, default=0.0)
    gst = Column(Float, nullable=False, default=0.0)
    ipft = Column(Float, nullable=True, default=0.0)
    slippage = Column(Float, nullable=True, default=0.0)
    total_charges = Column(Float, nullable=False, default=0.0)
    methodology_note = Column(Text, nullable=True)
    allocation_method = Column(String(60), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    strategy_run = relationship("StrategyRun", back_populates="charges_breakdowns")

    __table_args__ = (
        Index("ix_cb_report_date", "report_date"),
        Index("ix_cb_charge_source", "charge_source"),
    )


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    report_date = Column(Date, primary_key=True)
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    total_trades_executed = Column(Integer, nullable=False, default=0)
    total_strategy_runs = Column(Integer, nullable=False, default=0)
    win_count = Column(Integer, nullable=False, default=0)
    loss_count = Column(Integer, nullable=False, default=0)
    total_capital_deployed_peak = Column(Float, nullable=False, default=0.0)
    peak_margin_audit_metric_secondary = Column(Float, nullable=True)
    total_gross_pnl = Column(Float, nullable=False, default=0.0)
    total_transaction_cost_drag = Column(Float, nullable=False, default=0.0)
    total_transaction_cost_drag_pct_of_gross = Column(Float, nullable=True)
    total_net_pnl = Column(Float, nullable=False, default=0.0)
    portfolio_day_net_roi_pct = Column(Float, nullable=True)
    segment_breakdown = Column(JSON, nullable=True)
    strategy_breakdown = Column(JSON, nullable=True)
    report_hash = Column(String(64), nullable=True)
    disclaimer_version_tag = Column(String(20), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class EquityCurve(Base):
    __tablename__ = "equity_curve"

    report_date = Column(Date, primary_key=True)
    daily_net_pnl = Column(Float, nullable=False, default=0.0)
    cumulative_net_pnl = Column(Float, nullable=False, default=0.0)
    daily_net_roi_pct = Column(Float, nullable=True)
    cumulative_net_roi_pct = Column(Float, nullable=True)
    peak_equity = Column(Float, nullable=False, default=0.0)
    drawdown_pct = Column(Float, nullable=True)
    running_capital_base = Column(Float, nullable=True)
    running_trade_count = Column(Integer, nullable=True)
    running_win_rate_30d = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class MarketKnowledge(Base):
    __tablename__ = "market_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    underlying = Column(String(40), nullable=False)
    exchange = Column(String(10), nullable=False)
    instrument_type = Column(String(20), nullable=False)
    lot_size = Column(Integer, nullable=False)
    strike_interval = Column(Float, nullable=True)
    weekly_expiry_available = Column(Boolean, nullable=False, default=False)
    expiry_weekday_number = Column(Integer, nullable=True)
    span_margin_pct = Column(Float, nullable=False, default=0.0)
    exposure_margin_pct = Column(Float, nullable=False, default=0.0)
    effective_date = Column(Date, nullable=False)
    effective_from = Column(Date, nullable=True)
    effective_until = Column(Date, nullable=True)
    is_current = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("underlying", "instrument_type", "exchange", "effective_date", name="uq_mk_composite"),
        Index("ix_mk_current", "is_current"),
        Index("ix_mk_underlying", "underlying"),
    )


class BrokerChargeSchedule(Base):
    __tablename__ = "broker_charge_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    broker_name = Column(String(40), nullable=False, unique=True)
    effective_date = Column(Date, nullable=False)
    brokerage_per_order_inr = Column(Float, nullable=False, default=20.0)
    stt_option_sell_premium_pct = Column(Float, nullable=False, default=0.001)
    nse_exchange_option_pct = Column(Float, nullable=False, default=0.0003553)
    bse_exchange_option_pct = Column(Float, nullable=False, default=0.000325)
    sebi_fee_per_crore_inr = Column(Float, nullable=False, default=10.0)
    stamp_duty_option_buy_pct = Column(Float, nullable=False, default=0.00003)
    gst_pct = Column(Float, nullable=False, default=0.18)
    default_slippage_per_point_inr = Column(Float, nullable=False, default=0.10)
    ipft_per_crore_inr = Column(Float, nullable=True, default=1.0)
    is_default = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
