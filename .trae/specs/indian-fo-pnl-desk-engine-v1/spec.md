# Indian F&O P&L Desk Engine - Product Requirements Document (PRD) v1.0 Production

## Unified Spec: Tradetron Execution + Zerodha Broker + Founder Daily Reporting

## Overview

* **Summary**: A full-stack, local-first web application for an Indian quantitative options desk operating via **Tradetron execution on Zerodha**. Automates the end-to-end post-market workflow: upload 1–5 daily screenshots (Tradetron strategy cards, Zerodha Kite positions, Zerodha Virtual Contract Note charges popup) → Gemini 1.5 Flash Vision structured extraction → human-in-the-loop editable review → charges reconciliation (realized contract-note values if available, formula otherwise) → SEBI SPAN + Exposure margin audit metric → strategy-level ROI attribution using Capital Deployed from Tradetron → A4 print-ready PDF via Playwright (Chromium) + interactive web report + historical calendar analytics with equity curve and drawdowns. All records persist in a local SQLite database `data/quant_desk.db` with optional future cloud sync.
* **Purpose**: Fully replace manual Word/PDF P&L reporting. Eliminate arithmetic, categorization, and charge-allocation errors. Deliver the founder a Tradetron-matching strategy-card layout report that reads at a glance, with audit-grade charge reconciliation.
* **Target Users**: Proprietary trader (operator) + founder/boss (report recipient via PDF). Single-user private deployment.

## Goals

* **G1 Charge Accuracy (₹0.01)**: Every charge line-item reconciles to the Zerodha Virtual Contract Note exactly when the screenshot is provided; when missing, formula values match the external Zerodha Brokerage Calculator to within ₹0.05.
* **G2 Strategy-Level Founder View**: Every Tradetron strategy card visible in screenshots becomes a matching card in the report with correct Strategy Name, Multiplier (1x/2x/…), Deployment Status, Entry/Exit Timestamps, Capital Deployed/Allocated (₹X.XXL), Gross Booked P&L, Allocated Charges, Net P&L, Net ROI %.
* **G3 Capital-Deployed ROI (Primary)**: Strategy ROI denominator = **Capital Deployed for that strategy** (sourced from Tradetron card screenshot or editable review screen). Portfolio Day ROI denominator = **Total Day Peak Capital Deployed** across strategies. SEBI SPAN+Exposure margin is stored and labeled as secondary audit metric, not used for founder ROI.
* **G4 Tradetron + Kite + Contract Note Multimodal Extraction**: Gemini 1.5 Flash Vision extracts three distinct screenshot layouts (Strategy Cards / Positions Table / Contract Note Charges) with < 0.85 confidence flagged yellow in an editable `st.data_editor` staging review.
* **G5 Indian Market Knowledge**: Hard-coded, editable `market_knowledge` table with current 2026-04-01 index contract specs (lot sizes, weekly/monthly, strike intervals, exchanges): NIFTY (25, NSE, weekly Tue), BANKNIFTY (15, NSE, monthly Thu), SENSEX (20, BSE, weekly Mon), FINNIFTY (25, NSE, monthly Tue), MIDCPNIFTY (50, NSE, monthly Mon) + stock F&O classification.
* **G6 Professional Report Aesthetics**: Streamlit dark midnight-navy theme, glassmorphism KPI tiles, emerald profit / crimson loss, JetBrains Mono / Inter typography, gradient accent bars. Founder PDF (Playwright/Chromium, A4 print-ready) features the 6-KPI header strip, strategy breakdown cards matching Tradetron layout, 3-chart visual analytics quad, detailed trade log, and contract-note reconciliation table.
* **G7 Historical Analytics**: SQLite persistence enables date-range (Today/7D/30D/MTD/QTD/YTD/custom) aggregate reporting with green/red calendar P&L heatmap squares, 30-day rolling win rate, cumulative equity curve, max drawdown, best/worst days, and streak metrics.

## Non-Goals

* **NG1 No Order Placement**: Strictly read-only, post-market analysis. No Tradetron write endpoints, no Zerodha API order placement/cancel, no broker write operations.
* **NG2 No Live Signals / Strategy Backtesting**: Accounting/reconciliation system only; Tradetron handles execution, separate repos handle research/backtests.
* **NG3 No Multi-Tenant Authentication**: Single-user private local deployment; SQLite per-user; no login/roles pages.
* **NG4 Not Tax Filing Product**: Data supports ITR/STCG/LTCG analysis but explicit tax-product forms/schedules are out of scope.
* **NG5 Dhan Not Primary**: Dhan API wrapper is an optional secondary helper; never blocking for any core task. Zerodha + Tradetron screenshots are the canonical input path.

## Background & Context

