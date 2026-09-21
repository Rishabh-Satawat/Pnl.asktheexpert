# Plan: Dual-Mode Trade Ingestion Engine (Manual Entry + Screenshot Upload)

## Summary

Replace the current single-mode (screenshot-only) Page 1 with a dual-mode ingestion system. The user toggles between:
- **Mode A: ✍️ Manual Trade Entry** — fully self-contained, zero API dependency. An inline form lets the user enter strategy cards + individual execution legs. Feeds directly into the 9-stage pipeline.
- **Mode B: 📸 Screenshot Upload** — existing Gemini Vision path (kept as-is, wrapped in the toggle).

Both modes produce the same output: `staging_data` DataFrame + `strategy_cards_extracted` list in `st.session_state`, which the existing `_run_real_pipeline()` consumes without modification.

---

## Current State Analysis

### `ui/page_daily.py` (555 lines)
- Current flow: Date picker → Screenshot upload → Gemini extract button → Staging editor → Pipeline → Results
- The Gemini key check currently gates the entire input path; if no key, only a CSV fallback appears
- `_run_real_pipeline()` reads from `st.session_state["staging_data"]` (DataFrame) and `st.session_state["strategy_cards_extracted"]` (list of dicts)
- The staging DataFrame columns used downstream: `vendor_symbol`, `side`, `quantity`, `price`/`avg_price`, `execution_time`, `condition`, `exchange`, `segment`, `trade_date`
- Strategy card dict keys used in pipeline: `strategy_name`, `capital_deployed_allocated`, `multiplier_x`, `deployment_status`, `booked_gross_pnl`, `card_roi_pct`

### `src/pnl_pipeline.py`
- `stage_1_ingest_sources(manual_csv_df=staging_df)` — accepts any DataFrame as manual input
- `stage_3_review_staging()` — strategy cards are injected into `s3.dataframes["strategy_cards_df"]` by the UI runner
- No pipeline changes needed — the manual entry mode just populates the same session_state keys

### `src/market_knowledge.py`
- `_BUILTIN_SEEDS` provides: underlying, lot_size, exchange, expiry_weekday_number for all 5 indices
- Available via `MarketKnowledge()` with no DB dependency (fallback to seeds)
- Use this to auto-fill `exchange`, `segment`, `lot_size` in the manual entry form

---

## Proposed Changes

### Only 1 File Changes: `ui/page_daily.py`

#### A. Add Mode Toggle at the top of `render_daily_processing()`

Insert immediately after the date picker and before the existing screenshot upload block:

```python
st.divider()
mode = st.radio(
    "Select Ingestion Mode",
    ["✍️ Manual Trade Entry", "📸 Screenshot Upload"],
    horizontal=True,
    key="ingestion_mode",
)
st.divider()
```

#### B. Wrap the Existing Screenshot Block in `if mode == "📸 Screenshot Upload":`

Move the entire block from `# ── Screenshot Upload ─────` to `else: st.caption(...)` into this branch.

**Important:** The Gemini key error and missing-key path stay inside this branch. Manual entry has NO dependency on Gemini key.

#### C. Add `elif mode == "✍️ Manual Trade Entry":` block

This new block contains:

**1. Strategy Card Entry Form (collapsible expander)**

```python
with st.expander("📋 Strategy Card Details (Capital & Multiplier)", expanded=True):
    sc_name = st.text_input("Strategy Name", value="SENSEX BFO Dynamic Inside-Day Short Strangle v1", key="sc_name")
    col1, col2, col3 = st.columns(3)
    with col1:
        sc_capital = st.number_input("Capital Deployed (₹)", min_value=0.0, value=300000.0, step=10000.0, key="sc_capital")
    with col2:
        sc_multiplier = st.selectbox("Multiplier", [1, 2, 3, 4, 5], index=0, key="sc_multiplier")
    with col3:
        sc_status = st.selectbox("Status", ["Exited", "LIVE AUTO", "Paused"], key="sc_status")
    sc_broker = st.selectbox("Broker", ["Zerodha", "Dhan", "Upstox"], key="sc_broker")
```

**2. Underlying & Segment Selector (drives auto-fill)**

```python
col_seg, col_exch = st.columns(2)
with col_seg:
    segment = st.selectbox("Underlying / Segment", ["SENSEX", "BANKNIFTY", "NIFTY", "FINNIFTY", "MIDCPNIFTY"], key="me_segment")
with col_exch:
    # Auto-infer from segment
    exchange = "BSE" if segment == "SENSEX" else "NSE"
    st.text_input("Exchange", value=exchange, disabled=True, key="me_exchange")
```

