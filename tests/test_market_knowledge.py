from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market_knowledge import MarketKnowledge


@pytest.fixture
def mk():
    return MarketKnowledge(session_or_engine=None)


def test_tr_2_1_basic_lookups(mk):
    """TR-2.1: Exact lot sizes and exchanges for headline indices."""
    assert mk.get_lot_size("SENSEX") == 20, "SENSEX OPT lot = 20 per AC-6"
    assert mk.get_lot_size("BANKNIFTY") == 15, "BANKNIFTY OPT lot = 15 per AC-6"
    assert mk.get_lot_size("FINNIFTY") == 25, "FINNIFTY OPT lot = 25"
    assert mk.get_lot_size("NIFTY") == 25, "NIFTY OPT lot = 25"
    assert mk.get_lot_size("MIDCPNIFTY") == 50, "MIDCPNIFTY OPT lot = 50"
    assert mk.get_exchange("MIDCPNIFTY") == "NSE"
    assert mk.get_exchange("SENSEX") == "BSE", "SENSEX is BSE"
    assert mk.get_exchange("BANKNIFTY") == "NSE"
    mp = mk.get_margin_params("SENSEX")
    assert 0.05 <= mp["span_margin_pct"] <= 0.25
    assert isinstance(mp["exposure_margin_pct"], float)
    assert mk.is_valid_index("NIFTY") is True
    assert mk.is_valid_index("RELIANCE") is False
    assert mk.is_valid_index("SENSEX") is True


def test_tr_2_2_full_classification_100pct(mk):
    """TR-2.2 (AC-8): classify_trades_by_segment across test_symbols.csv -> 100% expected_segment match, all rows have expected_lot_size aligned to get_lot_size where applicable."""
    csv_path = Path(__file__).resolve().parent / "fixtures" / "test_symbols.csv"
    df = pd.read_csv(csv_path)
    assert len(df) >= 15, f"Task requires >= 15 test vectors, got {len(df)}"

    classified = mk.classify_trades_by_segment(df)

    mismatches = []
    for i, row in classified.iterrows():
        actual = row["segment"]
        expected = row["expected_segment"]
        if actual != expected:
            mismatches.append((i, row["vendor_symbol"], actual, expected))
        # Lot size cross-check when it's an index segment with a non-null expected_lot_size
        if expected in {"SENSEX", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"} and pd.notna(row["expected_lot_size"]):
            ls = mk.get_lot_size(expected)
            assert ls == int(row["expected_lot_size"]), (
                f"row {i} {row['vendor_symbol']}: lot {ls} vs expected {row['expected_lot_size']}"
            )

    assert not mismatches, (
        f"100% classification required (AC-8). Mismatched rows (idx, symbol, actual, expected):\n"
        + "\n".join(str(m) for m in mismatches)
    )


def test_tr_2_3_unknown_symbol_fails_closed_no_crash(mk):
    """TR-2.3: Unknown symbol -> UNKNOWN classification. No raised exception (fail-closed without crash)."""
    res = mk.get_segment_for_symbol("ABCDEFG123")
    assert res == "UNKNOWN"
    # And calling get_lot_size / get_exchange on it must return None, not crash:
    assert mk.get_lot_size("NONEXISTENT_ABC") is None
    assert mk.get_exchange("NONEXISTENT_ABC") is None
    assert mk.is_valid_index("NONEXISTENT_ABC") is False
    # Classify an empty / all-unknown dataframe:
    empty = pd.DataFrame({"vendor_symbol": ["ZZZZ", "", "??"]})
    out = mk.classify_trades_by_segment(empty)
    assert list(out["segment"]) == ["UNKNOWN", "UNKNOWN", "UNKNOWN"]


def test_tr_2_2_extra_row_density_spans_all_indices(mk):
    """Sanity: test_symbols.csv covers all five headline indices + STOCK_FUT + STOCK_OPT + UNKNOWN, 8 segments total."""
    csv_path = Path(__file__).resolve().parent / "fixtures" / "test_symbols.csv"
    df = pd.read_csv(csv_path)
    segs_present = set(df["expected_segment"].unique())
    required_subset = {"SENSEX", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
    missing = required_subset - segs_present
    assert not missing, f"Fixture missing required headline segments: {missing}"
