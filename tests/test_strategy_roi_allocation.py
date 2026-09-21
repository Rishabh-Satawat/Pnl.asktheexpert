"""Tests for FIFO matching + strategy ROI aggregation (AC-5 golden arithmetic)."""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.trade_matcher import TradeMatcher
from src.strategy_aggregator import aggregate_strategy_runs, compute_portfolio_day_summary

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_trade_diary.csv"


@pytest.fixture
def raw_df():
    return pd.read_csv(FIXTURE_PATH)


@pytest.fixture
def matcher():
    return TradeMatcher()


@pytest.fixture
def matched_result(raw_df, matcher):
    norm = matcher.parse_and_normalize_executions(raw_df)
    matched_df, open_legs_df = matcher.match_trades_fifo(norm)
    return matched_df, open_legs_df


# ------------------------------------------------------------------ #
# TR-5.1  FIFO gross P&L matches fixture
# ------------------------------------------------------------------ #
def test_tr_5_1_fifo_gross_pnl_matches_fixture(matched_result):
    matched_df, _ = matched_result
    s1_gross = matched_df.loc[matched_df["strategy_run_id"] == "S1", "gross_pnl"].sum()
    s2_gross = matched_df.loc[matched_df["strategy_run_id"] == "S2", "gross_pnl"].sum()
    print(f"S1 booked_gross_pnl = {s1_gross}")
    print(f"S2 booked_gross_pnl = {s2_gross}")
    assert s1_gross == pytest.approx(12000, abs=0.01), f"S1 gross expected 12000, got {s1_gross}"
    assert s2_gross == pytest.approx(-1050, abs=0.01), f"S2 gross expected -1050, got {s2_gross}"


# ------------------------------------------------------------------ #
# TR-5.2  Side correct: LONG vs SHORT
# ------------------------------------------------------------------ #
def test_tr_5_2_side_correct_long_short(matched_result):
    matched_df, _ = matched_result

    # SENSEX CE pair: BUY first -> LONG
    sensex_ce = matched_df[matched_df["vendor_symbol"] == "SENSEX2693077300CE"]
    assert len(sensex_ce) == 1, "Expected exactly 1 matched pair for SENSEX CE"
    assert sensex_ce.iloc[0]["side"] == "LONG", "SENSEX CE (BUY first) should be LONG"

    # SENSEX PE pair: SELL first -> SHORT
    sensex_pe = matched_df[matched_df["vendor_symbol"] == "SENSEX2693077400PE"]
    assert len(sensex_pe) == 1, "Expected exactly 1 matched pair for SENSEX PE"
    assert sensex_pe.iloc[0]["side"] == "SHORT", "SENSEX PE (SELL first) should be SHORT"

    # BANKNIFTY CE pair: BUY first -> LONG
    bn_ce = matched_df[matched_df["vendor_symbol"] == "BANKNIFTY26925120000CE"]
    assert len(bn_ce) == 1, "Expected exactly 1 matched pair for BANKNIFTY CE"
    assert bn_ce.iloc[0]["side"] == "LONG", "BANKNIFTY CE (BUY first) should be LONG"

    # BANKNIFTY PE pair: SELL first -> SHORT
    bn_pe = matched_df[matched_df["vendor_symbol"] == "BANKNIFTY26925120500PE"]
    assert len(bn_pe) == 1, "Expected exactly 1 matched pair for BANKNIFTY PE"
    assert bn_pe.iloc[0]["side"] == "SHORT", "BANKNIFTY PE (SELL first) should be SHORT"


# ------------------------------------------------------------------ #
# TR-5.3  All 8 legs matched, zero open
# ------------------------------------------------------------------ #
def test_tr_5_3_all_8_legs_matched_zero_open(matched_result):
    matched_df, open_legs_df = matched_result
    assert len(matched_df) == 4, f"Expected 4 matched pairs, got {len(matched_df)}"
    assert len(open_legs_df) == 0, f"Expected 0 open legs, got {len(open_legs_df)}"


