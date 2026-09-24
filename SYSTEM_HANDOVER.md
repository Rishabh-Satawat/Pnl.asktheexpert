# SYSTEM HANDOVER: Private Quant Desk P&L Engine v1.0

**Target Audience:** Senior Python engineer / Spark AI taking over independent development  
**Last Updated:** 2026-09-22  
**Python Version:** 3.11  

---

## 1. REPOSITORY INVENTORY & FILE MAP

### Core Modules Summary

| File | Purpose | Public APIs | Key Dependencies |
|------|---------|------------|------------------|
| `pnl_pipeline.py` | 9-stage pipeline orchestrator | `DailyPipelineOrchestrator.run_entire_pipeline()` | All cost, margin, symbol, trade_matcher modules |
| `cost_calculator.py` | Zerodha F&O charges (FORMULA vs REALIZED dual-mode) | `FOCostCalculator.calculate_option_roundtrip_costs_formula()`, `allocate_charges_to_strategies()` | pnl_pipeline, strategy_aggregator |
| `trade_matcher.py` | FIFO pairing of BUY/SELL executions per strategy+symbol+date | `TradeMatcher.match_trades_fifo()` | pnl_pipeline, strategy_aggregator |
| `symbol_parser.py` | Parse Indian F&O symbols (NIFTY2692224000CE → underlying, expiry, strike) | `parse_indian_symbol(symbol, market_knowledge)` raises `SymbolParseError` | pnl_pipeline stage 4, trade_matcher |
| `market_knowledge.py` | Segment/lot-size/exchange/margin lookup + builtin fallback seeds | `MarketKnowledge.get_lot_size()`, `.get_segment_for_symbol()`, `.get_margin_params()` | pnl_pipeline, trade_matcher, symbol_parser |
| `gemini_parser.py` | Google Gemini Vision multimodal extraction (Tradetron, Kite, contract note) | `GeminiScreenshotParser.parse_image(path)` → dict | pnl_pipeline stage 2 |
| `strategy_aggregator.py` | Aggregate matched trades → strategy-level P&L | `aggregate_strategy_runs()`, `compute_portfolio_day_summary()` | pnl_pipeline stage 7 |
| `margin_calculator.py` | SEBI SPAN + Exposure margin estimation (secondary audit metric) | `SEBIMarginCalculator.estimate_peak_margins()` | pnl_pipeline, report_engine |
| `supabase_store.py` | Dual-write Postgres persistence (primary cloud store) | `SupabaseStore.upsert_daily_summary()`, `.upsert_strategy_runs()`, `.upsert_equity_curve()` | pnl_pipeline stage 8 |
| `sqlite_store.py` | Local SQLite buffer + fallback store | SQLAlchemy ORM layer | pnl_pipeline stage 8, all UI pages |

---

## 2. DATA SCHEMAS & STATE MANAGEMENT

### Staging DataFrames (Pipeline Input)

**strategy_cards_df** (from Manual CSV or Gemini extraction):
```
strategy_name (str)              # e.g. "SENSEX Short Strangle v1"
deployment_status (str)          # EXITED | LIVE_AUTO | PARTIAL
multiplier_x (int)               # Leverage multiplier (1, 2, 3, ...)
capital_deployed_allocated (float) # ₹ from Tradetron card
booked_gross_pnl (float)         # Optional, extracted from card
broker (str)                     # Zerodha | Dhan | Upstox
```

**trade_executions_df** (post-stage 4 normalization):
```
strategy_run_id (int)            # Foreign key
vendor_symbol (str)              # Raw symbol as received (e.g. SENSEX24SEP2026PE74300)
segment (str) [DERIVED]          # SENSEX | NIFTY | BANKNIFTY | FINNIFTY | MIDCPNIFTY
underlying (str) [DERIVED]       # Parsed from vendor_symbol
exchange (str) [DERIVED]         # NSE or BSE
side (str)                       # BUY | SELL (normalized to upper)
quantity (int)                   # lots × lot_size
execution_price (float)          # Premium in ₹
option_type (str) [DERIVED]      # PE | CE | FUT
expiry_date (date) [DERIVED]     # Parsed from symbol
strike_price (float) [DERIVED]   # Parsed from symbol
lot_size_lookup (int) [DERIVED]  # From market_knowledge
```

