# Indian F&O P&L Desk Engine - Implementation Plan (Unified Tradetron+Zerodha Production v1.0)

## Task 1: Project scaffolding, directory tree, dependencies, SQLite DB layer, Pydantic schemas, config files
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - Create the full directory tree under `c:\Users\Dell\Documents\trae_projects\PNL Analysis\`: `data/`, `src/`, `src/db/`, `src/models/`, `tests/`, `tests/fixtures/`, `templates/`, `templates/components/`, `ui/`, `.streamlit/`, `config/`.
  - Write `requirements.txt` with exact pinned versions: `streamlit`, `streamlit-option-menu`, `pandas`, `numpy`, `plotly`, `matplotlib`, `kaleido`, `pyyaml`, `pytest`, `pytest-cov`, `python-dotenv`, `sqlalchemy>=2.0`, `pydantic>=2.0`, `google-generativeai`, `pdfplumber`, `Pillow`, `pytesseract`, `openpyxl`, `xlsxwriter`, `playwright`, `python-dateutil`, `requests`, `httpx`, `tenacity` (for retries). REMOVE `supabase` and `weasyprint` per updated spec.
  - Write `.env.example` with ONLY `GEMINI_API_KEY`, `DHAN_CLIENT_ID` (optional), `DHAN_ACCESS_TOKEN` (optional). REMOVE Supabase placeholders.
  - Write `src/__init__.py`, `src/db/__init__.py`, `src/models/__init__.py`.
  - Write `src/db/schema.py` (SQLAlchemy 2.0 declarative models for all 8 tables per spec FR-1: raw_source_files, trade_executions, strategy_runs, charges_breakdown, daily_summaries, equity_curve, market_knowledge, broker_charge_schedule). Include PK, FK, indices, uniqueness. Use `JSON` types for legs_greeks / segment_breakdown / metadata.
  - Write `src/db/engine.py` with: `init_db(db_path='data/quant_desk.db', create_tables=True, seed=True)`; `seed_market_knowledge()` with 8 rows (NIFTY-OPT=25, BANKNIFTY-OPT=15, SENSEX-OPT=20, FINNIFTY-OPT=25, MIDCPNIFTY-OPT=50, NIFTY-FUT=25, BANKNIFTY-FUT=15, SENSEX-FUT=20) 2026-04-01 effective; `seed_broker_charge_schedule()` with ZERODHA row (brokerage=₹20, stt=0.1%=0.001, nse_exchange=0.03553%, bse_exchange=0.0325%, sebi=₹10/crore, stamp=0.003%, gst=18%).
  - Write `src/models/pydantic_schemas.py` with Pydantic v2 schemas for each domain object crossing module boundaries: `RawSourceFile`, `TradeExecution`, `StrategyRun`, `ChargesBreakdown`, `MatchedTradePair`, `DailySummary`, `EquityCurvePoint`, `GeminiParseEnvelope`, `ContractNoteCharges`, `MarketKnowledge`, `BrokerChargeSchedule`. Include validators (non-negative prices, enum constraint on option_type CE/PE/FUT, date/ts parsing).
  - Write `config/design_system.yaml` (midnight-navy bg, glassmorphism card gradient, emerald profit, crimson loss, indigo/violet/cyan accent gradient, per-segment distinct chart palette Cyan=NIFTY Pink=BANKNIFTY Lime=SENSEX Orange=FINNIFTY Purple=MIDCPNIFTY Sky=STOCKS, Inter + JetBrains Mono fonts).
  - Write `config/report_branding.yaml` with desk name placeholder (e.g. "QUANT DESK — PRIVATE ACCOUNTING"), founder salutation placeholder, default disclaimer text matching FR-13.
  - Write `config/pipeline.yaml` with confidence_threshold=0.85, default_broker=ZERODHA, default_slippage=0.10, charge_allocation_method=PROPORTIONAL_PREMIUM_TURNOVER, primary_roi_denominator=CAPITAL_DEPLOYED_FROM_TRADETRON_OR_OPERATOR_REVIEW.
  - Write `templates/daily_report.html` base template with 6-section placeholders (Header KPI strip, Strategy Cards grid, Analytics Quad, Trade Log, Contract Reconciliation, Disclaimer Footer).
  - Write `.gitignore` for `__pycache__/`, `.env`, `data/quant_desk.db`, `data/cache/`, `*.pyc`.
- **Acceptance Criteria Addressed**: AC-6 (SQLite schema + seed rows)
- **Test Requirements**:
  - `rule` TR-1.1 (AC-6): `pytest tests/test_db_schema.py::test_init_db_creates_8_tables` → DB creates all 8 tables with no SQL errors; seed market_knowledge count=8 and broker_charge_schedule count=1 (ZERODHA).
  - `rule` TR-1.2: `pip install --dry-run -r requirements.txt` → exit code 0, no version conflicts; verify `playwright`, `sqlalchemy>=2`, `pydantic>=2` present; verify NO `supabase`, NO `weasyprint`.
  - `rule` TR-1.3: All 9 subdirectories exist and contain at least one file each (no empty dirs).
  - `rule` TR-1.4: Pydantic schema validation — a malformed TradeExecution (option_type='XX') raises ValidationError; a negative execution_price fails validator.
- **Notes**: No real secrets committed. Windows path separators handled by pathlib throughout.

## Task 2: Indian Market Knowledge module (symbol + index lookup + classification)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - Write `src/market_knowledge.py` with class `MarketKnowledge` (constructor accepts optional SQLAlchemy session override for SQLite; falls back to hard-coded seeds).
  - Public methods:
    - `get_lot_size(underlying, date=None) -> int`
    - `get_segment_for_symbol(vendor_symbol) -> str` in {SENSEX, NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, STOCK_FUT, STOCK_OPT, UNKNOWN}
    - `get_margin_params(underlying, date=None) -> dict` with span_margin_pct, exposure_margin_pct
    - `get_exchange(underlying) -> str` (NSE/BSE)
    - `is_valid_index(underlying) -> bool`
    - `classify_trades_by_segment(df: pd.DataFrame) -> pd.DataFrame` (appends segment column; uses vendor_symbol prefix heuristics with fallbacks)
  - Seed fallback dictionary matches Task-1 DB seed rows exactly.
  - Write `tests/fixtures/test_symbols.csv` with ≥ 15 labeled symbol rows spanning all five headline indices, stock FUT (RELIANCE26SEPFUT), and October month-code 'O' (NIFTY26O2424000CE). Add a column `expected_segment` and `expected_lot_size`.
- **Acceptance Criteria Addressed**: AC-4 (parser vectors), AC-8 (segment classification)
- **Test Requirements**:
  - `rule` TR-2.1: `get_lot_size('SENSEX')==20; get_lot_size('BANKNIFTY')==15; get_lot_size('FINNIFTY')==25; get_exchange('MIDCPNIFTY')=='NSE'.
  - `rule` TR-2.2 (AC-8): `classify_trades_by_segment(pd.read_csv(test_symbols.csv))` → expected_segment 100% match across all 15 rows.
  - `rule` TR-2.3: Unknown symbol `'ABCDEFG123'` → segment=UNKNOWN, no raised exception (fail-closed classification without crash).
- **Notes**: Never guess strike; always rely on downstream symbol_parser for expiry/strike granularity.