* Desk workflow: Tradetron (strategy engine, MIS deployments) → Zerodha (broker Kite, executions, positions, contract notes) → daily screenshots → manual Word/PDF report to founder with screenshots, gross P&L line, charge line, net P&L line, ROI, and Capital Deployed figures.
* Existing canonical ground-truth knowledge base files (contract specs, charge tables, 5-cycle SENSEX audit, 24-strategy research pack) live at:
  - `c:\Users\Dell\Documents\Master Algo Trading\Manus learning Md files\KIte DHan Tradetron\Quant Trading Agent Knowledge Base.md`
  - `...CTO Master Plan — Kite ↔ Dhan ↔ Tradetron.md`
  - `...Dhan API Sandox webhooks doc\DhanHQ v2 Python Integration — AI-Agent Master Guide.md`
* Reference P&L PDFs for canonical end-to-end fixtures: **03-09-2026, 16-09-2026, 17-09-2026, 18-09-2026**. Use these four to validate Gross P&L / Net P&L / Charges / ROI match manual logs.
* Key confirmed assets: Google Gemini API key (to be provided for Vision/OCR), optional Dhan API keys (secondary LTP cross-reference, not blocking), Windows 11 local-first deployment.

## Functional Requirements

* **FR-1 Data Layer (Local-First SQLite + SQLAlchemy + Pydantic v2)**:
  - Database file: `data/quant_desk.db`.
  - ORM via SQLAlchemy 2.0; domain input/output validated via Pydantic v2 schemas.
  - Five transactional tables:
    1. `raw_source_files` — SHA-256 hash dedupe, upload metadata, OCR raw text, processing status, OCR confidence, source type (TRADETRON_CARD / KITE_POSITIONS / ZERODHA_CONTRACT_NOTE / MANUAL_CSV).
    2. `trade_executions` — per-leg rows with vendor_symbol, underlying, segment, expiry, strike, option_type, side, lots, quantity, lot_size, execution_price, gross_premium, matched_pair_id, is_entry, parsing_confidence, manually_edited, strategy_run_id (FK).
    3. `strategy_runs` — Tradetron-strategy-level rows: strategy_name (e.g. "SENSEX BFO Dynamic Inside-Day Short Strangle", "BANKNIFTY NFO Dynamic Short Strangle"), deployment_status (LIVE AUTO / EXITED / PARTIAL), multiplier (1x/2x/…), counter, capital_deployed_allocated (₹X.XXL from Tradetron), entry_ts, exit_ts, legs_greeks JSON (Delta, Theta, Vega, IV, LTP per leg), underlying_segment, booked_gross_pnl, allocated_charges_total, net_pnl, net_roi_pct, operational_notes.
    4. `charges_breakdown` — per-strategy or per-matched-trade line itemization of: brokerage, exchange_turnover_fee, stt, sebi_turnover_charges, stamp_duty, gst, total_charges, charge_source (REALIZED_VIRTUAL_CONTRACT_NOTE vs FORMULA_COMPUTED).
    5. `daily_summaries` — report_date PK, generated_at, total_trades_executed, total_strategy_runs, win_count, loss_count, total_capital_deployed (peak per day), peak_margin_audit_metric (SPAN+Exposure secondary), total_gross_pnl, total_transaction_cost_drag, total_net_pnl, portfolio_day_net_roi_pct, segment_breakdown JSONB, report_hash.
    6. `equity_curve` — report_date PK, daily_net_pnl, cumulative_net_pnl, daily_net_roi_pct, cumulative_net_roi_pct, peak_equity, drawdown_pct, running_capital_base, running_trade_count, running_win_rate_30d, updated_at.
  - Two editable reference tables:
    7. `market_knowledge` — underlying, exchange, instrument_type, lot_size, strike_interval, weekly_expiry, expiry_weekday, span_margin_pct, exposure_margin_pct, effective_date, effective_from, effective_until, is_current.
    8. `broker_charge_schedule` — broker_name (default ZERODHA), effective_date, brokerage_per_order, stt_option_sell_premium_pct, nse_exchange_option_pct, bse_exchange_option_pct, sebi_fee_per_crore, stamp_duty_option_buy_pct, gst_pct, default_slippage_per_point, notes.

* **FR-2 Indian Market Knowledge Module**: Python module exposing `get_lot_size(underlying, date)`, `get_segment(symbol)`, `get_margin_params(underlying, date)`, `get_exchange(underlying)`, `is_valid_index(underlying)`, `classify_trades_by_segment(df)`. Seed NIFTY=25/Tue-weekly, BANKNIFTY=15/Thu-monthly, SENSEX=20/Mon-weekly, FINNIFTY=25/Tue-monthly, MIDCPNIFTY=50/Mon-monthly (2026-04-01 baseline). Editable override path via the SQLite `market_knowledge` table.

