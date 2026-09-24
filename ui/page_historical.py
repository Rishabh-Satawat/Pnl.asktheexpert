"""Historical Quant Desk: durable P&L analytics and optional market context."""
from __future__ import annotations

import calendar
import datetime as dt
import io

try:
    import streamlit as st
    import pandas as pd
    import plotly.graph_objects as go
except ImportError:  # pragma: no cover - enables import in lightweight tests
    st = pd = go = None  # type: ignore[assignment]


def _load_sqlite_data(start_date, end_date):
    """Read reporting, strategy and charges tables from the local durable store."""
    try:
        from sqlalchemy import and_
        from src.db.engine import init_db
        from src.db.schema import DailySummary, EquityCurve, StrategyRun, ChargesBreakdown

        _, session_factory = init_db("data/quant_desk.db")
        with session_factory() as session:
            summaries = session.query(DailySummary).filter(and_(
                DailySummary.report_date >= start_date,
                DailySummary.report_date <= end_date,
            )).order_by(DailySummary.report_date).all()
            equity = session.query(EquityCurve).filter(and_(
                EquityCurve.report_date >= start_date,
                EquityCurve.report_date <= end_date,
            )).order_by(EquityCurve.report_date).all()
            runs = session.query(StrategyRun).filter(and_(
                StrategyRun.report_date >= start_date,
                StrategyRun.report_date <= end_date,
            )).order_by(StrategyRun.report_date, StrategyRun.id).all()
            charges = session.query(ChargesBreakdown).filter(and_(
                ChargesBreakdown.report_date >= start_date,
                ChargesBreakdown.report_date <= end_date,
            )).all()

        summary_df = pd.DataFrame([{
            "report_date": row.report_date,
            "total_net_pnl": row.total_net_pnl,
            "total_gross_pnl": row.total_gross_pnl,
            "total_allocated_charges": row.total_transaction_cost_drag,
            "win_count": row.win_count,
            "loss_count": row.loss_count,
            "total_trades_executed": row.total_trades_executed,
            "peak_capital_deployed": row.total_capital_deployed_peak,
        } for row in summaries])
        equity_df = pd.DataFrame([{
            "report_date": row.report_date,
            "cumulative_net_pnl": row.cumulative_net_pnl,
            "drawdown_pct": row.drawdown_pct,
            "peak_equity": row.peak_equity,
        } for row in equity])
        runs_df = pd.DataFrame([{
            "id": row.id, "strategy_run_uuid": row.strategy_run_uuid,
            "report_date": row.report_date, "strategy_name": row.strategy_name,
            "deployment_status": row.deployment_status, "multiplier_x": row.multiplier_x,
            "capital_deployed_allocated": row.capital_deployed_allocated,
            "underlying_segment": row.underlying_segment,
            "booked_gross_pnl": row.booked_gross_pnl,
            "allocated_charges_total": row.allocated_charges_total,
            "net_pnl": row.net_pnl, "net_roi_pct": row.net_roi_pct,
        } for row in runs])
        charges_df = pd.DataFrame([{
            "strategy_run_id": row.strategy_run_id, "report_date": row.report_date,
            "charge_source": row.charge_source, "total_charges": row.total_charges,
        } for row in charges])
        return summary_df, equity_df, runs_df, charges_df, True
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), False


def _load_supabase_data(start_date, end_date):
    """Load all analytics inputs from Supabase when configured."""
    try:
        from src.supabase_store import get_supabase_store
        store = get_supabase_store()
        if not store.is_connected:
            return None
        summaries = store.get_daily_summaries(start_date=start_date, end_date=end_date)
        equity = store.get_equity_curve(start_date=start_date, end_date=end_date)
        runs = store.get_strategy_runs(start_date=start_date, end_date=end_date)
        charges = store.get_charges_breakdown(start_date=start_date, end_date=end_date)
        return tuple(pd.DataFrame(rows or []) for rows in (summaries, equity, runs, charges)) + (True,)
    except Exception:
        return None