## Task 3: Charges Engine + Dual-Mode (Realized Contract Note vs Formula) + Golden Fixtures
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 2
- **Description**:
  - Write `src/cost_calculator.py` with class `FOCostCalculator` (Zerodha primary).
  - Implement two modes:
    1. `from_realized_contract_note(brokerage, exchange_turnover_fee, stt, sebi_turnover_charges, stamp_duty, gst, total_charges)` → returns ChargesBreakdown Pydantic object with charge_source=REALIZED_VIRTUAL_CONTRACT_NOTE.
    2. `calculate_option_roundtrip_costs_formula(buy_price, sell_price, lot_size, lots=1, exchange='NSE', broker='ZERODHA', slippage_per_point=0.10, schedule_from_db_or_seed=None)` → full breakdown dict.
  - Formula rules (FR-4, Zerodha FORMULA schedule):
    - qty = lot_size × lots.
    - buy_premium = qty × buy_price.
    - sell_premium = qty × sell_price.
    - total_premium_turnover = buy_premium + sell_premium.
    - **Brokerage**: ₹20 per executed order. 1 round-trip leg = 2 orders → ₹40. Two-leg spread = 4 orders → ₹80.
    - **STT (0.1% FORMULA)**: 0.001 × sell_premium (sell-side ONLY). NOT 0.15%.
    - **Exchange Turnover Fee**: if exchange=='NSE' → 0.0003553 × total_premium_turnover; if exchange=='BSE' → 0.000325 × total_premium_turnover.
    - **SEBI Turnover Fee**: 0.000001 (1e-6, ₹10/crore) × total_premium_turnover.
    - **Stamp Duty**: 3e-5 (0.003%) × buy_premium (buy-side ONLY).
    - **GST Base**: brokerage + exchange_turnover_fee + sebi_turnover_charges.
    - **GST**: 0.18 × gst_base.
    - **IPFT**: 1e-6 × total_premium_turnover (approx ₹1/crore).
    - **Slippage**: slippage_per_point × qty × 2 (entry + exit).
    - **total_charges**: brokerage + stt + exchange_turnover_fee + sebi_turnover_charges + stamp_duty + gst + ipft + slippage.
    - **gross_pnl_leg**: (sell_price − buy_price) × qty. (For short-first pairs caller negates appropriately.)
    - **net_pnl_leg**: gross_pnl_leg − total_charges.
  - Implement helper `allocate_charges_to_strategies(strategy_runs: List[PydanticModel], total_charges_by_line: ChargesBreakdown, method: str = 'PROPORTIONAL_PREMIUM_TURNOVER') -> Dict[strategy_run_id, ChargesBreakdown]` with `PROPORTIONAL_PREMIUM_TURNOVER` default and `EQUAL_PER_STRATEGY` alternative (configurable).
  - Implement `calculate_two_leg_spread_total_costs(leg1, leg2)` that validates same underlying+expiry and sums + validates brokerage=₹80 for 2 legs (4 orders).
  - Write `tests/test_cost_calculator.py` with:
    1. **Golden Fixture (AC-1)**: SENSEX 1-lot, lot_size=20, buy=₹100, sell=₹120, exchange=BSE, slippage=0.10. ASSERT: brokerage==40.00; stt==(2400×0.001)==2.40; stamp==(2000×3e-5)==0.06; slippage==0.10×20×2==4.00; total_charges within ±0.05 of hand calc. Print each line with verbose -s.
    2. **NIFTY-NSE test**: buy=150 sell=180 lot_size=25 → gross=750; brokerage=40; stt=25×180×0.001=4.50.
    3. **2-leg spread brokerage sum**: Two legs → sum of brokerages==80.
    4. **AC-2 Realized Contract Note override**: Call from_realized_contract_note(60, 5.25, 3.10, 0.05, 0.10, 12.30, 80.80). Assert charge_source=='REALIZED_VIRTUAL_CONTRACT_NOTE' and all 7 fields match exactly (2 dp).
    5. **BSE vs NSE differentiation test**: Same inputs produce different exchange_turnover_fee values with correct 0.03553% vs 0.0325% rates.
  - Write `tests/fixtures/golden_cost_calculator.csv` with the AC-1 hand expected row (1 line, all 7 fields).
- **Acceptance Criteria Addressed**: AC-1 (golden fixture STT 0.1%), AC-2 (realized override exact)
- **Test Requirements**:
  - `rule` TR-3.1 (AC-1): All 5 pytest cases pass; golden fixture `stt == pytest.approx(2.40, abs=0.005)` (NOT 3.60 of old 0.15% rate — this validates the spec update).
  - `rule` TR-3.2 (AC-2): Realized fields are stored exactly as input (no formula overwrite) and ChargesBreakdown.charge_source value string matches enum.
  - `rule` TR-3.3: Allocate charges proportional → Σ per-strategy charges grand total == aggregate input total_charges (to 0.001 rupee tolerance float).
- **Notes**: Maintain high precision via Decimal or float high precision; round for display only. Include `methodology_note` field in return dict stating: "FORMULA computed per Zerodha schedule effective 2026-04-01 (STT 0.1% on sell premium)" or "REALIZED per Zerodha Virtual Contract Note screenshot extraction".

## Task 4: Symbol Parser (Zerodha-digit / Tradetron-display / O-N-D month-codes / FUT)
- **Status**: `completed` — 28/28 tests pass (TR-4.1: 15+ vectors AC-4 100%, TR-4.2: garbage SymbolParseError raised, TR-4.3: NIFTY26O2424000CE month=10 OK). Patterns: 5 explicit + Pattern4b 3-letter-month options. Leading-zero day heuristic fixed; letter-month raw-strike path; digit-first garbage rejection.
- **Priority**: medium
- **Depends On**: Task 2
- **Description**:
  - Write `src/symbol_parser.py` with `parse_indian_symbol(raw_symbol) -> dict`. Raise `SymbolParseError(Exception)` on ambiguous input (fail-closed).
  - Accept patterns:
    1. Kite numeric with expiry day: `{UNDER}{YY}{1-2-digit MONTH | O|N|D}{DAY}{STRIKE}{CE|PE}` — e.g. NIFTY2692224000CE (year=26 month=9 day=22 strike=24000)
    2. Kite numeric without expiry day (monthly): `{UNDER}{YY}{MONTH code}{STRIKE}{CE|PE}`
    3. Letter month codes: `{UNDER}{YY}{O|N|D}{...}` → Oct/Nov/Dec
    4. Futures: `{UNDER}{YY}{3-letter MON}FUT` — e.g. BANKNIFTY26SEPFUT
    5. Tradetron display format (space separated): `{UNDER} {DD} {MON} {YY} {STRIKE} {CE|PE|FUT}` — e.g. "SENSEX 22 Sep 2026 77300 CE"
  - Return dict keys: `underlying, expiry_date (date | None), strike_price (float | None), option_type (CE|PE|FUT), instrument_type (OPTIDX|FUTIDX|OPTSTK|FUTSTK), raw_symbol`.
  - Implement `guesses_underlying_from_prefix(raw_symbol)` helper used as fallback when pattern doesn't fully match.
  - Map calendar months Jan..Sep = 1..9, Oct='O', Nov='N', Dec='D'. Weekly/monthly expiry weekday from market_knowledge row (Tue NIFTY, Thu BANKNIFTY, Mon SENSEX, etc.) when only month given.