# ------------------------------------------------------------------ #
# TR-5.4  AC-5 strategy ROI golden numbers
# ------------------------------------------------------------------ #
def test_tr_5_4_ac5_strategy_roi_golden(raw_df, matched_result):
    matched_df, _ = matched_result

    # Build strategy_metadata_df from fixture data
    meta_records = [
        {
            "strategy_run_id": "S1",
            "strategy_name": "SENSEX BFO Short Strangle",
            "deployment_status": "LIVE_AUTO",
            "multiplier": 1,
            "counter": 1,
            "capital_deployed_allocated": 200000.0,
            "entry_ts": "2026-09-03 09:30:00",
            "exit_ts": "2026-09-03 14:35:00",
            "allocated_charges_total": 4000.0,
        },
        {
            "strategy_run_id": "S2",
            "strategy_name": "BANKNIFTY NFO Short Strangle",
            "deployment_status": "LIVE_AUTO",
            "multiplier": 1,
            "counter": 1,
            "capital_deployed_allocated": 325000.0,
            "entry_ts": "2026-09-03 09:32:00",
            "exit_ts": "2026-09-03 14:37:00",
            "allocated_charges_total": 2200.0,
        },
    ]
    strategy_metadata_df = pd.DataFrame(meta_records)

    strat_runs = aggregate_strategy_runs(matched_df, strategy_metadata_df)
    print("Strategy runs output:")
    print(strat_runs[["strategy_run_id", "booked_gross_pnl", "allocated_charges_total", "net_pnl", "net_roi_pct"]].to_string())

    s1 = strat_runs[strat_runs["strategy_run_id"] == "S1"].iloc[0]
    s2 = strat_runs[strat_runs["strategy_run_id"] == "S2"].iloc[0]

    assert s1["net_pnl"] == pytest.approx(8000, abs=0.01), f"S1 net_pnl expected 8000, got {s1['net_pnl']}"
    assert s1["net_roi_pct"] == pytest.approx(4.00, abs=0.01), f"S1 ROI expected 4.00%, got {s1['net_roi_pct']}"
    assert s2["net_pnl"] == pytest.approx(-3250, abs=0.01), f"S2 net_pnl expected -3250, got {s2['net_pnl']}"
    assert s2["net_roi_pct"] == pytest.approx(-1.00, abs=0.01), f"S2 ROI expected -1.00%, got {s2['net_roi_pct']}"

    # Portfolio day summary
    summary = compute_portfolio_day_summary(strat_runs)
    print(f"Portfolio summary: {summary}")
    assert summary["total_net_pnl"] == pytest.approx(4750, abs=0.01)
    assert summary["peak_capital_deployed"] == pytest.approx(525000, abs=0.01)
    assert summary["portfolio_day_roi_pct"] == pytest.approx(0.9047, abs=0.01)
    assert summary["win_count"] == 1
    assert summary["loss_count"] == 1
    assert summary["flat_count"] == 0


# ------------------------------------------------------------------ #
# TR-5.5  Zero capital -> NaN ROI, no crash
# ------------------------------------------------------------------ #
def test_tr_5_5_zero_capital_nan_roi_no_crash(matched_result):
    matched_df, _ = matched_result

    # Create a strategy with zero capital
    zero_meta = pd.DataFrame([{
        "strategy_run_id": "S_ZERO",
        "strategy_name": "Zero Capital Test",
        "deployment_status": "LIVE_AUTO",
        "multiplier": 1,
        "counter": 0,
        "capital_deployed_allocated": 0.0,
        "entry_ts": None,
        "exit_ts": None,
        "allocated_charges_total": 0.0,
    }])

    # Use empty matched_df for this strategy
    empty_matched = pd.DataFrame(columns=matched_df.columns) if not matched_df.empty else pd.DataFrame()

    with pytest.warns(UserWarning):
        result = aggregate_strategy_runs(empty_matched, zero_meta)

    row = result[result["strategy_run_id"] == "S_ZERO"].iloc[0]
    assert math.isnan(row["net_roi_pct"]), f"Expected NaN ROI for zero capital, got {row['net_roi_pct']}"
    print("Zero capital test passed -- NaN ROI, no crash")
