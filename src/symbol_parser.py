from __future__ import annotations

import calendar
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from .market_knowledge import MarketKnowledge


class SymbolParseError(ValueError):
    """Fail-closed parsing exception. Never silently return partial dict."""


_MONTH_LETTER = {"O": 10, "N": 11, "D": 12}
_LETTER_MONTH = {v: k for k, v in _MONTH_LETTER.items()}
_MONTH_NAME_SHORT = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_SUFFIX_RE = re.compile(r"(CE|PE|FUT|CALL|PUT|FUTURES)$", re.IGNORECASE)
# Pattern 4: futures with 3-letter month
_FUT_3LETTER_MONTH = re.compile(
    r"^(NIFTY|BANKNIFTY|SENSEX|FINNIFTY|MIDCPNIFTY|[A-Z][A-Z0-9]{1,})"
    r"(\d{2})"
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"FUT$",
    re.IGNORECASE,
)
# Pattern for options with 3-letter month (e.g. TCS26OCT3500CE, HDFCBANK26SEP1700PE)
_OPT_3LETTER_MONTH = re.compile(
    r"^([A-Z][A-Z0-9]{1,}?)"          # underlying
    r"(\d{2})"                          # YY
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"  # month
    r"(\d+)"                            # strike
    r"(CE|PE)$",                        # suffix
    re.IGNORECASE,
)

_UNDERLYING_PREFIXES = [
    "BANKNIFTY", "MIDCPNIFTY", "FINNIFTY", "SENSEX", "NIFTY",
]


def _split_underlying(raw: str) -> Tuple[str, str]:
    """Return (underlying, rest_of_symbol) using longest known prefix match."""
    up = raw.upper()
    for name in _UNDERLYING_PREFIXES:
        if up.startswith(name):
            return name, raw[len(name):]
    # Unknown underlying: try "first non-digit run" as underlying
    m = re.match(r"^([A-Z][A-Z_]+?)?(\d.*)$", up)
    if not m:
        return up, ""
    underlying = m.group(1)
    rest = m.group(2) if m.group(2) else ""
    return underlying or up, rest


def _classify_suffix(rest: str) -> Tuple[str, str]:
    m = _SUFFIX_RE.search(rest)
    if not m:
        return "", rest
    suf = m.group(1).upper()
    suf_map = {"CALL": "CE", "PUT": "PE", "FUTURES": "FUT"}
    return suf_map.get(suf, suf), rest[: m.start()]


def _guess_year(two_digit: int) -> int:
    return 2000 + two_digit


def _month_from_token(tok: str) -> Optional[int]:
    if not tok:
        return None
    up = tok.upper()
    if up in _MONTH_NAME_SHORT:
        return _MONTH_NAME_SHORT[up]
    if up in {"O", "N", "D"}:
        return _MONTH_LETTER[up]
    if up.isdigit():
        n = int(up)
        if 1 <= n <= 12:
            return n
    return None


def _parse_month_and_numerical_tail(tail: str) -> Tuple[int, str, str]:
    """
    After stripping underlying+year, return (month_int, day_chunk_or_empty, strike_chunk).
    Month token is either a single digit 1-9, letter O/N/D, or 10/11/12 two digits.

    NOTE: For letter-month codes (O/N/D), the tail after the letter is the RAW strike with NO embedded day.
    Zerodha monthly-with-no-day numeric codes (e.g. FINNIFTY2611024500 where "11"=Nov):
      these return after_month with a possible leading-zero day (Zerodha padding) — handled by _split_day_strike.
    """
    t = tail
    if not t:
        raise SymbolParseError(f"No month/tail token after year in tail={tail!r}")
    first = t[0]
    # O/N/D letter month — rest is raw strike (NO embedded day for letter-month contracts)
    if first in {"O", "N", "D"}:
        return _MONTH_LETTER[first], "", t[1:]
    # Two-digit numeric months 10/11/12
    if len(t) >= 2 and t[:2].isdigit() and 10 <= int(t[:2]) <= 12:
        return int(t[:2]), "", t[2:]
    # One-digit numeric month (1-9)
    if first.isdigit() and 1 <= int(first) <= 9:
        return int(first), "", t[1:]
    raise SymbolParseError(f"Cannot determine month from tail token: {tail!r}")