* **FR-3 Symbol Parser**: Parse both Zerodha/Kite-style symbols (month digit codes + `O`/`N`/`D` for Oct/Nov/Dec) and Tradetron display formats; classify expiry, strike, CE/PE vs FUT; fail closed on ambiguous symbols with a human-readable `SymbolParseError`.

* **FR-4 Charges Engine (Zerodha Primary, Dual-Mode)**:
  - Mode A (Highest Priority) — If a Zerodha Virtual Contract Note charges screenshot exists in the uploads, **use the exact realized values** extracted from it (Brokerage, Exchange Turnover Fee, STT, SEBI Turnover Charges, Stamp Duty, GST, Total Charges) and tag charge_source=REALIZED_VIRTUAL_CONTRACT_NOTE.
  - Mode B (Fallback Formula) — When contract note is missing, calculate line-by-line:
    - Brokerage: Flat ₹20 per executed order (one single-option leg = 2 orders = ₹40; one two-leg spread = 4 orders = ₹80).
    - STT: **0.1% (0.001)** on sell-side option premium turnover (Zerodha effective).
    - Exchange Turnover Fee: NSE 0.03553% × premium turnover; BSE 0.0325% × premium turnover.
    - SEBI Turnover Fee: ₹10 per crore (0.000001 = 1e-6) × total premium turnover.
    - Stamp Duty: 0.003% (3e-5) on BUY-side premium only.
    - GST: 18% × (Brokerage + Exchange Turnover Fee + SEBI Turnover Charges).
    - Optionally include IPFT (~₹1 per crore) for complete audit parity.
  - Implement a `allocate_charges_to_strategies(strategy_runs, realized_or_formula_charges)` method that distributes aggregate charges across strategy_runs proportionally by premium turnover (or custom strategy-level override).

* **FR-5 Margin Calculator (Audit Metric, Secondary)**:
  - Per-trade classification {Long Option, Short Option, Future, Defined-Risk Spread}.
  - Computes {notional_value, span_margin, exposure_margin, total_margin_required, premium_paid_received, audit_net_capital_blocked_secondary}.
  - Rules mirror SEBI SPAN + Exposure: Long Option = premium only (no SPAN/Exposure added to primary). Short Option = SPAN+Exposure reduced by premium received. Spreads = max(debit_paid, max_loss × qty).
  - Stores the result as `peak_margin_audit_metric` on `daily_summaries` but **never uses it for founder ROI denominator** (Capital Deployed stays primary).
  - Auto-estimates underlying_price from screenshot context plus heuristics (strike ± premium, index reference bands) and always surfaces the methodology for manual override.

* **FR-6 Gemini 1.5 Flash Vision Multimodal Extractor (Zero-Error Pipeline)**:
  - Three distinct prompt templates + few-shot examples, selected per `source_type` of uploaded screenshot:
    1. **TRADETRON_STRATEGY_CARDS_TEMPLATE**: Instructs model to extract per card: Strategy Name, Deployment Status (LIVE AUTO / Exited), Multiplier (1x/2x/…), Counter, Capital Deployed/Allocated (₹X.XXL), Entry Timestamp, Exit Timestamp, and leg Greeks (Delta/Theta/Vega/IV/LTP per leg). Returns structured JSON array `strategy_cards: [...]` plus per-card `confidence`.
    2. **ZERODHA_KITE_POSITIONS_TEMPLATE**: Extract Instrument Symbol, Product Type (MIS/NRML), Quantity, Average Price, LTP, Individual Leg P&L (green=+, red=−), Total Executed P&L. Returns `kite_positions: [...]` array.
    3. **ZERODHA_VIRTUAL_CONTRACT_NOTE_TEMPLATE**: Extract exact realized charges 6-tuple: {Brokerage, Exchange Turnover Fee, Securities Transaction Tax (STT), SEBI Turnover Charges, Stamp Duty, GST} plus {Total Charges}. Returns `contract_note_charges: {...}` object and confirms grand-total reconciliation.
  - General output envelope JSON Schema: `{ screen_type, broker_identified, overall_confidence, visible_underlying_levels: {NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY}, visible_margin_hud: {used, available, total}, strategy_cards?, kite_positions?, contract_note_charges?, execution_rows?: [...] }`
  - Fail-closed: any JSON schema violation triggers one retry with a cleaner prompt; on second failure, falls back to `confidence=0.5`, `processing_status=NEEDS_REVIEW`, entire batch routed to Human-in-the-Loop staging.
  - Confidence threshold < 0.85 flags the row yellow in the staging review table.
  - Local Tesseract as very-last-resort when Gemini is unreachable (lower-confidence + mandatory-review flag).