**3. Trade Execution Legs Table**

Use `st.data_editor` with an initial template DataFrame. The operator can add/edit/delete rows directly.

Initial template (2 rows for a standard short strangle — sell PE + sell CE):

```python
import pandas as pd
_LOT_MAP = {"SENSEX": 20, "BANKNIFTY": 15, "NIFTY": 25, "FINNIFTY": 25, "MIDCPNIFTY": 50}
lot_size = _LOT_MAP.get(segment, 20)

default_rows = pd.DataFrame([
    {
        "vendor_symbol": f"OPTIDX_{segment}_{report_date.strftime('%d%b%Y').upper()}_PE_00000",
        "trade_date": str(report_date),
        "execution_time": "09:30:00",
        "condition": "Entry",
        "side": "SELL",
        "quantity": lot_size * sc_multiplier,
        "price": 0.0,
        "amount": 0.0,
        "exchange": exchange,
        "segment": segment,
    },
    {
        "vendor_symbol": f"OPTIDX_{segment}_{report_date.strftime('%d%b%Y').upper()}_PE_00000",
        "trade_date": str(report_date),
        "execution_time": "15:20:00",
        "condition": "Universal Exit",
        "side": "BUY",
        "quantity": lot_size * sc_multiplier,
        "price": 0.0,
        "amount": 0.0,
        "exchange": exchange,
        "segment": segment,
    },
    {
        "vendor_symbol": f"OPTIDX_{segment}_{report_date.strftime('%d%b%Y').upper()}_CE_00000",
        "trade_date": str(report_date),
        "execution_time": "09:30:00",
        "condition": "Entry",
        "side": "SELL",
        "quantity": lot_size * sc_multiplier,
        "price": 0.0,
        "amount": 0.0,
        "exchange": exchange,
        "segment": segment,
    },
    {
        "vendor_symbol": f"OPTIDX_{segment}_{report_date.strftime('%d%b%Y').upper()}_CE_00000",
        "trade_date": str(report_date),
        "execution_time": "15:20:00",
        "condition": "Universal Exit",
        "side": "BUY",
        "quantity": lot_size * sc_multiplier,
        "price": 0.0,
        "amount": 0.0,
        "exchange": exchange,
        "segment": segment,
    },
])
```

Render with `st.data_editor`:
```python
edited_legs = st.data_editor(
    st.session_state.get("manual_entry_legs", default_rows),
    use_container_width=True,
    num_rows="dynamic",
    column_config={
        "side": st.column_config.SelectboxColumn("Side", options=["BUY", "SELL"]),
        "condition": st.column_config.SelectboxColumn("Condition", options=["Entry", "Universal Exit", "SL Hit", "Target Hit"]),
        "exchange": st.column_config.SelectboxColumn("Exchange", options=["NSE", "BSE"]),
        "segment": st.column_config.SelectboxColumn("Segment", options=["SENSEX", "BANKNIFTY", "NIFTY", "FINNIFTY", "MIDCPNIFTY"]),
    },
    key="manual_legs_editor",
)
st.session_state["manual_entry_legs"] = edited_legs
```

**4. "Load into Staging" Button**

```python
if st.button("✅ Load into Staging", type="primary", key="btn_load_manual"):
    # Build staging_data from legs
    st.session_state["staging_data"] = edited_legs.copy()

    # Build strategy card dict
    strategy_card = {
        "strategy_name": sc_name,
        "capital_deployed_allocated": sc_capital,
        "multiplier_x": sc_multiplier,
        "deployment_status": sc_status,
        "broker": sc_broker,
        "booked_gross_pnl": 0.0,   # will be computed by pipeline
        "card_roi_pct": 0.0,
    }
    st.session_state["strategy_cards_extracted"] = [strategy_card]
    st.success(f"✅ {len(edited_legs)} execution rows loaded into staging. Scroll down to review and run pipeline.")
```

**5. Optional: Contract Note Charges (for REALIZED mode)**