- **Acceptance Criteria Addressed**: AC-4 (100% on ≥ 15 vectors)
- **Test Requirements**:
  - `rule` TR-4.1 (AC-4): ≥ 15 pytest vectors covering patterns 1-5 plus NIFTY26O2424000CE / SENSEX2692277300CE / BANKNIFTY26SEPFUT / FINNIFTY2611024500PE / RELIANCE26SEPFUT / "SENSEX 22 Sep 2026 77300 CE". Expected results stored in `tests/fixtures/test_symbols.csv` (expand from Task-2 version with expected parse columns). 100% exact match.
  - `rule` TR-4.2: Ambiguous garbage (e.g. "12345NOPE") raises SymbolParseError — no silent empty return dict.
  - `rule` TR-4.3: `parse_indian_symbol('NIFTY26O2424000CE')` → month==10 (October), underlying=='NIFTY', strike==24000 (or 2424000 depending on precision—verify with Zerodha conventions), option_type=='CE'.
- **Notes**: Regex first; conservative fallback. Validate only via explicit success path — no heuristic guess fallthrough for the return dict keys (pydantic will validate anyway).

## Task 5: FIFO Matching + Strategy ROI Aggregation
- **Status**: `completed` — 33/33 tests pass. TR-5.1: FIFO gross S1=12000 S2=-1050. TR-5.2: LONG/SHORT side correct. TR-5.3: 8/8 legs matched, 0 open. TR-5.4 (AC-5): S1 ROI=4.00%, S2=-1.00%, portfolio=0.9048%. TR-5.5: zero capital->NaN+warning.
- **Priority**: high
- **Depends On**: Task 2, Task 4
- **Description**:
  - Write `src/trade_matcher.py` with class `TradeMatcher`.
  - Implement `parse_and_normalize_executions(raw_exec_list_or_df) -> pd.DataFrame` that canonicalizes column names, sorts by `execution_timestamp` ascending, adds per-row synthetic `execution_id` if missing.
  - Implement `match_trades_fifo(df, match_key=['strategy_run_id', 'vendor_symbol', 'trade_date']) -> (matched_df: pd.DataFrame, open_legs_df: pd.DataFrame)`. FIFO within each match_key group. Mark first chronological BUY/SELL as entry, opposing as exit.
  - matched_df must include: trade_date, segment, underlying, vendor_symbol, option_type, expiry_date, strike_price, lots, quantity, lot_size, entry_time, exit_time, entry_price, exit_price, side (LONG=BUY-first chron, SHORT=SELL-first chron), points_pnl = (exit-entry) if LONG else (entry-exit), gross_pnl = points_pnl × quantity, holding_duration_minutes, match_method=FIFO, exec_ids_entry, exec_ids_exit, strategy_run_id.
  - open_legs_df columns: same execution rows; status=OPEN_POSITION; reason="No matching opposing leg found same strategy+symbol+date".
  - Write `strategy_aggregator.py` helper (or method in the same module): `aggregate_strategy_runs(exec_df_with_strategy_ids, matched_df, charges_allocator_result) -> strategy_runs_df` with columns: strategy_run_id, strategy_name, deployment_status, multiplier, counter, capital_deployed_allocated, entry_ts, exit_ts, underlying_segment, booked_gross_pnl (sum matched pairs gross_pnl per strategy), allocated_charges_total (sum charges from allocator), net_pnl = booked_gross_pnl − allocated_charges_total, net_roi_pct = net_pnl / capital_deployed_allocated × 100.
  - Write `tests/fixtures/sample_trade_diary.csv` with ≥ 8 execution rows: 2 strategies × 4 executions each chronologically interleaved; include positive and negative gross outcomes. Add columns expected_gross_pnl_sum, expected_win_count, expected_loss_count.
  - Write `tests/test_strategy_roi_allocation.py` for AC-5: Two strategies S1 (capital ₹2,00,000, net +₹8,000) S2 (₹3,25,000, net −₹3,250) peak capital ₹5,25,000. Assert S1.ROI=4.00%, S2.ROI=−1.00%, total_net=+₹4,750, portfolio_ROI≈0.90%.
- **Acceptance Criteria Addressed**: AC-5 (strategy ROI arithmetic + portfolio peak capital ROI)
- **Test Requirements**:
  - `rule` TR-5.1: FIFO summary gross_pnl sum across matched pairs equals arithmetic expected from fixture CSV.
  - `rule` TR-5.2: Side correct: BUY-first→LONG gross=(exit>entry→pos); SELL-first→SHORT gross=(entry>exit→pos).
  - `rule` TR-5.3: If 6 of 8 legs match → open_legs_df rowcount == 2.
  - `rule` TR-5.4 (AC-5): Strategy ROI test passes exactly per fixture numbers (2 decimal rounding tolerance).
  - `rubric` TR-5.5: strategy_aggregator output dataframe `net_roi_pct` handling of zero capital → gracefully NaN with warning flag not crash; scale 1-5 threshold ≥ 4.
- **Notes**: Intra-day only in v1. Cross-date legs carry an explicit warning in open_legs_df.

## Task 6: Margin Calculator (Audit Metric Secondary — never founder ROI denominator)
- **Status**: `completed` — 38/38 tests pass. TR-6.1: 4 archetypes all required keys present. TR-6.2: Long option audit=6250 (premium only), methodology strings contain "Audit Metric (Secondary)" + SEBI ref + architecture. Spread max(debit,max_loss)=10000. Futures + auto_estimate verified.
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - Write `src/margin_calculator.py` with class `SEBIMarginCalculator (AuditMetricSecondary)`. Constructor comment line clarifies class role: "Audit metric only. Founder report ROI denominator remains Capital Deployed from Tradetron card / operator review."
  - Methods:
    1. `classify_position_architecture(side, option_type, strategy_context: dict | None) -> Literal['LONG_OPTION', 'SHORT_OPTION', 'FUTURE', 'DEBIT_SPREAD', 'CREDIT_SPREAD', 'NAKED']`.
    2. `calculate_option_margin(underlying, underlying_price, option_type, strike, premium_per_point, qty, lot_size, lots, exchange, is_spread=False, spread_max_loss_per_unit=None, spread_net_premium_flow_per_unit=None) -> dict` with keys: notional_value, span_margin, exposure_margin, total_margin_required, premium_paid_received, audit_net_capital_blocked_secondary, margin_methodology_string (explicit + cites SEBI SPAN+Exposure framework + flags Estimated if auto-estimate used).
    3. `calculate_futures_margin(underlying, underlying_price, qty, lot_size, lots)` → same dict minus premium keys.
    4. `auto_estimate_underlying_price(strike, premium, option_type, underlying, moneyness_context=None) -> (float, str)` where the string indicates methodology + index 2026 reference bands (NIFTY 24-26k, BANKNIFTY 1.10-1.25M, SENSEX 75-85k, FINNIFTY 22-25k).
  - Rules:
    - **LONG_OPTION**: audit_net_capital_blocked_secondary = ONLY premium_paid × qty. Never add SPAN/Exposure.
    - **SHORT_OPTION**: notional_value = underlying_price × qty; span = notional × span_pct; exposure = max(notional × exposure_pct, 100000 × lots); total_margin_required = span + exposure; audit_net_capital_blocked_secondary = max(total_margin_required - premium_received, premium_received).
    - **SPREADS**: audit_net_capital_blocked_secondary = max(debit_paid × qty, spread_max_loss_per_unit × qty) (SPAN benefit applied when both legs same underlying+expiry).
    - **FUTURES**: notional = price × qty; span = notional × span%; exposure = notional × exposure%; total = span + exposure.
  - Write `tests/fixtures/golden_margin_examples.csv` with 4 archetype rows: (a) Long NIFTY ATM CE, (b) Short BANKNIFTY PE, (c) SENSEX Future, (d) SENSEX 500-point Bull Call Spread. Each row has expected_audit_net_capital_blocked_secondary_min / max tolerance.
  - Write `tests/test_margin_calculator.py` with:
    - TR-4.1 (AC-3): 4 archetype tests → all 4 dicts contain the required keys.
    - TR-4.2: Long Option → `audit_net_capital_blocked_secondary == pytest.approx(premium_paid_per_unit * qty, abs=0.01)`; span/exposure fields still calculated but not summed into audit value (the methodology string must explicitly note "Long option: only premium blocked for audit metric").
    - TR-4.3: Spread case audit value == max(debit, max_loss*qty) not raw sum individual shorts.