* **FR-7 Human-in-the-Loop Review Staging**: After multimodal extraction, present all rows in an editable `st.data_editor` staging table(s): Strategy Run staging, Position Execution staging, Contract Note staging. Rows with confidence < 0.85 are highlighted yellow. UI note: "5-second manual verification of Capital Deployed and Strategy Names recommended". Buttons "Approve All / Mark Reviewed" and "Save Edits & Continue".

* **FR-8 Strategy-Level ROI & FIFO Matching**:
  - FIFO match BUY→SELL executions per vendor_symbol per strategy_run; produce matched_trade pairs with entry/exit, gross P&L.
  - Aggregate per `strategy_runs` row: booked_gross_pnl = matched legs gross sum; allocated_charges_total = proportional distribution; net_pnl = booked_gross_pnl − allocated_charges_total; net_roi_pct = (net_pnl / capital_deployed_allocated) × 100.
  - Portfolio: `total_day_net_pnl` = Σ strategy net_pnl; `portfolio_day_net_roi_pct` = total_day_net_pnl / (peak Σ capital_deployed across strategies) × 100.

* **FR-9 Daily Pipeline Orchestrator (Zero-Error, Observable)**:
  9 stages, each with per-stage timing + counts + error messages + fail-closed semantics:
  1. ingest_sources (SHA-256 dedupe, classify screen_type).
  2. gemini_multimodal_parse (per-screen-type prompt selection → JSON envelope).
  3. review_staging → user approval checkpoint; returns validated DataFrames.
  4. classify_symbols → segment/underlying/lot_size from market_knowledge.
  5. fifo_match_within_strategies → matched_trades + open legs list.
  6. compute_charges (REALIZED_VIRTUAL_CONTRACT_NOTE when present, else formula) + allocate to strategies.
  7. compute_secondary_margin_audit_metric + strategy_roi + daily_summary KPIs.
  8. persist_sqlite_transactional (all 5 tables in one SQLAlchemy transaction).
  9. rebuild_equity_curve (for current date; or historical rerun window).
  - Implement `rerun_historical(from_date, to_date)` idempotently.

* **FR-10 Founder Report Generator (Web + Playwright Chromium PDF)**:
  Six A4 sections in daily HTML report (CSS fully inlined for PDF):
  1. **Header & KPI Strip** (single row, 6 tiles): Trading Date, Desk Name, Total Net P&L (green/red), Net ROI %, Win/Loss Trade Count, Total Capital Deployed, Total Transaction Cost Drag (as ₹ + as % of gross).
  2. **Strategy Breakdown Cards** — One card per strategy_runs row, visual layout matching Tradetron card layout: Strategy Name (bold), Multiplier chip, Entry/Exit Timestamps, Capital Deployed (₹X.XXL), Booked P&L, Charges (mini breakdown), Net P&L, Net ROI %, Operational/Slippage Notes. Emerald/crimson borders conditional on net sign.
  3. **Visual Analytics Quad** (3 charts, balanced quad layout):
     - Segment Contribution Donut (SENSEX vs BANKNIFTY vs NIFTY vs FINNIFTY vs MIDCPNIFTY).
     - Gross vs Net P&L Comparison Bars (grouped side-by-side, per segment).
     - Transaction Cost Waterfall (Gross → Brokerage → STT → Exchange/GST/Stamp → Net) — Plotly waterfall with colored steps.
  4. **Detailed Trade & Position Log** (sortable table): Instrument, Product (MIS/NRML), Quantity, Avg Price, LTP, Leg-wise P&L, Strategy Name link.
  5. **Contract Note Reconciliation Table** (line-by-line charges): Brokerage | Exchange Turnover Fee | STT | SEBI Turnover | Stamp Duty | GST | Grand Total. Column: `Source` = REALIZED_VIRTUAL_CONTRACT_NOTE (badge green) vs FORMULA (badge amber).
  6. **Mandatory Disclaimer Footer** — Bold, prominent, audit-only compliance notice (see FR-13 exact text).
  - Aggregate/date-range report adds: equity curve with drawdown area, green/red P&L calendar heatmap squares, 30-day rolling win rate line, best day / worst day cards, winning/losing streak metrics, per-strategy attribution bar.
  - PDF: `playwright install chromium` at setup; render HTML in headless Chromium, `page.pdf(format='A4', print_background=True)`.
  - Excel: XLSX export with styled color-coded sheets (1-KPI 2-StrategyCards 3-Trades 4-Charges 5-Appendix).
  - CSV: trade_executions + strategy_runs + charges_breakdown CSVs.

