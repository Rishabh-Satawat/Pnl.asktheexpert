"""Plotly chart builder with dark-themed styling from design_system.yaml."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    HAS_PLOTLY = True
except ImportError:
    px = None  # type: ignore[assignment]
    go = None  # type: ignore[assignment]
    make_subplots = None  # type: ignore[assignment]
    HAS_PLOTLY = False

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


def _load_design_system() -> dict:
    """Load design_system.yaml from the config directory."""
    cfg_path = Path(__file__).resolve().parent.parent / "config" / "design_system.yaml"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class PlotlyThemedCharts:
    """Generate dark-themed Plotly figures for the Founder Report."""

    def __init__(self, design_config: Optional[dict] = None) -> None:
        if design_config is None:
            design_config = _load_design_system()
        self.cfg = design_config
        self.theme = self.cfg.get("theme", {})
        self.segment_palette = self.cfg.get("segment_palette", {})
        self.pnl_colors = self.cfg.get("pnl_colors", {})
        self.charts_cfg = self.cfg.get("charts", {})
        self.bg_color = self.theme.get("background_color", "#0B1426")
        self.surface_color = self.theme.get("surface_color", "#121F3D")
        self.font_family = self.charts_cfg.get("font_family", "Inter")
        self.rupee_prefix = self.charts_cfg.get("rupee_tick_prefix", "\u20b9")

    # ------------------------------------------------------------------
    # 1. Segment P&L Donut
    # ------------------------------------------------------------------
    def segment_pnl_donut(self, segment_data: Dict[str, float]) -> Any:
        """Donut chart of P&L by segment. segment_data: {segment_name: pnl_value}."""
        if not HAS_PLOTLY:
            raise ImportError("plotly is required for chart generation")

        labels = list(segment_data.keys())
        values = [abs(v) for v in segment_data.values()]
        colors = [self.segment_palette.get(s, "#94A3B8") for s in labels]

        fig = px.pie(
            names=labels,
            values=values,
            hole=0.4,
            color_discrete_sequence=colors,
        )
        fig.update_traces(
            textinfo="label+percent",
            marker=dict(colors=colors),
        )
        fig = self._apply_dark_theme(fig)
        fig.update_layout(title_text="Segment P&L Contribution")
        return fig

    # ------------------------------------------------------------------
    # 2. Gross vs Net Bars
    # ------------------------------------------------------------------
    def gross_vs_net_bars(self, segment_data: List[Dict[str, Any]]) -> Any:
        """Grouped bar chart: gross vs net by segment.

        segment_data: list of dicts with keys segment, gross_pnl, net_pnl.
        """
        if not HAS_PLOTLY:
            raise ImportError("plotly is required for chart generation")

        segments = [d["segment"] for d in segment_data]
        gross_vals = [d["gross_pnl"] for d in segment_data]
        net_vals = [d["net_pnl"] for d in segment_data]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Gross P&L",
            x=segments,
            y=gross_vals,
            marker_color=self.pnl_colors.get("profit_emerald", "#10B981"),
        ))
        fig.add_trace(go.Bar(
            name="Net P&L",
            x=segments,
            y=net_vals,
            marker_color="#22D3EE",
        ))
        fig.update_layout(barmode="group")
        fig = self._apply_dark_theme(fig)
        fig.update_layout(title_text="Gross vs Net P&L by Segment")
        return fig

    # ------------------------------------------------------------------
    # 3. Transaction Cost Waterfall
    # ------------------------------------------------------------------
    def transaction_cost_waterfall(
        self, gross: float, charges_dict: Dict[str, float], net: float
    ) -> Any:
        """Waterfall chart: Gross -> charges -> Net."""
        if not HAS_PLOTLY:
            raise ImportError("plotly is required for chart generation")

        x_labels = ["Gross P&L"]
        y_values = [gross]
        measures = ["absolute"]

        for charge_name, charge_val in charges_dict.items():
            x_labels.append(charge_name)
            y_values.append(-abs(charge_val))
            measures.append("relative")

        x_labels.append("Net P&L")
        y_values.append(net)
        measures.append("total")

        fig = go.Figure(go.Waterfall(
            x=x_labels,
            y=y_values,
            measure=measures,
            connector={"line": {"color": "#64748B", "width": 1}},
            increasing={"marker": {"color": self.pnl_colors.get("profit_emerald", "#10B981")}},
            decreasing={"marker": {"color": self.pnl_colors.get("loss_crimson", "#EF4444")}},
            totals={"marker": {"color": "#6366F1"}},
            textposition="outside",
        ))
        fig = self._apply_dark_theme(fig)
        fig.update_layout(title_text="Transaction Cost Waterfall")
        return fig

    # ------------------------------------------------------------------
    # 4. Equity Curve with Drawdown
    # ------------------------------------------------------------------
    def equity_curve_with_drawdown(self, ec_df: Any) -> Any:
        """Two-row subplot: cumulative P&L line (top) + drawdown area (bottom).

        ec_df must have columns: date, cumulative_pnl, drawdown_pct.
        """
        if not HAS_PLOTLY:
            raise ImportError("plotly is required for chart generation")

        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
            subplot_titles=("Cumulative P&L", "Drawdown %"),
        )

        fig.add_trace(
            go.Scatter(
                x=ec_df["date"],
                y=ec_df["cumulative_pnl"],
                mode="lines",
                name="Cumulative P&L",
                line=dict(color=self.pnl_colors.get("profit_emerald", "#10B981"), width=2),
            ),
            row=1, col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=ec_df["date"],
                y=ec_df["drawdown_pct"],
                fill="tozeroy",
                name="Drawdown",
                line=dict(color=self.pnl_colors.get("loss_crimson", "#EF4444"), width=1),
                fillcolor="rgba(239,68,68,0.25)",
            ),
            row=2, col=1,
        )

        fig = self._apply_dark_theme(fig)
        fig.update_layout(title_text="Equity Curve & Drawdown")
        return fig

    # ------------------------------------------------------------------
    # 5. Calendar P&L Heatmap
    # ------------------------------------------------------------------
    def calendar_pnl_heatmap(self, daily_df: Any) -> Any:
        """Heatmap of daily P&L by month x day-of-month.

        daily_df must have columns: date, daily_pnl.
        """
        if not HAS_PLOTLY:
            raise ImportError("plotly is required for chart generation")

        df = daily_df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df["month"] = df["date"].dt.strftime("%Y-%m")
        df["day"] = df["date"].dt.day

        pivot = df.pivot_table(index="month", columns="day", values="daily_pnl", aggfunc="sum")
        pivot = pivot.fillna(0)

        gap = self.charts_cfg.get("calendar_gap_px", 2)

        fig = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=[str(c) for c in pivot.columns],
            y=list(pivot.index),
            colorscale=[
                [0.0, self.pnl_colors.get("loss_crimson", "#EF4444")],
                [0.5, "#1E293B"],
                [1.0, self.pnl_colors.get("profit_emerald", "#10B981")],
            ],
            xgap=gap,
            ygap=gap,
            colorbar=dict(title="P&L"),
        ))
        fig = self._apply_dark_theme(fig)
        fig.update_layout(
            title_text="Calendar P&L Heatmap",
            xaxis_title="Day of Month",
            yaxis_title="Month",
        )
        return fig

    # ------------------------------------------------------------------
    # 6. Dark Theme Applier
    # ------------------------------------------------------------------
    def _apply_dark_theme(self, fig: Any) -> Any:
        """Apply dark navy background, white text, rupee tick prefix."""
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(
                family=self.font_family,
                color="#E2E8F0",
                size=12,
            ),
            title_font=dict(size=16, color="#F8FAFC"),
            margin=dict(l=60, r=30, t=50, b=40),
        )
        # Apply rupee prefix to y-axes
        for axis_name in ["yaxis", "yaxis2", "yaxis3", "yaxis4"]:
            axis = fig.layout.get(axis_name)
            if axis is not None:
                axis.update(tickprefix=self.rupee_prefix)
        return fig