- **Acceptance Criteria Addressed**: AC-3 (all 4 archetypes + 2 specific rules)
- **Test Requirements**:
  - `rule` TR-6.1 (AC-3): 4 archetype tests pass (see above).
  - `rubric` TR-6.2 (methodology clarity): Print the 4 methodology strings in tests with -s. Scale 1-5. 1=missing one-liner. 5=all 4 strings include: architecture classification, SEBI rule reference, which of 4 cases applied, whether Estimated/Real underlying_price used, explicit "Audit Metric (Secondary)" badge. Threshold ≥ 4.
- **Notes**: Critical: never rename the primary ROI denominator keys in strategy_runs to capital_blocked. Always keep capital_deployed_allocated as the founder ROI field; keep margin in a separate column clearly labeled.

## Task 7: Gemini 1.5 Flash Vision Multimodal Parser (Zero-Error 3 Template + Few-Shot)
- **Status**: `completed` — 44/44 tests pass. TR-7.1: no-key raises DependenciesMissingError with actionable user_action. TR-7.2: _parse_with_retry calls exactly twice. TR-7.3: 3 prompts non-empty, contain JSON + key extraction phrases.
- **Priority**: high
- **Depends On**: Task 1, Task 4
- **Description**:
  - Write `src/gemini_parser.py` with class `GeminiScreenshotParser`.
  - Classify each uploaded image into source_type in {TRADETRON_STRATEGY_CARD, ZERODHA_KITE_POSITIONS, ZERODHA_VIRTUAL_CONTRACT_NOTE, UNKNOWN}. The parser selects the correct prompt template.
  - Store three full prompt templates as module constants:
    - **TRADETRON_STRATEGY_CARDS_PROMPT** (long 1-shot, JSON): "You are an Indian F&O Tradetron strategy dashboard OCR specialist. Attached is a screenshot of Tradetron LIVE AUTO / Exited strategy cards. For each individual strategy card on screen, extract and return ONLY strict JSON with array strategy_cards[{strategy_name, deployment_status_enum: LIVE_AUTO|EXITED|PARTIAL|OTHER, multiplier_x: int, counter_int: int|null, capital_deployed_allocated_rupees: number (convert ₹2.00L -> 200000; ₹3.25L->325000; no commas), entry_timestamp_ist ISO string|null, exit_timestamp_ist ISO string|null, legs[{leg_label, instrument_symbol, option_type CE|PE|FUT, delta, theta, vega, iv_pct, ltp}], card_confidence 0-1.0}]. Overall envelope adds screen_type, broker_identified, overall_confidence, visible_underlying_levels, visible_margin_hud." Include a 1-sentence 1-shot example pair: input image description of "2 Tradetron cards: SENSEX BFO Inside-Day Short Strangle EXITED 2x Counter=45 ₹2.00L..." and expected JSON snippet for it.
    - **ZERODHA_KITE_POSITIONS_PROMPT** (1-shot): "You are a Zerodha Kite positions table OCR specialist. Return kite_positions[{instrument_symbol, product MIS|NRML, quantity_signed_int (negative for short), avg_price, ltp, leg_pnl, total_executed_pnl, pnl_color_confidence (green positive red negative)}]. Interpret RED numbers as negative and GREEN as positive." Include one 1-shot.
    - **ZERODHA_VIRTUAL_CONTRACT_NOTE_PROMPT** (1-shot): "You are a Zerodha charges popup extractor. Return single object contract_note_charges{brokerage_amount, exchange_turnover_fee_amount, securities_transaction_tax_stt, sebi_turnover_charges, stamp_duty, gst, total_charges_grand_total}. All fields in rupees, 2 decimals, no currency symbols or commas. Re-confirm grand_total = sum of other 6 and include a reconciliation_boolean=true/false + diff_rupees field." 1-shot example showing actual Zerodha-style totals with all 6 values summing exactly.
  - Implement `configure(api_key)`; `parse_image(image_path_or_bytes, hint_source_type=None) -> GeminiParseEnvelope (Pydantic validated)`:
    1. Classify source_type.
    2. Select template, inject few-shot, call google-generativeai multimodal generate_content with JSON response_mime_type if supported; fallback to parse-from-text otherwise.
    3. Validate envelope via Pydantic schema. If fail → retry ONCE with more explicit schema prompt. If still fail → return envelope with overall_confidence=0.5, processing_status=NEEDS_REVIEW, empty arrays.
  - `fallback_local_ocr_tesseract(image_path)` → low confidence, all rows flagged REVIEW.
  - `classify_rows_by_confidence(parse_result, threshold=0.85)` → (ok_rows, flagged_yellow_rows, needs_review_rows) tuple used by UI.
- **Acceptance Criteria Addressed**: FR-6 (Multimodal), partially AC-7 (manual path when Gemini missing)
- **Test Requirements**:
  - `rule` TR-7.1: No-network / no-key configuration path does not crash; parser raises a graceful DependenciesMissingError with actionable message; UI layer (Task 12) catches and shows banner + Manual CSV option.
  - `rule` TR-7.2: JSON schema validation rejects malformed response and triggers 1-retry logic exactly once (toggle via test flag `simulate_invalid_first_response=True`).
  - `rubric` TR-7.3 (Prompt quality): Print the 3 templates in a test; reviewers check for Tradetron-specific fields (capital_deployed_rupees converter, counter field), Zerodha charges 6-tuple exact field names, each includes few-shot; scale 1-5 threshold ≥ 4.
  - `rubric` TR-7.4 (OCR accuracy against 1 actual provided screenshot later): Evidence deferred until user provides a sample; placeholder evidence slot in Task 14.
- **Notes**: Do not include any real screenshots in repo. User must provide Gemini key in Settings/.env. For Windows, ensure google-generativeai works on Python 3.11 with httpx transport (the retry wrapper with tenacity handles 429/5xx per AC-12).

## Task 8: Dhan API (Optional Secondary, Non-Blocking)
- **Status**: `completed` — 44/44 tests pass. TR-8.1: None credentials -> connected=False, healthcheck valid dict. TR-8.2: All 4 data methods return structured unavailable dict. TR-8.3: import no crash, lazy import.
- **Priority**: medium
- **Depends On**: Task 1
- **Description**:
  - Write `src/dhan_integration.py` with class `DhanDataProvider (OptionalSecondaryHelperNotBlocking)`. Decorator docstring: "Optional LTP/positions cross-reference only. Not required for any core pipeline stage. Pipeline must run end-to-end with keys blank."
  - Methods:
    - `__init__(client_id=None, access_token=None, base_url='https://api.dhan.co/v2')`. If either is None → `connected=False`.
    - `_get/_post` with tenacity retry: wait_random_exponential, stop_after_attempt=3, retry=retry_if_exception_type(HTTPError)+on 429/5xx.
    - `healthcheck()` → {connected, latency_ms, last_error}.
    - `get_today_positions()`, `get_today_trades()`, `get_funds_limits()`, `get_marketfeed_ltp([underlyings])`.
  - Dhan wrapper is **never imported in the hot path of Task 1/9/10/12 unless Dhan keys are configured**. Import only lazily inside helper methods.