**matched_df** (post-stage 5 FIFO matching):
```
match_pair_id (str)              # UUID linking BUY-SELL pair
strategy_run_id (int)
segment, underlying, exchange (str)
side (str)                       # LONG | SHORT (derived from entry/exit order)
entry_price (float)              # BUY price for LONG (or SELL for SHORT)
exit_price (float)               # SELL price for LONG (or BUY for SHORT)
quantity (int)
gross_pnl (float)                # (exit - entry) × qty for LONG; reversed for SHORT
holding_duration_minutes (float) # (exit_ts - entry_ts) / 60
```

### Supabase PostgreSQL Schema (5 Tables)

**daily_summaries** (PK: `report_date`)
```
report_date DATE PRIMARY KEY
total_trades_executed INTEGER
total_strategy_runs INTEGER
win_count, loss_count INTEGER
total_capital_deployed_peak NUMERIC(18,2)
total_gross_pnl NUMERIC(18,2)
total_transaction_cost_drag NUMERIC(18,2)  -- sum of all allocated_charges
total_net_pnl NUMERIC(18,2)
portfolio_day_net_roi_pct NUMERIC(10,4)    -- (net_pnl / peak_capital) × 100
```

**strategy_runs** (PK: `id`, FK: `report_date` → daily_summaries)
```
strategy_run_uuid UUID UNIQUE
report_date DATE
strategy_name TEXT
deployment_status TEXT
capital_deployed_allocated NUMERIC(18,2)
booked_gross_pnl NUMERIC(18,2)
allocated_charges_total NUMERIC(18,2)
net_pnl NUMERIC(18,2)
net_roi_pct NUMERIC(10,4)
underlying_segment TEXT
```

**charges_breakdown** (PK: `id`, FK: `strategy_run_uuid`)
```
charge_source TEXT              -- REALIZED_VIRTUAL_CONTRACT_NOTE | FORMULA_COMPUTED
brokerage, exchange_turnover_fee, stt, sebi_turnover_charges
stamp_duty, gst, ipft NUMERIC(12,4)
total_charges NUMERIC(12,4)
methodology_note TEXT           -- Stores calculation rationale
```

**equity_curve** (PK: `report_date`)
```
daily_net_pnl NUMERIC(18,2)
cumulative_net_pnl NUMERIC(18,2)  -- Running sum from inception
peak_equity NUMERIC(18,2)         -- Highest cumulative value
drawdown_pct NUMERIC(10,4)        -- ((peak - cumulative) / peak) × 100
running_win_rate_30d NUMERIC(10,4)
```

**trade_executions** (PK: `id`, FK: `strategy_run_uuid`)
```
vendor_symbol TEXT
underlying, segment, exchange TEXT
side TEXT                       -- BUY | SELL
quantity INTEGER
execution_price NUMERIC(12,4)
matched_pair_id UUID            -- Links to opposite leg
```

---

## 3. CALCULATION ENGINE TRACE: 2-Leg SENSEX Short Strangle

### Example Setup
- **Underlying:** SENSEX (BSE)
- **Lot Size:** 20 per contract
- **Multiplier:** 1x
- **Capital Deployed:** ₹300,000

### Leg 1 (PE Strangle Entry-Exit):
```
Entry: SELL 20 PE @ ₹190.00  → Premium = 20 × 190 = ₹3,800
Exit:  BUY  20 PE @ ₹160.00  → Premium = 20 × 160 = ₹3,200
P&L (SHORT): (₹190 - ₹160) × 20 = ₹600.00 gross
```