def _to_daily_from_runs(runs: pd.DataFrame) -> pd.DataFrame:
    if runs.empty:
        return pd.DataFrame(columns=["report_date", "total_net_pnl", "total_gross_pnl", "total_allocated_charges", "peak_capital_deployed", "run_count"])
    work = runs.copy()
    work["report_date"] = pd.to_datetime(work["report_date"], errors="coerce").dt.date
    for col in ("net_pnl", "booked_gross_pnl", "allocated_charges_total", "capital_deployed_allocated"):
        if col not in work:
            work[col] = 0.0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
    return work.groupby("report_date", as_index=False).agg(
        total_net_pnl=("net_pnl", "sum"),
        total_gross_pnl=("booked_gross_pnl", "sum"),
        total_allocated_charges=("allocated_charges_total", "sum"),
        peak_capital_deployed=("capital_deployed_allocated", "sum"),
        run_count=("strategy_name", "count"),
    )


def _render_calendar(daily: pd.DataFrame, year: int, month: int, base_capital: float) -> None:
    st.subheader("Monthly Trading Calendar")
    st.caption("Green and red cells show recorded trading days. Grey cells mean no saved run for that date.")
    pnl_by_day = {}
    if not daily.empty:
        for _, row in daily.iterrows():
            day = pd.to_datetime(row["report_date"]).date()
            pnl_by_day[day.day] = float(row.get("total_net_pnl", 0) or 0)
    header = st.columns([1, 1, 1, 1, 1, 1.25])
    for col, label in zip(header, ("Mon", "Tue", "Wed", "Thu", "Fri", "Week total")):
        col.markdown(f"**{label}**")
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        cols = st.columns([1, 1, 1, 1, 1, 1.25])
        week_total = 0.0
        for idx, col in enumerate(cols[:5]):
            day_num = week[idx]
            if day_num == 0:
                col.markdown('<div style="height:78px"></div>', unsafe_allow_html=True)
                continue
            if day_num in pnl_by_day:
                pnl = pnl_by_day[day_num]
                roi = pnl / base_capital * 100 if base_capital else 0.0
                week_total += pnl
                background = "rgba(16,185,129,.20)" if pnl >= 0 else "rgba(239,68,68,.20)"
                color = "#10B981" if pnl >= 0 else "#F87171"
                value = f"₹{pnl:,.0f}<br><small>{roi:+.2f}%</small>"
            else:
                background, color, value = "rgba(100,116,139,.12)", "#64748B", "No trades"
            col.markdown(
                f'<div style="height:78px;border-radius:9px;padding:8px;background:{background};color:{color};">'
                f'<b>{day_num}</b><div style="font-size:.8rem;margin-top:7px">{value}</div></div>',
                unsafe_allow_html=True,
            )
        cols[5].markdown(f"<div style='padding:12px 6px;font-weight:700'>₹{week_total:,.0f}</div>", unsafe_allow_html=True)