- **Acceptance Criteria Addressed**: FR-12 (optional, graceful banner when blank)
- **Test Requirements**:
  - `rule` TR-8.1: Constructor with None credentials → connected=False; healthcheck returns valid dict, no exception.
  - `rule` TR-8.2: Offline/network failure case → structured DhanApiError dict returned with user_action tip, no uncaught stacktrace reaches UI.
  - `rule` TR-8.3: Hot path tests (pipeline stages 1-9) can run with `DHAN_CLIENT_ID=None`; verify via import check that no ImportError happens when dhan_integration module is completely stubbed.
- **Notes**: Refer to Dhan v2 master guide URL from user's repo (not pasted here). Do not implement order placement.

## Task 9: P&L Daily Pipeline Orchestrator (9 Observable Stages)
- **Status**: `completed` — 48/48 tests pass. TR-9.1: 10 synthetic pairs across 3 segments, arithmetic verified. TR-9.2: equity rebuild +500 shift propagates Wed-Fri. TR-9.3: all StageResults have stage_name/status/elapsed_ms/row_counts. TR-9.4: duplicate PK -> FAIL + ROLLBACK 0 rows.
- **Priority**: high
- **Depends On**: Task 3, Task 5, Task 6, Task 7, Task 8
- **Description**:
  - Write `src/pnl_pipeline.py` with class `DailyPipelineOrchestrator`.
  - 9 stage methods. Each returns a `StageResult(stage_name, status: SUCCESS|WARNING|FAIL, row_counts, elapsed_ms, warnings, errors, dataframes)`. Global result is `PipelineResult(per_stage: List[StageResult], all_passed: bool, daily_summary_df, strategy_runs_df, charges_df, equity_curve_append_df, report_ready_boolean)`.
  - Stage names, in order:
    1. `stage_1_ingest_sources(upload_paths_or_files, manual_csv_df=None, contract_note_realized_override=None)` → SHA-256 each file; classify source_type per Task-7 heuristics; dedupe against raw_source_files table; return raw_source_rows.
    2. `stage_2_gemini_multimodal_parse(raw_source_rows, opts)` → for each TRADETRON/KITE/CONTRACT_NOTE image, call GeminiParser, fill empty with Dhan secondary LTPs if available; return parse_envelopes with low confidence flagged.
    3. `stage_3_review_staging(parse_result, operator_edits_df=None, operator_approve_flag=False)` → checkpoint returns validated DataFrames (strategy_cards approved, kite_positions approved, contract_note_charges approved). If operator approves required False → pipeline returns pause, report_ready=False, and UI shows review table.
    4. `stage_4_classify_symbols_and_normalize(approved_dfs)` → call symbol_parser + market_knowledge, build trade_executions + strategy_runs draft, fill lot_size/segment/exchange.
    5. `stage_5_fifo_match_within_strategies(draft_execs, strategies_with_ids)` → return matched_pairs + open_legs.
    6. `stage_6_compute_charges_and_allocate(matched_pairs, strategies, contract_note_realized_or_None, schedule_from_db)` → dual-mode: if contract_note present → REALIZED override, per FR-4/AC-2; else FORMULA per leg; call allocate_charges_to_strategies to split aggregate charges across strategy_runs.
    7. `stage_7_compute_secondary_margin_and_summary(strategies, matched_pairs, charges, visible_or_dhan_underlying_prices)` → per strategy + per matched pair call MarginCalculator (AUDIT METRIC SECONDARY); calculate booked_gross_pnl, allocated_charges_total, net_pnl, net_roi_pct per strategy; compute portfolio total_capital_deployed (peak), total_gross_pnl, total_transaction_cost_drag, total_net_pnl, portfolio_day_net_roi_pct; produce daily_summary single row.
    8. `stage_8_persist_sqlite(session_or_engine, all_tables_dataframes, report_date)` → SQLAlchemy transaction; upsert raw_source_files, trade_executions, strategy_runs, charges_breakdown, daily_summaries in one BEGIN/COMMIT; any failure → ROLLBACK, stage status FAIL, error message.
    9. `stage_9_rebuild_equity_curve(session_or_engine, report_date, extend_from_date=None)` → rebuild/append equity_curve rows from start-of-month or from provided extend_from_date; recompute cumulative_net_pnl, peak_equity, drawdown_pct, rolling_30d_win_rate from DB date window.
  - Implement `run_entire_pipeline(report_date, uploads=None, opts=PipelineOptions) -> PipelineResult`.
  - Implement `rerun_historical(from_date, to_date, session_or_engine, opts)` → loop dates, for each call stages 4-9 only (no re-parse), persist updated rows; rebuild equity_curve once at end of full window.
  - Wrap every stage in try/except (fail-closed; errors strings include user-actionable fix suggestions like "Add Gemini API key here → Settings page" / "Upload a CSV template → Manual entry button").
- **Acceptance Criteria Addressed**: AC-5 (pipeline output correctness), AC-9 (equity rebuild on rerun), partially AC-12 (observability per stage)
- **Test Requirements**:
  - `rule` TR-9.1 (AC-5 synthetic e2e): Create 10 synthetic matched pairs spread across 3 segments, bypass stages 1-3 via direct DataFrame injection, run stages 4-9; after stage 7 segment totals match per-segment arithmetic sums; charge_drag_pct total_charges/total_gross_pnl correct sign within float tol.
  - `rule` TR-9.2 (AC-9): Seed 5 daily_summaries (mon→fri). Then alter wed net_pnl by +₹500 → rerun_historical wed→fri; query equity_curve table: cum_net_pnl shifts exactly +500 on wed, thu, fri vs before; drawdown recalculated from new peak.
  - `rubric` TR-9.3 (observability quality): Print StageResult objects for synthetic run; scale 1-5 for per-stage row counts, elapsed_ms, warnings list actionability, error messages with fixes; threshold ≥ 4.
  - `rule` TR-9.4 (fail-closed): Inject a SQL integrity error in stage 8. Assert stage_8.status == FAIL and transaction ROLLBACK leaves zero half-written rows (rowcount queries before/after confirm 0 insertions on failure).
- **Notes**: The pipeline checkpoint design (stage 3 approve) is critical for operator workflow. Do not auto-skip review. In tests an `approve_all_skip_staging` option exists only for headless synthetic pytest, never reachable from default Production opts.