* **FR-11 Streamlit UI (Dark Trading-Desk Theme)**: Four pages via streamlit-option-menu sidebar:
  - **Page 1 — 📸 Daily Processing**: Multi-uploader (1–5 screenshots). Auto-detect screen_type card previews. Step 2 editable staging tables (yellow flags < 0.85). Capital Deployed per-strategy editable. Generate button with 9-stage progress bar. Report inline tabs (Summary / Strategy Cards / Analytics / Trades / Reconciliation). Export row (💾 Save to DB / 📄 Download PDF / 📊 Download Excel / 📁 Download CSV).
  - **Page 2 — 📊 Historical Founder Dashboard**: Date range picker + Today/7D/30D/MTD/QTD/YTD/Custom quick buttons. Segment/strategy filters. KPI strip. Equity curve + drawdown dual-axis. Green/red calendar heatmap squares. Best day / worst day / streak cards. Drill-down: click any calendar square → jump to that day's Daily Processing.
  - **Page 3 — 🧠 Settings & Knowledge Base**: API keys fields (Gemini, Dhan optional) password-masked with Test-Connect buttons, save to local `.env`. Editable Market Knowledge table + Editable Broker Charge Schedule table (both st.data_editor → write to SQLite). Cost Calculator Playground (live inputs → instant line-item breakdown). Margin Calculator Playground (4-archetype tabs). Branding (Desk Name, Founder report salutation, Disclaimer Editor). First-run guided wizard when `.env` empty.
  - **Page 4 — ⚙️ Audit & Reconciliation**: Raw source file browser (searchable, filter by date/status/screen_type). Processing Logs stream (stage-level timing/warnings). Unmatched / Orphan legs panel. Duplicate detection (by SHA-256 hash). Single-date / date-range "Re-run P&L" buttons. Contract Note vs Formula variance panel when both sources exist.

* **FR-12 Dhan API (Optional Secondary Helper)**: Wrapper `DhanDataProvider` with read-only endpoints: `get_today_positions`, `get_today_trades`, `get_funds_limits`, `get_marketfeed_ltp(underlyings)`. Used only as secondary cross-reference: when screenshot visible_underlying_levels are missing, marketfeed LTPs are the first fallback for accurate margin notional. **No blocking dependency in Task 1 or Task 9.** All pipeline stages must run end-to-end with Dhan credentials blank; graceful banner appears to user: "Dhan API not configured — using screenshot/estimated underlying levels (editable)".

* **FR-13 Mandatory Disclaimer**: Every generated report footer (PDF, Excel, web inline) displays in bold prominent text:
  > **CONFIDENTIAL — FOR INTERNAL FOUNDER AUDIT USE ONLY.** This report is a private accounting reconciliation artifact and is not financial advice, investment research, or a solicitation to trade. Capital Deployed ROI figures use the allocation sourced from the Tradetron strategy card screenshot / operator review. All charge line items labeled REALIZED_VIRTUAL_CONTRACT_NOTE are exact extractions from the Zerodha Virtual Contract Note; FORMULA charges are estimates computed per publicly available Zerodha / NSE / BSE / SEBI fee schedules and may differ by rounding. All secondary SPAN+Exposure margin metrics are audit-only approximations computed per SEBI-standard methodology and are not used for the founder ROI calculation. Always reconcile against the official Zerodha contract note and ledger before making risk or financial decisions. Past performance is not indicative of future results.

* **FR-14 Rerunnable Historical Pipeline**: Re-triggering a historical date rebuilds strategy_runs → matched_trades → charges → daily_summary → equity_curve atomically and correctly updates cumulative figures for all dates >= the re-processed date (AC-9).

## Non-Functional Requirements

* **NFR-1 Charge Precision**: High-precision float arithmetic; round only at display/summary step. Golden fixture (Contract-Note-absent formula path) must match Zerodha calculator to ₹0.05. When Contract Note is present, output must be byte-for-byte identical to the extracted values (to 2 dp).
* **NFR-2 Fail-Closed Parsing**: Confidence < 0.85 → yellow row; entire extraction batch that fails JSON Schema → routing to mandatory manual review with no silent fallthrough values.
* **NFR-3 Audit Trail**: SHA-256 per source file, raw OCR JSON stored, strategy_runs rows carry source FK, manual edits set `manually_edited=true` + timestamp.
* **NFR-4 Privacy**: Only external network calls are (a) optional Gemini Vision for parsing screenshots provided by operator, (b) optional Dhan read-only cross-reference. No telemetry, no data uploads beyond these explicit scoped calls.
* **NFR-5 Local-First Graceful Degradation**: Gemini key blank → Manual CSV entry mode renders. Dhan key blank → "Screenshot/estimated price" banner. No network → SQLite local write-only with pending upload/sync marker when keys return.
* **NFR-6 Test Coverage**: Golden-fixture pytest suites exist for charges, margin, symbol parsing, FIFO matching, and strategy ROI allocation. ≥ 5 test vectors per engine module.
* **NFR-7 Setup Documentation**: `SETUP_AND_RUN.md` covers: Python 3.11, venv, `pip install -r requirements.txt`, Tesseract optional install, `playwright install chromium` for PDF, where to paste Gemini API key + optional Dhan key, where SQLite file lives, first-run wizard flow, and launch command `streamlit run app.py`.
* **NFR-8 Responsive Layout**: Report and UI render cleanly on 14″ laptop and 27″ monitor; KPI grid flexes; Plotly charts fill containers; Playwright A4 PDF never truncates strategy cards.
* **NFR-9 Pydantic v2 + SQLAlchemy 2.0 Strictness**: All cross-module IO passes Pydantic validation; no raw dicts enter database layer; SQLAlchemy 2.0 style sessions with explicit commits/rollbacks.

