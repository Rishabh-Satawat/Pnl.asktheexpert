#!/usr/bin/env python3
"""
Reproduction script: directly call the pipeline logic (as page_daily.py does)
with 4 SENSEX rows and verify all stages + result population.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from datetime import date

TEST_DF = pd.DataFrame([
    {"vendor_symbol": "OPTIDX_SENSEX_24SEP2026_PE_73800", "trade_date": "2026-09-22",
     "execution_time": "09:30:00", "condition": "Entry", "side": "SELL",
     "quantity": 20, "price": 51.05, "amount": -1021.0, "exchange": "BSE", "segment": "SENSEX"},
    {"vendor_symbol": "OPTIDX_SENSEX_24SEP2026_PE_73800", "trade_date": "2026-09-22",
     "execution_time": "11:00:00", "condition": "Universal Exit", "side": "BUY",
     "quantity": 20, "price": 63.00, "amount": 1260.0, "exchange": "BSE", "segment": "SENSEX"},
    {"vendor_symbol": "OPTIDX_SENSEX_24SEP2026_PE_74800", "trade_date": "2026-09-22",
     "execution_time": "09:30:00", "condition": "Entry", "side": "SELL",
     "quantity": 20, "price": 423.60, "amount": -8472.0, "exchange": "BSE", "segment": "SENSEX"},
    {"vendor_symbol": "OPTIDX_SENSEX_24SEP2026_PE_74800", "trade_date": "2026-09-22",
     "execution_time": "11:00:00", "condition": "Universal Exit", "side": "BUY",
     "quantity": 20, "price": 318.20, "amount": 6364.0, "exchange": "BSE", "segment": "SENSEX"},
])

STRATEGY_CARD = {
    "strategy_name": "SENSEX BFO Dynamic Inside-Day Short Strangle v1",
    "capital_deployed_allocated": 300000.0,
    "multiplier_x": 1,
    "deployment_status": "Exited",
    "broker": "Zerodha",
    "strategy_run_id": 0,
}


def main():
    staging_df = TEST_DF.copy()
    strategies_df = pd.DataFrame([STRATEGY_CARD])

    from src.db.engine import init_db
    from src.pnl_pipeline import DailyPipelineOrchestrator, PipelineResult

    engine, SessionLocal = init_db("data/quant_desk.db")
    orch = DailyPipelineOrchestrator(db_engine=engine, session_factory=SessionLocal)
    report_date = date.today()

    print("=" * 70)
    print("TEST: Simulating _run_real_pipeline() as page_daily.py does it")
    print("=" * 70)

    # ── Stage 1
    s1 = orch.stage_1_ingest_sources(manual_csv_df=staging_df)
    print(f"Stage 1 [{s1.status}]: {s1.row_counts}")

    # ── Stage 2
    raw_sources = s1.dataframes.get("raw_sources_df", pd.DataFrame())
    s2 = orch.stage_2_gemini_multimodal_parse(raw_sources)
    print(f"Stage 2 [{s2.status}]: {s2.row_counts}")
    assert len(s2.dataframes.get("trade_executions_df", pd.DataFrame())) == 4
    assert s2.dataframes.get("strategy_cards_df", pd.DataFrame()).empty

    # ── Stage 3
    s3 = orch.stage_3_review_staging(s2, operator_edits_df=staging_df, operator_approve_flag=True)
    print(f"Stage 3 [{s3.status}]: {s3.row_counts}")
    print(f"  s3.dataframes keys: {list(s3.dataframes.keys())}")
    print(f"  trade_executions_df in s3: {'trade_executions_df' in s3.dataframes}")
    assert len(s3.dataframes["trade_executions_df"]) == 4
    s3.dataframes["strategy_cards_df"] = strategies_df.copy()

    # ── Stage 4
    s4 = orch.stage_4_classify_symbols(s3.dataframes)
    print(f"Stage 4 [{s4.status}]: {s4.row_counts}")
    if s4.warnings:
        for w in s4.warnings:
            print(f"  WARN: {w}")

    # ── Stage 5
    trade_exec_df = s4.dataframes.get("trade_executions_df", pd.DataFrame())
    s5 = orch.stage_5_fifo_match(trade_exec_df)
    print(f"Stage 5 [{s5.status}]: {s5.row_counts}")
    matched_df = s5.dataframes.get("matched_df", pd.DataFrame())
    if s5.errors:
        for e in s5.errors:
            print(f"  ERROR: {e}")
    print(f"  matched_df shape: {matched_df.shape}")

    # ── Stage 6
    cn_charges = None
    s6 = orch.stage_6_compute_charges(matched_df, strategies_df, contract_note_charges=cn_charges)
    print(f"Stage 6 [{s6.status}]: {s6.row_counts}")
    charges_df = s6.dataframes.get("charges_df", pd.DataFrame())

    # ── Stage 7
    s7 = orch.stage_7_compute_summary(strategies_df, matched_df, charges_df)
    print(f"Stage 7 [{s7.status}]: {s7.row_counts}")
    if s7.errors:
        for e in s7.errors:
            print(f"  ERROR: {e}")
    strategy_runs_df = s7.dataframes.get("strategy_runs_df", pd.DataFrame())
    daily_summary_dict = s7.dataframes.get("daily_summary_dict", {})
    print(f"  strategy_runs_df shape: {strategy_runs_df.shape}")
    print(f"  daily_summary_dict: {daily_summary_dict}")

    # ── PipelineResult assembly (as in page_daily.py)
    result = PipelineResult(
        per_stage=[s1, s2, s3, s4, s5, s6, s7],
        strategy_runs_df=strategy_runs_df,
        charges_df=charges_df,
        daily_summary_df=daily_summary_dict,
    )
    result.all_passed = all(s.status in ("SUCCESS", "WARNING") for s in result.per_stage)
    result.report_ready = result.all_passed

    print("\n" + "=" * 70)
    print("PIPELINE RESULT:")
    print(f"  all_passed: {result.all_passed}")
    print(f"  strategy_runs_df is None: {result.strategy_runs_df is None}")
    print(f"  strategy_runs_df empty: {result.strategy_runs_df.empty if result.strategy_runs_df is not None else 'N/A'}")
    print(f"  daily_summary_df type: {type(result.daily_summary_df)}")
    print(f"  daily_summary_df value: {result.daily_summary_df}")

    if not matched_df.empty and "gross_pnl" in matched_df.columns:
        gross = matched_df["gross_pnl"].sum()
        diff = abs(gross - 1869.0)
        status = "PASS" if diff < 1.0 else "FAIL"
        print(f"\n{status}: Gross P&L = Rs {gross:,.2f} (expected Rs 1,869.00)")
    else:
        print("\nFAIL: matched_df is empty")

    # Check what Section 4 would show
    print("\n--- Section 4 render check ---")
    print(f"  pipeline_result is not None: {result is not None}")
    print(f"  daily_summary is None: {result.daily_summary_df is None}")
    print(f"  is dict: {isinstance(result.daily_summary_df, dict)}")
    print(f"  strategy_runs_df has rows: {not result.strategy_runs_df.empty if result.strategy_runs_df is not None else False}")

    return 0 if result.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