### Leg 2 (CE Strangle Entry-Exit):
```
Entry: SELL 20 CE @ ₹210.00  → Premium = 20 × 210 = ₹4,200
Exit:  BUY  20 CE @ ₹180.00  → Premium = 20 × 180 = ₹3,600
P&L (SHORT): (₹210 - ₹180) × 20 = ₹600.00 gross
```

### **Combined Gross P&L: ₹1,200.00**

### Zerodha FORMULA Charges (Per Leg)

**1. Brokerage:** ₹20 per executed order × 2 orders = **₹40.00**

**2. STT (Securities Transaction Tax):**
   - Formula estimate applies to SELL-side option premium only: ₹3,200 × 0.15% = ₹4.80, rounded to the nearest rupee: **₹5.00**
   - Published Zerodha rate is 0.15% from 2026-04-01. An actual Zerodha Virtual Contract Note always overrides formula estimates.

**3. Exchange Turnover Fee (BSE 0.0325%):**
   - Total premium turnover = ₹3,800 + ₹3,200 = ₹7,000
   - Fee = ₹7,000 × 0.000325 = **₹2.28**

**4. SEBI Turnover Charges (₹10 per crore):**
   - Rate: 10 / 10,000,000 = 0.000001
   - ₹7,000 × 0.000001 = **₹0.01**

**5. Stamp Duty (0.003% buy-side only):**
   - Entry premium × 0.00003 = ₹3,800 × 0.00003 = **₹0.11**

**6. GST (18% on brokerage + exchange + sebi):**
   - (₹40 + ₹2.28 + ₹0.01) × 0.18 = **₹7.61**

**Leg 1 Total:** ₹40 + ₹3.20 + ₹2.28 + ₹0.01 + ₹0.11 + ₹7.61 = **₹53.21**  
**Leg 2 Total:** **₹53.21** (identical calculation)  
**Combined Charges:** **₹106.42**

### Strategy ROI Calculation
```
Strategy ROI = (Net P&L / Capital Deployed) × 100
             = (₹1,200 - ₹106.42) / ₹300,000 × 100
             = ₹1,093.58 / ₹300,000 × 100
             = 0.3645%
```

### Portfolio ROI (Multiple Strategies Same Day)
```
If 3 strategies:
  - Strategy A: net = ₹1,093.58, capital = ₹300k
  - Strategy B: net = -₹500.00, capital = ₹200k
  - Strategy C: net = ₹2,000.00, capital = ₹400k

Portfolio ROI = (₹1,093.58 - ₹500 + ₹2,000) / (₹300k + ₹200k + ₹400k) × 100
              = ₹2,593.58 / ₹900k × 100
              = 0.288%
```

---

## 4. RUNTIME DEPENDENCIES & ENVIRONMENT

### Python Version: 3.11

### Key Pinned Packages
```
streamlit>=1.32.0              # UI framework
pandas>=2.2.0                  # DataFrames
numpy>=1.26.4                  # Numeric operations
sqlalchemy>=2.0.29             # ORM (SQLite + Postgres)
pydantic>=2.6.4                # Data validation (v2 syntax)
google-genai>=1.0.0            # Gemini Vision API
playwright>=1.42.0             # Headless Chrome (PDF generation)
supabase>=2.4.0                # Postgres client
pyyaml>=6.0.1                  # Config parsing
openpyxl>=3.1.2                # Excel generation
```

### Environment Variables

**Required:**
```bash
GEMINI_API_KEY=AQ.Ab8_...     # From https://aistudio.google.com/app/apikey
```

**Optional (Cloud Persistence):**
```bash
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_SERVICE_ROLE_KEY=sbp_xyz...
```

**Optional (Dhan Broker):**
```bash
DHAN_CLIENT_ID=...
DHAN_ACCESS_TOKEN=...
```

**Access Control:**
```bash
APP_ACCESS_PASSWORD=...       # Leave blank for local; set for production
```

### Local Setup Steps
```powershell
# 1. Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright Chromium (one-time, ~150MB download)
python -m playwright install chromium --with-deps

# 4. Copy .env.example → .env and fill in GEMINI_API_KEY

# 5. Run app
streamlit run app.py
# Opens at http://localhost:8501
```