## Constraints

### Technical
* Python 3.11+ on Windows 11.
* Frontend: Streamlit (no React rewrite).
* DB: Local SQLite + SQLAlchemy 2.0 ORM + Pydantic v2 schema layer.
* Vision: Google Gemini 1.5 Flash (preferred). Tesseract fallback.
* Charts: Plotly interactive (Streamlit); Plotly static export via kaleido + Chromium PDF path.
* PDF: Playwright Headless Chromium (no WeasyPrint — Windows GTK+/Pango DLLs excluded).
* Spreadsheet: XlsxWriter / openpyxl.

### Business
* Primary broker default **ZERODHA** flat ₹20 per executed order.
* STT fallback formula rate: **0.1% (0.001)** on sell-side option premium turnover (labeled clearly FORMULA rate; real numbers always override when Contract Note screenshot provided).
* Capital Deployed (Tradetron-card / operator-reviewed) is **always** the founder ROI denominator; SPAN+Exposure values stored but labeled "Audit Metric (Secondary)".
* Dhan API is strictly optional secondary helper — no blocking behavior anywhere in core pipeline.
* Tradetron execution ecosystem context (strategy names, multipliers, counters, deployment statuses) is respected as first-class domain object (`strategy_runs` table + breakdown cards).

### Dependencies
* Referenced Zerodha charge rates from user's CTO Master Plan §7 (SENSEX 2-leg spread audit).
* Referenced lot sizes / strike intervals / expiries from Quant Trading Agent KB §3.
* Reference P&L PDFs 03-09-2026 / 16-09-2026 / 17-09-2026 / 18-09-2026 as canonical e2e fixtures.

## Assumptions

* **A-1 Primary input sources are three Zerodha/Tradetron screenshot types**: Tradetron strategy cards dashboard, Zerodha Kite Positions, Zerodha Virtual Contract Note. Operator uploads 1–5 images per day covering these sections.
* **A-2 Gemini API key supports image inputs on user's tier**; if not, operator will upgrade tier — system does not silently switch OCR engines without a banner.
* **A-3 Capital Deployed values are extracted from Tradetron cards (₹2.00L / ₹3.25L patterns)**. When the value is missing or OCR < 0.85 confident, the Human-in-the-Loop review screen always requires the operator to confirm/type it manually before pipeline proceeds (no guess).
* **A-4 One-lot defaults only when the qty/lot_size equation matches a known index exactly**; otherwise, parser flags the row for review.
* **A-5 STT 0.1% (0.001) is correct Zerodha FORMULA rate for this desk's date range.** When a Contract Note screenshot is present, REALIZED values always take precedence and silently correct any rate drift in historical FORMULA rows.
* **A-6 "Strategy" level P&L = Tradetron strategy cards**; multiple executions can belong to one strategy; charges allocated by premium-turnover weight (configurable in settings).

## Acceptance Criteria

### AC-1: Cost Formula Golden Fixture (SENSEX 1-lot option leg) matches external calculator
* **Type**: `rule`
* **Given**: Charges calculator seeded with 2026-04-01 Zerodha/BSE FORMULA schedule
* **When**: Single SENSEX option leg: lot_size=20, buy_price=₹100, sell_price=₹120, exchange=BSE, slippage=₹0.10/point
* **Then**: Every cost component matches hand calculation
* **Pass Condition**: brokerage = ₹40.00 (2 orders × ₹20), stt = (20 × 120) × 0.001 = ₹2.40 (new STT 0.1% NOT 0.15%), stamp_duty = (20 × 100) × 3e-5 = ₹0.06, slippage = 0.10 × 20 × 2 = ₹4.00. Total charges matches hand calc ± ₹0.05.
* **Evidence**: `pytest -v -s tests/test_cost_calculator.py::TestCostCalculatorGoldenFixture::test_sensex_bull_call_leg_roundtrip` with verbose printed line-item breakdown

