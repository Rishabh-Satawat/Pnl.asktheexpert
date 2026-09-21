from __future__ import annotations

import datetime

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:
    import plotly.graph_objects as go
except ImportError:  # pragma: no cover
    go = None  # type: ignore[assignment]


def _load_supabase_data(start_date, end_date):
    """Fetch daily_summaries + equity_curve from Supabase. Returns (summaries_df, equity_df)."""
    try:
        from src.supabase_store import get_supabase_store
        sb = get_supabase_store()
        if not sb.is_connected:
            return None, None, False
        summaries = sb.get_daily_summaries(start_date=start_date, end_date=end_date)
        equity = sb.get_equity_curve(start_date=start_date, end_date=end_date)
        s_df = pd.DataFrame(summaries) if summaries and pd is not None else pd.DataFrame()
        e_df = pd.DataFrame(equity) if equity and pd is not None else pd.DataFrame()
        return s_df, e_df, True
    except Exception:
        return None, None, False


def render_historical_dashboard() -> None:
    """Page 2: Historical Dashboard - KPIs, equity curve, heatmap, streaks."""
    if st is None:
        return

    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("Historical Dashboard")

    # ── Date Range Picker ─────────────────────────────────────────
    st.subheader("Date Range")
    today = datetime.date.today()

    pill_cols = st.columns(7)
    quick_ranges = {
        "Today": (today, today),
        "7D": (today - datetime.timedelta(days=7), today),
        "30D": (today - datetime.timedelta(days=30), today),
        "MTD": (today.replace(day=1), today),
        "QTD": (today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1), today),
        "YTD": (today.replace(month=1, day=1), today),
        "Custom": (None, None),
    }
    selected_range = st.session_state.get("hist_range", "30D")
    for i, label in enumerate(quick_ranges):
        with pill_cols[i]:
            if st.button(label, key=f"pill_{label}", use_container_width=True):
                st.session_state["hist_range"] = label
                selected_range = label

    if selected_range == "Custom":
        date_col1, date_col2 = st.columns(2)
        with date_col1:
            start_date = st.date_input("Start", value=today - datetime.timedelta(days=30), key="hist_start")
        with date_col2:
            end_date = st.date_input("End", value=today, key="hist_end")
    else:
        range_val = quick_ranges.get(selected_range, quick_ranges["30D"])
        start_date, end_date = range_val  # type: ignore[assignment]
        if start_date is None:
            start_date = today - datetime.timedelta(days=30)
            end_date = today

    # ── Load data from Supabase ────────────────────────────────────
    summaries_df, equity_df, sb_connected = _load_supabase_data(start_date, end_date)
    if not sb_connected:
        st.warning(
            "Supabase not connected. Configure SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY "
            "in Settings or .env to load historical data.",
            icon="☁️",
        )
    elif summaries_df is not None and summaries_df.empty:
        st.info("No trading data found for the selected date range.", icon="📭")

    # ── Filters ───────────────────────────────────────────────────
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        segments = st.multiselect(
            "Segments",
            options=["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY", "STOCK_FUT", "STOCK_OPT"],
            default=[],
            key="hist_segments",
        )
    with filter_col2:
        strategies = st.multiselect(
            "Strategies",
            options=[],
            default=[],
            key="hist_strategies",
            help="Strategies will populate from database.",
        )

    # ── 6 KPI Tiles ───────────────────────────────────────────────
    st.subheader("Key Performance Indicators")
    kpi_cols = st.columns(6)

    # Compute KPIs from Supabase data if available
    if summaries_df is not None and not summaries_df.empty and pd is not None:
        total_pnl = summaries_df["total_net_pnl"].sum() if "total_net_pnl" in summaries_df.columns else 0
        wins = summaries_df["win_count"].sum() if "win_count" in summaries_df.columns else 0
        losses = summaries_df["loss_count"].sum() if "loss_count" in summaries_df.columns else 0
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        avg_daily = summaries_df["total_net_pnl"].mean() if "total_net_pnl" in summaries_df.columns else 0
        max_dd = equity_df["drawdown_pct"].max() if equity_df is not None and not equity_df.empty and "drawdown_pct" in equity_df.columns else 0
        total_trades = summaries_df["total_trades_executed"].sum() if "total_trades_executed" in summaries_df.columns else 0

        kpi_data = [
            ("Total P&L", f"₹{total_pnl:,.0f}", "pnl-positive" if total_pnl >= 0 else "pnl-negative"),
            ("Win Rate", f"{win_rate:.1f}%", ""),
            ("Avg Daily P&L", f"₹{avg_daily:,.0f}", "pnl-positive" if avg_daily >= 0 else "pnl-negative"),
            ("Max Drawdown", f"{max_dd:.2f}%", "pnl-negative" if max_dd > 0 else ""),
            ("Sharpe Ratio", "--", ""),
            ("Total Trades", f"{int(total_trades):,}", ""),
        ]
    else:
        kpi_data = [
            ("Total P&L", "--", ""), ("Win Rate", "--", ""), ("Avg Daily P&L", "--", ""),
            ("Max Drawdown", "--", ""), ("Sharpe Ratio", "--", ""), ("Total Trades", "--", ""),
        ]

    for i, (label, val, cls) in enumerate(kpi_data):
        with kpi_cols[i]:
            color_class = f'class="{cls}"' if cls else ""
            st.markdown(
                f'<div class="kpi-card"><div style="font-size:0.78rem;color:#94A3B8;">{label}</div>'
                f'<div {color_class} style="font-size:1.5rem;font-weight:700;color:#E5E7EB;">{val}</div></div>',
                unsafe_allow_html=True,
            )

    # ── Equity Curve + Drawdown ───────────────────────────────────
    st.subheader("Equity Curve & Drawdown")
    if go is not None:
        fig = go.Figure()
        if equity_df is not None and not equity_df.empty and "report_date" in equity_df.columns:
            fig.add_trace(go.Scatter(
                x=equity_df["report_date"],
                y=equity_df["cumulative_net_pnl"] if "cumulative_net_pnl" in equity_df.columns else [],
                mode="lines",
                name="Cumulative P&L",
                line=dict(color="#10B981", width=2),
                fill="tozeroy",
                fillcolor="rgba(16,185,129,0.10)",
            ))
            if "drawdown_pct" in equity_df.columns:
                fig.add_trace(go.Scatter(
                    x=equity_df["report_date"],
                    y=[-v for v in equity_df["drawdown_pct"]],
                    mode="lines",
                    name="Drawdown %",
                    line=dict(color="#EF4444", width=1.5, dash="dot"),
                    yaxis="y2",
                ))
        else:
            fig.add_trace(go.Scatter(x=[], y=[], mode="lines", name="Cumulative P&L"))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter"),
            height=350,
            margin=dict(l=40, r=20, t=30, b=30),
            yaxis2=dict(overlaying="y", side="right", showgrid=False, ticksuffix="%"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Install plotly for equity curve visualization.")

    # ── Calendar Heatmap ──────────────────────────────────────────
    st.subheader("Calendar Heatmap")
    if summaries_df is not None and not summaries_df.empty and go is not None:
        # Simple daily P&L bar chart as proxy for heatmap
        fig2 = go.Figure()
        colors = [
            "#10B981" if v >= 0 else "#EF4444"
            for v in summaries_df.get("total_net_pnl", [])
        ]
        fig2.add_trace(go.Bar(
            x=summaries_df["report_date"],
            y=summaries_df["total_net_pnl"] if "total_net_pnl" in summaries_df.columns else [],
            marker_color=colors,
            name="Daily Net P&L",
        ))
        fig2.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter"),
            height=220,
            margin=dict(l=40, r=20, t=20, b=30),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.caption(
            "Calendar heatmap will display daily P&L color-coded cells once Supabase is connected."
        )

    # ── Best / Worst / Streak Cards ───────────────────────────────
    st.subheader("Performance Highlights")
    card_cols = st.columns(3)

    if summaries_df is not None and not summaries_df.empty and "total_net_pnl" in summaries_df.columns:
        best_val = summaries_df["total_net_pnl"].max()
        worst_val = summaries_df["total_net_pnl"].min()
        best_str = f"₹{best_val:,.0f}"
        worst_str = f"₹{worst_val:,.0f}"
    else:
        best_str = worst_str = "--"

    with card_cols[0]:
        st.markdown(
            f'<div class="kpi-card"><div style="font-size:0.78rem;color:#94A3B8;">Best Day</div>'
            f'<div class="pnl-positive" style="font-size:1.3rem;font-weight:700;">{best_str}</div></div>',
            unsafe_allow_html=True,
        )
    with card_cols[1]:
        st.markdown(
            f'<div class="kpi-card"><div style="font-size:0.78rem;color:#94A3B8;">Worst Day</div>'
            f'<div class="pnl-negative" style="font-size:1.3rem;font-weight:700;">{worst_str}</div></div>',
            unsafe_allow_html=True,
        )
    with card_cols[2]:
        st.markdown(
            '<div class="kpi-card"><div style="font-size:0.78rem;color:#94A3B8;">Current Streak</div>'
            '<div style="font-size:1.3rem;font-weight:700;color:#E5E7EB;">--</div></div>',
            unsafe_allow_html=True,
        )

    # ── Raw data table (optional expand) ──────────────────────────
    if summaries_df is not None and not summaries_df.empty:
        with st.expander("View Raw Daily Summary Data"):
            st.dataframe(summaries_df, use_container_width=True)
