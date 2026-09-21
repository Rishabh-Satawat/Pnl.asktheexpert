from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .schema import (
    Base, MarketKnowledge, BrokerChargeSchedule,
)

DEFAULT_DB_PATH = Path("data/quant_desk.db")


def build_engine(db_path: str | Path = DEFAULT_DB_PATH) -> Engine:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )
    return engine


def _session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(
    db_path: str | Path = DEFAULT_DB_PATH,
    create_tables: bool = True,
    seed: bool = True,
) -> tuple[Engine, sessionmaker]:
    engine = build_engine(db_path)
    if create_tables:
        Base.metadata.create_all(engine)
    SessionLocal = _session_factory(engine)
    if seed:
        with SessionLocal.begin() as session:
            seed_market_knowledge(session)
            seed_broker_charge_schedule(session)
    return engine, SessionLocal


def seed_market_knowledge(session: Session, effective: date = date(2026, 4, 1)) -> None:
    existing = session.query(MarketKnowledge).filter(
        MarketKnowledge.effective_date == effective
    ).count()
    if existing > 0:
        return
    seeds = [
        MarketKnowledge(
            underlying="NIFTY", exchange="NSE", instrument_type="OPTIDX",
            lot_size=25, strike_interval=50.0, weekly_expiry_available=True,
            expiry_weekday_number=1, span_margin_pct=0.12, exposure_margin_pct=0.05,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Nifty 50 weekly options, expiry Tuesday (1=Mon..0=Mon? - use 1=Tue 0-indexed)",
        ),
        MarketKnowledge(
            underlying="BANKNIFTY", exchange="NSE", instrument_type="OPTIDX",
            lot_size=15, strike_interval=100.0, weekly_expiry_available=True,
            expiry_weekday_number=3, span_margin_pct=0.14, exposure_margin_pct=0.06,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Bank Nifty weekly/monthly options, expiry Thursday (3=Thu)",
        ),
        MarketKnowledge(
            underlying="SENSEX", exchange="BSE", instrument_type="OPTIDX",
            lot_size=20, strike_interval=100.0, weekly_expiry_available=True,
            expiry_weekday_number=0, span_margin_pct=0.12, exposure_margin_pct=0.05,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Sensex weekly options, expiry Monday (0=Mon)",
        ),
        MarketKnowledge(
            underlying="FINNIFTY", exchange="NSE", instrument_type="OPTIDX",
            lot_size=25, strike_interval=50.0, weekly_expiry_available=False,
            expiry_weekday_number=1, span_margin_pct=0.12, exposure_margin_pct=0.05,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Fin Nifty monthly options, expiry Tuesday",
        ),
        MarketKnowledge(
            underlying="MIDCPNIFTY", exchange="NSE", instrument_type="OPTIDX",
            lot_size=50, strike_interval=25.0, weekly_expiry_available=False,
            expiry_weekday_number=0, span_margin_pct=0.14, exposure_margin_pct=0.06,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Midcap Nifty monthly options, expiry Monday",
        ),
        MarketKnowledge(
            underlying="NIFTY", exchange="NSE", instrument_type="FUTIDX",
            lot_size=25, strike_interval=None, weekly_expiry_available=False,
            expiry_weekday_number=3, span_margin_pct=0.10, exposure_margin_pct=0.03,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Nifty futures",
        ),
        MarketKnowledge(
            underlying="BANKNIFTY", exchange="NSE", instrument_type="FUTIDX",
            lot_size=15, strike_interval=None, weekly_expiry_available=False,
            expiry_weekday_number=3, span_margin_pct=0.11, exposure_margin_pct=0.04,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Bank Nifty futures",
        ),
        MarketKnowledge(
            underlying="SENSEX", exchange="BSE", instrument_type="FUTIDX",
            lot_size=20, strike_interval=None, weekly_expiry_available=False,
            expiry_weekday_number=3, span_margin_pct=0.10, exposure_margin_pct=0.03,
            effective_date=effective, effective_from=effective, effective_until=None,
            is_current=True, notes="Sensex futures",
        ),
    ]
    session.add_all(seeds)


def seed_broker_charge_schedule(session: Session, effective: date = date(2026, 4, 1)) -> None:
    existing = session.query(BrokerChargeSchedule).filter(
        BrokerChargeSchedule.broker_name == "ZERODHA"
    ).count()
    if existing > 0:
        return
    seed = BrokerChargeSchedule(
        broker_name="ZERODHA",
        effective_date=effective,
        brokerage_per_order_inr=20.0,
        stt_option_sell_premium_pct=0.001,
        nse_exchange_option_pct=0.0003553,
        bse_exchange_option_pct=0.000325,
        sebi_fee_per_crore_inr=10.0,
        stamp_duty_option_buy_pct=0.00003,
        gst_pct=0.18,
        default_slippage_per_point_inr=0.10,
        ipft_per_crore_inr=1.0,
        is_default=True,
        notes="Zerodha discount broker FORMULA schedule effective 2026-04-01. STT=0.1% on sell-side option premium. REALIZED values from Zerodha Virtual Contract Note always override when present.",
    )
    session.add(seed)


def vacuum_and_analyze(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
        conn.execute(text("PRAGMA optimize;"))
        conn.commit()