```python
with st.expander("📄 Contract Note Charges (optional — leave blank for FORMULA mode)"):
    col_b, col_stt, col_gst = st.columns(3)
    with col_b:
        cn_brokerage = st.number_input("Brokerage (₹)", value=0.0, min_value=0.0, key="cn_brokerage")
    with col_stt:
        cn_stt = st.number_input("STT (₹)", value=0.0, min_value=0.0, key="cn_stt")
    with col_gst:
        cn_gst = st.number_input("GST (₹)", value=0.0, min_value=0.0, key="cn_gst")
    col_exch_fee, col_sebi, col_stamp = st.columns(3)
    with col_exch_fee:
        cn_exchange_fee = st.number_input("Exchange Fee (₹)", value=0.0, min_value=0.0, key="cn_exch_fee")
    with col_sebi:
        cn_sebi = st.number_input("SEBI Charges (₹)", value=0.0, min_value=0.0, key="cn_sebi")
    with col_stamp:
        cn_stamp = st.number_input("Stamp Duty (₹)", value=0.0, min_value=0.0, key="cn_stamp")
    cn_total = cn_brokerage + cn_stt + cn_gst + cn_exchange_fee + cn_sebi + cn_stamp
    if cn_total > 0:
        st.metric("Total Charges", f"₹{cn_total:,.2f}")
        # Store for pipeline to pick up
        st.session_state["contract_note_extracted"] = {
            "brokerage_amount": cn_brokerage,
            "securities_transaction_tax_stt": cn_stt,
            "gst": cn_gst,
            "exchange_turnover_fee_amount": cn_exchange_fee,
            "sebi_turnover_charges": cn_sebi,
            "stamp_duty": cn_stamp,
            "total_charges_grand_total": cn_total,
        }
```

#### D. Shared Section (Both Modes) — Staging Review + Pipeline + Results

The existing Staging Review (`st.data_editor`), Pipeline execution button, Results tabs, and Export buttons remain **unchanged** and appear for both modes.

---

## Data Flow After Fix

```
Manual Entry Mode:
  User fills form → clicks "Load into Staging"
    → st.session_state["staging_data"] = DataFrame(execution_legs)
    → st.session_state["strategy_cards_extracted"] = [strategy_card_dict]
    → (optional) st.session_state["contract_note_extracted"] = charges_dict

  → Staging Review (editable) → "Approve & Run Pipeline"
    → _run_real_pipeline(staging_df) → 9 stages (Stage 2 skips Gemini for manual input)
    → Results tabs: Summary, Strategy Cards, Analytics, Trade Log, Reconciliation
    → Export: PDF, Excel, CSVs, DB save

Screenshot Mode:
  (unchanged — Gemini extracts → staging → pipeline)
```

---

## Files to Change

| File | Change |
|------|--------|
| `ui/page_daily.py` | Add mode toggle, add Manual Entry block, wrap Screenshot block in condition |

No other files need modification — the pipeline, aggregator, matcher, and cost calculator all remain unchanged.

---

## Assumptions & Decisions

- **Session state key `manual_entry_legs`**: Persists the leg table across Streamlit reruns (avoids losing user edits when segment changes)
- **`booked_gross_pnl` in strategy card**: Set to 0.0 at "Load into Staging" time; the pipeline computes actual gross P&L from matched legs in Stage 5/7
- **FORMULA charge mode is default**: If no contract note charges are entered, pipeline uses Zerodha formula. REALIZED mode activates automatically when `contract_note_extracted` has `total_charges_grand_total > 0`
- **Template rows auto-update on segment change**: The `default_rows` template is only shown when `manual_entry_legs` is not in session_state. Once loaded, the editor shows persisted data.
- **No validation on symbol format**: The symbol field is free text — the pipeline's symbol parser (Pattern 0 for OPTIDX_* format) handles parsing. Operator can type the exact Tradetron vendor symbol.
- **Gemini API error does NOT affect Manual Entry mode** — the error is only shown inside the Screenshot Upload branch

---

## Verification Steps

1. Run `pytest tests/ -q` — all existing tests should still pass (no pipeline changes)
2. Open app locally → Page 1 → confirm mode toggle appears at top
3. Select "✍️ Manual Trade Entry" → fill in SENSEX, capital ₹3L, 2x, PE at 193.75 sell + 218.35 buy, CE at 407.40 sell + 333.55 buy
4. Click "Load into Staging" → verify 4 rows appear in staging editor
5. Click "Approve & Run Pipeline" → verify Summary tab shows Net P&L and ROI
6. Select "📸 Screenshot Upload" → verify existing behavior unchanged
7. Push to GitHub → verify Streamlit Cloud redeploys successfully