def _split_day_strike(numeric_tail: str) -> Tuple[Optional[int], float]:
    """
    Given numerals after month, return (day or None, strike_price).

    Zerodha weekly contracts embed the day: e.g. NIFTY2692224000CE → tail after month is "2224000"
      → day=22, strike=24000.
    Monthly contracts have NO day embedded: e.g. SENSEX26977300CE → tail after month is "77300"
      → day=None, strike=77300.

    Heuristic: If removing a valid 1-2 digit day prefix leaves a sensible strike (>=100),
    we take the day. Otherwise the entire tail is the strike (monthly contract).

    Special case: letter-month codes (O/N/D) after year return NO day; entire tail = strike.
    """
    if not numeric_tail or not numeric_tail.isdigit():
        return None, 0.0
    n = len(numeric_tail)
    if n <= 3:
        # Too short to hold day+strike; treat entire tail as strike
        return None, float(int(numeric_tail))
    # Try 2-digit day first, then 1-digit day
    for dl in (2, 1):
        if n <= dl:
            continue
        day_candidate = numeric_tail[:dl]
        strike_candidate = numeric_tail[dl:]
        if not day_candidate.isdigit() or not strike_candidate.isdigit():
            continue
        day_val = int(day_candidate)
        strike_val = int(strike_candidate)
        # Valid day: 1-31; valid strike: meaningful non-zero value >=100
        if 1 <= day_val <= 31 and strike_val >= 100:
            # Extra sanity: do NOT split if the "day" candidate would lead to an implausibly tiny strike
            # e.g. "024500" with dl=2 → day=02, strike=4500 (WRONG; strike should be 24500 for FINNIFTY)
            # We accept the split only if the leading digit(s) are non-zero (no leading zero day)
            if day_candidate[0] == "0":
                continue  # Leading-zero day like "02" is Zerodha monthly format with no explicit day
            return day_val, float(strike_val)
    # No valid day split: entire tail = strike (monthly contract)
    return None, float(int(numeric_tail))


def _lookup_expiry_date(
    underlying: str, year: int, month: int, day: Optional[int], mk: Optional[MarketKnowledge]
) -> Optional[date]:
    if day is not None:
        try:
            return date(year, month, day)
        except ValueError:
            pass
    # Weekly/monthly default: use market_knowledge expiry_weekday_number to find default
    # e.g. NIFTY weekly Tuesday → last Tuesday or find any week expiry day.
    if mk is None:
        mk = MarketKnowledge()
    params = None
    try:
        row = mk._find_row(underlying)  # type: ignore[attr-defined]
        if row:
            params = row
    except Exception:
        params = None
    wd = None
    if params:
        wd = params.get("expiry_weekday_number")
    if wd is None:
        if underlying in {"SENSEX", "MIDCPNIFTY"}:
            wd = 0  # Monday
        elif underlying in {"NIFTY", "FINNIFTY"}:
            wd = 1  # Tuesday
        elif underlying == "BANKNIFTY":
            wd = 3  # Thursday
        else:
            wd = 3
    # Last weekday of the month
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != wd:
        d -= timedelta(days=1)
    return d