### AC-2: Realized Contract Note charges override formula exactly
* **Type**: `rule`
* **Given**: A `contract_note_charges` extraction with 6 realized values and total_charges
* **When**: Pipeline encounters matching daily run
* **Then**: `charges_breakdown` rows write charge_source=REALIZED_VIRTUAL_CONTRACT_NOTE and all 7 fields (6 line items + total) equal the extracted values exactly to 2 decimal places; strategy allocations sum to the exact realized total, not a formula sum
* **Evidence**: pytest `tests/test_cost_calculator.py::test_realized_contract_note_overrides_formula`

### AC-3: Margin audit metric calculator produces correct outputs for all four archetypes
* **Type**: `rule`
* **Given**: Margin calculator seeded 2026-04-01 SPAN%/Exposure% + known underlying_price
* **When**: (a) Long NIFTY ATM CE, (b) Short BANKNIFTY PE, (c) SENSEX future, (d) SENSEX 500-point bull-call spread
* **Then**: Each returns dict containing notional_value, span_margin, exposure_margin, total_margin_required, premium_paid_received, audit_net_capital_blocked_secondary, and methodology string
* **Pass Condition**: Long Option → `audit_net_capital_blocked_secondary` == premium_paid × qty only (no SPAN/Exposure added as primary ROI). Spread block equals max(debit, max_loss×qty) not raw sum of shorts.
* **Evidence**: pytest `tests/test_margin_calculator.py` output

### AC-4: Symbol parser handles Zerodha-digit / Tradetron-display / O-N-D month codes / futures
* **Type**: `rule`
* **Given**: ≥ 15 test vectors including `NIFTY26O2424000CE` (Oct), `SENSEX2692277300CE`, `BANKNIFTY26SEPFUT`, `FINNIFTY2611024500PE`, `SENSEX 22 Sep 2026 77300 CE` (display format)
* **When**: `parse_indian_symbol()` invoked
* **Then**: Correct underlying, expiry_date, strike_price, option_type, instrument_type
* **Pass Condition**: 100% of vectors match expected labeled columns in fixture CSV
* **Evidence**: pytest `tests/test_symbol_parser.py`

### AC-5: Strategy-Level ROI uses Capital Deployed as denominator, portfolio ROI uses peak capital
* **Type**: `rule`
* **Given**: Two strategies: (S1) Capital Deployed ₹2,00,000 Net P&L +₹8,000. (S2) Capital Deployed ₹3,25,000 Net P&L −₹3,250. Peak capital deployed intraday = ₹5,25,000.
* **When**: Daily summary aggregates
* **Then**: S1.net_roi_pct = (8000 / 200000) × 100 = 4.00%; S2.net_roi_pct = (−3250 / 325000) × 100 = −1.00%; total_day_net_pnl = +₹4,750; portfolio_day_net_roi_pct = (4750 / 525000) × 100 = 0.9047% ≈ 0.90%.
* **Pass Condition**: All 6 computed numbers exact within 2 dp rounding.
* **Evidence**: pytest `tests/test_strategy_roi_allocation.py`

### AC-6: SQLite schema + seed rows initialize with no SQL errors and correct canonical lot sizes
* **Type**: `rule`
* **Given**: `src/db/schema.py` + seed runner executed against a blank `data/quant_desk.db`
* **When**: `SELECT * FROM market_knowledge WHERE is_current=true;`
* **Then**: 8 rows return; lot sizes match {NIFTY OPT:25, BANKNIFTY OPT:15, SENSEX OPT:20, FINNIFTY OPT:25, MIDCPNIFTY OPT:50, NIFTY FUT:25, BANKNIFTY FUT:15, SENSEX FUT:20}; broker_charge_schedule returns a ZERODHA row.
* **Pass Condition**: All SQLAlchemy tables create cleanly. Foreign keys test OK.
* **Evidence**: `pytest tests/test_db_schema.py` DB creation output

### AC-7: Streamlit Daily Processing runs end-to-end via Manual CSV entry with NO API keys configured
* **Type**: `rule`
* **Given**: Streamlit server started with blank Gemini + Dhan keys.
* **When**: Operator navigates Daily Processing → Manual Strategy/CSV Template → uploads the synthetic fixture CSV → Approves staging review → clicks Generate.
* **Then**: Progress bar completes; no traceback; KPI strip renders; Download Excel produces a readable multi-sheet file.
* **Pass Condition**: Streamlit logs show 0 tracebacks.
* **Evidence**: Saved screenshot of successful summary view + Excel file SHA-256

### AC-8: Segment classification across 6 categories is 100% accurate on labeled fixture
* **Type**: `rule`
* **Given**: Mixed trade dataframe covering NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY, and one Stock FUT (RELIANCE26SEPFUT)
* **When**: `classify_trades_by_segment(df)`
* **Then**: Each row has exactly one non-null segment; counts match input fixture.
* **Pass Condition**: 100% match vs expected labels.
* **Evidence**: pytest `tests/test_market_knowledge.py` classification report