### Streamlit Cloud Deployment
1. Push to public GitHub repo
2. Create account at https://share.streamlit.io
3. Deploy: select repo, main file `app.py`
4. Settings → Secrets → paste `secrets.toml` with API keys

---

## 5. KNOWN FAILURE MODES & TROUBLESHOOTING

### A. Silent Pipeline Failures

**Symptom:** Pipeline claims "SUCCESS" but Dashboard shows ₹0.00 P&L

| Cause | Fix |
|-------|-----|
| CSV column names don't match | Check `trade_matcher.py:rename_map` lines 37-50 for accepted aliases (vendor_symbol, symbol, instrument_symbol, Instrument) |
| FIFO matching returns 0 pairs | Ensure executions have both BUY and SELL orders; add complementary legs if missing |
| Charges computed as ₹0.00 | Verify matched_df has rows in stage 5 output; or provide contract_note_charges dict |
| Strategy ROI = NaN | Set capital_deployed_allocated > 0.0 (check for null/0 in input) |

### B. Symbol Parsing Errors

**Symptom:** Stage 4 WARNING: "Symbol parse warning: XXXXX..."

**Expected Patterns:**
- SENSEX: `SENSEX2698PEXXXXCE` (index symbol format)
- NIFTY: `NIFTY2692224000CE` (2-digit day + 5-digit strike)
- Monthly: `FINNIFTY2611024500CE` (YYMMSTRIKE, no day embedded)

**Code Reference:** `src/symbol_parser.py:parse_indian_symbol()` lines 200-280  
**Fix:** Verify vendor_symbol format in source; if systematic, check source file type

### C. Supabase Offline / Credentials Missing

**Symptom:** Historical Dashboard shows no data; stage 8 logs warning

**Fallback Behavior:**
- SQLite local cache always works (no network required)
- Supabase write is non-blocking (pipeline continues if Supabase fails)
- Data never lost; syncs when Supabase back online

**Fix:**
1. Set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY environment variables
2. Restart Streamlit app
3. Verify connection status in Page 3 (Settings) → "Supabase Connection Status"

**Code Reference:** `src/supabase_store.py:_get_supabase_client()` lines 24-62

### D. PDF Compilation Errors

**Symptom:** "Generate PDF Report" button → "Playwright not installed" or "Chromium binary missing"

**Fix:**
```powershell
python -m playwright install chromium --with-deps
# OR on fresh Streamlit Cloud server: app.py auto-runs this; wait 2-3 min, refresh
```

**Fallback:** Download Excel instead (no Playwright dependency)

### E. Gemini API Authentication Errors

| Error | Fix |
|-------|-----|
| `API_KEY_SERVICE_BLOCKED` or 403 | Enable Generative Language API: https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com → select project → ENABLE → wait 30-60s |
| `PERMISSION_DENIED` | Create new API key: https://aistudio.google.com/app/apikey → copy full key → paste in Settings page |
| `UNAUTHENTICATED` or 401 | API key expired/invalid. Create new key at https://aistudio.google.com/app/apikey |

**Fallback:** Use Manual Trade Entry mode (no Gemini API required)

---

## 6. ARCHITECTURE DECISIONS

### Dual-Write Pattern (Supabase + SQLite)
- **Supabase = primary durable store** (cloud, multi-user, persistent)
- **SQLite = local cache + fallback** (works offline, low latency)
- **Resilience:** If Supabase down, app continues; data syncs when online

### 9-Stage Pipeline (Not Monolithic)
1. **Observability:** Each stage emits `StageResult` with timing, row counts, warnings/errors
2. **Checkpoint Safety:** Stage 3 (Review) is mandatory human approval gate
3. **Testability:** Each stage can be unit tested in isolation
4. **Future Parallelization:** Stages 1-2 could theoretically run in parallel

