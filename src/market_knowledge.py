from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, List, Any

import pandas as pd

from .db.engine import build_engine
from .db.schema import MarketKnowledge as MKModel
from sqlalchemy.orm import Session, sessionmaker


SEGMENTS = ["SENSEX", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "STOCK_FUT", "STOCK_OPT", "UNKNOWN"]


@dataclass(frozen=True)
class _MKBuiltinSeed:
    underlying: str
    exchange: str
    instrument_type: str
    lot_size: int
    strike_interval: Optional[float]
    weekly_expiry_available: bool
    expiry_weekday_number: Optional[int]
    span_margin_pct: float
    exposure_margin_pct: float
    effective_date: date


_BUILTIN_SEEDS: List[_MKBuiltinSeed] = [
    _MKBuiltinSeed("NIFTY", "NSE", "OPTIDX", 25, 50.0, True, 1, 0.12, 0.05, date(2026, 4, 1)),
    _MKBuiltinSeed("BANKNIFTY", "NSE", "OPTIDX", 15, 100.0, True, 3, 0.14, 0.06, date(2026, 4, 1)),
    _MKBuiltinSeed("SENSEX", "BSE", "OPTIDX", 20, 100.0, True, 0, 0.12, 0.05, date(2026, 4, 1)),
    _MKBuiltinSeed("FINNIFTY", "NSE", "OPTIDX", 25, 50.0, False, 1, 0.12, 0.05, date(2026, 4, 1)),
    _MKBuiltinSeed("MIDCPNIFTY", "NSE", "OPTIDX", 50, 25.0, False, 0, 0.14, 0.06, date(2026, 4, 1)),
    _MKBuiltinSeed("NIFTY", "NSE", "FUTIDX", 25, None, False, 3, 0.10, 0.03, date(2026, 4, 1)),
    _MKBuiltinSeed("BANKNIFTY", "NSE", "FUTIDX", 15, None, False, 3, 0.11, 0.04, date(2026, 4, 1)),
    _MKBuiltinSeed("SENSEX", "BSE", "FUTIDX", 20, None, False, 3, 0.10, 0.03, date(2026, 4, 1)),
]

_KNOWN_UNDERLYINGS = {s.underlying for s in _BUILTIN_SEEDS}

_INDEX_PREFIX_RE = re.compile(
    r"^(NIFTY|BANKNIFTY|SENSEX|FINNIFTY|MIDCPNIFTY)[\s\-_0-9A-Z]?",
    re.IGNORECASE,
)

_FUT_RE = re.compile(r"(FUT|FUTURE|FUTURES)$", re.IGNORECASE)
_OPT_RE = re.compile(r"(CE|PE|CALL|PUT)$", re.IGNORECASE)