### AC-9: Equity curve cumulative values rebuild correctly when one historical date is re-processed
* **Type**: `rule`
* **Given**: 5 consecutive daily summaries (mon-fri) with mon-thu cumulative chains built correctly.
* **When**: Day-3 (wed) net_pnl is changed +₹500 and re-processed via pipeline.
* **Then**: cumulative_net_pnl for wed/thu/fri each shift exactly +₹500. drawdown_pct recomputes from new peak.
* **Pass Condition**: No stale carry values.
* **Evidence**: Before/after DB extracts of equity_curve table aligned by date.

### AC-10: UI & PDF adhere to hedge-fund visual quality bar
* **Type**: `rubric`
* **Dimension**: Visual & UX polish across Streamlit 4 pages + Playwright A4 PDF first page + strategy breakdown cards
* **Scale**: 1-5
* **Anchors**: 1 = default Streamlit white theme, default tables; 3 = dark CSS applied, colored P&L, basic charts; 5 = consistent dark midnight-navy theme, glassmorphism KPI tiles with hover/transition, gradient accent bars, Inter/JetBrains Mono @import webfonts, properly formatted ₹ values with commas + 2 dp everywhere, emerald profit with soft glow + crimson loss with soft glow (never reversed), 3 labeled chart types per daily report (donut + grouped bars + waterfall), strategy breakdown cards visually match Tradetron layout with status chips and greeks mini display, Playwright PDF prints with full styling (no element clipping, backgrounds on, A4 page breaks between strategy cards when > 3), color-coded segment palette stable across pages.
* **Pass Threshold**: >= 4
* **Evidence**: Screenshot gallery: 4 Streamlit pages + Playwright PDF page 1 + sample strategy breakdown spread.

### AC-11: Report formatting rigor, audit readiness, disclaimer placement
* **Type**: `rubric`
* **Dimension**: Accuracy, hygiene, audit-readiness of report content
* **Scale**: 1-5
* **Anchors**: 1 = unlabeled numbers, no provenance; 3 = currency labels, section headers, charge rows; 5 = every KPI + chart axis + strategy card + trade log row with consistent ₹ prefix, comma thousands, 2 dp, emerald/crimson strictly positive/negative (no swap), Contract Note Reconciliation table clearly labels Source with green/amber badges, "Audit Metric (Secondary)" badge next to every SPAN+Exposure value, methodology appendix lists each charge formula + NSE/BSE/SEBI/Zerodha source reference + date-versioned rates used, FR-13 disclaimer footer is prominent and bold on every page, input screenshot thumbnails embedded in appendix section, OCR confidence < 1.0 rows show a small warning badge next to them, Capital Deployed values carry a "Tradetron source / operator reviewed" provenance tag.
* **Pass Threshold**: >= 4
* **Evidence**: Annotated sample report scan with each rubric dimension boxed.

### AC-12: System reliability, graceful degradation with optional dependencies absent
* **Type**: `rubric`
* **Dimension**: Stability with zero/partial Gemini + Dhan + network
* **Scale**: 1-5
* **Anchors**: 1 = unhandled exceptions crash app; 3 = exceptions print to UI; 5 = all 9 pipeline stages have dedicated status blocks, per-stage timing + count readouts, Gemini timeout/429 → banner "Gemini rate limited / unavailable — switch to Manual CSV (1-click template)" with no crash, Dhan key blank or no network → banner "Dhan API not configured — using screenshot/estimated underlying prices (editable per trade)" with editable fields, 1 retry with backoff on 429/5xx, no silent number corruption, SQLite continues to write with no external dependencies, Historical Dashboard reads local DB even when both APIs fail.
* **Pass Threshold**: >= 4
* **Evidence**: Fault-injection screenshots (keys blank, network disabled) showing expected graceful banner outputs + manual path still works end-to-end.

## Open Questions

* [ ] **O1** Confirm STT formula fallback rate: set to 0.1% (0.001) per unified spec — override any 0.15% from prior draft. Confirm matches Zerodha calculator for desk's specific contract notes.
* [ ] **O2** Confirm 4 fixture PDFs are 03-09-2026, 16-09-2026, 17-09-2026, 18-09-2026 (per updated spec — prior draft had 01-09).
* [ ] **O3** Strategy charge allocation default: proportional by premium turnover — accept default or prefer equal-weight per strategy?
* [ ] **O4** Desk name & founder salutation placeholder for branding config — supply values during first-run or use generic placeholder?
* [ ] **O5** Gemini tier / rate limit expectations per daily run (5 screenshots × ~20s inference each)? This guides UI progress timeout tuning.
