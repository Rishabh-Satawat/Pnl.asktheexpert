from __future__ import annotations

import os
import traceback
from datetime import date

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]


def render_daily_processing() -> None:
    """Page 1: Daily Processing - screenshot upload, staging review, pipeline execution."""
    if st is None:
        return

    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("Daily Processing")

    # ── Date Picker ───────────────────────────────────────────────
    report_date = st.date_input("Trading Date", value=date.today())
    st.session_state["report_date"] = report_date

    # ── Screenshot Upload ─────────────────────────────────────────
    st.subheader("1. Upload Source Screenshots")
    uploaded_files = st.file_uploader(
        "Upload 1-5 screenshots (PNG / JPG / PDF)",
        type=["png", "jpg", "jpeg", "pdf"],
        accept_multiple_files=True,
        key="daily_upload",
    )

    if uploaded_files:
        if len(uploaded_files) > 5:
            st.warning("Maximum 5 files allowed. Only the first 5 will be processed.")
            uploaded_files = uploaded_files[:5]

        st.markdown("**Detected sources:**")
        for uf in uploaded_files:
            ext = uf.name.rsplit(".", 1)[-1].upper() if "." in uf.name else "UNKNOWN"
            badge_color = {"PNG": "#22D3EE", "JPG": "#F472B6", "JPEG": "#F472B6", "PDF": "#A3E635"}.get(ext, "#94A3B8")
            st.markdown(
                f'<span style="background:{badge_color}20;color:{badge_color};padding:2px 8px;border-radius:4px;'
                f'font-size:0.82rem;font-weight:600;">{ext}</span> {uf.name}',
                unsafe_allow_html=True,
            )

    # ── Gemini key check ──────────────────────────────────────────
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        try:
            gemini_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass

    def _show_manual_csv_fallback():
        st.subheader("Manual CSV Upload")
        csv_file = st.file_uploader("Upload staging CSV", type=["csv"], key="manual_csv")
        if csv_file and pd is not None:
            try:
                staging_df = pd.read_csv(csv_file)
                st.session_state["staging_data"] = staging_df
                st.dataframe(staging_df, use_container_width=True)
            except Exception as exc:
                st.error(f"Error reading CSV: {exc}")
        st.download_button(
            "Download CSV Template",
            data="report_date,strategy_name,segment,symbol,side,lots,lot_size,quantity,execution_price,option_type\n",
            file_name="staging_template.csv",
            mime="text/csv",
        )

    if not gemini_key:
        st.info(
            "Gemini API key not configured. You can set it in **Settings & Knowledge Base** page, "
            "or use manual CSV upload below."
        )
        _show_manual_csv_fallback()
    elif uploaded_files:
        # ── Extract button ────────────────────────────────────────
        st.markdown("")
        extract_clicked = st.button(
            "🔍 Extract Data from Screenshots",
            type="primary",
            key="btn_extract_screenshots",
            help="Send uploaded screenshots to Gemini Vision AI to extract trade data",
        )
        if extract_clicked:
            st.session_state["extract_clicked"] = True

        if st.session_state.get("extract_clicked"):
            try:
                from src.gemini_parser import GeminiScreenshotParser, DependenciesMissingError

                with st.spinner("Calling Gemini Vision... This may take 10-30 seconds."):
                    parser = GeminiScreenshotParser(api_key=gemini_key)
                    image_bytes_list = [f.read() for f in uploaded_files]
                    result = parser.parse_screenshots(image_bytes_list)

                positions = result.get("positions", [])
                strategy_cards = result.get("strategy_cards", [])
                contract_note = result.get("contract_note", {})

                if positions:
                    staging_df = pd.DataFrame(positions) if pd is not None else None
                elif strategy_cards:
                    staging_df = pd.DataFrame(strategy_cards) if pd is not None else None
                else:
                    staging_df = pd.DataFrame() if pd is not None else None

                st.session_state["staging_data"] = staging_df
                st.session_state["gemini_result"] = result

                if staging_df is not None and not staging_df.empty:
                    st.success(
                        f"✅ Extracted {len(staging_df)} rows from {len(uploaded_files)} screenshot(s). "
                        "Review and edit below before running the pipeline."
                    )
                else:
                    st.warning(
                        "Gemini processed the screenshots but found no position or strategy card rows. "
                        "Try manual CSV upload or check the screenshot quality."
                    )
                    _show_manual_csv_fallback()

                # Reset flag so button can be clicked again if needed
                st.session_state["extract_clicked"] = False

            except Exception as exc:
                st.error(f"OCR failed: {exc}")
                with st.expander("Traceback"):
                    st.code(traceback.format_exc())
                _show_manual_csv_fallback()
    else:
        st.caption("Upload screenshots above, then click **Extract Data from Screenshots**.")

    # ── Staging Review ────────────────────────────────────────────
    st.subheader("2. Staging Review")
    st.markdown(
        '<div class="kpi-card" style="border-left:3px solid #F59E0B;margin-bottom:1rem;">'
        "<b>5-second manual verification of Capital Deployed &amp; Strategy Names recommended</b>"
        "</div>",
        unsafe_allow_html=True,
    )

    if "staging_data" in st.session_state and pd is not None:
        edited_df = st.data_editor(
            st.session_state["staging_data"],
            use_container_width=True,
            num_rows="dynamic",
            key="staging_editor",
        )
        st.session_state["staging_data"] = edited_df
    else:
        st.caption("No staging data loaded yet. Upload screenshots above to begin.")

    # ── Pipeline Execution ────────────────────────────────────────
    st.subheader("3. Approve & Run Pipeline")
    col_approve, col_status = st.columns([1, 3])
    with col_approve:
        run_pipeline = st.button("Approve & Run Pipeline", type="primary", key="btn_approve")
    with col_status:
        if run_pipeline:
            staging_df = st.session_state.get("staging_data")
            if staging_df is None or (pd is not None and staging_df.empty):
                st.warning("No staging data to process. Upload screenshots or a CSV first.")
            else:
                gemini_result = st.session_state.get("gemini_result", {})
                _run_real_pipeline(staging_df, gemini_result=gemini_result)

    # ── Results Tabs ──────────────────────────────────────────────
    pipeline_result = st.session_state.get("pipeline_result")
    if pipeline_result is not None:
        st.subheader("4. Results")
        tab_summary, tab_strategy, tab_analytics, tab_trades, tab_recon = st.tabs(
            ["Summary", "Strategy Cards", "Analytics", "Trade Log", "Reconciliation"]
        )

        daily_summary = getattr(pipeline_result, "daily_summary_df", None)
        strategy_runs_df = getattr(pipeline_result, "strategy_runs_df", None)
        charges_df = getattr(pipeline_result, "charges_df", None)

        with tab_summary:
            _render_summary_tab(daily_summary)

        with tab_strategy:
            _render_strategy_tab(strategy_runs_df)

        with tab_analytics:
            _render_analytics_tab(strategy_runs_df)

        with tab_trades:
            _render_trades_tab(pipeline_result)

        with tab_recon:
            _render_recon_tab(charges_df)

        # ── Export Buttons ────────────────────────────────────────
        st.subheader("5. Export")
        exp_cols = st.columns(4)
        with exp_cols[0]:
            st.button("Save to DB", key="btn_save_db")
        with exp_cols[1]:
            st.button("Download PDF", key="btn_pdf")
        with exp_cols[2]:
            st.button("Download Excel", key="btn_excel")
        with exp_cols[3]:
            st.button("Download CSVs", key="btn_csvs")


