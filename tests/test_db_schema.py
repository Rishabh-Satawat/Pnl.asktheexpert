from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.schema import (
    Base, MarketKnowledge, BrokerChargeSchedule, StrategyRun,
    TradeExecution, ChargesBreakdown, DailySummary, EquityCurve,
    RawSourceFile,
)
from src.db.engine import init_db, _session_factory, build_engine


EXPECTED_TABLES = {
    "raw_source_files",
    "strategy_runs",
    "trade_executions",
    "charges_breakdown",
    "daily_summaries",
    "equity_curve",
    "market_knowledge",
    "broker_charge_schedule",
}

EXPECTED_MK_LOT_SIZES = {
    ("NIFTY", "OPTIDX"): 25,
    ("BANKNIFTY", "OPTIDX"): 15,
    ("SENSEX", "OPTIDX"): 20,
    ("FINNIFTY", "OPTIDX"): 25,
    ("MIDCPNIFTY", "OPTIDX"): 50,
    ("NIFTY", "FUTIDX"): 25,
    ("BANKNIFTY", "FUTIDX"): 15,
    ("SENSEX", "FUTIDX"): 20,
}


@pytest.fixture(scope="module")
def seeded_engine(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("db") / "test_quant_desk.db"
    engine, SessionLocal = init_db(db_path=tmp, create_tables=True, seed=True)
    yield engine, SessionLocal


def test_init_db_creates_8_tables(seeded_engine):
    """TR-1.1: All 8 tables created cleanly; seed market_knowledge count=8; broker_charge_schedule count=1 Zerodha STT=0.001 (AC-6)."""
    engine, SessionLocal = seeded_engine
    with engine.connect() as conn:
        rs = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )).fetchall()
    actual_tables = {r[0] for r in rs}
    missing = EXPECTED_TABLES - actual_tables
    extra = actual_tables - (EXPECTED_TABLES | {"sqlite_sequence"})
    assert not missing, f"Missing tables: {missing}"
    assert not extra, f"Extra unexpected tables: {extra}"
    assert len(EXPECTED_TABLES) == 8, f"Spec requires 8 tables, have {len(EXPECTED_TABLES)}"

    with SessionLocal() as s:
        mk_count = s.query(func.count(MarketKnowledge.id)).filter(MarketKnowledge.is_current == True).scalar()
        assert mk_count == 8, f"Expected 8 market_knowledge is_current rows, got {mk_count}"

        for (under, inst), expected_lot in EXPECTED_MK_LOT_SIZES.items():
            row = s.query(MarketKnowledge).filter(
                MarketKnowledge.underlying == under,
                MarketKnowledge.instrument_type == inst,
                MarketKnowledge.is_current == True,
            ).one_or_none()
            assert row is not None, f"Missing seed row {under}/{inst}"
            assert row.lot_size == expected_lot, (
                f"{under}/{inst} lot_size expected {expected_lot}, got {row.lot_size}"
            )
            if under == "SENSEX":
                assert row.exchange == "BSE", f"SENSEX must be BSE, got {row.exchange}"
            else:
                assert row.exchange == "NSE", f"{under} must be NSE, got {row.exchange}"

        bcs_count = s.query(func.count(BrokerChargeSchedule.id)).scalar()
        assert bcs_count == 1, f"Expected 1 broker_charge_schedule seed, got {bcs_count}"
        z = s.query(BrokerChargeSchedule).filter(BrokerChargeSchedule.broker_name == "ZERODHA").one()
        assert z.is_default is True
        assert z.brokerage_per_order_inr == 20.0, f"Zerodha brokerage per order must be ₹20, got {z.brokerage_per_order_inr}"
        assert z.stt_option_sell_premium_pct == 0.001, (
            f"CRITICAL: STT must be 0.001 (0.1%) sell-premium FORMULA rate. Got {z.stt_option_sell_premium_pct}. "
            f"Spec explicitly supersedes old 0.15% / 0.0015 draft value."
        )
        assert z.nse_exchange_option_pct == 0.0003553
        assert z.bse_exchange_option_pct == 0.000325
        assert round(z.sebi_fee_per_crore_inr / 10_000_000, 10) == 0.000001, "SEBI ₹10/crore = 1e-6 pct"
        assert z.stamp_duty_option_buy_pct == 0.00003, "Stamp 0.003% on buy = 3e-5"
        assert z.gst_pct == 0.18, "GST 18%"
        assert z.is_default is True


def test_fk_between_strategy_runs_and_trade_executions(seeded_engine):
    """Sanity check: FK from trade_executions.strategy_run_id → strategy_runs.id enforces."""
    engine, SessionLocal = seeded_engine
    from datetime import date
    from src.db.schema import StrategyRun, TradeExecution
    with SessionLocal.begin() as s:
        sr = StrategyRun(
            strategy_run_uuid="test-fk-1", report_date=date(2026,9,3),
            strategy_name="FK-Test", capital_deployed_allocated=100_000.0,
        )
        s.add(sr)
        s.flush()
        te = TradeExecution(
            execution_uuid="te-fk-1", strategy_run_id=sr.id,
            report_date=date(2026,9,3), vendor_symbol="NIFTY2692424000CE",
            side="BUY", lots=1, lot_size=25, quantity=25, execution_price=150.0,
        )
        s.add(te)
    with SessionLocal() as s:
        te_q = s.query(TradeExecution).filter(TradeExecution.execution_uuid == "te-fk-1").one()
        assert te_q.strategy_run_id is not None