### FIFO Matching (Not Greedy)
- **FIFO respects chronological entry-exit order** (matches daytrader intent)
- **Greedy** would minimize costs but create artificial P&Ls
- **Limitation:** Assumes user closes oldest position first

### Primary ROI Denominator: Capital Deployed (Not Margin)
- **Why:** Capital is known & immutable (from Tradetron card); margins are approximations
- **Secondary Metric:** SEBI SPAN/Exposure margins used for audit only, never for ROI
- **Config Reference:** `config/pipeline.yaml` line 6

---

## 7. HANDOFF CHECKLIST

- [ ] Clone repo; create venv + install dependencies
- [ ] Run `pytest tests/ -v` to verify all tests pass
- [ ] Set GEMINI_API_KEY; test page_daily.py manual CSV upload end-to-end
- [ ] Inspect SQLite schema: `sqlite3 data/quant_desk.db ".schema"`
- [ ] Review `config/pipeline.yaml` and understand all 9 stage names
- [ ] Spot-check 3 formulas in `cost_calculator.py` against Zerodha fee schedule
- [ ] Create test strategy (₹300k, 2 legs, entry @ ₹100/200, exit @ ₹105/195); trace full pipeline
- [ ] Run Historical Dashboard; verify equity curve populated from SQLite
- [ ] Read docstrings in `pnl_pipeline.py` (lines 1-45) and `cost_calculator.py` (lines 74-86)
- [ ] Review `src/db/schema.py` ORM relationships (StrategyRun ↔ TradeExecution, ChargesBreakdown)

---

**Document Version:** 1.0  
**Generated:** 2026-09-22  
**Status:** PRODUCTION-GRADE HANDOVER READY FOR SPARK AI DEPLOYMENT

---

## 11. REPORTING AND HISTORICAL QUANT TERMINAL — 2026-09-24

### Work completed in this reliability/analytics pass

- Fixed four-digit Tradetron expiry parsing. The vendor symbol `OPTIDX_BANKNIFTY_29SEP2026_PE_56100` now retains `2026-09-29`; the old parser incorrectly applied `% 100` and produced year `0026`.
- Reworked the daily founder report to use HTML currency entities and a local system-font fallback; `fonts-noto-core` is included in `packages.txt` for the Streamlit Debian runtime. The report print stylesheet switches to a light, paper-friendly palette.
- The report KPI row now includes deployed capital, gross P&L, realized/formula charges, net P&L, gross ROI, and net ROI. Optional index/VIX fields are user-entered and clearly show “Not supplied” when blank.
- Strategy cards now sanitize NaN/missing multiplier values, omit the exact fixture name `Test Strat` from reports only (no database deletion), show available entry/exit/holding timing, and include matched-leg details. The wide raw trade/charge dump was replaced with a narrower, scrollable report table.
- Empty chart inputs now cause local SVG segment-contribution and gross/charges/net charts to be generated and embedded as data URIs. This avoids remote chart scripts or image services during PDF generation. HTML export remains independent of PDF runtime availability.
- `ui/page_historical.py` now reads strategy runs and charges from the configured Supabase store, then SQLite fallback. Strategy and segment filters drive daily totals and the analytics modules. It contains a weekday-only monthly calendar with weekly totals, a strategy leaderboard, weekday profitability, and account-equity/drawdown visualization.
- Historical drawdown uses `account base + cumulative net P&L`. For persisted equity rows the migration-free rebuild uses the first saved day's peak deployed capital as a **reference baseline**; the dashboard lets the operator enter actual account base capital. Do not describe first-day deployed capital as verified account equity.
- The TradingView terminal uses the official Advanced Chart embed. Its selected chart still depends on the selected symbol being available in TradingView's widget market data and the user's browser allowing the third-party chart.
- Historical benchmark curves, FII/DII cash-flow plots, and VIX/CPR/range regime labels accept user-uploaded CSV context. No source was available in this project to truthfully persist or auto-fetch historical index closes, participant flows, IV, or CPR values. Uploaded values are session inputs, not permanent database records.
- Matched-trade CSV includes holding duration where timestamps exist, plus blank MFE/MAE/slippage fields for future enrichment. These values must stay blank until timestamp-aligned tick/candle and execution-reference data is integrated; do not infer them from entry/exit fills.

