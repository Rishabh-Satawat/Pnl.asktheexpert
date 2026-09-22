# Plan: Multimodal Multi-Image Parsing & Tradetron Ingestion Fix

## Summary

Four critical bugs were observed in production when 3 screenshots (Tradetron strategy card + 2 Tradetron position modals) were uploaded:

1. **Image overwrite bug** — only CE leg survived; PE leg was dropped
2. **`exchange: None`** — SENSEX/BSE not auto-inferred; charges failed
3. **Missing timestamps & condition** — `execution_time`, `condition` (Entry vs Universal Exit) not extracted
4. **Strategy card not linked to executions** — capital/multiplier/ROI not available in results

## Current State Analysis

### `src/gemini_parser.py`
- `UNIVERSAL_EXTRACTION_PROMPT` returns `kite_positions[]` (Zerodha Kite format) and `strategy_cards[]`
- `parse_screenshots()` calls `parse_image()` per image, appends `kite_positions` into `positions` list and `strategy_cards` separately
- **Bug root cause:** Tradetron position modals are NOT Zerodha Kite positions. They have a completely different structure: `Date`, `Time`, `Condition` (Entry / Universal Exit), `Instrument`, `Quantity`, `Price`, `Amount`. The current prompt schema has NO `executions[]` field for this format. So when Gemini sees Image B (PE modal) it tries to fit it into `kite_positions[]` but likely fails or partially overwrites because the schema doesn't match → empty result → dropped.
- `exchange` is never inferred from symbol content in the parser — it's entirely Gemini's job, which fails for `OPTIDX_SENSEX_*` symbols.

### `ui/page_daily.py`
- After extraction: `staging_df = pd.DataFrame(positions)` — only Kite positions format
- If `positions` is empty and `strategy_cards` has data, falls back to strategy_cards DataFrame
- **No `executions[]` path exists** — Tradetron modal executions are silently lost
- The `gemini_result["strategy_cards"]` is stored separately but never merged into the staging DataFrame shown to the user

### `src/symbol_parser.py`
- Does NOT parse `OPTIDX_SENSEX_24SEP2026_PE_74300` format (Tradetron vendor symbols with underscore-separated format)
- Current patterns handle NSE-style compact symbols only (e.g., `SENSEX26SEP74300PE`)

### `src/cost_calculator.py`
- Requires `exchange` field (`"NSE"` or `"BSE"`) for correct fee rates
- When `exchange = None`, fee calculation fails silently

## Proposed Changes

### File 1: `src/gemini_parser.py`

**What:** Replace `UNIVERSAL_EXTRACTION_PROMPT` with a new schema that adds an `executions[]` array specifically for Tradetron position modal rows. Keep `kite_positions[]` for Zerodha Kite screenshots. Add auto-inference of `exchange` and `segment` from symbol name.

**How:**

1. Replace the JSON schema in `UNIVERSAL_EXTRACTION_PROMPT` to include:
```json
{
  "screen_type": "TRADETRON_STRATEGY_CARD | TRADETRON_POSITION_MODAL | ZERODHA_KITE_POSITIONS | ZERODHA_VIRTUAL_CONTRACT_NOTE | UNKNOWN",
  "strategy_cards": [ ... ],
  "executions": [
    {
      "vendor_symbol": "OPTIDX_SENSEX_24SEP2026_PE_74300",
      "trade_date": "2026-09-21",
      "execution_time": "09:30:02",
      "condition": "Entry",
      "side": "SELL",
      "quantity": 40,
      "price": 193.75,
      "amount": -7750.0,
      "exchange": "BSE",
      "segment": "SENSEX"
    }
  ],
  "kite_positions": [ ... ],
  "contract_note_charges": { ... }
}
```

2. Add a **few-shot example** for Tradetron position modal in the prompt showing:
   - `OPTIDX_SENSEX_24SEP2026_PE_74300` → `exchange: "BSE"`, `segment: "SENSEX"`
   - `Entry` condition with qty `-40` → `side: "SELL"`
   - `Universal Exit` condition with qty `40` → `side: "BUY"`