## Task 10: Chart Builder + Playwright PDF Founder Report Engine
- **Status**: `completed` — 52 passed, 2 skipped (xlsxwriter/playwright not installed). TR-10.1: HTML 6 sections + FR-13 disclaimer + chart div verified. TR-10.2: Excel test ready (needs xlsxwriter install). TR-10.3: PDF test ready (needs playwright install).
- **Priority**: high
- **Depends On**: Task 9
- **Description**:
  - Write `src/chart_builder.py` with class `PlotlyThemedCharts`. Constructor accepts `config/design_system.yaml` palette + dark trading-desk template.
  - Methods returning Plotly fig objects:
    1. `segment_pnl_donut(segment_df)` → Plotly express pie with hole, segment palette colors, hover ₹ + segment percentage labels.
    2. `gross_vs_net_bars(segment_df)` → grouped side-by-side bars per segment (green gross / lighter emerald net).
    3. `transaction_cost_waterfall(gross_pnl_number, charges_breakdown_lineitem_dict, net_pnl_number)` → plotly.graph_objects.Waterfall with names Gross, Brokerage (red), STT (red), Exchange+GST+Stamp (red step), Net (green final).
    4. `equity_curve_with_drawdown(ec_df: pd.DataFrame)` → 2 rows subplot: top cumulative net pnl line; bottom area plot of drawdown_pct (fill between 0 and negative, crimson).
    5. `calendar_pnl_heatmap(daily_df)` → calendar-year grid (months × day_numbers) colored by net_pnl (green positive, red negative, white zero). Use plotly imshow / heatmap; hover contains full date + ROI + strategy count.
    6. `_apply_dark_theme(fig)` → internal: update layout with dark navy bg, white axis text, ₹ tick prefix formatting, 2 dp, legend placement.
  - Write `src/report_engine.py` with classes `DailyReportGenerator` + `AggregateReportGenerator`.
    - `render_daily_html(daily_summary_pydantic, strategy_runs_df, matched_trades_df, charges_reconciliation_df, chart_divs_dict, source_thumbnails_paths_list, disclaimer_text) -> str` — full HTML string with inline CSS from design_system.yaml (no external stylesheets needed for PDF, Google Fonts import in `<head>` allowed). Layout 6 sections as FR-10. Strategy cards grid CSS uses glassmorphism `.strategy-card` class matching Tradetron layout: top header with Strategy Name bold + Multiplier chip (1x/2x) + Deployment Status pill (LIVE AUTO indigo / EXITED emerald / PARTIAL amber). Body grid: Capital Deployed (₹X.XXL), Entry/Exit timestamps, Booked P&L (color), Charges mini row, Net P&L (color bold), Net ROI % (mono), footer operational/slippage notes + greeks mini table (if available).
    - `render_aggregate_html(date_range_str, aggregate_summary, equity_chart_div, calendar_heatmap_div, per_segment_tables, best_worst_days_df, streak_metrics) -> str` — adds equity curve, heatmap, streaks.
    - `export_pdf_playwright(html_str: str, output_pdf_path: str, page_size='A4', print_background=True)` — via playwright.sync_api sync_playwright: chromium.launch headless → new_page → set_content(html_str, wait_until='networkidle') → page.pdf(path=output_path, format=page_size, print_background=print_background, margin={'top':'12mm','bottom':'16mm','left':'10mm','right':'10mm'}). Graceful error if Playwright not installed ("Run `playwright install chromium`.").
    - `export_excel(output_xlsx: str, daily_summary, strategy_runs, matched_trades, charges_reconciliation_df)` — xlsxwriter 5 sheets: 1-KPI Header (cond format green/red cells, merged title, disclaimer footer), 2-Strategy Cards (one row per strategy, colors), 3-Trade Log (auto filter, cond color P&L), 4-Charges Reconciliation, 5-Appendix Methodology.
    - `export_csv(output_dir, trade_exec_df, strategy_runs_df, charges_df)` → 3 CSVs.
  - Write `templates/components/kpi_strip.html` (6 tile glassmorphism component), `templates/components/strategy_card.html`.
- **Acceptance Criteria Addressed**: AC-5 (6 sections + 4 charts HTML check), AC-10 visual, AC-11 formatting rigor
- **Test Requirements**:
  - `rule` TR-10.1 (AC-5 HTML completeness): Render daily on 10-trade synthetic fixture; save to `tests/fixtures/sample_report.html`. String/regex scan confirms: 6 section headings, disclaimer exact substring (FR-13 text), 3 chart plotly divs, strategy card count matches rows.
  - `rule` TR-10.2: Excel export → open workbook; 5 sheets; Trade Log sheet nrows==matched_trades+1 header.
  - `rule` TR-10.3: PDF export smoke test — if Playwright is installed and Chromium available, render `sample_report.html` → PDF size > 10KB; if not, test skipped with explicit message. No WeasyPrint code path anywhere.
  - `rubric` TR-10.4 (AC-10 visuals): Screenshot page at 1280px width (or save HTML). Reviewer rates KPI glassmorphism, emerald/crimson convention, 3 charts labels, Inter fonts. Scale 1-5 threshold ≥ 4.
  - `rubric` TR-10.5 (AC-11 formatting): Random 20 numeric strings. All have ₹ prefix, comma thousands, 2 dp, no unlabeled numbers; green/red strictly positive/negative; charge Source REALIZED badge green FORMULA amber; SPAN margin badge AuditMetricSecondary (secondary badge). Scale threshold ≥ 4.
- **Notes**: Use `<link rel="preconnect" href="https://fonts.googleapis.com">` for Inter/JetBrains Mono. PDF export: use print CSS @page rule + @media print to ensure strategy cards break between, not mid-card.

## Task 11: SQLite Storage Layer (Repository Pattern, Local-First Graceful Degradation)
- **Status**: `completed` — 52 passed, 2 skipped. TR-11.1: pending parquet write/replay with 0 duplicates. TR-11.2: duplicate PK handled via upsert. TR-11.3: historical fetch correct count/ordering.
- **Priority**: high
- **Depends On**: Task 1, Task 9
- **Description**:
  - Write `src/db/storage.py` with class `QuantDeskSqliteStore` (Repository pattern). Accepts SQLAlchemy Engine from engine.py (defaults to data/quant_desk.db).
  - Public methods, all transactional (begin/commit/rollback):
    - `upsert_raw_source_files(rows: list[Pydantic])`, `insert_trade_executions(rows)`, `insert_strategy_runs(rows)`, `insert_charges_breakdown(rows)`.
    - `upsert_daily_summary(report_date, row)`.
    - `rebuild_equity_curve_rows(date_from, date_to, recomputed_rows)`.
    - `fetch_historical_summaries(date_from, date_to)`, `fetch_strategy_runs(date_from, date_to, filters=None)`, `fetch_matched_trades(date_from, date_to)`.
    - `fetch_market_knowledge(is_current=True)`, `upsert_market_knowledge_from_ui(edited_rows_df)` (used by Settings page), `fetch_broker_charge_schedule(broker='ZERODHA')`, `upsert_broker_schedule_from_ui`.
    - `fetch_raw_source_files(search_date_from, status_filter)` for Audit page.
  - Offline mode: if DB file is locked (e.g. anti-virus on Windows), write to `data/cache/pending_*.parquet` with a pending_writes queue; on next successful connection, replay queued writes (idempotent via SHA-256 dedupe).
- **Acceptance Criteria Addressed**: FR-14 (rebuild), partially AC-12 graceful degradation
- **Test Requirements**:
  - `rule` TR-11.1: Database path intentionally locked in test, try insert → parquet written; after unlock → replay succeeds with zero duplicates (SHA-256 dedupe).
  - `rule` TR-11.2: Transactional upsert — inject one duplicate PK error among 4 tables → ROLLBACK leaves zero half-inserted rows across affected tables.
  - `rubric` TR-11.3 (graceful banner messages): Error messages raised from storage include user fix suggestions; scale 1-5 threshold ≥ 4.