# ---------------------------------------------------------------------------
# Real pipeline runner
# ---------------------------------------------------------------------------

def _run_real_pipeline(staging_df, gemini_result: dict | None = None) -> None:
    """Instantiate orchestrator, run pipeline, store result in session_state."""
    import os
    from datetime import date
    if gemini_result is None:
        gemini_result = {}
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    # Resolve credentials (Streamlit secrets > env vars)
    def _secret(key: str, default: str = "") -> str:
        try:
            val = st.secrets.get(key, "")
            if val:
                return val
        except Exception:
            pass
        return os.environ.get(key, default)

    gemini_key = _secret("GEMINI_API_KEY")
    dhan_client_id = _secret("DHAN_CLIENT_ID")
    dhan_access_token = _secret("DHAN_ACCESS_TOKEN")

    report_date = st.session_state.get("report_date", date.today())

    stage_labels = [
        "Stage 1: Source Ingestion",
        "Stage 2: OCR / Gemini Parse",
        "Stage 3: Staging Validation",
        "Stage 4: Symbol Parsing",
        "Stage 5: Trade Matching",
        "Stage 6: Cost Calculation",
        "Stage 7: Strategy Aggregation",
        "Stage 8: Persist (SQLite + Supabase)",
        "Stage 9: Equity Curve Rebuild",
    ]
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        from src.db.engine import init_db
        from src.pnl_pipeline import DailyPipelineOrchestrator

        status_text.text("Initialising database...")
        engine, SessionLocal = init_db("data/quant_desk.db")

        orchestrator = DailyPipelineOrchestrator(
            db_engine=engine,
            session_factory=SessionLocal,
            gemini_api_key=gemini_key,
            dhan_client_id=dhan_client_id,
            dhan_access_token=dhan_access_token,
        )

        status_text.text("Running pipeline…")
        # The orchestrator's run_entire_pipeline handles all stages internally.
        # We simulate per-stage progress by running each stage explicitly here.
        import pandas as _pd

        # ── Stage 1 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 0)
        s1 = orchestrator.stage_1_ingest_sources(manual_csv_df=staging_df)

        # ── Stage 2 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 1)
        raw_sources = s1.dataframes.get("raw_sources_df", _pd.DataFrame())
        s2 = orchestrator.stage_2_gemini_multimodal_parse(raw_sources)

        # ── Stage 3 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 2)
        s3 = orchestrator.stage_3_review_staging(s2, operator_edits_df=staging_df, operator_approve_flag=True)

        # ── Stage 4 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 3)
        s4 = orchestrator.stage_4_classify_symbols(s3.dataframes)

        # ── Stage 5 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 4)
        trade_exec_df = s4.dataframes.get("trade_executions_df", _pd.DataFrame())
        s5 = orchestrator.stage_5_fifo_match(trade_exec_df)

        # ── Stage 6 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 5)
        matched_df = s5.dataframes.get("matched_df", _pd.DataFrame())
        strategies_df = s3.dataframes.get("strategy_cards_df", _pd.DataFrame())
        cn_charges = s2.dataframes.get("contract_note_charges")
        if cn_charges is None:
            cn_charges = gemini_result.get("contract_note")
        s6 = orchestrator.stage_6_compute_charges(matched_df, strategies_df, contract_note_charges=cn_charges)

        # ── Stage 7 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 6)
        charges_df = s6.dataframes.get("charges_df", _pd.DataFrame())
        s7 = orchestrator.stage_7_compute_summary(strategies_df, matched_df, charges_df)

        # ── Stage 8 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 7)
        strategy_runs_df = s7.dataframes.get("strategy_runs_df")
        daily_summary_dict = s7.dataframes.get("daily_summary_dict")
        tables = {
            "strategy_runs_df": strategy_runs_df,
            "daily_summary_dict": daily_summary_dict,
            "charges_df": charges_df,
            "matched_trades_df": matched_df,
        }
        s8 = orchestrator.stage_8_persist_sqlite(SessionLocal or engine, tables, report_date)

        # ── Stage 9 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 8)
        s9 = orchestrator.stage_9_rebuild_equity_curve(SessionLocal or engine, report_date)

        progress_bar.progress(1.0)

        # Build PipelineResult
        from src.pnl_pipeline import PipelineResult
        result = PipelineResult(
            per_stage=[s1, s2, s3, s4, s5, s6, s7, s8, s9],
            strategy_runs_df=strategy_runs_df,
            charges_df=charges_df,
            daily_summary_df=daily_summary_dict,
        )
        result.all_passed = all(s.status in ("SUCCESS", "WARNING") for s in result.per_stage)
        result.report_ready = result.all_passed

        st.session_state["pipeline_result"] = result
        st.session_state["pipeline_complete"] = True

        failed = [s for s in result.per_stage if s.status == "FAIL"]
        if failed:
            status_text.warning(f"Pipeline completed with failures in: {[s.stage_name for s in failed]}")
        else:
            status_text.success("Pipeline completed successfully!")

        st.rerun()

    except Exception as exc:
        import traceback
        status_text.error(f"Pipeline error: {exc}")
        with st.expander("Traceback"):
            st.code(traceback.format_exc())