def _render_benchmark_tools(daily: pd.DataFrame, base_capital: float) -> None:
    with st.expander("Benchmark return history (optional CSV)", expanded=False):
        st.caption("The desk does not currently store historical index closes. Upload verified daily returns to compare real benchmark performance; no index values are estimated.")
        template = "date,nifty_return_pct,banknifty_return_pct\n2026-09-22,0.51,-0.32\n"
        st.download_button("Download benchmark CSV template", template, "benchmark_returns_template.csv", "text/csv", key="hist_benchmark_template")
        upload = st.file_uploader("Upload daily index returns CSV", type=["csv"], key="hist_benchmark_csv")
        if upload is None:
            st.info("Benchmark curves will appear after verified daily return data is uploaded.")
            return
        try:
            benchmark = pd.read_csv(upload)
            required = {"date", "nifty_return_pct", "banknifty_return_pct"}
            if not required.issubset(benchmark.columns):
                st.error("CSV needs date, nifty_return_pct, and banknifty_return_pct columns.")
                return
            benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce").dt.date
            for col in ("nifty_return_pct", "banknifty_return_pct"):
                benchmark[col] = pd.to_numeric(benchmark[col], errors="coerce")
            benchmark = benchmark.dropna(subset=["date"])
            if daily.empty:
                st.info("Add trade history first to compare it with this file.")
                return
            compare = daily.merge(benchmark, left_on="report_date", right_on="date", how="left").sort_values("report_date")
            compare["desk_cumulative_roi_pct"] = compare["total_net_pnl"].cumsum() / base_capital * 100
            for col in ("nifty_return_pct", "banknifty_return_pct"):
                compare[f"{col}_cumulative"] = ((1 + compare[col] / 100).cumprod() - 1) * 100
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=compare["report_date"], y=compare["desk_cumulative_roi_pct"], name="Desk cumulative ROI", line=dict(color="#10B981", width=3)))
            fig.add_trace(go.Scatter(x=compare["report_date"], y=compare["nifty_return_pct_cumulative"], name="NIFTY 50 return", line=dict(color="#64748B", dash="dash"), yaxis="y2"))
            fig.add_trace(go.Scatter(x=compare["report_date"], y=compare["banknifty_return_pct_cumulative"], name="BANK NIFTY return", line=dict(color="#F59E0B", dash="dash"), yaxis="y2"))
            fig.update_layout(template="plotly_dark", height=380, yaxis=dict(title="Desk ROI (%)", ticksuffix="%"), yaxis2=dict(title="Index return (%)", overlaying="y", side="right", ticksuffix="%"), xaxis=dict(tickformat="%d %b %Y"), legend=dict(orientation="h"), margin=dict(t=20, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Desk cumulative ROI uses cumulative net P&L divided by the account base entered above. Benchmark cumulative returns compound the uploaded daily returns.")
        except Exception as exc:
            st.error(f"Could not read benchmark file: {exc}")


def _render_flows_and_regimes(daily: pd.DataFrame) -> None:
    with st.expander("FII / DII cash-flow context (optional CSV)", expanded=False):
        st.caption("FII/DII cash-market flows are context only. They are not a substitute for derivatives positioning or a directional signal.")
        st.download_button(
            "Download flow CSV template",
            "date,fii_cash_net_inr_cr,dii_cash_net_inr_cr\n2026-09-22,1000,-250\n",
            "participant_flows_template.csv", "text/csv", key="hist_flows_template",
        )
        upload = st.file_uploader("Upload verified participant flow data", type=["csv"], key="hist_flows_csv")
        if upload is None:
            st.info("No participant-flow source is configured. Upload an official or otherwise verified data file to display it.")
        else:
            try:
                flows = pd.read_csv(upload)
                required = {"date", "fii_cash_net_inr_cr", "dii_cash_net_inr_cr"}
                if not required.issubset(flows.columns):
                    st.error("CSV needs date, fii_cash_net_inr_cr, and dii_cash_net_inr_cr columns.")
                else:
                    flows["date"] = pd.to_datetime(flows["date"], errors="coerce")
                    fig = go.Figure()
                    fig.add_bar(x=flows["date"], y=pd.to_numeric(flows["fii_cash_net_inr_cr"], errors="coerce"), name="FII cash flow", marker_color="#38BDF8")
                    fig.add_bar(x=flows["date"], y=pd.to_numeric(flows["dii_cash_net_inr_cr"], errors="coerce"), name="DII cash flow", marker_color="#A78BFA")
                    fig.update_layout(template="plotly_dark", barmode="group", height=320, yaxis_title="Net flow (₹ crore)", xaxis=dict(tickformat="%d %b %Y"))
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as exc:
                st.error(f"Could not read participant-flow file: {exc}")

    with st.expander("Market regime review (optional verified context)", expanded=False):
        st.caption("Regime tags are descriptive diagnostics. They are not a trade signal and need enough sessions of verified inputs to be useful.")
        sample = "date,india_vix_change_pct,cpr_width_pct,index_intraday_range_pct\n2026-09-22,8.5,0.32,0.74\n"
        st.download_button("Download regime CSV template", sample, "regime_context_template.csv", "text/csv", key="hist_regime_template")
        upload = st.file_uploader("Upload daily VIX / CPR / range context", type=["csv"], key="hist_regime_csv")
        if upload is None:
            st.info("No IV, CPR, or index range history is stored in the project yet.")
            return
        try:
            context = pd.read_csv(upload)
            required = {"date", "india_vix_change_pct", "cpr_width_pct", "index_intraday_range_pct"}
            if not required.issubset(context.columns):
                st.error("CSV needs date, india_vix_change_pct, cpr_width_pct, and index_intraday_range_pct columns.")
                return
            context["date"] = pd.to_datetime(context["date"], errors="coerce").dt.date
            for col in required - {"date"}:
                context[col] = pd.to_numeric(context[col], errors="coerce")
            context = context.dropna(subset=list(required))
            if len(context) < 10:
                st.warning("At least 10 valid sessions are required before percentile-based regime tags are shown.")
                return
            narrow = context["cpr_width_pct"].quantile(.25)
            wide = context["cpr_width_pct"].quantile(.75)
            range_median = context["index_intraday_range_pct"].median()

            def classify(row):
                if row["india_vix_change_pct"] >= 10:
                    return "High IV expansion"
                if row["cpr_width_pct"] <= narrow and row["index_intraday_range_pct"] <= range_median:
                    return "Narrow CPR / range candidate"
                if row["cpr_width_pct"] >= wide and row["index_intraday_range_pct"] >= range_median:
                    return "Wide CPR / trend candidate"
                return "Mixed / normal"

            context["regime"] = context.apply(classify, axis=1)
            if not daily.empty:
                pnl_context = daily.copy()
                pnl_context["report_date"] = pd.to_datetime(pnl_context["report_date"], errors="coerce").dt.date
                joined = pnl_context.merge(context[["date", "regime"]], left_on="report_date", right_on="date", how="inner")
                if not joined.empty:
                    summary = joined.groupby("regime", as_index=False).agg(
                        sessions=("total_net_pnl", "count"), mean_net_pnl=("total_net_pnl", "mean"), total_net_pnl=("total_net_pnl", "sum"),
                    )
                    st.dataframe(summary, use_container_width=True, hide_index=True)
                else:
                    st.info("Uploaded regime context does not overlap the selected trading history.")
            st.dataframe(context[["date", "regime", "india_vix_change_pct", "cpr_width_pct", "index_intraday_range_pct"]], use_container_width=True, hide_index=True)
            st.caption("Thresholds: VIX expansion >= +10%; narrow/wide CPR are upload-sample 25th/75th percentiles; range state uses the upload-sample median.")
        except Exception as exc:
            st.error(f"Could not read regime context file: {exc}")


def render_historical_dashboard() -> None:
    if st is None or pd is None or go is None:
        return
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("Historical Quant Desk")
    today = dt.date.today()
    choices = {"7D": 7, "30D": 30, "90D": 90, "YTD": None, "All": "all", "Custom": "custom"}
    range_name = st.selectbox("Reporting period", list(choices), index=1, key="hist_range")
    if range_name == "Custom":
        left, right = st.columns(2)
        with left:
            start_date = st.date_input("Start date", today - dt.timedelta(days=30), key="hist_start")
        with right:
            end_date = st.date_input("End date", today, key="hist_end")
    elif range_name == "YTD":
        start_date, end_date = today.replace(month=1, day=1), today
    elif range_name == "All":
        start_date, end_date = dt.date(2000, 1, 1), today
    else:
        start_date, end_date = today - dt.timedelta(days=choices[range_name]), today
    if start_date > end_date:
        st.error("Start date must be on or before end date.")
        return

    loaded = _load_supabase_data(start_date, end_date)
    if loaded:
        summaries, equity, runs, charges, _ = loaded
        st.caption("Data source: Supabase")
    else:
        summaries, equity, runs, charges, available = _load_sqlite_data(start_date, end_date)
        st.caption("Data source: local SQLite" if available else "Data source: SQLite (currently no rows or unavailable)")
        if not available:
            st.warning("Could not read the local reporting database. Check app storage and database initialization.")
    if not runs.empty and "strategy_name" in runs:
        runs = runs[runs["strategy_name"].astype(str).str.strip().str.casefold() != "test strat"].copy()
    if not summaries.empty:
        summaries["report_date"] = pd.to_datetime(summaries["report_date"], errors="coerce").dt.date
    if not runs.empty:
        runs["report_date"] = pd.to_datetime(runs["report_date"], errors="coerce").dt.date
        run_names = sorted(runs["strategy_name"].dropna().astype(str).unique().tolist())
        segment_names = sorted(runs.get("underlying_segment", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
    else:
        run_names, segment_names = [], []
    filter_a, filter_b = st.columns(2)
    with filter_a:
        selected_strategies = st.multiselect("Strategies", run_names, key="hist_strategies")
    with filter_b:
        selected_segments = st.multiselect("Underlying / segment", segment_names, key="hist_segments")
    filtered_runs = runs.copy()
    if selected_strategies:
        filtered_runs = filtered_runs[filtered_runs["strategy_name"].isin(selected_strategies)]
    if selected_segments:
        filtered_runs = filtered_runs[filtered_runs["underlying_segment"].isin(selected_segments)]
    daily = _to_daily_from_runs(filtered_runs) if not filtered_runs.empty else pd.DataFrame()
    if daily.empty and not selected_strategies and not selected_segments and not summaries.empty:
        daily = summaries.copy()
    if daily.empty:
        st.info("No saved trading runs match this date range and filter. Save a daily pipeline run first.")
        _render_flows_and_regimes(daily)
        return
    daily["report_date"] = pd.to_datetime(daily["report_date"], errors="coerce").dt.date
    aliases = {
        "peak_capital_deployed": "total_capital_deployed_peak",
        "total_allocated_charges": "total_transaction_cost_drag",
    }
    for target, source in aliases.items():
        if target not in daily and source in daily:
            daily[target] = daily[source]
    for required_col in ("total_net_pnl", "total_gross_pnl", "total_allocated_charges", "peak_capital_deployed"):
        if required_col not in daily:
            daily[required_col] = 0.0
    daily = daily.sort_values("report_date").reset_index(drop=True)
    daily["total_net_pnl"] = pd.to_numeric(daily["total_net_pnl"], errors="coerce").fillna(0.0)
    first_capital = pd.to_numeric(daily["peak_capital_deployed"], errors="coerce").fillna(0.0)
    default_capital = float(first_capital.iloc[0]) if len(first_capital) and float(first_capital.iloc[0]) > 0 else 300000.0
    base_capital = st.number_input("Account base capital for ROI and drawdown (₹)", min_value=1.0, value=default_capital, step=10000.0, key="hist_base_capital", help="Defaults to first saved day's deployed capital as a reference. Change this to your actual account equity for investor-grade ROI and drawdown.")
    st.caption("Drawdown is calculated from account equity = account base + cumulative net P&L, so it is not divided by cumulative profit.")
    pnl = daily["total_net_pnl"].astype(float)
    equity_metrics = pd.DataFrame({"report_date": daily["report_date"], **{
        key: value.values for key, value in __import__("src.analytics", fromlist=["equity_and_drawdown"]).equity_and_drawdown(pnl, base_capital).items()
    }})
    wins = int((pnl > 0).sum())
    losses = int((pnl < 0).sum())
    gross_total = float(pd.to_numeric(daily["total_gross_pnl"], errors="coerce").fillna(0).sum())
    charges_total = float(pd.to_numeric(daily["total_allocated_charges"], errors="coerce").fillna(0).sum())
    total_net = float(pnl.sum())
    dd_max = float(equity_metrics["drawdown_pct"].max())
    win_rate = wins / (wins + losses) * 100 if wins + losses else 0.0
    metrics = st.columns(6)
    values = [("Net P&L", f"₹{total_net:,.2f}"), ("Gross P&L", f"₹{gross_total:,.2f}"), ("Charges", f"₹{charges_total:,.2f}"), ("Net ROI", f"{total_net/base_capital*100:+.2f}%"), ("Win days", f"{win_rate:.1f}%"), ("Max drawdown", f"{dd_max:.2f}%")]
    for col, (label, value) in zip(metrics, values):
        col.metric(label, value)
    daily_returns = pnl / base_capital
    risk_cols = st.columns(4)
    if len(daily_returns) >= 20:
        volatility = daily_returns.std(ddof=1)
        downside = daily_returns[daily_returns < 0]
        sharpe = (daily_returns.mean() / volatility * (252 ** .5)) if volatility > 0 else float("nan")
        downside_vol = downside.std(ddof=1) if len(downside) > 1 else 0.0
        sortino = (daily_returns.mean() / downside_vol * (252 ** .5)) if downside_vol > 0 else float("nan")
        risk_values = [("Annualized Sharpe", f"{sharpe:.2f}" if pd.notna(sharpe) else "N/A"), ("Annualized Sortino", f"{sortino:.2f}" if pd.notna(sortino) else "N/A"), ("Cost drag / gross", f"{charges_total/abs(gross_total)*100:.2f}%" if gross_total else "N/A"), ("Trading sessions", str(len(daily)))]
    else:
        risk_values = [("Annualized Sharpe", "Need 20+ sessions"), ("Annualized Sortino", "Need 20+ sessions"), ("Cost drag / gross", f"{charges_total/abs(gross_total)*100:.2f}%" if gross_total else "N/A"), ("Trading sessions", str(len(daily)))]
    for col, (label, value) in zip(risk_cols, risk_values):
        col.metric(label, value)

    st.subheader("Account Equity & Drawdown")
    dates = pd.to_datetime(equity_metrics["report_date"]).dt.strftime("%d %b %Y")
    fig = go.Figure()
    fig.add_scatter(x=dates, y=equity_metrics["equity"], mode="lines+markers", name="Account equity", line=dict(color="#10B981", width=3))
    fig.add_scatter(x=dates, y=-equity_metrics["drawdown_pct"], mode="lines", name="Drawdown", line=dict(color="#EF4444", dash="dot"), yaxis="y2")
    fig.update_layout(template="plotly_dark", height=350, yaxis=dict(title="Account equity (₹)"), yaxis2=dict(title="Drawdown (%)", overlaying="y", side="right", ticksuffix="%"), xaxis=dict(type="category", tickangle=-25), margin=dict(t=20, b=30))
    st.plotly_chart(fig, use_container_width=True)

    month_options = sorted({(d.year, d.month) for d in daily["report_date"]})
    month_names = [dt.date(y, m, 1).strftime("%B %Y") for y, m in month_options]
    selected_month = st.selectbox("Calendar month", range(len(month_options)), format_func=lambda index: month_names[index], key="hist_calendar_month")
    _render_calendar(daily[daily["report_date"].map(lambda d: (d.year, d.month) == month_options[selected_month])], *month_options[selected_month], base_capital)

    st.subheader("Strategy Performance Leaderboard")
    if filtered_runs.empty:
        st.info("Strategy detail is not available for this range.")
    else:
        work = filtered_runs.copy()
        for col in ("net_pnl", "booked_gross_pnl", "allocated_charges_total", "capital_deployed_allocated", "multiplier_x"):
            if col not in work:
                work[col] = 0.0
            work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
        leaderboard = work.groupby("strategy_name", as_index=False).agg(
            Multiplier=("multiplier_x", "max"), Runs=("strategy_name", "count"),
            Wins=("net_pnl", lambda values: int((values > 0).sum())),
            Gross_PnL=("booked_gross_pnl", "sum"), Charges=("allocated_charges_total", "sum"),
            Net_PnL=("net_pnl", "sum"), Capital=("capital_deployed_allocated", "sum"),
            Positive=("net_pnl", lambda values: float(values[values > 0].sum())),
            Negative=("net_pnl", lambda values: float(abs(values[values < 0].sum()))),
        )
        leaderboard["Win Rate %"] = leaderboard["Wins"] / leaderboard["Runs"] * 100
        leaderboard["Net ROI %"] = leaderboard["Net_PnL"] / leaderboard["Capital"].replace(0, float("nan")) * 100
        leaderboard["Run-level Profit Factor"] = leaderboard["Positive"] / leaderboard["Negative"].replace(0, float("nan"))
        leaderboard = leaderboard.rename(columns={"strategy_name": "Strategy", "Multiplier": "Multiplier", "Gross_PnL": "Total Gross P&L", "Charges": "Total Charges", "Net_PnL": "Total Net P&L"})
        st.dataframe(leaderboard[["Strategy", "Multiplier", "Runs", "Win Rate %", "Total Gross P&L", "Total Charges", "Total Net P&L", "Net ROI %", "Run-level Profit Factor"]], use_container_width=True, hide_index=True)
        st.caption("Profit factor is run-level because the database currently stores strategy-run totals, not tick-by-tick marked-to-market excursions.")

    st.subheader("Average Net P&L by Weekday")
    weekday = daily.copy()
    weekday["Weekday"] = pd.to_datetime(weekday["report_date"]).dt.day_name()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    average = weekday.groupby("Weekday")["total_net_pnl"].mean().reindex(order).dropna()
    if not average.empty:
        colors = ["#10B981" if value >= 0 else "#EF4444" for value in average]
        day_fig = go.Figure(go.Bar(x=average.index, y=average.values, marker_color=colors))
        day_fig.update_layout(template="plotly_dark", height=300, yaxis_title="Average net P&L (₹)")
        st.plotly_chart(day_fig, use_container_width=True)
        st.caption("Expiry labels depend on the selected instrument and the exchange's current contract calendar; Thursday is shown by weekday only.")

    _render_benchmark_tools(daily, base_capital)
    _render_flows_and_regimes(daily)
    with st.expander("Daily records"):
        st.dataframe(daily, use_container_width=True, hide_index=True)