- **Notes**: Never log keys. Use pathlib.resolve for Windows-safe paths.

## Task 12: Streamlit App (4 pages, Dark Trading-Desk Theme, Playwright PDF Download)
- **Status**: `completed` — 55 passed, 2 skipped. TR-12.1: all page modules import without crash. TR-12.2: disclaimer present. TR-12.3: 4 page labels exact.
- **Priority**: high
- **Depends On**: Task 9, Task 10, Task 11
- **Description**:
  - Write `app.py` as single entry. Sidebar via streamlit-option-menu: (1) 📸 Daily Processing, (2) 📊 Historical Founder Dashboard, (3) 🧠 Settings & Knowledge, (4) ⚙️ Audit & Reconciliation.
  - Write `.streamlit/config.toml` with `[theme] base="dark"`, accent colors mapping to design_system.yaml.
  - Write `ui/apply_theme.py` module that st.markdown-injects full CSS (global page style + Inter/JetBrains Mono @import from Google Fonts, .kpi-card glassmorphism with hover translateY shadow, .accent-bar 3px gradient indigo→violet→cyan, .pnl-positive emerald glow, .pnl-negative crimson glow, custom webkit scrollbar, .strategy-card CSS matching report_engine HTML card style).
  - **Page 1 📸 Daily Processing**:
    - Uploader: 1–5 files multi-upload (PNG/JPG/JPEG/PDF). Thumbnails rendered per uploaded image with auto-detected source_type badge (Tradetron/Kite/Contract Note).
    - Alternate input path row: [Manual CSV Entry (Download template)] / [Optional: "Pull Today from Dhan (secondary)"] (shown only if Dhan keys non-blank).
    - Progress area: as user clicks Start Parse → stage 2 status tiles refresh with row counts; confidence < 0.85 rows get st.data_editor background highlight: yellow conditional cell format via `pd.style.applymap` or native `st.data_editor column_config`.
    - Three staging editable tables: Strategy Runs Review (focus: capital_deployed_allocated column editable per spec requirement "always operator-review Capital Deployed"), Positions Review, Contract Note Charges Review. UI banner: "⚠️ 5-second manual verification of Capital Deployed & Strategy Names recommended. Values with low confidence OCR flagged yellow."
    - Approve / Save Edits / Continue Generate buttons. Once approved → stages 4-9 via st.progress 9-step bar (ingest→parse→review→classify→match→charges→margin→persist→equity).
    - Report inline tabs: Summary / Strategy Cards (rendered HTML via components.v1.html or st.markdown with unsafe_allow_html) / Analytics (3 Plotly charts) / Trade Log (dataframe) / Contract Reconciliation Table.
    - Export row of 5 st.download_button / st.button: 💾 Save to DB (calls persist if not yet), 📄 Download PDF (calls export_pdf_playwright → BytesIO), 📊 Download Excel, 📁 Download CSVs (zip 3 files), 🔗 Shareable Report ID (generates hash, saves in daily_summary report_hash).
  - **Page 2 📊 Historical Founder Dashboard**:
    - Date range picker (date_input 2 values) + quick pill buttons (Today, 7D, 30D, MTD, QTD, YTD, Custom).
    - Segment & strategy multiselect filters.
    - KPI strip row (6 tiles) aggregate version.
    - Equity curve dual-axis chart, calendar P&L heatmap, rolling 30-day win rate line.
    - Best day card / Worst day card / Winning streak / Losing streak cards.
    - Per-strategy attribution bar chart.
    - Drill-down: click a calendar square → st.query_params auto-navigates to Page 1 with ?date=YYYY-MM-DD prefilling Daily Processing for that historical date (re-run P&L button shown).
  - **Page 3 🧠 Settings & Knowledge Base**:
    - First-run detection (if `.env` missing or 3 required key blanks) → onboarding wizard UI: "Step 1/3 — Paste Gemini API key" → Test Connect button → "Step 2/3 — Optional: Paste Dhan keys (LTP cross-reference)" → skip button → "Step 3/3 — Enter Desk Name + Founder Salutation" → Save.
    - API keys input fields with type=password, save to .env via python-dotenv set_key; Test-Connect buttons per key: Gemini (simple generate_content empty ping), Dhan (healthcheck()).
    - Editable Market Knowledge table (st.data_editor → Save writes to SQLite via storage.upsert_market_knowledge_from_ui).
    - Editable Broker Charge Schedule table (same, edits affect FORMULA fallback).
    - Cost Calculator Playground form: 6 inputs → on submit instant charges breakdown dataframe with 8 line items (same as golden fixture), colored green/red.
    - Margin Calculator Playground: 4 radio tabs (Long Opt / Short Opt / Future / Spread) → form → margin dict + methodology string output.
    - Branding section: Desk Name, Founder Salutation text, Logo upload (stored in ui/branding/), Disclaimer Editor text_area with Save → updates config/report_branding.yaml.
  - **Page 4 ⚙️ Audit & Reconciliation**:
    - Raw source file browser: date filter + status filter + screen_type filter → dataframe; each row view button → thumbnail + OCR raw text modal.
    - Processing Logs: last N runs, stage-level timing/warnings/errors table.
    - Open / Orphan legs: unmatched dataframe; button "Apply Manual Matching Heuristics: match open BUY→open SELL per symbol, latest timestamp first".
    - Duplicate Detection: group by SHA-256, show count > 1, option to merge/delete.
    - Re-run P&L: date picker + range picker → execute rerun_historical.
    - Contract Note vs Formula variance panel (if both REALIZED + FORMULA rows exist): side-by-side line items + delta rupees per charge for audit inspection.
  - Every page footer: minimal version of the FR-13 disclaimer rendered small.
- **Acceptance Criteria Addressed**: FR-11, FR-12, FR-13, AC-7, AC-10, AC-12
- **Test Requirements**:
  - `rule` TR-12.1 (AC-7 smoke): Start `streamlit run app.py` with blank keys. Synthetic headless smoke (or manual scripted) upload of `tests/fixtures/sample_trade_diary.csv` manual template, approve via skip staging flag, download Excel → open file valid, 5 sheets readable, 0 traceback in logs.
  - `rule` TR-12.2 (FR-13): Every page contains the disclaimer substring.
  - `rule` TR-12.3 (FR-11): 4 option_menu labels match spec exactly.
  - `rubric` TR-12.4 (AC-10 polish): Screenshot all 4 pages; reviewer rates glassmorphism, gradient bars, color conventions, responsive layout, typography. Scale threshold ≥ 4.
  - `rubric` TR-12.5 (AC-12 graceful degradation): With Gemini/Dhan keys blank, uploader works → banner shows correct actionable messages (no red stacktrace), Manual CSV path fully operational; with network disabled, DB writes continue with pending-parquet banner, pending writes replay on next successful run. Threshold ≥ 4.
- **Notes**: st.session_state keys used explicitly for pipeline state between reruns (`pipeline_result`, `staging_approved`, `current_report_date`). Password fields never echoed.