class MarketKnowledge:
    """
    Indian F&O index + contract knowledge module.
    Primary lookup: SQLite market_knowledge table (writable via Settings page).
    Secondary fallback: frozen _BUILTIN_SEEDS (always identical to Task-1 DB seed rows) —
    ensures hot path works even when DB hasn't been initialised yet (e.g. tests, manual CSV import).
    """

    def __init__(self, session_or_engine=None):
        self._session_provider: Optional[sessionmaker] = None
        self._use_db = False
        if session_or_engine is not None:
            try:
                from sqlalchemy.engine import Engine
                from sqlalchemy.orm import Session as _S
                if isinstance(session_or_engine, Engine):
                    self._session_provider = sessionmaker(bind=session_or_engine, autoflush=False, autocommit=False, future=True)
                elif isinstance(session_or_engine, _S):
                    self._session_provider = lambda: session_or_engine
                else:
                    self._session_provider = session_or_engine
                self._use_db = True
            except Exception:
                self._use_db = False

    # ---------- public API ----------
    def get_lot_size(self, underlying: str, date_: Optional[date] = None) -> Optional[int]:
        row = self._find_row(underlying=underlying.upper().strip())
        if row is None:
            return None
        return row["lot_size"]

    def get_segment_for_symbol(self, vendor_symbol: str) -> str:
        if not vendor_symbol:
            return "UNKNOWN"
        sym = vendor_symbol.strip().upper()
        for idx in ["BANKNIFTY", "MIDCPNIFTY", "FINNIFTY", "SENSEX", "NIFTY"]:
            if sym.startswith(idx):
                return idx
        m = _INDEX_PREFIX_RE.match(sym)
        if m:
            found = m.group(1).upper()
            if found in _KNOWN_UNDERLYINGS:
                return found
        # Stock classification: futures vs options
        if _FUT_RE.search(sym) or "FUT" in sym:
            return "STOCK_FUT"
        if _OPT_RE.search(sym):
            return "STOCK_OPT"
        # Heuristic: numeric-heavy + 20+ chars is likely STOCK_OPT; short raw tickers UNKNOWN
        if re.search(r"\d{4,}", sym):
            # has strike cluster: likely an option we didn't recognise
            return "STOCK_OPT"
        return "UNKNOWN"

    def get_margin_params(self, underlying: str, date_: Optional[date] = None) -> Dict[str, float]:
        row = self._find_row(underlying=underlying.upper().strip())
        if row is None:
            return {
                "span_margin_pct": 0.14,
                "exposure_margin_pct": 0.06,
                "source": "fallback_defaults_unknown_underlying",
            }
        return {
            "span_margin_pct": row["span_margin_pct"],
            "exposure_margin_pct": row["exposure_margin_pct"],
            "lot_size": row["lot_size"],
            "exchange": row["exchange"],
            "source": "current",
        }

    def get_exchange(self, underlying: str) -> Optional[str]:
        row = self._find_row(underlying=underlying.upper().strip())
        if row is None:
            return None
        return row["exchange"]

    def is_valid_index(self, underlying: str) -> bool:
        if not underlying:
            return False
        u = underlying.upper().strip()
        r = self._find_row(underlying=u)
        return r is not None and r["instrument_type"] in {"OPTIDX", "FUTIDX"}

    def classify_trades_by_segment(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            out = df.copy()
            out["segment"] = pd.Series(dtype="object")
            return out
        sym_col = self._pick_symbol_col(df)
        if sym_col is None:
            df = df.copy()
            df["segment"] = "UNKNOWN"
            return df
        out = df.copy()
        out["segment"] = out[sym_col].astype(str).map(self.get_segment_for_symbol).fillna("UNKNOWN")
        if "lot_size" not in out.columns:
            def _infer_lot(row):
                seg = row["segment"]
                if seg in _KNOWN_UNDERLYINGS:
                    return self.get_lot_size(seg)
                return None
            out["expected_lot_size"] = out.apply(_infer_lot, axis=1)
        return out

    # ---------- internals ----------
    def _pick_symbol_col(self, df: pd.DataFrame) -> Optional[str]:
        for cand in ["vendor_symbol", "symbol", "instrument_symbol", "Instrument", "instrument"]:
            if cand in df.columns:
                return cand
        return None

    def _find_row(self, underlying: str) -> Optional[Dict[str, Any]]:
        if self._use_db:
            db_row = self._db_find(underlying)
            if db_row is not None:
                return db_row
        for s in _BUILTIN_SEEDS:
            if s.underlying == underlying:
                # prefer OPTIDX when caller hasn't specified instrument_type yet
                return self._seed_to_dict(s)
        return None

    def _db_find(self, underlying: str) -> Optional[Dict[str, Any]]:
        try:
            if self._session_provider is None:
                return None
            sess = self._session_provider()
            try:
                row = sess.query(MKModel).filter(
                    MKModel.underlying == underlying,
                    MKModel.is_current == True,
                ).order_by(MKModel.effective_date.desc()).first()
                if row is None:
                    return None
                return {
                    "underlying": row.underlying,
                    "exchange": row.exchange,
                    "instrument_type": row.instrument_type,
                    "lot_size": row.lot_size,
                    "strike_interval": row.strike_interval,
                    "weekly_expiry_available": bool(row.weekly_expiry_available),
                    "expiry_weekday_number": row.expiry_weekday_number,
                    "span_margin_pct": float(row.span_margin_pct),
                    "exposure_margin_pct": float(row.exposure_margin_pct),
                    "effective_date": row.effective_date,
                    "source": "db_market_knowledge",
                }
            finally:
                try:
                    sess.close()
                except Exception:
                    pass
        except Exception:
            return None

    @staticmethod
    def _seed_to_dict(s: _MKBuiltinSeed) -> Dict[str, Any]:
        return {
            "underlying": s.underlying,
            "exchange": s.exchange,
            "instrument_type": s.instrument_type,
            "lot_size": s.lot_size,
            "strike_interval": s.strike_interval,
            "weekly_expiry_available": s.weekly_expiry_available,
            "expiry_weekday_number": s.expiry_weekday_number,
            "span_margin_pct": s.span_margin_pct,
            "exposure_margin_pct": s.exposure_margin_pct,
            "effective_date": s.effective_date,
            "source": "builtin_seed_2026_04_01",
        }