### Verification and handover status

- Latest full test run after implementation: **64 passed, 2 skipped**. The skipped checks are environment-dependent Excel/PDF checks because `xlsxwriter` and Playwright are not installed in the active project interpreter. Python compilation succeeded with the workspace runtime.
- The supplied PDF was visually inspected. It shows missing rupee glyphs, `0026` expiry dates, a `nanx` multiplier, `Test Strat` leakage, absent charts, extremely wide tables, and unused page space. A new Chromium PDF was not generated in this environment; verify the final downloadable PDF after installing Playwright/Chromium and deploying the Noto fonts.
- No database schema or data file was edited in this pass; no new database backup was required. The app's next Stage 9 run rebuilds old equity rows with the new formula.
- Current working branch when this section was written: `main`. Commit/push and live Streamlit Cloud verification are release steps, not completed by the test run. Do not stage the pre-existing `.env.example` edit, `.dbg/`, `.trae/documents/`, `debug-blank-results-tabs.md`, or temporary QA files.

### Recommended next work, in order

1. Install the project's complete development dependencies, including Playwright Chromium and `xlsxwriter`; generate and visually verify HTML and PDF exports on Windows and Streamlit Cloud.
2. In the deployed app, enter a 2–4-strategy date, save it, append another strategy to the same date, and verify Supabase + SQLite records, summary totals, and export files.
3. Add an explicit account-level starting-capital setting stored per authenticated account; migrate historical drawdown baselines from the provisional first-day deployed-capital reference.
4. Add an exchange-licensed market-data adapter with source, timestamp, timezone, symbol, and revision metadata. Persist daily underlying closes, intraday OHLC, India VIX, CPR inputs, and—if permitted—official cash-market FII/DII flows.
5. Once path data exists, calculate MFE/MAE, execution slippage against a declared quote benchmark, time-in-trade, IV/regime-conditioned expectancy, and properly matched strategy-versus-index alpha.
6. Before multi-user production, add owner/account isolation through the schema and Supabase Row Level Security. The existing trading tables do not have tenant ownership keys.

---

## 8. RELIABILITY BUILD HANDOVER — 2026-09-24

### Current implementation

- Manual trade entry supports additional strategy blocks for the same trading date. Entries carry a strategy run ID through matching, charges, aggregation, and persistence.
- CSV `report_date` input is normalized to `trade_date`; manual executions are routed as executions instead of being mistaken for strategy cards.
- Results render from `st.session_state["pipeline_result"]` while `st.session_state["pipeline_executed"]` is true, including after tab changes and Streamlit reruns.
- Same-date processing defaults to append. Existing saved strategy totals and charges are combined; replacing a date requires choosing the explicit replace option.
- SQLite persistence now updates the date-keyed daily summary, uses stable strategy/execution IDs, and stores raw execution legs. Supabase payloads include mapped UUIDs and current summary aliases.
- HTML and PDF exports call the report generator’s actual interface. PDF uses Playwright Chromium, with installed Chrome/Edge as a Windows fallback; the Streamlit startup installer now records success only after a successful browser download.
- Formula STT uses the published Zerodha 0.15% sell-side option premium rate, rounded to the nearest rupee. Realized contract-note totals take precedence.

### Data safety and verification

- Pre-change SQLite backup: `data/quant_desk.db.pre-codex-20260924.bak` (151,552 bytes; SHA-256 `9EF17D45B782C554533222C83636920BF258981876F60A4705317C038C523C89`).
- The four-leg SENSEX regression reproduction passes: 4 execution rows, 2 matched trades, ₹1,869 gross P&L, no unmatched legs.
- Latest full verification run: 57 passed, 0 skipped. The four-leg regression also passes with 4 execution rows, 2 matched trades, no unmatched legs, and ₹1,869 gross P&L.
- HTML export smoke: PASS. PDF export smoke using installed Windows browser: PASS (17,233-byte PDF).
- Continue developing on `codex/reliability-reporting`; merge into `main` and push only after the full suite passes and the final diff contains only intended project files.

