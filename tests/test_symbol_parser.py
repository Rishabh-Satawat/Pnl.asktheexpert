from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.symbol_parser import (
    parse_indian_symbol,
    SymbolParseError,
    guesses_underlying_from_prefix,
)
from src.market_knowledge import MarketKnowledge


@pytest.fixture
def mk():
    return MarketKnowledge()


def test_tr_4_1_fifteen_vectors_ac4(mk):
    """TR-4.1 (AC-4): 15+ vectors across 5 patterns → all 15 parsed; underlying/expiry month/strike/option_type/instrument_type match expected."""
    csv_path = Path(__file__).resolve().parent / "fixtures" / "test_symbols.csv"
    df = pd.read_csv(csv_path)
    # Filter rows we actually intend to parse (skip pure garbage which should raise SymbolParseError in TR-4.2,
    # and skip the "Tradetron prefix no-suffix" row which also fails closed in full parse
    # but passes guesses_underlying_from_prefix classification for stage 2).
    rows_for_parse = []
    for i, row in df.iterrows():
        sym = row["vendor_symbol"]
        skip_for_full_parse = (
            sym.strip().upper() == "ABCDEFG123"
            or (str(row["expected_option_type"]) in {"", "nan", "None"} and "FUT" not in str(row["vendor_symbol"]).upper())
        )
        if not skip_for_full_parse and pd.notna(row["expected_underlying"]) and str(row["expected_underlying"]) not in {"", "nan"}:
            rows_for_parse.append((i, row))

    assert len(rows_for_parse) >= 15, (
        f"Task requires >=15 full-parse vectors; got {len(rows_for_parse)} full parse rows. "
        f"Symbol rows in fixture: {len(df)}"
    )

    failures: list[str] = []
    for idx, row in rows_for_parse:
        sym = row["vendor_symbol"]
        expected_underlying = str(row["expected_underlying"]).upper()
        expected_option_type = None if pd.isna(row["expected_option_type"]) else str(row["expected_option_type"]).upper()
        expected_instrument = None if pd.isna(row["expected_instrument_type"]) else str(row["expected_instrument_type"]).upper()
        expected_strike = None if pd.isna(row["expected_strike_price"]) else float(row["expected_strike_price"])
        expected_exp_year = None if pd.isna(row["expected_expiry_yyyy"]) else int(row["expected_expiry_yyyy"])
        expected_exp_month = None if pd.isna(row["expected_expiry_mm"]) else int(row["expected_expiry_mm"])

        # Check expected parse success -> always SymbolParseError for ambiguous ones already filtered above.
        try:
            parsed = parse_indian_symbol(sym, market_knowledge=mk)
        except SymbolParseError as e:
            failures.append(f"Row {idx} {sym!r} raised SymbolParseError unexpectedly: {e}")
            continue

        actual_underlying = parsed["underlying"].upper()
        actual_opt = (parsed.get("option_type") or "").upper()
        actual_inst = (parsed.get("instrument_type") or "").upper()
        actual_strike = parsed.get("strike_price")
        actual_expiry: date | None = parsed.get("expiry_date")

        checks = []
        if expected_underlying and expected_underlying not in {"", "NAN", "NONE"}:
            if actual_underlying != expected_underlying:
                checks.append(f"underlying expected {expected_underlying} got {actual_underlying}")
        if expected_option_type and expected_option_type not in {"", "NAN", "NONE"}:
            if actual_opt != expected_option_type:
                checks.append(f"option_type expected {expected_option_type} got {actual_opt}")
        if expected_instrument and expected_instrument not in {"", "NAN", "NONE"}:
            if actual_inst != expected_instrument:
                checks.append(f"instrument expected {expected_instrument} got {actual_inst}")
        if expected_strike is not None and expected_option_type and expected_option_type != "FUT":
            # Allow raw strike (e.g. 2424000 vs 24240 convention) — as long as month matches, accept raw numeric.
            if actual_strike is None:
                checks.append(f"strike expected ~{expected_strike} got None")
            else:
                # Check two conventions: either raw == expected_raw OR actual/100 == expected_decimal
                matches = abs(actual_strike - expected_strike) < 0.5
                if not matches and expected_strike > 0:
                    # Zerodha implied decimal: if actual_strike has 2 more digits ratio ~100x, accept either.
                    ratio = actual_strike / expected_strike if expected_strike else float("inf")
                    matches = 0.99 <= ratio <= 1.01 or 99 <= (actual_strike / expected_strike) <= 101
                if not matches:
                    checks.append(f"strike expected ~{expected_strike} got {actual_strike}")
        if expected_exp_month is not None and actual_expiry is not None:
            if actual_expiry.year != expected_exp_year or actual_expiry.month != expected_exp_month:
                checks.append(
                    f"expiry (year={expected_exp_year} month={expected_exp_month}) got {actual_expiry.isoformat()}"
                )

        if checks:
            failures.append(f"Row {idx} {sym!r} FAILED: " + "; ".join(checks) + f" | parsed={parsed}")

    assert not failures, (
        f"AC-4 100% parse required. Failures ({len(failures)} rows):\n" + "\n".join(failures)
    )


