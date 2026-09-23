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

    # ── Mode Toggle ───────────────────────────────────────────────
    st.divider()
    mode = st.radio(
        "Select Ingestion Mode",
        ["✍️ Manual Trade Entry", "📸 Screenshot Upload"],
        horizontal=True,
        key="ingestion_mode",
    )
    st.divider()

    # ── Gemini key helper (used only in Screenshot mode) ──────────
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
                st.dataframe(staging_df, width="stretch")
            except Exception as exc:
                st.error(f"Error reading CSV: {exc}")
        st.download_button(
            "Download CSV Template",
            data="report_date,strategy_name,segment,symbol,side,lots,lot_size,quantity,execution_price,option_type\n",
            file_name="staging_template.csv",
            mime="text/csv",
        )

    # =================================================================
    # MODE A: MANUAL TRADE ENTRY (zero API dependency)
    # =================================================================
    if mode == "✍️ Manual Trade Entry":
        st.subheader("1. Strategy Card Details")

        _LOT_MAP = {"SENSEX": 20, "BANKNIFTY": 15, "NIFTY": 25, "FINNIFTY": 25, "MIDCPNIFTY": 50}

        with st.expander("📋 Strategy Card (Capital, Multiplier, Broker)", expanded=True):
            sc_name = st.text_input(
                "Strategy Name",
                value="SENSEX BFO Dynamic Inside-Day Short Strangle v1",
                key="sc_name",
            )
            col1, col2, col3 = st.columns(3)
            with col1:
                sc_capital = st.number_input(
                    "Capital Deployed (₹)", min_value=0.0, value=300000.0, step=10000.0, key="sc_capital",
                )
            with col2:
                sc_multiplier = st.selectbox("Multiplier", [1, 2, 3, 4, 5], index=0, key="sc_multiplier")
            with col3:
                sc_status = st.selectbox("Status", ["Exited", "LIVE AUTO", "Paused"], key="sc_status")
            sc_broker = st.selectbox("Broker", ["Zerodha", "Dhan", "Upstox"], key="sc_broker")

        st.subheader("2. Underlying & Segment")
        col_seg, col_exch, col_lot = st.columns(3)
        with col_seg:
            segment = st.selectbox(
                "Underlying",
                ["SENSEX", "BANKNIFTY", "NIFTY", "FINNIFTY", "MIDCPNIFTY"],
                key="me_segment",
            )
        with col_exch:
            exchange = "BSE" if segment == "SENSEX" else "NSE"
            st.text_input("Exchange (auto)", value=exchange, disabled=True, key="me_exchange_display")
        with col_lot:
            lot_size = _LOT_MAP.get(segment, 20)
            st.text_input("Lot Size (auto)", value=str(lot_size), disabled=True, key="me_lotsize_display")

        st.subheader("3. Execution Legs")
        st.caption(
            "Edit the table below. Add/remove rows as needed. "
            "Tip: For a standard short strangle, you need 4 rows — PE Entry, PE Exit, CE Entry, CE Exit."
        )

        # Build default 4-leg template for a short strangle
        _date_str = str(report_date)
        _sym_date = report_date.strftime("%d%b%Y").upper()
        _qty = lot_size * sc_multiplier

        _default_legs = pd.DataFrame([
            {
                "vendor_symbol": f"OPTIDX_{segment}_{_sym_date}_PE_00000",
                "trade_date": _date_str,
                "execution_time": "09:30:00",
                "condition": "Entry",
                "side": "SELL",
                "quantity": _qty,
                "price": 0.0,
                "amount": 0.0,
                "exchange": exchange,
                "segment": segment,
            },
            {
                "vendor_symbol": f"OPTIDX_{segment}_{_sym_date}_PE_00000",
                "trade_date": _date_str,
                "execution_time": "15:20:00",
                "condition": "Universal Exit",
                "side": "BUY",
                "quantity": _qty,
                "price": 0.0,
                "amount": 0.0,
                "exchange": exchange,
                "segment": segment,
            },
            {
                "vendor_symbol": f"OPTIDX_{segment}_{_sym_date}_CE_00000",
                "trade_date": _date_str,
                "execution_time": "09:30:00",
                "condition": "Entry",
                "side": "SELL",
                "quantity": _qty,
                "price": 0.0,
                "amount": 0.0,
                "exchange": exchange,
                "segment": segment,
            },
            {
                "vendor_symbol": f"OPTIDX_{segment}_{_sym_date}_CE_00000",
                "trade_date": _date_str,
                "execution_time": "15:20:00",
                "condition": "Universal Exit",
                "side": "BUY",
                "quantity": _qty,
                "price": 0.0,
                "amount": 0.0,
                "exchange": exchange,
                "segment": segment,
            },
        ]) if pd is not None else None

        # Use session state to persist edits across reruns
        _init_key = f"manual_entry_legs_{segment}_{sc_multiplier}"
        if _init_key not in st.session_state or st.session_state.get("me_last_key") != _init_key:
            st.session_state["manual_entry_legs"] = _default_legs
            st.session_state["me_last_key"] = _init_key

        edited_legs = st.data_editor(
            st.session_state.get("manual_entry_legs", _default_legs),
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "side": st.column_config.SelectboxColumn("Side", options=["BUY", "SELL"]),
                "condition": st.column_config.SelectboxColumn(
                    "Condition", options=["Entry", "Universal Exit", "SL Hit", "Target Hit"]
                ),
                "exchange": st.column_config.SelectboxColumn("Exchange", options=["NSE", "BSE"]),
                "segment": st.column_config.SelectboxColumn(
                    "Segment", options=["SENSEX", "BANKNIFTY", "NIFTY", "FINNIFTY", "MIDCPNIFTY"]
                ),
                "price": st.column_config.NumberColumn("Price (₹)", format="₹%.2f"),
                "amount": st.column_config.NumberColumn("Amount (₹)", format="₹%.2f"),
                "quantity": st.column_config.NumberColumn("Qty", format="%d"),
            },
            key="manual_legs_editor",
        )
        st.session_state["manual_entry_legs"] = edited_legs

        # Optional: Contract Note Charges
        with st.expander("📄 Contract Note Charges (optional — leave blank for FORMULA mode)"):
            st.caption("If you have exact charges from your broker contract note, enter them here (REALIZED mode). Otherwise leave blank and the Zerodha formula will be used.")
            col_b, col_stt, col_gst = st.columns(3)
            with col_b:
                cn_brokerage = st.number_input("Brokerage (₹)", value=0.0, min_value=0.0, step=1.0, key="cn_brokerage")
            with col_stt:
                cn_stt = st.number_input("STT (₹)", value=0.0, min_value=0.0, step=0.01, key="cn_stt")
            with col_gst:
                cn_gst = st.number_input("GST (₹)", value=0.0, min_value=0.0, step=0.01, key="cn_gst")
            col_ef, col_sebi, col_stamp = st.columns(3)
            with col_ef:
                cn_exch_fee = st.number_input("Exchange Fee (₹)", value=0.0, min_value=0.0, step=0.01, key="cn_exch_fee")
            with col_sebi:
                cn_sebi = st.number_input("SEBI Charges (₹)", value=0.0, min_value=0.0, step=0.01, key="cn_sebi")
            with col_stamp:
                cn_stamp = st.number_input("Stamp Duty (₹)", value=0.0, min_value=0.0, step=0.01, key="cn_stamp")
            cn_total = cn_brokerage + cn_stt + cn_gst + cn_exch_fee + cn_sebi + cn_stamp
            if cn_total > 0:
                st.metric("Total Realized Charges", f"₹{cn_total:,.2f}")
                st.session_state["contract_note_extracted"] = {
                    "brokerage_amount": cn_brokerage,
                    "securities_transaction_tax_stt": cn_stt,
                    "gst": cn_gst,
                    "exchange_turnover_fee_amount": cn_exch_fee,
                    "sebi_turnover_charges": cn_sebi,
                    "stamp_duty": cn_stamp,
                    "total_charges_grand_total": cn_total,
                }
            else:
                # Clear any previously stored contract note so FORMULA mode is used
                st.session_state.pop("contract_note_extracted", None)

        # Load into Staging button
        if st.button("✅ Load into Staging", type="primary", key="btn_load_manual"):
            if edited_legs is not None and len(edited_legs) > 0:
                st.session_state["staging_data"] = edited_legs.copy()
                strategy_card = {
                    "strategy_name": sc_name,
                    "capital_deployed_allocated": sc_capital,
                    "multiplier_x": sc_multiplier,
                    "deployment_status": sc_status,
                    "broker": sc_broker,
                    "booked_gross_pnl": 0.0,
                    "card_roi_pct": 0.0,
                }
                st.session_state["strategy_cards_extracted"] = [strategy_card]
                st.session_state["gemini_result"] = {}
                st.success(
                    f"✅ {len(edited_legs)} execution rows loaded into staging. "
                    "Scroll down to review, then click **Approve & Run Pipeline**."
                )
            else:
                st.warning("No rows to load. Please add at least one execution leg above.")

    # =================================================================
    # MODE B: SCREENSHOT UPLOAD (Gemini Vision)
    # =================================================================
    elif mode == "📸 Screenshot Upload":
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
        else:
            uploaded_files = []

        if not gemini_key:
            st.warning(
                "⚠️ Gemini API key not configured. Switch to **✍️ Manual Trade Entry** mode above, "
                "or set GEMINI_API_KEY in Settings."
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
                    from src.gemini_parser import (
                        GeminiScreenshotParser,
                        DependenciesMissingError,
                        GeminiAuthError,
                    )

                    with st.spinner("Calling Gemini Vision... This may take 10-30 seconds."):
                        parser = GeminiScreenshotParser(api_key=gemini_key)
                        filenames = [f.name for f in uploaded_files]
                        image_bytes_list = [f.read() for f in uploaded_files]
                        result = parser.parse_screenshots(image_bytes_list, filenames=filenames)

                    executions = result.get("executions", [])
                    positions = result.get("positions", [])
                    strategy_cards = result.get("strategy_cards", [])
                    contract_note = result.get("contract_note", {})

                    # Priority: Tradetron executions > Kite positions > strategy cards
                    if executions:
                        staging_df = pd.DataFrame(executions) if pd is not None else None
                    elif positions:
                        staging_df = pd.DataFrame(positions) if pd is not None else None
                    elif strategy_cards:
                        staging_df = pd.DataFrame(strategy_cards) if pd is not None else None
                    else:
                        staging_df = pd.DataFrame() if pd is not None else None

                    st.session_state["staging_data"] = staging_df
                    st.session_state["gemini_result"] = result
                    st.session_state["strategy_cards_extracted"] = strategy_cards
                    st.session_state["contract_note_extracted"] = contract_note

                    with st.expander("🔍 Debug: Raw Gemini Output", expanded=False):
                        st.json(result)
                        st.caption(
                            f"Executions: {len(executions)} | "
                            f"Kite positions: {len(positions)} | "
                            f"Strategy cards: {len(strategy_cards)}"
                        )

                    # Show strategy card info box when cards were found
                    if strategy_cards:
                        st.info("**Strategy Cards Detected:**")
                        for sc in strategy_cards:
                            name = sc.get("strategy_name", "Unknown Strategy")
                            capital = sc.get("capital_deployed_allocated", 0)
                            multiplier = sc.get("multiplier_x", 1)
                            status = sc.get("deployment_status", "")
                            pnl = sc.get("booked_gross_pnl", 0)
                            roi = sc.get("card_roi_pct", 0)
                            capital_l = f"₹{capital/100000:.2f}L" if capital else "N/A"
                            pnl_str = f"₹{pnl:+,.0f}" if pnl else "N/A"
                            st.markdown(
                                f"**{name}** | {multiplier}x | Capital: {capital_l} | "
                                f"Status: {status} | Booked P&L: {pnl_str} ({roi:+.2f}%)"
                            )

                    if staging_df is not None and not staging_df.empty:
                        total_rows = len(staging_df)
                        source = "execution" if executions else ("position" if positions else "strategy card")
                        st.success(
                            f"✅ Extracted {total_rows} {source} row(s) from {len(uploaded_files)} screenshot(s). "
                            "Review and edit below before running the pipeline."
                        )
                    else:
                        st.warning(
                            "Gemini processed the screenshots but found no position or strategy card rows. "
                            "Switch to Manual Trade Entry mode or check screenshot quality."
                        )
                        _show_manual_csv_fallback()

                    # Reset flag so button can be clicked again if needed
                    st.session_state["extract_clicked"] = False

                except GeminiAuthError as auth_exc:
                    st.error("❌ Gemini API Error - Cannot Extract Data")
                    st.error(auth_exc.user_action)
                    with st.expander("Technical Details"):
                        st.code(f"{auth_exc.error_code}: {auth_exc.original_error}")
                    st.info("💡 **Tip:** Switch to **✍️ Manual Trade Entry** mode above to enter trades without any API.")
                    _show_manual_csv_fallback()
                    st.session_state["extract_clicked"] = False
                except DependenciesMissingError as dep_exc:
                    st.error("❌ Configuration Error")
                    st.error(dep_exc.user_action)
                    _show_manual_csv_fallback()
                    st.session_state["extract_clicked"] = False
                except Exception as exc:
                    st.error(f"❌ Unexpected Error: {exc}")
                    with st.expander("Traceback"):
                        st.code(traceback.format_exc())
                    _show_manual_csv_fallback()
                    st.session_state["extract_clicked"] = False
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
        exp_cols = st.columns(5)
        with exp_cols[0]:
            if st.button("💾 Save to DB", key="btn_save_db", type="primary"):
                _save_to_db(
                    st.session_state.get("pipeline_result"),
                    st.session_state.get("report_date", date.today()),
                )
        with exp_cols[1]:
            # PDF export
            try:
                from src.report_engine import DailyReportGenerator
                pr = st.session_state["pipeline_result"]
                gen = DailyReportGenerator(
                    report_date=st.session_state.get("report_date", date.today()),
                    strategy_runs_df=pr.strategy_runs_df,
                    daily_summary_dict=pr.daily_summary_df,
                    charges_df=pr.charges_df,
                    matched_trades_df=getattr(pr, "matched_trades_df", None),
                )
                pdf_bytes = gen.render_daily_pdf() if hasattr(gen, "render_daily_pdf") else None
                if pdf_bytes:
                    st.download_button("📄 Download PDF", data=pdf_bytes,
                        file_name=f"Quant_Report_{st.session_state.get('report_date', date.today()).isoformat()}.pdf",
                        mime="application/pdf", key="btn_pdf")
                else:
                    st.button("📄 Download PDF", disabled=True, key="btn_pdf_na", help="PDF generation unavailable")
            except Exception:
                st.button("📄 Download PDF", disabled=True, key="btn_pdf_err", help="PDF unavailable")
        with exp_cols[2]:
            # Excel export
            try:
                import io
                pr = st.session_state["pipeline_result"]
                buf = io.BytesIO()
                with __import__("pandas").ExcelWriter(buf, engine="openpyxl") as writer:
                    if pr.strategy_runs_df is not None and not pr.strategy_runs_df.empty:
                        pr.strategy_runs_df.to_excel(writer, sheet_name="Strategy Runs", index=False)
                    if pr.charges_df is not None and not pr.charges_df.empty:
                        pr.charges_df.to_excel(writer, sheet_name="Charges", index=False)
                    if isinstance(pr.daily_summary_df, dict):
                        __import__("pandas").DataFrame([pr.daily_summary_df]).to_excel(writer, sheet_name="Summary", index=False)
                st.download_button("📊 Download Excel", data=buf.getvalue(),
                    file_name=f"Quant_Report_{st.session_state.get('report_date', date.today()).isoformat()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="btn_excel")
            except Exception as exc:
                st.button("📊 Download Excel", disabled=True, key="btn_excel_err", help=f"Excel error: {str(exc)[:80]}")
        with exp_cols[3]:
            # CSV export
            try:
                import io, zipfile
                pr = st.session_state["pipeline_result"]
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    if pr.strategy_runs_df is not None and not pr.strategy_runs_df.empty:
                        zf.writestr("strategy_runs.csv", pr.strategy_runs_df.to_csv(index=False))
                    if pr.charges_df is not None and not pr.charges_df.empty:
                        zf.writestr("charges.csv", pr.charges_df.to_csv(index=False))
                    if isinstance(pr.daily_summary_df, dict):
                        zf.writestr("summary.csv", __import__("pandas").DataFrame([pr.daily_summary_df]).to_csv(index=False))
                st.download_button("📁 Download CSVs", data=zip_buf.getvalue(),
                    file_name=f"Quant_CSVs_{st.session_state.get('report_date', date.today()).isoformat()}.zip",
                    mime="application/zip", key="btn_csvs")
            except Exception as exc:
                st.button("📁 Download CSVs", disabled=True, key="btn_csvs_err", help=f"CSV error: {str(exc)[:80]}")
        with exp_cols[4]:
            # HTML export
            try:
                from src.report_engine import DailyReportGenerator
                pr = st.session_state["pipeline_result"]
                gen = DailyReportGenerator(
                    report_date=st.session_state.get("report_date", date.today()),
                    strategy_runs_df=pr.strategy_runs_df,
                    daily_summary_dict=pr.daily_summary_df,
                    charges_df=pr.charges_df,
                    matched_trades_df=getattr(pr, "matched_trades_df", None),
                )
                html_str = gen.render_daily_html()
                st.download_button("🌐 Download HTML", data=html_str,
                    file_name=f"Quant_Report_{st.session_state.get('report_date', date.today()).isoformat()}.html",
                    mime="text/html", key="btn_html")
            except Exception as e:
                st.warning(f"HTML export unavailable: {str(e)[:100]}")
    else:
        st.info("ℹ️ Load trades into staging above and click **Approve & Run Pipeline** to view results.")


# ---------------------------------------------------------------------------
# DB save helper
# ---------------------------------------------------------------------------

def _save_to_db(pipeline_result, report_date) -> None:
    """Persist today's pipeline result to SQLite + Supabase."""
    if pipeline_result is None:
        st.warning("No pipeline result to save. Run the pipeline first.")
        return
    try:
        from src.db.engine import init_db
        engine, SessionLocal = init_db("data/quant_desk.db")
        from src.pnl_pipeline import DailyPipelineOrchestrator
        orch = DailyPipelineOrchestrator(db_engine=engine, session_factory=SessionLocal)
        tables = {
            "strategy_runs_df": pipeline_result.strategy_runs_df,
            "daily_summary_dict": pipeline_result.daily_summary_df,
            "charges_df": pipeline_result.charges_df,
            "matched_trades_df": getattr(pipeline_result, "matched_trades_df", None),
        }
        s8 = orch.stage_8_persist_sqlite(SessionLocal or engine, tables, report_date)
        if s8.status in ("SUCCESS", "WARNING"):
            st.success(f"✅ Saved to SQLite successfully!")
            # Also try Supabase
            try:
                from src.supabase_store import get_supabase_store
                sb = get_supabase_store()
                if sb.is_connected:
                    strategy_runs = pipeline_result.strategy_runs_df.to_dict("records") if pipeline_result.strategy_runs_df is not None and not pipeline_result.strategy_runs_df.empty else []
                    sb.upsert_daily_batch(
                        report_date=report_date,
                        daily_summary=pipeline_result.daily_summary_df if isinstance(pipeline_result.daily_summary_df, dict) else None,
                        strategy_runs=strategy_runs,
                        charges=pipeline_result.charges_df.to_dict("records") if pipeline_result.charges_df is not None and not pipeline_result.charges_df.empty else [],
                    )
                    st.success("☁️ Saved to Supabase successfully!")
                else:
                    st.info("Supabase not connected — data saved to SQLite only.")
            except Exception as sb_exc:
                st.warning(f"Supabase save failed (SQLite save succeeded): {sb_exc}")
        else:
            st.error(f"❌ Save failed: {s8.errors}")
    except Exception as exc:
        import traceback
        st.error(f"❌ Save to DB failed: {exc}")
        with st.expander("Traceback"):
            st.code(traceback.format_exc())


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

        # Inject strategy cards extracted by Gemini into stage_3 dataframes
        # so stage_6 and stage_7 can compute capital-deployed ROI
        _sc_extracted = st.session_state.get("strategy_cards_extracted", [])
        if _sc_extracted and "strategy_cards_df" not in s3.dataframes:
            import pandas as _pd2
            s3.dataframes["strategy_cards_df"] = _pd2.DataFrame(_sc_extracted)

        # PATCH 1A: In manual mode, staging_df IS the trade_executions_df.
        # Stage_3 only merges Gemini-parsed strategy_cards; it never sets trade_executions_df.
        # We inject it directly so stage_4 and stage_5 see the real rows.
        if "trade_executions_df" not in s3.dataframes or s3.dataframes["trade_executions_df"].empty:
            s3.dataframes["trade_executions_df"] = staging_df.copy()

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

        # PATCH 1B: Ensure strategies_df has at least one valid row with strategy_run_id.
        # In manual mode, strategy_cards_df may be empty or missing the run_id key.
        if strategies_df is None or strategies_df.empty:
            _sc_list = st.session_state.get("strategy_cards_extracted", [])
            if _sc_list:
                strategies_df = _pd.DataFrame(_sc_list)
            else:
                strategies_df = _pd.DataFrame([{
                    "strategy_name": st.session_state.get("sc_name", "Manual Strategy"),
                    "capital_deployed_allocated": st.session_state.get("sc_capital", 0.0),
                    "multiplier_x": st.session_state.get("sc_multiplier", 1),
                    "deployment_status": "Exited",
                    "broker": st.session_state.get("sc_broker", "Zerodha"),
                }])
        # Assign strategy_run_id=0 if missing (matches default in TradeMatcher)
        if "strategy_run_id" not in strategies_df.columns:
            strategies_df = strategies_df.copy()
            strategies_df["strategy_run_id"] = 0

        s7 = orchestrator.stage_7_compute_summary(strategies_df, matched_df, charges_df)

        # ── Stage 8 ──────────────────────────────────────────────
        _update_progress(progress_bar, status_text, stage_labels, 7)
        strategy_runs_df = s7.dataframes.get("strategy_runs_df")
        daily_summary_dict = s7.dataframes.get("daily_summary_dict")

        # Fallback: if stage_7 failed or returned empty dict, compute directly from matched_df
        if not daily_summary_dict or not isinstance(daily_summary_dict, dict):
            _gross = float(matched_df["gross_pnl"].sum()) if not matched_df.empty and "gross_pnl" in matched_df.columns else 0.0
            _chrgs = float(charges_df["total_charges"].sum()) if not charges_df.empty and "total_charges" in charges_df.columns else 0.0
            _net = _gross - _chrgs
            _cap = float(strategies_df["capital_deployed_allocated"].iloc[0]) if not strategies_df.empty and "capital_deployed_allocated" in strategies_df.columns else 0.0
            daily_summary_dict = {
                "total_gross_pnl": _gross,
                "total_allocated_charges": _chrgs,
                "total_net_pnl": _net,
                "peak_capital_deployed": _cap,
                "portfolio_day_roi_pct": (_net / _cap * 100.0) if _cap > 0 else 0.0,
                "win_count": int((matched_df["gross_pnl"] > 0).sum()) if not matched_df.empty and "gross_pnl" in matched_df.columns else 0,
                "loss_count": int((matched_df["gross_pnl"] < 0).sum()) if not matched_df.empty and "gross_pnl" in matched_df.columns else 0,
                "flat_count": 0,
            }
        # Fallback: if strategy_runs_df is missing/empty, build minimal version
        if strategy_runs_df is None or (hasattr(strategy_runs_df, "empty") and strategy_runs_df.empty):
            import pandas as _pd3
            strategy_runs_df = _pd3.DataFrame([{
                "strategy_name": strategies_df["strategy_name"].iloc[0] if not strategies_df.empty and "strategy_name" in strategies_df.columns else "Manual Strategy",
                "booked_gross_pnl": daily_summary_dict.get("total_gross_pnl", 0.0),
                "allocated_charges_total": daily_summary_dict.get("total_allocated_charges", 0.0),
                "net_pnl": daily_summary_dict.get("total_net_pnl", 0.0),
                "net_roi_pct": daily_summary_dict.get("portfolio_day_roi_pct", 0.0),
                "capital_deployed_allocated": daily_summary_dict.get("peak_capital_deployed", 0.0),
                "strategy_run_id": 0,
            }])
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

        # Populate audit session_state
        open_legs_df = None
        for _s in result.per_stage:
            if "open_legs_df" in _s.dataframes:
                open_legs_df = _s.dataframes["open_legs_df"]
                break
        if open_legs_df is not None and not open_legs_df.empty:
            st.session_state["orphan_legs"] = open_legs_df.to_dict("records")
        # Store matched_trades_df on result for export
        for _s in result.per_stage:
            if "matched_df" in _s.dataframes and not _s.dataframes["matched_df"].empty:
                result.matched_trades_df = _s.dataframes["matched_df"]
                break
        # Stage timings for audit
        st.session_state["pipeline_timings"] = [
            {"stage": s.stage_name, "status": s.status, "elapsed_ms": round(s.elapsed_ms, 1)}
            for s in result.per_stage
        ]

        failed = [s for s in result.per_stage if s.status == "FAIL"]
        if failed:
            status_text.warning(f"Pipeline completed with failures in: {[s.stage_name for s in failed]}")
            # Display error banner
            st.error(f"⚠️ **Pipeline Failed** — {len(failed)} stage(s) failed. Check details below:")
            for stage in failed:
                with st.expander(f"📍 {stage.stage_name} — {stage.error_message or 'Unknown error'}"):
                    if stage.errors:
                        for err in stage.errors:
                            st.code(str(err))
        else:
            status_text.success("Pipeline completed successfully!")

        st.rerun()

    except Exception as exc:
        import traceback as _tb
        status_text.error(f"Pipeline error: {exc}")
        st.error(f"❌ **Pipeline Execution Crashed**: {exc}")
        with st.expander("Full Traceback — click to expand"):
            st.code(_tb.format_exc())


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

    st.dataframe(matched_df, width="stretch")


def _render_recon_tab(charges_df) -> None:
    if charges_df is None or charges_df.empty:
        st.caption("No charges/reconciliation data available.")
        return

    st.dataframe(charges_df, width="stretch")