3. Add an **exchange/segment inference rule** in the prompt:
   - Symbol contains `SENSEX` → `exchange = "BSE"`, `segment = "SENSEX"`
   - Symbol contains `BANKNIFTY` → `exchange = "NSE"`, `segment = "BANKNIFTY"`
   - Symbol contains `NIFTY` (not BANKNIFTY) → `exchange = "NSE"`, `segment = "NIFTY"`
   - Symbol contains `FINNIFTY` → `exchange = "NSE"`, `segment = "FINNIFTY"`
   - Symbol contains `MIDCPNIFTY` → `exchange = "NSE"`, `segment = "MIDCPNIFTY"`

4. Update `parse_screenshots()` to merge `executions[]` from all images into a combined list (same append pattern as `kite_positions`):
```python
executions: List[dict] = []
...
executions.extend(result.get("executions") or [])
...
return {
    "positions": positions,
    "executions": executions,         # NEW
    "strategy_cards": strategy_cards,
    "contract_note": contract_note,
}
```

5. Add a post-processing `_infer_exchange()` static method as a fallback that runs after Gemini extraction on any row where `exchange` is `None` or missing:
```python
@staticmethod
def _infer_exchange(symbol: str) -> tuple[str, str]:
    """Infer (exchange, segment) from symbol string."""
    s = symbol.upper()
    if "SENSEX" in s:
        return "BSE", "SENSEX"
    if "BANKNIFTY" in s:
        return "NSE", "BANKNIFTY"
    if "FINNIFTY" in s:
        return "NSE", "FINNIFTY"
    if "MIDCPNIFTY" in s or "MIDCAP" in s:
        return "NSE", "MIDCPNIFTY"
    if "NIFTY" in s:
        return "NSE", "NIFTY"
    return "NSE", "UNKNOWN"
```
Apply `_infer_exchange()` to every row in `executions`, `kite_positions` where `exchange` is None/missing after extraction.

---

### File 2: `ui/page_daily.py`

**What:** After Gemini extraction, build the staging DataFrame from `executions` first (Tradetron modal format), then fall back to `positions` (Kite format), then `strategy_cards`. Store strategy card metadata separately in session_state for the pipeline.

**How:**

1. In the extraction button handler, after `result = parser.parse_screenshots(...)`:
```python
executions = result.get("executions", [])
positions  = result.get("positions", [])
sc         = result.get("strategy_cards", [])

if executions:
    staging_df = pd.DataFrame(executions)
elif positions:
    staging_df = pd.DataFrame(positions)
elif sc:
    staging_df = pd.DataFrame(sc)
else:
    staging_df = pd.DataFrame()

st.session_state["staging_data"] = staging_df
st.session_state["gemini_result"] = result
st.session_state["strategy_cards_extracted"] = sc   # store for pipeline
```

2. Show a **strategy card info box** above the staging table when `strategy_cards_extracted` is populated — one line per card showing: strategy name, capital, multiplier, status, booked P&L. This gives the user immediate visual confirmation the card was read.

3. In `_run_real_pipeline()`, pass `strategy_cards_extracted` to stage_3:
   - Extract from `st.session_state.get("strategy_cards_extracted", [])` and store as `strategies_df = pd.DataFrame(strategy_cards_extracted)`
   - Use this `strategies_df` when calling `stage_7_compute_summary(strategies_df, matched_df, charges_df)` so capital deployed is available for ROI calculation.

---

### File 3: `src/symbol_parser.py`

**What:** Add Pattern 0 for Tradetron's `OPTIDX_UNDERLYING_DDMMMYYYY_CE/PE_STRIKE` format so `OPTIDX_SENSEX_24SEP2026_PE_74300` can be parsed into `{underlying: "SENSEX", expiry: "2026-09-24", option_type: "PE", strike: 74300.0}`.

**How:**

Add at the top of `parse_indian_symbol()`, before any existing patterns:
```python
# Pattern 0: Tradetron OPTIDX format
# e.g. OPTIDX_SENSEX_24SEP2026_PE_74300
_OPTIDX_RE = re.compile(
    r"^OPTIDX_([A-Z]+)_(\d{2})([A-Z]{3})(\d{4})_(CE|PE)_(\d+)$"
)
m = _OPTIDX_RE.match(raw.upper())
if m:
    underlying = m.group(1)   # e.g. "SENSEX"
    day  = int(m.group(2))    # 24
    mon  = m.group(3)         # "SEP"
    year = int(m.group(4))    # 2026
    opt  = m.group(5)         # "PE"
    strike = float(m.group(6))  # 74300.0
    month_int = _MONTH_NAME_SHORT[mon]  # 9
    expiry = _lookup_expiry_date(underlying, year % 100, month_int, day, market_knowledge)
    exchange, segment = ("BSE", "SENSEX") if underlying == "SENSEX" else ("NSE", underlying)
    return {
        "underlying": underlying,
        "expiry_date": expiry,
        "option_type": opt,
        "strike": strike,
        "exchange": exchange,
        "segment": segment,
        "raw": raw,
    }
```

