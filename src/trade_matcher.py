"""FIFO trade matching engine for Indian F&O intra-day execution logs."""
from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .market_knowledge import MarketKnowledge
from .symbol_parser import parse_indian_symbol, SymbolParseError


class TradeMatcher:
    """FIFO matcher: pairs chronological BUY/SELL executions within each match-key group."""

    def __init__(self, market_knowledge: Optional[MarketKnowledge] = None):
        self._mk = market_knowledge or MarketKnowledge()

    # ------------------------------------------------------------------ #
    # 1. Normalise raw executions
    # ------------------------------------------------------------------ #
    def parse_and_normalize_executions(
        self,
        raw_exec_list_or_df: Any,
    ) -> pd.DataFrame:
        """Canonicalize column names, ensure required fields, sort by execution_timestamp asc."""
        if isinstance(raw_exec_list_or_df, pd.DataFrame):
            df = raw_exec_list_or_df.copy()
        elif isinstance(raw_exec_list_or_df, list):
            df = pd.DataFrame(raw_exec_list_or_df)
        else:
            raise TypeError("Expected pd.DataFrame or list of dicts")

        # Canonical column renames (keep existing names if already correct)
        rename_map: Dict[str, str] = {
            "symbol": "vendor_symbol",
            "instrument_symbol": "vendor_symbol",
            "Instrument": "vendor_symbol",
            "instrument": "vendor_symbol",
            "strategy_id": "strategy_run_id",
            "strat_id": "strategy_run_id",
            "exec_price": "execution_price",
            "price": "execution_price",
            "qty": "quantity",
            "ts": "execution_timestamp",
            "timestamp": "execution_timestamp",
            "exec_id": "execution_id",
        }
        for old_name, new_name in rename_map.items():
            if old_name in df.columns and new_name not in df.columns:
                df.rename(columns={old_name: new_name}, inplace=True)

        # Normalize side to upper
        if "side" in df.columns:
            df["side"] = df["side"].astype(str).str.strip().str.upper()
            df["side"] = df["side"].replace({"B": "BUY", "LONG": "BUY", "S": "SELL", "SHORT": "SELL"})

        # Ensure execution_id
        if "execution_id" not in df.columns:
            df["execution_id"] = [str(uuid.uuid4()) for _ in range(len(df))]

        # Parse execution_timestamp
        if "execution_timestamp" in df.columns:
            df["execution_timestamp"] = pd.to_datetime(df["execution_timestamp"])

        # Parse trade_date
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        # Sort by execution_timestamp ascending
        if "execution_timestamp" in df.columns:
            df.sort_values("execution_timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)

        return df

    # ------------------------------------------------------------------ #
    # 2. FIFO matching
    # ------------------------------------------------------------------ #
    def match_trades_fifo(
        self,
        df: pd.DataFrame,
        match_key: Optional[List[str]] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        FIFO match executions within each match_key group.

        Returns (matched_df, open_legs_df).
        """
        if match_key is None:
            match_key = ["strategy_run_id", "vendor_symbol", "trade_date"]

        matched_rows: List[Dict[str, Any]] = []
        open_rows: List[Dict[str, Any]] = []

        groups = df.groupby(match_key, sort=False)
        for _key, grp in groups:
            grp_sorted = grp.sort_values("execution_timestamp")
            buy_queue: deque = deque()
            sell_queue: deque = deque()

            for _, row in grp_sorted.iterrows():
                row_dict = row.to_dict()
                side = str(row_dict.get("side", "")).upper()
                if side == "BUY":
                    buy_queue.append(row_dict)
                elif side == "SELL":
                    sell_queue.append(row_dict)

            # FIFO pair: match first BUY with first SELL (chronological order)
            while buy_queue and sell_queue:
                buy_row = buy_queue[0]
                sell_row = sell_queue[0]

                buy_ts = buy_row.get("execution_timestamp")
                sell_ts = sell_row.get("execution_timestamp")

                # Determine which came first -> that determines side (LONG vs SHORT)
                if buy_ts <= sell_ts:
                    # BUY first -> LONG
                    entry_row = buy_queue.popleft()
                    exit_row = sell_queue.popleft()
                    side_label = "LONG"
                else:
                    # SELL first -> SHORT
                    entry_row = sell_queue.popleft()
                    exit_row = buy_queue.popleft()
                    side_label = "SHORT"

                matched_rows.append(
                    self._build_matched_record(entry_row, exit_row, side_label)
                )

            # Remaining unmatched
            for leftover in list(buy_queue) + list(sell_queue):
                open_rows.append({
                    **leftover,
                    "status": "OPEN_POSITION",
                    "reason": "No matching opposing leg found same strategy+symbol+date",
                })

        matched_df = pd.DataFrame(matched_rows) if matched_rows else pd.DataFrame()
        open_legs_df = pd.DataFrame(open_rows) if open_rows else pd.DataFrame()

        return matched_df, open_legs_df

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _build_matched_record(
        self,
        entry_row: Dict[str, Any],
        exit_row: Dict[str, Any],
        side_label: str,
    ) -> Dict[str, Any]:
        vendor_symbol = str(entry_row.get("vendor_symbol", ""))
        entry_price = float(entry_row.get("execution_price", 0))
        exit_price = float(exit_row.get("execution_price", 0))
        quantity = int(entry_row.get("quantity", 0))
        lot_size = int(entry_row.get("lot_size", 0)) or quantity
        lots = quantity // lot_size if lot_size else 1

        # Symbol parsing for segment info
        segment = self._mk.get_segment_for_symbol(vendor_symbol)
        underlying = segment if segment not in ("UNKNOWN", "STOCK_FUT", "STOCK_OPT") else None
        option_type = None
        expiry_date = None
        strike_price = None
        try:
            parsed = parse_indian_symbol(vendor_symbol, self._mk)
            underlying = parsed.get("underlying", underlying)
            option_type = parsed.get("option_type")
            expiry_date = parsed.get("expiry_date")
            strike_price = parsed.get("strike_price")
        except SymbolParseError:
            pass

        if side_label == "LONG":
            points_pnl = exit_price - entry_price
        else:
            points_pnl = entry_price - exit_price
        gross_pnl = points_pnl * quantity

        entry_ts = entry_row.get("execution_timestamp")
        exit_ts = exit_row.get("execution_timestamp")
        holding_mins = None
        if entry_ts is not None and exit_ts is not None:
            try:
                delta = exit_ts - entry_ts
                holding_mins = delta.total_seconds() / 60.0
            except Exception:
                pass

        trade_date = entry_row.get("trade_date")

        return {
            "trade_date": trade_date,
            "segment": segment,
            "underlying": underlying,
            "vendor_symbol": vendor_symbol,
            "option_type": option_type,
            "expiry_date": expiry_date,
            "strike_price": strike_price,
            "lots": lots,
            "quantity": quantity,
            "lot_size": lot_size,
            "entry_time": entry_ts,
            "exit_time": exit_ts,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "side": side_label,
            "points_pnl": round(points_pnl, 2),
            "gross_pnl": round(gross_pnl, 2),
            "holding_duration_minutes": round(holding_mins, 2) if holding_mins is not None else None,
            "match_method": "FIFO",
            "exec_ids_entry": [entry_row.get("execution_id")],
            "exec_ids_exit": [exit_row.get("execution_id")],
            "strategy_run_id": entry_row.get("strategy_run_id"),
        }