def _update_progress(progress_bar, status_text, labels: list, idx: int) -> None:
    progress_bar.progress((idx + 1) / len(labels))
    status_text.text(f"Running {labels[idx]}…")


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def _render_summary_tab(daily_summary) -> None:
    if daily_summary is None:
        st.caption("No summary data available.")
        return

    if isinstance(daily_summary, dict):
        d = daily_summary
    else:
        st.caption("No summary data available.")
        return

    cols = st.columns(3)
    kpi_items = [
        ("Total Net P&L", d.get("total_net_pnl", 0), "₹"),
        ("Net ROI", d.get("portfolio_day_roi_pct", d.get("net_roi_pct", 0)), "%"),
        ("Win Count", d.get("win_count", 0), ""),
        ("Loss Count", d.get("loss_count", 0), ""),
        ("Capital Deployed", d.get("peak_capital_deployed", d.get("total_capital_deployed_peak", 0)), "₹"),
        ("Total Charges", d.get("total_allocated_charges", d.get("total_transaction_cost_drag", 0)), "₹"),
    ]
    for i, (label, value, prefix) in enumerate(kpi_items):
        with cols[i % 3]:
            if isinstance(value, float):
                display = f"{prefix}{value:,.2f}" if prefix == "₹" else f"{value:.2f}{prefix}"
            else:
                display = f"{value}"
            st.metric(label=label, value=display)