def parse_indian_symbol(
    raw_symbol: str,
    market_knowledge: Optional[MarketKnowledge] = None,
    as_of_year: int = 2026,
) -> Dict[str, Any]:
    """
    Parse Indian F&O symbols. Raises SymbolParseError (fail-closed) when no explicit success pattern matched.

    Accepts 5 patterns:
      1. Zerodha weekly-digit:   {UNDER}{YY}{MM}{DAY}{STRIKE}{CE|PE}  e.g. NIFTY2692224000CE
      2. Zerodha monthly-digit:  {UNDER}{YY}{MM}{STRIKE}{CE|PE}        e.g. SENSEX26977300CE
      3. Letter month code O/N/D: {UNDER}{YY}{O|N|D}{DAY?}{STRIKE}{CE|PE} e.g. NIFTY26O2424000CE (O=Oct)
      4. Futures 3-letter month: {UNDER}{YY}{3-LETTER-MON}FUT         e.g. BANKNIFTY26SEPFUT
      5. Tradetron display:       {UNDER} {DD} {MON} {YYYY} {STRIKE} {CE|PE|FUT} e.g. "SENSEX 22 Sep 2026 77300 CE"

    Returns keys: underlying, expiry_date (date | None), strike_price (float | None),
                  option_type (CE|PE|FUT), instrument_type (OPTIDX|FUTIDX|OPTSTK|FUTSTK), raw_symbol.
    """
    if raw_symbol is None or not str(raw_symbol).strip():
        raise SymbolParseError("Empty symbol cannot be parsed")
    raw = str(raw_symbol).strip()

    # Reject symbols that start with a digit — Zerodha/Tradetron symbols always start with a letter
    if raw[0].isdigit():
        raise SymbolParseError(
            f"Symbol starts with digit, not a valid Indian F&O symbol: {raw!r}"
        )

    # ── Pattern 0: Tradetron OPTIDX/FUTIDX/OPTSTK/FUTSTK vendor symbol format ──
    # e.g. OPTIDX_SENSEX_24SEP2026_PE_74300
    #      FUTIDX_BANKNIFTY_25SEP2026_FUT
    #      OPTSTK_TCS_30OCT2026_CE_3500
    _TRADETRON_VENDOR_RE = re.compile(
        r"^(OPTIDX|FUTIDX|OPTSTK|FUTSTK)_([A-Z0-9]+)_(\d{2})([A-Z]{3})(\d{4})_(CE|PE|FUT)(?:_(\d+))?$",
        re.IGNORECASE,
    )
    m0 = _TRADETRON_VENDOR_RE.match(raw.upper())
    if m0:
        inst_prefix = m0.group(1).upper()   # OPTIDX / FUTIDX / OPTSTK / FUTSTK
        underlying  = m0.group(2).upper()   # SENSEX / BANKNIFTY / TCS
        day         = int(m0.group(3))      # 24
        mon_str     = m0.group(4).upper()   # SEP
        year        = int(m0.group(5))      # 2026
        suffix      = m0.group(6).upper()   # CE / PE / FUT
        strike_str  = m0.group(7)           # "74300" or None for FUT

        month_int = _MONTH_NAME_SHORT.get(mon_str)
        if month_int is None:
            raise SymbolParseError(f"Unknown month abbreviation {mon_str!r} in {raw!r}")

        strike = float(strike_str) if strike_str else 0.0
        # The vendor token is already a four-digit Gregorian year (e.g. 2026).
        # Passing year % 100 created year 0026 in reports and persisted records.
        expiry = _lookup_expiry_date(underlying, year, month_int, day, market_knowledge)

        # Infer exchange and segment from underlying
        u = underlying.upper()
        if "SENSEX" in u or inst_prefix in ("OPTIDX", "FUTIDX") and "SENSEX" in u:
            exchange, segment = "BSE", "SENSEX"
        elif "BANKNIFTY" in u:
            exchange, segment = "NSE", "BANKNIFTY"
        elif "FINNIFTY" in u:
            exchange, segment = "NSE", "FINNIFTY"
        elif "MIDCPNIFTY" in u or "MIDCAP" in u:
            exchange, segment = "NSE", "MIDCPNIFTY"
        elif "NIFTY" in u:
            exchange, segment = "NSE", "NIFTY"
        else:
            # Stock options/futures — NSE by default
            exchange, segment = "NSE", underlying

        # Map inst_prefix to instrument_type
        instrument_type_map = {
            "OPTIDX": "OPTIDX", "FUTIDX": "FUTIDX",
            "OPTSTK": "OPTSTK", "FUTSTK": "FUTSTK",
        }
        instrument_type = instrument_type_map.get(inst_prefix, inst_prefix)

        return {
            "underlying": underlying,
            "expiry_date": expiry,
            "strike_price": strike,
            "option_type": suffix,
            "instrument_type": instrument_type,
            "exchange": exchange,
            "segment": segment,
            "raw_symbol": raw,
        }

    # -------- Pattern 5: Tradetron space-separated display format --------
    if " " in raw and re.search(r"\b(CE|PE|FUT|CALL|PUT)\b", raw, re.IGNORECASE):
        return _parse_tradetron_display(raw, market_knowledge, as_of_year)

    # -------- Pattern 4: 3-letter month FUT --------
    up = raw.upper()
    m4 = _FUT_3LETTER_MONTH.match(up)
    if m4:
        underlying, yy_s, month_short = m4.group(1), m4.group(2), m4.group(3)
        month = _MONTH_NAME_SHORT[month_short.upper()]
        year = _guess_year(int(yy_s))
        expiry = _lookup_expiry_date(underlying, year, month, None, market_knowledge)
        inst_type = _instrument_type(underlying, "FUT")
        return {
            "underlying": underlying,
            "expiry_date": expiry,
            "strike_price": None,
            "option_type": "FUT",
            "instrument_type": inst_type,
            "raw_symbol": raw,
        }

    # -------- Pattern 4b: 3-letter month OPTION (e.g. TCS26OCT3500CE, HDFCBANK26SEP1700PE) --------
    m4b = _OPT_3LETTER_MONTH.match(up)
    if m4b:
        underlying, yy_s, month_short, strike_s, suf = (
            m4b.group(1), m4b.group(2), m4b.group(3), m4b.group(4), m4b.group(5)
        )
        month = _MONTH_NAME_SHORT[month_short.upper()]
        year = _guess_year(int(yy_s))
        strike = float(int(strike_s))
        expiry = _lookup_expiry_date(underlying, year, month, None, market_knowledge)
        inst_type = _instrument_type(underlying, suf.upper())
        return {
            "underlying": underlying,
            "expiry_date": expiry,
            "strike_price": strike,
            "option_type": suf.upper(),
            "instrument_type": inst_type,
            "raw_symbol": raw,
        }

    # -------- Patterns 1/2/3: Option-style UNDER...{CE|PE} -------------
    underlying, tail1 = _split_underlying(up)
    suffix, numeric_tail_all = _classify_suffix(tail1)
    if suffix == "":
        # Unknown suffix -> cannot trust heuristic guess, fail closed
        raise SymbolParseError(
            f"No known suffix (CE/PE/FUT) in symbol. Raw={raw!r}. Fail-closed to avoid silent guesses."
        )
    if not numeric_tail_all:
        raise SymbolParseError(f"Empty numeric section after underlying in symbol {raw!r}")
    if len(numeric_tail_all) < 3:
        raise SymbolParseError(f"Numeric tail too short to hold YY+month in symbol {raw!r}")
    # First 2 chars are year
    if not numeric_tail_all[:2].isdigit():
        raise SymbolParseError(f"Year digits not where expected in tail: {numeric_tail_all!r} from {raw!r}")
    yy = int(numeric_tail_all[:2])
    year = _guess_year(yy)
    post_year = numeric_tail_all[2:]
    # _parse_month_and_numerical_tail returns (month, "", after_month)
    month_int, _day_dummy, after_month_numbers = _parse_month_and_numerical_tail(post_year)
    # Detect if this was a letter-month (O/N/D) — if so, after_month_numbers is the RAW strike (no embedded day)
    is_letter_month = post_year and post_year[0] in {"O", "N", "D"}
    if suffix == "FUT":
        day = None
        strike = None
        inst = _instrument_type(underlying, "FUT")
        expiry = _lookup_expiry_date(underlying, year, month_int, None, market_knowledge)
    elif is_letter_month:
        # Letter-month: no embedded day; entire after_month_numbers = raw strike
        day = None
        strike = float(int(after_month_numbers)) if after_month_numbers.isdigit() else 0.0
        expiry = _lookup_expiry_date(underlying, year, month_int, None, market_knowledge)
        inst = _instrument_type(underlying, suffix)
    else:
        day, strike = _split_day_strike(after_month_numbers)
        expiry = _lookup_expiry_date(underlying, year, month_int, day, market_knowledge)
        inst = _instrument_type(underlying, suffix)
    return {
        "underlying": underlying,
        "expiry_date": expiry,
        "strike_price": strike,
        "option_type": suffix,
        "instrument_type": inst,
        "raw_symbol": raw,
    }