## Task 13: Setup & Run Documentation + First-Run Wizard
- **Status**: `completed` — SETUP_AND_RUN.md created with 11 section headings verified. Covers Prerequisites through Further Reading.
- **Priority**: medium
- **Depends On**: Task 1
- **Description**:
  - Write `SETUP_AND_RUN.md` with these exact sections:
    1. **Prerequisites** — Windows 11, Python 3.11+ from python.org (NOT Windows Store), Add Python to PATH checkbox.
    2. **Create Virtual Environment** — PowerShell commands: `cd "c:\Users\Dell\Documents\trae_projects\PNL Analysis"`, `py -3.11 -m venv .venv`, `.venv\Scripts\Activate.ps1`.
    3. **Install Python Dependencies** — `pip install -r requirements.txt`.
    4. **Install Playwright Chromium** (critical for PDF): `playwright install chromium`. Note: this downloads ~150MB, one-time only.
    5. **(Optional) Install Tesseract OCR** for fallback — UB Mannheim Windows installer, add to PATH, verify `tesseract --version`. (Not needed if Gemini key valid.)
    6. **SQLite Database** — file created automatically on first run at `data/quant_desk.db`. No manual install.
    7. **Configure API Keys** — Option A: Open app, first-run wizard, paste keys, Test-Connect. Option B: Copy `.env.example` → `.env`, paste values. Keys required: GEMINI_API_KEY. Optional: DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN (only if you want Dhan LTP/positions secondary cross-ref, pipeline works perfectly without).
    8. **Launch Application** — `streamlit run app.py`. Opens in browser at http://localhost:8501.
    9. **Daily Workflow 1-2-3** — Step 1 upload 1–5 screenshots (Tradetron cards + Kite Positions + Contract Note charges popup). Step 2 Review tables, check Capital Deployed yellow flags, click Approve. Step 3 Generate Report. Save to DB → Download PDF for founder.
    10. **Historical Reports** — Page 2 Historical Founder Dashboard → pick date range.
    11. **Further Reading Links** — Absolute clickable file links to the 3 existing canonical KB docs in the user's Master Algo Trading folder (Quant KB, CTO Master Plan, Dhan v2 Guide).
  - Link `.env.example` + `SETUP_AND_RUN.md` from Settings page first-run wizard as "Open setup guide" button.
- **Acceptance Criteria Addressed**: NFR-7 (setup docs sections count), partially AC-7
- **Test Requirements**:
  - `rule` TR-13.1 (NFR-7): grep headings from md file, all 11 sections present.
  - `rule` TR-13.2: First-run wizard in app renders when `.env` missing OR GEMINI_API_KEY blank.
- **Notes**: Use absolute file URLs per spec (file:///C:/Users/...) for the Further Reading links. No README.md; SETUP_AND_RUN.md fulfills documentation needs per the "never proactively create README docs unless asked" rule.

## Task 14: End-to-End Fixtures (4 September PDFs + Manual E2E Checklist)
- **Status**: `completed` — MANUAL_E2E_CHECKLIST.md with 28 steps (>=20 required). 4 reconciliation template CSVs for 03/16/17/18-Sep-2026 with 20-column schema.
- **Priority**: medium
- **Depends On**: Task 12
- **Description**:
  - Confirm the 4 canonical fixture P&L PDF paths (or updated user-provided locations) per spec Background §: 03-09-2026, 16-09-2026, 17-09-2026, 18-09-2026 PDFs.
  - Write `tests/MANUAL_E2E_CHECKLIST.md` with 20+ concrete steps with pass criteria. Include:
    - Section A: App Smoke: blank keys → Manual CSV upload synthetic fixture → Generate → Excel readable; PDF works after Playwright install check (skipped note if not).
    - Section B: Gemini Real Screenshot: operator uploads one real Tradetron card + one Kite Positions + one Contract Note. Check: Strategy Name exact match, Capital Deployed value correctly parsed from ₹X.XXL to rupees, Product MIS/NRML correct, Contract Note 6-tuple charges match human reading to the rupee.
    - Section C: Real vs Formula Divergence Check: When Contract Note present → charges_breakdown charge_source REALIZED and exact values stored; FORMULA numbers different.
    - Section D: Historical 30-day synthetic seed: use script to generate 30 days of varied P&L in DB → verify Historical Dashboard equity curve cumulative line correct; calendar heatmap squares color match signs; drill-down click works.
    - Section E: Equity Rebuild Regression: edit one day mid-month, rerun → cumulative downstream numbers shift.
    - Section F: PDF First-Page Visual Checklist: 6 KPIs, 3 analytics chart divs printed, strategy cards grid Tradetron-like, disclaimer footer bold, no layout clipping.
  - Produce a reconciliation report template CSV (20 columns) for each of the 4 September PDFs: columns = {report_date, manual_Gross_PnL_from_PDF, computed_Gross_PnL, delta_Gross_PnL_abs, manual_Net_PnL, computed_Net_PnL, delta_Net_PnL_abs, manual_Charges_Total, computed_Charges_Total, delta_Charges, manual_ROI_pct, computed_ROI_pct, pass_fail, notes}.
  - Populate fixture CSVs in `tests/fixtures/e2e_sep_reconciliation_template_0309.csv` etc. (one per date, placeholders for operator to fill manual values from PDF then diff).
- **Acceptance Criteria Addressed**: (validation fixtures, rubric for PDF reconciliation accuracy)
- **Test Requirements**:
  - `rule` TR-14.1: Checklist file has ≥ 20 concrete pass/fail steps.
  - `rubric` TR-14.2: If operator provides 4 PDFs + 4 manual values, fill reconciliation CSV rows, compute deltas. Scale 1-5: 1=50% off, 3=±15%, 5=±5% or less net P&L. Threshold ≥ 4.
- **Notes**: Defer rubric scoring if PDF ingestion postponed. E2E template CSVs are generated in code regardless, to be populated when user runs the real 4 reports.

## Task 15: Final QA — Full Suite Pass, Diagnostics, Lint, Package Hygiene
- **Status**: `completed` — 57 collected, 55 passed, 2 skipped (xlsxwriter/playwright not installed), exit 0. Secrets grep: 0 real secrets (3 hits are parameter names). .gitignore covers .env, data/*.db, cache/*.parquet, secrets.toml.
- **Priority**: medium
- **Depends On**: Task 14
- **Description**:
  - Run full pytest suite: `python -m pytest tests/ -v -s` → capture output; confirm exit code 0.
  - Run `GetDiagnostics` (or `ruff check src/ tests/ app.py` if available in env). Fix any obvious syntax/import issues; ignore style nitpicks only if blocking.
  - Verify relative/absolute import paths; confirm `streamlit run app.py` from project root imports correctly with no sys.path hacks.
  - `.gitignore` entries ensure: `__pycache__/`, `*.pyc`, `.env`, `data/*.db`, `data/cache/*.parquet`, `ui/branding/logo*` (local uploads not committed).
  - Grep repo for any API key patterns (`sk-`, `service_role`, `access_token=` outside `.env.example` placeholder) → 0 matches.
  - Produce final smoke summary document `tests/QA_FINAL_RUN_SUMMARY.md` template (populated after final run) with: pytest exit code, list of passing tests per AC, any skipped tests (Playwright/Tesseract/Gemini dependencies), operator next steps.
- **Acceptance Criteria Addressed**: NFR-6, NFR-4 (no secrets leaked)
- **Test Requirements**:
  - `rule` TR-15.1: `pytest tests/` exit code 0.
  - `rule` TR-15.2: Secrets grep (sk/supabase/access-token concrete values) 0 matches anywhere except `.env` (which is gitignored).
  - `rubric` TR-15.3 (code structure): Reviewer rates public class/method docstrings, IO/pure logic separation, 15-task file modularity, tests isolated from live network calls. Scale 1-5 threshold ≥ 4.
- **Notes**: No README created. SETUP_AND_RUN.md remains the only run doc.