def _render_strategy_tab(strategy_runs_df) -> None:
    if strategy_runs_df is None or strategy_runs_df.empty:
        st.caption("No strategy data available.")
        return

    for _, row in strategy_runs_df.iterrows():
        net_pnl = float(row.get("net_pnl", 0))
        color = "#10B981" if net_pnl >= 0 else "#EF4444"
        strategy_name = str(row.get("strategy_name", "Unknown"))
        gross_pnl = float(row.get("booked_gross_pnl", 0))
        charges = float(row.get("allocated_charges_total", 0))
        roi = row.get("net_roi_pct")
        roi_str = f"{float(roi):.2f}%" if roi is not None else "N/A"
        segment = str(row.get("underlying_segment", ""))

        st.markdown(
            f"""<div class="kpi-card" style="border-left:4px solid {color};margin-bottom:1rem;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <b style="font-size:1.05rem;">{strategy_name}</b>
                    {"&nbsp;<span style='color:#94A3B8;font-size:0.8rem;'>" + segment + "</span>" if segment else ""}
                </div>
                <div style="text-align:right;">
                    <span style="color:{color};font-size:1.2rem;font-weight:700;">₹{net_pnl:,.2f}</span>
                    <br><span style="color:#94A3B8;font-size:0.8rem;">Net P&L ({roi_str})</span>
                </div>
            </div>
            <div style="margin-top:0.5rem;display:flex;gap:2rem;">
                <span style="color:#94A3B8;font-size:0.82rem;">Gross: <b style="color:#E2E8F0;">₹{gross_pnl:,.2f}</b></span>
                <span style="color:#94A3B8;font-size:0.82rem;">Charges: <b style="color:#F59E0B;">₹{charges:,.2f}</b></span>
            </div>
            </div>""",
            unsafe_allow_html=True,
        )


def _render_analytics_tab(strategy_runs_df) -> None:
    if strategy_runs_df is None or strategy_runs_df.empty:
        st.caption("No analytics data available.")
        return

    try:
        from src.chart_builder import PlotlyThemedCharts
        charts = PlotlyThemedCharts()

        # Segment donut
        if "underlying_segment" in strategy_runs_df.columns and "net_pnl" in strategy_runs_df.columns:
            seg_data = (
                strategy_runs_df.groupby("underlying_segment")["net_pnl"]
                .sum()
                .to_dict()
            )
            if seg_data:
                fig_donut = charts.segment_pnl_donut(seg_data)
                st.plotly_chart(fig_donut, use_container_width=True)

        # Gross vs Net bars
        if all(c in strategy_runs_df.columns for c in ["underlying_segment", "booked_gross_pnl", "net_pnl"]):
            seg_bar_data = (
                strategy_runs_df.groupby("underlying_segment", as_index=False)
                .agg({"booked_gross_pnl": "sum", "net_pnl": "sum"})
                .rename(columns={"underlying_segment": "segment", "booked_gross_pnl": "gross_pnl"})
                .to_dict("records")
            )
            if seg_bar_data:
                fig_bars = charts.gross_vs_net_bars(seg_bar_data)
                st.plotly_chart(fig_bars, use_container_width=True)

    except Exception as chart_exc:
        st.caption(f"Charts unavailable: {chart_exc}")


def _render_trades_tab(pipeline_result) -> None:
    import pandas as _pd
    # Look for matched trades in per_stage results
    matched_df = None
    for stage in getattr(pipeline_result, "per_stage", []):
        if "matched_df" in stage.dataframes and not stage.dataframes["matched_df"].empty:
            matched_df = stage.dataframes["matched_df"]
            break

    if matched_df is None or matched_df.empty:
        st.caption("No matched trade data available.")
        return

    st.dataframe(matched_df, use_container_width=True)


def _render_recon_tab(charges_df) -> None:
    if charges_df is None or charges_df.empty:
        st.caption("No charges/reconciliation data available.")
        return

    st.dataframe(charges_df, use_container_width=True)