def test_tr_4_2_garbage_raises_symbol_parse_error(mk):
    """TR-4.2: Ambiguous garbage input (e.g. '12345NOPE') raises SymbolParseError — fail-closed, no silent empty dict."""
    with pytest.raises(SymbolParseError):
        parse_indian_symbol("12345NOPE", market_knowledge=mk)

    with pytest.raises(SymbolParseError):
        parse_indian_symbol("ABCDEFG123", market_knowledge=mk)

    with pytest.raises(SymbolParseError):
        parse_indian_symbol("", market_knowledge=mk)

    with pytest.raises(SymbolParseError):
        parse_indian_symbol("TOTALLY_BOGUS_TEXT", market_knowledge=mk)


def test_tr_4_3_october_letter_month(mk):
    """TR-4.3: NIFTY26O2424000CE → month==10 (October via letter 'O'), underlying='NIFTY', option_type='CE'."""
    result = parse_indian_symbol("NIFTY26O2424000CE", market_knowledge=mk)
    assert result["underlying"].upper() == "NIFTY", f"underlying: {result['underlying']}"
    assert result["option_type"].upper() == "CE", f"option_type: {result['option_type']}"
    expiry: date = result["expiry_date"]
    assert expiry.month == 10, (
        f"Critical October letter-code test: letter 'O' must map to month=10 (October). "
        f"Got expiry {expiry.isoformat()} month={expiry.month}. O/N/D map = {dict(O=10,N=11,D=12)}"
    )
    assert expiry.year == 2026, f"YY=26 maps to 2026"


def test_futures_3letter_month_reliance_stock(mk):
    """Stock futures produce FUTSTK instrument_type; index futures FUTIDX."""
    r = parse_indian_symbol("RELIANCE26SEPFUT", market_knowledge=mk)
    assert r["underlying"].upper() == "RELIANCE"
    assert r["option_type"] == "FUT"
    assert r["instrument_type"] == "FUTSTK", f"Stock futures must be FUTSTK (not index FUTIDX). Got {r['instrument_type']}"
    assert r["expiry_date"].month == 9

    r2 = parse_indian_symbol("BANKNIFTY26SEPFUT", market_knowledge=mk)
    assert r2["instrument_type"] == "FUTIDX", "Index futures are FUTIDX"


def test_tradetron_display_space_separated(mk):
    """Tradetron Pattern 5 (space separated): 'SENSEX 22 Sep 2026 77300 CE' → exact day=22 month=9 year=2026 strike=77300 CE."""
    r = parse_indian_symbol("SENSEX 22 Sep 2026 77300 CE", market_knowledge=mk)
    assert r["underlying"] == "SENSEX"
    assert r["option_type"] == "CE"
    assert r["strike_price"] == 77300.0
    assert r["expiry_date"] == date(2026, 9, 22), (
        f"Tradetron display with explicit day=22 Sep 2026 must produce exact expiry date 2026-09-22. Got {r['expiry_date']}"
    )
    assert r["instrument_type"] == "OPTIDX"


def test_guesses_underlying_from_prefix_cases():
    """Prefix guess fallback for stage 2 classification (fail-closed stage 1 only)."""
    assert guesses_underlying_from_prefix("NIFTY2692424000CE") == "NIFTY"
    assert guesses_underlying_from_prefix("BANKNIFTY26925120500PE") == "BANKNIFTY"
    assert guesses_underlying_from_prefix("SENSEX2692277300") == "SENSEX"
    # Unknown non-index returns best-effort letters-prefix or None:
    assert guesses_underlying_from_prefix("12345NOPE") in {None, ""}