def _instrument_type(underlying: str, option_type: str) -> str:
    known_idx = {"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"}
    is_idx = underlying.upper() in known_idx
    if option_type == "FUT":
        return "FUTIDX" if is_idx else "FUTSTK"
    return "OPTIDX" if is_idx else "OPTSTK"


def _parse_tradetron_display(raw: str, mk: Optional[MarketKnowledge], as_of_year: int) -> Dict[str, Any]:
    tokens = [t for t in re.split(r"[\s_]+", raw.strip()) if t]
    if len(tokens) < 4:
        raise SymbolParseError(f"Tradetron display too few tokens: {raw!r}")
    # First token = underlying
    underlying = tokens[0].upper()
    # Suffix = last token (CE/PE/FUT)
    suf_tok = tokens[-1].upper()
    if suf_tok in {"CALL", "PUT"}:
        suf_tok = "CE" if suf_tok == "CALL" else "PE"
    if suf_tok not in {"CE", "PE", "FUT"}:
        raise SymbolParseError(f"Last token not CE/PE/FUT in Tradetron display {raw!r}")
    # Find strike = second-to-last token (numeric)
    strike_str = tokens[-2]
    if not strike_str.replace(".", "", 1).isdigit():
        raise SymbolParseError(f"Strike token not numeric in Tradetron display {raw!r}")
    strike_price = float(strike_str)
    # Find year: 4-digit numeric in tokens [1:-2]
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    for t in tokens[1:-2]:
        if t.isdigit() and len(t) == 4 and 2000 <= int(t) <= 2100:
            year = int(t)
        elif t.isdigit() and 1 <= len(t) <= 2 and 1 <= int(t) <= 31:
            day = int(t)
        elif t.upper() in _MONTH_NAME_SHORT:
            month = _MONTH_NAME_SHORT[t.upper()]
    if year is None:
        year = as_of_year
    if month is None:
        raise SymbolParseError(f"Month token missing in Tradetron display {raw!r}")
    if day is None:
        expiry = _lookup_expiry_date(underlying, year, month, None, mk)
    else:
        try:
            expiry = date(year, month, day)
        except ValueError:
            expiry = _lookup_expiry_date(underlying, year, month, None, mk)
    return {
        "underlying": underlying,
        "expiry_date": expiry,
        "strike_price": strike_price,
        "option_type": suf_tok,
        "instrument_type": _instrument_type(underlying, suf_tok),
        "exchange": "BSE" if underlying == "SENSEX" else "NSE",
        "segment": underlying,
        "raw_symbol": raw,
    }


def guesses_underlying_from_prefix(raw_symbol: str) -> Optional[str]:
    """Fallback used in symbol_parser when full pattern does not match. Returns best-guess underlying string or None."""
    if not raw_symbol:
        return None
    up = str(raw_symbol).upper().strip()
    for name in _UNDERLYING_PREFIXES:
        if up.startswith(name):
            return name
    m = re.match(r"^([A-Z][A-Z_]{1,}?)[\s_\-0-9]", up)
    if m:
        return m.group(1)
    return None