### Notes for the next coding session

- Start with this section and the git history for the reliability build. Keep local secrets, `.dbg/`, the SQLite backup, and pre-existing debug notes out of commits.
- After deployment, verify a multi-strategy same-date batch, append one additional strategy to that date, open every Results tab, save, then download HTML and PDF.
- Confirm the Streamlit Cloud Supabase credentials and schema are available before treating hosted persistence as verified. This local run did not verify a live Supabase transaction.

## 9. MANUAL ENTRY ERROR REPORTING AND NORMALIZATION — 2026-09-24

- Added `StageResult.error_message` as a backward-compatible property and made the failed-stage UI read errors safely, so an actual pipeline failure cannot be hidden by an `AttributeError` while rendering its diagnostic.
- Manual CSV still passes through Stage 1 ingestion and Stage 2 parsing: Stage 1 wraps the manual rows as a source, and Stage 2 forwards those rows without requiring screenshots or invoking Gemini OCR. Do not ignore failures from these stages; they feed the execution pipeline. The reported manual-mode failure cause was therefore the missing `error_message` attribute, not the absence of screenshots.
- Trade normalization now converts signed whole-number quantities to positive integers while preserving `side`, and derives the exchange from the recognized underlying (SENSEX → BSE; BANKNIFTY/NIFTY/FINNIFTY/MIDCPNIFTY → NSE).
- Added regression coverage for the compatibility property, negative SELL quantity, and BANKNIFTY/SENSEX exchange correction.
- Verification after this fix: `58 passed, 2 skipped` (PDF/Excel environment-dependent checks); `scripts/debug_manual_run.py` exited 0 with 4 executions, 2 matched trades, 0 open legs, ₹1,869 gross P&L, ₹124.83 charges, and ₹1,744.17 net P&L.
- Fixture caveat: the four-execution fixture uses two SENSEX PE symbols, not a call-plus-put short strangle. It validates the reported matching/P&L vector, but not canonical strangle structure.

## 10. PERSISTENCE SANITIZATION AND TRADE DOCTOR — 2026-09-24

- Added `sanitize_for_sqlite()` in `src/sqlite_store.py`. It normalizes pandas/numpy missing values, rounds valid integer fields, supplies safe values for invalid integer inputs, preserves missing auto-increment IDs as `None`, and converts numpy scalars before SQLAlchemy receives them. The generic SQLite upsert and Stage 8's strategy, daily summary, charges, and execution inserts use it.
- Added the first rule-based Trade Doctor view to the Analytics tab: closed-trade count, win rate, profit factor, expectancy, average winners/losers, cost drag, unmatched-leg count, strategy attribution, and review flags. It intentionally omits Greeks, benchmark slippage, and index-range correlation until the app has timestamp-aligned market/quote data and a documented Greeks source/model.
- Corrected the default NSE IPFT assumption to ₹0.01 per crore and include that charge in the GST base, matching current Zerodha's published schedule. Existing database default schedules are migrated from the old ₹1/crore value by `init_db` without changing non-default schedules. Contract-note realized charges remain the reconciliation source of truth.
- Automated tests were not run for this upgrade; run the full suite and a Streamlit manual-entry → Save to DB smoke test before relying on the release.
- The current trading schema has no owner/account/tenant key. `init_db` seeds market reference data and a broker charge schedule, not a `Test Strat` trade. Do not delete that strategy until its source/date and linked executions/charges are inspected. Production multi-user isolation requires an authenticated owner/account ID carried through every trade, strategy, charge, query, and RLS policy.
- The screenshots referenced in the latest request were not attached here; the persistence diagnosis is based on the supplied error text and the current code paths.