Also add `SENSEX` to `_UNDERLYING_PREFIXES` list if not already present.

---

### File 4: `src/cost_calculator.py`

**What:** Add a guard so when `exchange` is `None` or unrecognized, the calculator auto-infers from the symbol string rather than crashing.

**How:**

In the method that picks NSE vs BSE exchange turnover fee rate, add:
```python
exchange = execution.get("exchange") or ""
if not exchange:
    sym = execution.get("vendor_symbol", "")
    exchange = "BSE" if "SENSEX" in sym.upper() else "NSE"
```

This is a safety net — the primary fix is in the parser. This ensures the cost calculator is resilient even if exchange is not set.

---

## Data Flow After Fix (End-to-End)

```
Image A (Strategy Card)   → gemini_parser → strategy_cards[{name, capital, multiplier, pnl}]
Image B (PE modal)        → gemini_parser → executions[{PE Entry row, PE Exit row}]
Image C (CE modal)        → gemini_parser → executions[{CE Entry row, CE Exit row}]

parse_screenshots() merges: executions = [PE_Entry, PE_Exit, CE_Entry, CE_Exit]

ui staging_df = DataFrame(executions)  ← 4 rows visible in staging table

strategy_cards stored in session_state["strategy_cards_extracted"]

pipeline.stage_7_compute_summary(
    strategies_df = DataFrame(strategy_cards),  ← capital_deployed = 300000
    matched_df    = FIFO matched executions,
    charges_df    = computed charges
)

Strategy Net ROI = (Net P&L / 300000) * 100
```

---

## Verification Steps

1. **Unit test:** `pytest tests/test_gemini_parser.py -v` — all pass
2. **Symbol parser test:** `pytest tests/test_symbol_parser.py -v` — `OPTIDX_SENSEX_24SEP2026_PE_74300` parses correctly
3. **Full suite:** `pytest tests/ -q` — 56+ passed, 0 failures
4. **Live test:** Upload 3 screenshots (strategy card + PE modal + CE modal) in the Streamlit app
   - Staging table must show **4 rows** (PE Entry, PE Exit, CE Entry, CE Exit)
   - Strategy card info box must appear above staging table
   - `exchange` column must show `BSE` for all SENSEX rows
   - After running pipeline: Summary tab shows Net P&L and ROI% using capital ₹3,00,000
   - Reconciliation tab shows charges data (no longer empty)
5. **Push to GitHub** → Streamlit Cloud auto-deploys

---

## Assumptions & Decisions

- Tradetron `OPTIDX_*` format is the primary ingestion format (not Zerodha Kite positions) for this desk's workflow
- Strategy card is always Image 1 (or first card image); position modals are subsequent images — but the fix handles any order by merging all executions regardless of image order
- `exchange` and `segment` are always deterministic from the symbol name — no user input needed for these two fields
- Strategy card capital (`₹3.00 L = 300000`) is the ROI denominator — not SPAN margin
- Multiplier (`2x`) is stored but not doubled against the lot quantities (Tradetron already executes at the multiplied quantity in the position modals)
- The `OPTIDX_SENSEX_24SEP2026_PE_74300` format uses the actual expiry date (`24SEP2026`) not the weekly code — so `_lookup_expiry_date` with day=24 should directly return `2026-09-24`

---

## Files to Change (Summary)

| File | Change Type | Priority |
|------|------------|----------|
| `src/gemini_parser.py` | Prompt schema + `executions[]` merge + `_infer_exchange()` | HIGH |
| `ui/page_daily.py` | Use `executions` for staging_df + strategy card info box | HIGH |
| `src/symbol_parser.py` | Pattern 0 for `OPTIDX_*` format | HIGH |
| `src/cost_calculator.py` | Exchange fallback guard | MEDIUM |
