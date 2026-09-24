"""Report generation engine: HTML, PDF (Playwright), Excel, CSV exports."""
from __future__ import annotations

import csv
import html as html_module
import base64
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore[assignment]
    HAS_PANDAS = False

try:
    import yaml

    HAS_YAML = True
except ImportError:
    yaml = None  # type: ignore[assignment]
    HAS_YAML = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DESIGN_SYSTEM_PATH = Path(__file__).resolve().parent.parent / "config" / "design_system.yaml"
_BRANDING_PATH = Path(__file__).resolve().parent.parent / "config" / "report_branding.yaml"


def _load_yaml(path: Path) -> dict:
    if not HAS_YAML or not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _rupee(val: float) -> str:
    """Format a number as Indian Rupees."""
    try:
        number = float(val)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    sign = "" if number >= 0 else "-"
    formatted = f"{abs(number):,.2f}"
    return f'{sign}<span class="currency-symbol">&#8377;</span>{formatted}'


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _fmt_time(value: Any) -> str:
    if value is None or (HAS_PANDAS and pd.isna(value)):
        return "—"
    try:
        return value.strftime("%I:%M %p")
    except (AttributeError, ValueError):
        try:
            return pd.to_datetime(value).strftime("%I:%M %p") if HAS_PANDAS else str(value)
        except Exception:
            return str(value)


def _pct(val: float) -> str:
    return f"{val:+.2f}%"


def _pnl_color(val: float) -> str:
    return "#10B981" if val >= 0 else "#EF4444"


def _status_pill_styles(status: str) -> tuple:
    """Return (bg, text_color) for a deployment status pill."""
    s = str(status).upper()
    if s in ("LIVE", "ACTIVE", "RUNNING"):
        return ("rgba(16,185,129,0.18)", "#10B981")
    if s in ("PAUSED", "STOPPED"):
        return ("rgba(245,158,11,0.18)", "#F59E0B")
    if s in ("EXITED", "CLOSED"):
        return ("rgba(100,116,139,0.18)", "#94A3B8")
    return ("rgba(99,102,241,0.18)", "#6366F1")


# ---------------------------------------------------------------------------
# HTML report CSS
# ---------------------------------------------------------------------------

_INLINE_CSS = """

*, *::before, *::after { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: #0B1426; color: #E2E8F0;
  font-family: 'Noto Sans', 'Inter', 'Segoe UI', Arial, sans-serif;
  font-size: 14px; line-height: 1.5;
}
.page { padding: 18mm 14mm; max-width: 1100px; margin: 0 auto; }
h1 { font-size: 22px; font-weight: 700; color: #F8FAFC; margin: 0 0 4px; }
h2 { font-size: 17px; font-weight: 600; color: #F8FAFC; margin: 22px 0 10px; border-bottom: 1px solid #1E3A5F; padding-bottom: 6px; }
h3 { font-size: 14px; font-weight: 600; color: #CBD5E1; margin: 0 0 8px; }
.sub { font-size: 12px; color: #94A3B8; margin-bottom: 16px; }

/* KPI strip */
.kpi-tiles-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 22px;
}
.kpi-card {
  background: rgba(18,31,61,0.72);
  backdrop-filter: blur(18px) saturate(150%);
  border: 1px solid rgba(99,102,241,0.22);
  border-radius: 16px; padding: 16px 18px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.35);
}
.kpi-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #94A3B8; margin-bottom: 6px; }
.kpi-value { font-size: 22px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
.currency-symbol { font-family: 'Noto Sans', 'Segoe UI Symbol', sans-serif; font-weight: 600; }

/* Strategy cards */
.strategy-cards-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.benchmark-ribbon { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 12px 0 20px; }
.benchmark-item { background: rgba(18,31,61,0.72); border: 1px solid rgba(99,102,241,0.22); border-radius: 10px; padding: 10px 12px; }
.benchmark-item span { display:block; color:#94A3B8; font-size:10px; letter-spacing:.04em; margin-bottom:4px; }
.benchmark-item b { color:#E2E8F0; font-size:12px; }
.timing-strip { display:flex; gap:16px; flex-wrap:wrap; margin:10px 0; color:#94A3B8; font-size:11px; }
.timing-strip b { color:#E2E8F0; margin-left:3px; }
.legs-details { margin-top:12px; border-top:1px solid #1E3A5F; padding-top:8px; }
.legs-details summary { cursor:pointer; color:#A5B4FC; font-size:11px; }
.legs-empty, .chart-empty { color:#94A3B8; font-size:11px; margin-top:10px; }
.table-scroll { overflow-x:auto; }
.embedded-chart { display:block; width:100%; max-height:280px; object-fit:contain; }
.strategy-card {
  background: rgba(18,31,61,0.72);
  backdrop-filter: blur(18px) saturate(150%);
  border: 1px solid rgba(99,102,241,0.22);
  border-radius: 16px; padding: 18px 20px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.35);
  page-break-inside: avoid;
}
.strategy-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.strategy-name { font-size: 15px; font-weight: 600; color: #F8FAFC; }
.multiplier-chip {
  display: inline-block; background: linear-gradient(135deg, #6366F1, #A855F7);
  color: #fff; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 20px;
  margin-left: 8px; font-family: 'JetBrains Mono', monospace;
}
.status-pill {
  display: inline-block; font-size: 10px; font-weight: 600; padding: 3px 10px;
  border-radius: 20px; text-transform: uppercase; letter-spacing: 0.04em;
}
.metrics-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
}
.metric-label { color: #94A3B8; font-size: 10px; font-family: 'Inter', sans-serif; }

/* Analytics */
.analytics-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.chart-panel { background: rgba(18,31,61,0.55); border-radius: 12px; padding: 14px; border: 1px solid rgba(30,58,95,0.5); }
.chart-full { grid-column: span 2; }

/* Trade log table */
.trade-table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: 'JetBrains Mono', monospace; }
.trade-table th {
  background: #121F3D; color: #94A3B8; text-transform: uppercase; font-size: 10px;
  letter-spacing: 0.05em; padding: 8px 10px; text-align: left; border-bottom: 1px solid #1E3A5F;
}
.trade-table td { padding: 7px 10px; border-bottom: 1px solid rgba(30,58,95,0.4); color: #CBD5E1; }
.trade-table tr:hover { background: rgba(99,102,241,0.06); }
.trade-table th { white-space: nowrap; }

/* Charges table */
.charges-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.charges-table th { background: #121F3D; color: #94A3B8; padding: 8px 10px; text-align: left; border-bottom: 1px solid #1E3A5F; }
.charges-table td { padding: 7px 10px; border-bottom: 1px solid rgba(30,58,95,0.4); color: #CBD5E1; }

/* Disclaimer */
.disclaimer-footer {
  font-size: 10px; font-weight: 700; opacity: 0.85;
  border-top: 1px solid #1E3A5F; padding-top: 10px; margin-top: 24px;
  color: #94A3B8; line-height: 1.55;
}

@media print {
  html, body { background: #fff !important; color: #111827 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .page { padding: 0; }
  h1, h2, h3, .strategy-name { color: #111827 !important; }
  .sub, .metric-label, .kpi-label { color: #475569 !important; }
  .kpi-card, .strategy-card, .chart-panel { background: #fff !important; box-shadow: none !important; border-color: #cbd5e1 !important; }
  .kpi-value, .metric-value { color: #111827 !important; }
  .trade-table, .charges-table { color: #111827 !important; }
  .strategy-card { page-break-inside: avoid; break-inside: avoid; }
}
"""


# ---------------------------------------------------------------------------
# DailyReportGenerator
# ---------------------------------------------------------------------------

class DailyReportGenerator:
    """Render daily founder report as full HTML."""

    def __init__(self) -> None:
        self.design = _load_yaml(_DESIGN_SYSTEM_PATH)
        self.branding = _load_yaml(_BRANDING_PATH)
        self.segment_palette = self.design.get("segment_palette", {})
        self.desk_name = self.branding.get("desk", {}).get("name", "QUANT DESK")

    def render_daily_html(
        self,
        daily_summary: Dict[str, Any],
        strategy_runs_df: Any,
        matched_trades_df: Any,
        charges_df: Any,
        chart_divs: Dict[str, str],
        disclaimer_text: str,
        benchmark_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return a complete HTML string with 6 sections."""
        report_date = daily_summary.get("report_date", str(date.today()))

        # --- KPI strip ---
        total_net = _safe_float(daily_summary.get("total_net_pnl"))
        gross = _safe_float(daily_summary.get("total_gross_pnl"))
        net_roi = _safe_float(daily_summary.get("net_roi_pct"))
        gross_roi = _safe_float(daily_summary.get("gross_roi_pct"))
        wins = daily_summary.get("winning_strategies", 0)
        losses = daily_summary.get("losing_strategies", 0)
        capital = daily_summary.get("total_capital_deployed", 0.0)
        txn_drag = daily_summary.get("total_charges", 0.0)
        strat_count = daily_summary.get("strategy_count", 0)

        kpis_html = self._render_kpi_strip([
            {"label": "Capital Deployed (Peak)", "value": _rupee(capital), "color": "#E2E8F0", "html": True},
            {"label": "Total Gross P&L", "value": _rupee(gross), "color": _pnl_color(gross), "html": True},
            {"label": "Brokerage & Statutory Charges", "value": _rupee(txn_drag), "color": "#EF4444", "html": True},
            {"label": "Total Net P&L", "value": _rupee(total_net), "color": _pnl_color(total_net), "html": True},
            {"label": "Day Gross ROI", "value": _pct(gross_roi), "color": _pnl_color(gross_roi)},
            {"label": "Day Net ROI", "value": _pct(net_roi), "color": _pnl_color(net_roi)},
        ])

        # --- Strategy cards ---
        strat_html = self._render_strategy_cards(strategy_runs_df, matched_trades_df)

        # --- Charts ---
        if not chart_divs:
            chart_divs = self._build_embedded_charts(strategy_runs_df)
        charts_html = self._render_charts_section(chart_divs)
        benchmark_html = self._render_benchmark_ribbon(benchmark_context or {})

        # --- Trade log ---
        trade_log_html = self._render_trade_log(matched_trades_df)

        # --- Charges reconciliation ---
        charges_html = self._render_charges_table(charges_df)

        # --- Assemble ---
        escaped_disclaimer = html_module.escape(disclaimer_text)

        body = f"""<!DOCTYPE html>
<html lang="en-IN">
<head>
  <meta charset="UTF-8">
  <title>Daily P&amp;L Report - {html_module.escape(str(report_date))}</title>
  <style>{_INLINE_CSS}</style>
</head>
<body>
<div class="page">

  <!-- SECTION 1: KPI -->
  <section id="section-header-kpi" class="report-section">
    <h1>{html_module.escape(self.desk_name)}</h1>
    <div class="sub">Daily Founder P&amp;L Report &mdash; {html_module.escape(str(report_date))}</div>
    {kpis_html}
    {benchmark_html}
  </section>

  <!-- SECTION 2: Strategy Breakdown -->
  <section id="section-strategy-cards" class="report-section">
    <h2>Strategy Breakdown</h2>
    <div class="strategy-cards-grid">
      {strat_html}
    </div>
  </section>

  <!-- SECTION 3: Visual Analytics -->
  <section id="section-analytics" class="report-section">
    <h2>Visual Analytics</h2>
    {charts_html}
  </section>

  <!-- SECTION 4: Detailed Trade Log -->
  <section id="section-trade-log" class="report-section">
    <h2>Detailed Trade Log</h2>
    {trade_log_html}
  </section>

  <!-- SECTION 5: Charges Reconciliation -->
  <section id="section-charges-reconciliation" class="report-section">
    <h2>Charges Reconciliation</h2>
    {charges_html}
  </section>

  <!-- SECTION 6: Disclaimer -->
  <section id="section-disclaimer" class="report-section">
    <div class="disclaimer-footer">
      <strong>{escaped_disclaimer}</strong>
    </div>
  </section>

</div>
</body>
</html>"""
        return body

    # -- Private renderers --

    def _render_kpi_strip(self, kpis: List[Dict[str, str]]) -> str:
        tiles = []
        for k in kpis:
            subtitle = k.get("subtitle", "")
            sub_html = f'<div style="font-size:10px;color:#64748B;margin-top:4px;">{html_module.escape(subtitle)}</div>' if subtitle else ""
            tiles.append(f"""<div class="kpi-card">
  <div class="kpi-label">{html_module.escape(k["label"])}</div>
  <div class="kpi-value" style="color:{k['color']}">{k["value"] if k.get("html") else html_module.escape(k["value"])}</div>
  {sub_html}
</div>""")
        return f'<div class="kpi-tiles-grid">{"".join(tiles)}</div>'

    def _render_strategy_cards(self, strategy_runs_df: Any, matched_trades_df: Any = None) -> str:
        if strategy_runs_df is None or (HAS_PANDAS and isinstance(strategy_runs_df, pd.DataFrame) and strategy_runs_df.empty):
            return '<div style="color:#64748B;">No strategy data available.</div>'

        cards = []
        rows = strategy_runs_df.to_dict("records") if HAS_PANDAS else []
        for row in rows:
            name = row.get("strategy_name", "Unknown")
            if str(name).strip().casefold() == "test strat":
                continue
            multiplier = _safe_float(row.get("multiplier_x", row.get("multiplier", 1.0)), 1.0)
            if multiplier <= 0:
                multiplier = 1.0
            status = row.get("deployment_status", "LIVE")
            gross = _safe_float(row.get("booked_gross_pnl"))
            charges = _safe_float(row.get("allocated_charges_total"))
            net = _safe_float(row.get("net_pnl"), gross - charges)
            cap = _safe_float(row.get("capital_deployed_allocated"))
            roi = _safe_float(row.get("net_roi_pct"))
            segment = row.get("underlying_segment") or row.get("underlying") or row.get("segment") or "UNKNOWN"
            seg_color = self.segment_palette.get(segment, "#94A3B8")

            trades = []
            if HAS_PANDAS and isinstance(matched_trades_df, pd.DataFrame) and not matched_trades_df.empty:
                run_id = row.get("strategy_run_id", row.get("id"))
                if run_id is not None and "strategy_run_id" in matched_trades_df:
                    trades = matched_trades_df[
                        matched_trades_df["strategy_run_id"].astype(str) == str(run_id)
                    ].to_dict("records")
            entry_times = [t.get("entry_time") for t in trades if t.get("entry_time") is not None and not (HAS_PANDAS and pd.isna(t.get("entry_time")))]
            exit_times = [t.get("exit_time") for t in trades if t.get("exit_time") is not None and not (HAS_PANDAS and pd.isna(t.get("exit_time")))]
            entry = min(entry_times) if entry_times else row.get("entry_timestamp_ist")
            exit_ = max(exit_times) if exit_times else row.get("exit_timestamp_ist")
            duration = sum(_safe_float(t.get("holding_duration_minutes")) for t in trades)
            timing_html = f'''<div class="timing-strip"><span>Entry <b>{html_module.escape(_fmt_time(entry))}</b></span>
              <span>Exit <b>{html_module.escape(_fmt_time(exit_))}</b></span>
              <span>Matched duration <b>{duration / 60:.1f}h</b></span></div>'''
            legs_html = self._render_strategy_legs(trades)

            status_bg, status_color = _status_pill_styles(status)

            cards.append(f"""<div class="strategy-card">
  <div class="strategy-header">
    <div>
      <span class="strategy-name">{html_module.escape(str(name))}</span>
      <span class="multiplier-chip">{multiplier:g}x</span>
    </div>
    <span class="status-pill" style="background:{status_bg};color:{status_color};">{html_module.escape(str(status))}</span>
  </div>
  {timing_html}
  <div class="metrics-grid">
    <div><div class="metric-label">Gross P&amp;L</div><div style="color:{_pnl_color(gross)};font-weight:600;">{_rupee(gross)}</div></div>
    <div><div class="metric-label">Charges</div><div style="color:#EF4444;font-weight:600;">{_rupee(charges)}</div></div>
    <div><div class="metric-label">Net P&amp;L</div><div style="color:{_pnl_color(net)};font-weight:600;">{_rupee(net)}</div></div>
    <div><div class="metric-label">Capital Deployed</div><div style="color:#E2E8F0;font-weight:600;">{_rupee(cap)}</div></div>
    <div><div class="metric-label">Net ROI</div><div style="color:{_pnl_color(roi)};font-weight:600;">{_pct(roi)}</div></div>
    <div><div class="metric-label">Segment</div><div style="color:{seg_color};font-weight:600;">{html_module.escape(str(segment))}</div></div>
  </div>
  {legs_html}
</div>""")
        return "\n".join(cards)

    def _render_strategy_legs(self, trades: List[Dict[str, Any]]) -> str:
        if not trades:
            return '<div class="legs-empty">No matched execution detail available for this strategy.</div>'
        rows = []
        for trade in trades:
            expiry = trade.get("expiry_date")
            if hasattr(expiry, "isoformat"):
                expiry = expiry.isoformat()
            symbol = html_module.escape(str(trade.get("vendor_symbol", trade.get("instrument", "—"))))
            rows.append("<tr>" + "".join(f"<td>{html_module.escape(str(value if value is not None else '—'))}</td>" for value in (
                symbol, trade.get("option_type", "—"), trade.get("strike_price", "—"), trade.get("side", "—"),
                trade.get("quantity", trade.get("qty", "—")), trade.get("entry_price", trade.get("price", "—")),
                trade.get("exit_price", "—"), f"{_safe_float(trade.get('gross_pnl')):,.2f}", expiry or "—",
            )) + "</tr>")
        return ('<details class="legs-details"><summary>Matched legs &amp; execution details</summary>'
                '<div class="table-scroll"><table class="trade-table"><thead><tr><th>Symbol</th><th>Type</th><th>Strike</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Leg P&amp;L</th><th>Expiry</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div></details>')

    def _render_benchmark_ribbon(self, context: Dict[str, Any]) -> str:
        labels = (("NIFTY 50", "nifty"), ("BANK NIFTY", "banknifty"), ("SENSEX", "sensex"), ("INDIA VIX", "india_vix"))
        items = []
        for label, key in labels:
            value = context.get(key)
            if not isinstance(value, dict) or not value:
                display = "Not supplied"
            elif key == "india_vix":
                display = f"{_safe_float(value.get('close')):,.2f} ({_safe_float(value.get('change_pct')):+.2f}%)"
            else:
                display = f"{_safe_float(value.get('points')):+,.2f} pts ({_safe_float(value.get('change_pct')):+.2f}%)"
            items.append(f'<div class="benchmark-item"><span>{label}</span><b>{html_module.escape(display)}</b></div>')
        return '<h2>Market Benchmark Context</h2><div class="benchmark-ribbon">' + "".join(items) + '</div>'

    def _build_embedded_charts(self, strategies_df: Any) -> Dict[str, str]:
        """Generate portable inline SVG charts (no remote JS or image service)."""
        if not HAS_PANDAS or not isinstance(strategies_df, pd.DataFrame) or strategies_df.empty:
            return {}
        data = strategies_df.copy()
        if "strategy_name" in data:
            data = data[data["strategy_name"].astype(str).str.casefold() != "test strat"]
        if data.empty:
            return {}
        segments = data.groupby(data.get("underlying_segment", pd.Series(["Strategy"] * len(data))).fillna("Strategy")).agg(
            pnl=("net_pnl", "sum") if "net_pnl" in data else ("booked_gross_pnl", "sum")
        )
        palette = ["#10B981", "#38BDF8", "#F59E0B", "#A78BFA", "#F472B6"]
        total = sum(abs(_safe_float(v)) for v in segments["pnl"])
        if total:
            circumference = 2 * math.pi * 58
            offset = 0.0
            circles = []
            for idx, (name, amount) in enumerate(segments["pnl"].items()):
                portion = abs(_safe_float(amount)) / total * circumference
                circles.append(f'<circle cx="100" cy="100" r="58" fill="none" stroke="{palette[idx % len(palette)]}" stroke-width="22" stroke-dasharray="{portion:.2f} {circumference - portion:.2f}" stroke-dashoffset="{-offset:.2f}"/>')
                offset += portion
            donut_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" role="img" aria-label="Strategy contribution donut"><rect width="200" height="200" fill="#0B1426" rx="12"/>' + "".join(circles) + '<text x="100" y="96" text-anchor="middle" fill="#F8FAFC" font-size="12" font-family="sans-serif">Net P&amp;L</text><text x="100" y="116" text-anchor="middle" fill="#94A3B8" font-size="10" font-family="sans-serif">by strategy</text></svg>'
            donut = self._svg_data_uri(donut_svg)
        else:
            donut = '<div class="chart-empty">No non-zero contribution values.</div>'
        gross = sum(_safe_float(v) for v in data.get("booked_gross_pnl", []))
        charges = sum(_safe_float(v) for v in data.get("allocated_charges_total", []))
        net = sum(_safe_float(v) for v in data.get("net_pnl", []))
        values = [gross, -charges, net]
        max_abs = max([abs(v) for v in values] + [1.0])
        bars = []
        for idx, (label, value) in enumerate(zip(("Gross", "Charges", "Net"), values)):
            height = max(3, abs(value) / max_abs * 100)
            color = "#EF4444" if value < 0 else ("#38BDF8" if idx == 2 else "#10B981")
            y = 140 - height
            bars.append(f'<rect x="{35 + idx * 105}" y="{y:.1f}" width="56" height="{height:.1f}" rx="5" fill="{color}"/><text x="{63 + idx * 105}" y="164" text-anchor="middle" fill="#CBD5E1" font-size="11" font-family="sans-serif">{label}</text><text x="{63 + idx * 105}" y="{max(14, y - 5):.1f}" text-anchor="middle" fill="#F8FAFC" font-size="9" font-family="sans-serif">&#8377;{abs(value):,.0f}</text>')
        waterfall_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 190" role="img" aria-label="Gross, charges and net P&amp;L chart"><rect width="360" height="190" fill="#0B1426" rx="12"/><line x1="20" y1="140" x2="340" y2="140" stroke="#475569"/>' + "".join(bars) + '</svg>'
        return {"Strategy Contribution": donut, "Gross / Charges / Net": self._svg_data_uri(waterfall_svg)}

    @staticmethod
    def _svg_data_uri(svg: str) -> str:
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f'<img class="embedded-chart" alt="P&amp;L chart" src="data:image/svg+xml;base64,{encoded}">'

    def _render_charts_section(self, chart_divs: Dict[str, str]) -> str:
        if not chart_divs:
            return '<div style="color:#64748B;">No charts generated.</div>'
        panels = []
        for title, div_html in chart_divs.items():
            css_class = "chart-panel chart-full" if "waterfall" in title.lower() else "chart-panel"
            panels.append(f'<div class="{css_class}"><h3>{html_module.escape(title)}</h3>{div_html}</div>')
        return f'<div class="analytics-grid">{"".join(panels)}</div>'

    def _render_trade_log(self, matched_trades_df: Any) -> str:
        if matched_trades_df is None or (HAS_PANDAS and isinstance(matched_trades_df, pd.DataFrame) and matched_trades_df.empty):
            return '<div style="color:#64748B;">No trade data.</div>'

        preferred = ["trade_date", "segment", "vendor_symbol", "option_type", "expiry_date", "strike_price", "side", "quantity", "entry_price", "exit_price", "gross_pnl", "holding_duration_minutes"]
        cols = [col for col in preferred if col in matched_trades_df.columns]
        if not cols:
            cols = list(matched_trades_df.columns[:12])
        header = "".join(f"<th>{html_module.escape(str(c))}</th>" for c in cols)
        rows_html = []
        for _, row in matched_trades_df.iterrows():
            cells_list = []
            for col in cols:
                value = row[col]
                if HAS_PANDAS and pd.isna(value):
                    value = "—"
                elif col in {"trade_date", "expiry_date"} and hasattr(value, "strftime"):
                    value = value.strftime("%d %b %Y")
                if col in {"entry_price", "exit_price", "gross_pnl"}:
                    cells_list.append(f"<td>{_rupee(value)}</td>")
                else:
                    cells_list.append(f"<td>{html_module.escape(str(value))}</td>")
            cells = "".join(cells_list)
            rows_html.append(f"<tr>{cells}</tr>")
        return f'<div class="table-scroll"><table class="trade-table"><thead><tr>{header}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'

    def _render_charges_table(self, charges_df: Any) -> str:
        if charges_df is None or (HAS_PANDAS and isinstance(charges_df, pd.DataFrame) and charges_df.empty):
            return '<div style="color:#64748B;">No charges data.</div>'

        frame = charges_df.copy()
        amount_columns = [c for c in ("brokerage", "exchange_turnover_fee", "stt", "sebi_turnover_charges", "stamp_duty", "gst", "ipft", "slippage", "total_charges") if c in frame]
        if amount_columns:
            frame = frame.dropna(how="all", subset=amount_columns)
        if frame.empty:
            return '<div style="color:#64748B;">No reconciled charge rows available.</div>'
        preferred = ["report_date", "strategy_run_uuid", "charge_source", "brokerage", "exchange_turnover_fee", "stt", "sebi_turnover_charges", "stamp_duty", "gst", "ipft", "slippage", "total_charges"]
        cols = [col for col in preferred if col in frame.columns]
        if not cols:
            cols = list(frame.columns[:12])
        header = "".join(f"<th>{html_module.escape(str(c))}</th>" for c in cols)
        rows_html = []
        for _, row in frame.iterrows():
            cells_list = []
            for col in cols:
                value = row[col]
                if col in amount_columns:
                    cells_list.append(f"<td>{_rupee(value)}</td>")
                else:
                    text = "—" if value is None or (HAS_PANDAS and pd.isna(value)) or str(value).strip().casefold() in {"none", "nan", "nat"} else str(value)
                    cells_list.append(f"<td>{html_module.escape(text)}</td>")
            cells = "".join(cells_list)
            rows_html.append(f"<tr>{cells}</tr>")
        return f'<div class="table-scroll"><table class="charges-table"><thead><tr>{header}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'


# ---------------------------------------------------------------------------
# AggregateReportGenerator
# ---------------------------------------------------------------------------

class AggregateReportGenerator:
    """Render aggregate (multi-day) report HTML."""

    def __init__(self) -> None:
        self.design = _load_yaml(_DESIGN_SYSTEM_PATH)
        self.branding = _load_yaml(_BRANDING_PATH)
        self.desk_name = self.branding.get("desk", {}).get("name", "QUANT DESK")

    def render_aggregate_html(
        self,
        date_range: str,
        summary: Dict[str, Any],
        equity_chart_div: str,
        heatmap_div: str,
        stats: Dict[str, Any],
    ) -> str:
        total_net = summary.get("total_net_pnl", 0.0)
        total_days = stats.get("trading_days", 0)
        win_rate = stats.get("win_rate_pct", 0.0)
        max_dd = stats.get("max_drawdown_pct", 0.0)

        return f"""<!DOCTYPE html>
<html lang="en-IN">
<head>
  <meta charset="UTF-8">
  <title>Aggregate P&amp;L Report - {html_module.escape(date_range)}</title>
  <style>{_INLINE_CSS}</style>
</head>
<body>
<div class="page">

  <section class="report-section">
    <h1>{html_module.escape(self.desk_name)}</h1>
    <div class="sub">Aggregate Founder Report &mdash; {html_module.escape(date_range)}</div>
    <div class="kpi-tiles-grid">
      <div class="kpi-card">
        <div class="kpi-label">Total Net P&amp;L</div>
        <div class="kpi-value" style="color:{_pnl_color(total_net)}">{_rupee(total_net)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Trading Days</div>
        <div class="kpi-value" style="color:#E2E8F0">{total_days}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Win Rate</div>
        <div class="kpi-value" style="color:#E2E8F0">{win_rate:.1f}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Max Drawdown</div>
        <div class="kpi-value" style="color:#EF4444">{max_dd:.2f}%</div>
      </div>
    </div>
  </section>

  <section class="report-section">
    <h2>Equity Curve</h2>
    <div class="chart-panel chart-full">{equity_chart_div}</div>
  </section>

  <section class="report-section">
    <h2>Calendar Heatmap</h2>
    <div class="chart-panel chart-full">{heatmap_div}</div>
  </section>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# PDF export via Playwright
# ---------------------------------------------------------------------------

def export_pdf_playwright(
    html_str: str,
    output_path: str | Path,
    page_size: str = "A4",
    print_background: bool = True,
) -> Dict[str, Any]:
    """Export HTML string to PDF using Playwright (sync API).

    Returns dict with 'success' bool and either 'path' or 'error' message.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "success": False,
            "error": "playwright is not installed. Run `pip install playwright` then `playwright install chromium`",
        }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as bundled_error:
                browser = None
                if os.name == "nt":
                    for installed_channel in ("msedge", "chrome"):
                        try:
                            browser = p.chromium.launch(channel=installed_channel, headless=True)
                            break
                        except Exception:
                            continue
                if browser is None:
                    raise bundled_error
            page = browser.new_page()
            page.set_content(html_str, wait_until="networkidle")
            page.pdf(
                path=str(output_path),
                format=page_size,
                print_background=print_background,
                margin={
                    "top": "12mm",
                    "bottom": "16mm",
                    "left": "10mm",
                    "right": "10mm",
                },
            )
            browser.close()
        return {"success": True, "path": str(output_path)}
    except Exception as exc:
        return {
            "success": False,
            "error": f"PDF generation failed: {exc}. Run `playwright install chromium`",
        }


# ---------------------------------------------------------------------------
# Excel export via xlsxwriter
# ---------------------------------------------------------------------------

def export_excel(
    output_path: str | Path,
    daily_summary: Dict[str, Any],
    strategy_runs_df: Any,
    matched_trades_df: Any,
    charges_df: Any,
    disclaimer_text: str = "",
) -> Dict[str, Any]:
    """Export data to Excel with 5 sheets, conditional formatting, and disclaimer footers.

    Returns dict with 'success' bool.
    """
    try:
        import xlsxwriter
    except ImportError:
        return {"success": False, "error": "xlsxwriter is not installed. Run `pip install xlsxwriter`"}

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        wb = xlsxwriter.Workbook(str(output_path))

        # Formats
        header_fmt = wb.add_format({
            "bold": True, "bg_color": "#121F3D", "font_color": "#E2E8F0",
            "border": 1, "border_color": "#1E3A5F",
        })
        green_fmt = wb.add_format({"font_color": "#10B981", "num_format": "#,##0.00"})
        red_fmt = wb.add_format({"font_color": "#EF4444", "num_format": "#,##0.00"})
        num_fmt = wb.add_format({"num_format": "#,##0.00"})
        disclaimer_fmt = wb.add_format({
            "bold": True, "font_size": 9, "text_wrap": True,
            "font_color": "#64748B",
        })

        def _write_disclaimer(ws: Any, row: int) -> None:
            if disclaimer_text:
                ws.merge_range(row + 1, 0, row + 2, 5, disclaimer_text, disclaimer_fmt)

        # Sheet 1: KPI Header
        ws_kpi = wb.add_worksheet("KPI Header")
        kpi_items = [
            ("Total Net P&L", daily_summary.get("total_net_pnl", 0)),
            ("Net ROI %", daily_summary.get("net_roi_pct", 0)),
            ("Winning Strategies", daily_summary.get("winning_strategies", 0)),
            ("Losing Strategies", daily_summary.get("losing_strategies", 0)),
            ("Total Capital Deployed", daily_summary.get("total_capital_deployed", 0)),
            ("Total Charges", daily_summary.get("total_charges", 0)),
            ("Strategy Count", daily_summary.get("strategy_count", 0)),
            ("Report Date", str(daily_summary.get("report_date", ""))),
        ]
        ws_kpi.write_row(0, 0, ["Metric", "Value"], header_fmt)
        for i, (metric, val) in enumerate(kpi_items, start=1):
            ws_kpi.write(i, 0, metric)
            ws_kpi.write(i, 1, val)
        _write_disclaimer(ws_kpi, len(kpi_items) + 2)

        # Sheet 2: Strategy Cards
        ws_strat = wb.add_worksheet("Strategy Cards")
        if HAS_PANDAS and isinstance(strategy_runs_df, pd.DataFrame) and not strategy_runs_df.empty:
            cols = list(strategy_runs_df.columns)
            for c_i, col in enumerate(cols):
                ws_strat.write(0, c_i, col, header_fmt)
            for r_i, (_, row) in enumerate(strategy_runs_df.iterrows(), start=1):
                for c_i, col in enumerate(cols):
                    val = row[col]
                    try:
                        fval = float(val)
                        if "pnl" in col.lower() or "roi" in col.lower():
                            fmt = green_fmt if fval >= 0 else red_fmt
                        else:
                            fmt = num_fmt
                        ws_strat.write_number(r_i, c_i, fval, fmt)
                    except (ValueError, TypeError):
                        ws_strat.write(r_i, c_i, str(val) if val is not None else "")
            _write_disclaimer(ws_strat, len(strategy_runs_df) + 2)
        else:
            ws_strat.write(0, 0, "No strategy data")
            _write_disclaimer(ws_strat, 3)

        # Sheet 3: Trade Log (with auto-filter)
        ws_trade = wb.add_worksheet("Trade Log")
        if HAS_PANDAS and isinstance(matched_trades_df, pd.DataFrame) and not matched_trades_df.empty:
            cols = list(matched_trades_df.columns)
            for c_i, col in enumerate(cols):
                ws_trade.write(0, c_i, col, header_fmt)
            for r_i, (_, row) in enumerate(matched_trades_df.iterrows(), start=1):
                for c_i, col in enumerate(cols):
                    val = row[col]
                    try:
                        fval = float(val)
                        if "pnl" in col.lower():
                            fmt = green_fmt if fval >= 0 else red_fmt
                        else:
                            fmt = num_fmt
                        ws_trade.write_number(r_i, c_i, fval, fmt)
                    except (ValueError, TypeError):
                        ws_trade.write(r_i, c_i, str(val) if val is not None else "")
            ws_trade.autofilter(0, 0, len(matched_trades_df), len(cols) - 1)
            _write_disclaimer(ws_trade, len(matched_trades_df) + 2)
        else:
            ws_trade.write(0, 0, "No trade data")
            _write_disclaimer(ws_trade, 3)

        # Sheet 4: Charges Reconciliation
        ws_charges = wb.add_worksheet("Charges Reconciliation")
        if HAS_PANDAS and isinstance(charges_df, pd.DataFrame) and not charges_df.empty:
            cols = list(charges_df.columns)
            for c_i, col in enumerate(cols):
                ws_charges.write(0, c_i, col, header_fmt)
            for r_i, (_, row) in enumerate(charges_df.iterrows(), start=1):
                for c_i, col in enumerate(cols):
                    val = row[col]
                    try:
                        fval = float(val)
                        ws_charges.write_number(r_i, c_i, fval, num_fmt)
                    except (ValueError, TypeError):
                        ws_charges.write(r_i, c_i, str(val) if val is not None else "")
            _write_disclaimer(ws_charges, len(charges_df) + 2)
        else:
            ws_charges.write(0, 0, "No charges data")
            _write_disclaimer(ws_charges, 3)

        # Sheet 5: Appendix Methodology
        ws_appendix = wb.add_worksheet("Appendix Methodology")
        methodology_lines = [
            "Appendix: Methodology Notes",
            "",
            "1. Gross P&L = sum of matched trade P&L (buy price vs sell price x quantity).",
            "2. REALIZED charges sourced from Zerodha Virtual Contract Note (exact).",
            "3. FORMULA charges estimated per Zerodha fee schedule effective 2026-04-01.",
            "4. Net P&L = Gross P&L - Total Charges.",
            "5. ROI = Net P&L / Capital Deployed (from Tradetron operator card).",
            "6. SPAN+Exposure margins are audit-only approximations, NEVER used as ROI denominators.",
        ]
        for i, line in enumerate(methodology_lines):
            ws_appendix.write(i, 0, line)
        _write_disclaimer(ws_appendix, len(methodology_lines) + 2)

        wb.close()
        return {"success": True, "path": str(output_path)}

    except Exception as exc:
        return {"success": False, "error": f"Excel generation failed: {exc}"}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(
    output_dir: str | Path,
    trade_exec_df: Any,
    strategy_runs_df: Any,
    charges_df: Any,
) -> Dict[str, Any]:
    """Export 3 CSV files to output_dir."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files_written: List[str] = []

    def _write_csv(df: Any, filename: str) -> None:
        if df is not None and HAS_PANDAS and isinstance(df, pd.DataFrame) and not df.empty:
            path = output_dir / filename
            df.to_csv(str(path), index=False, encoding="utf-8")
            files_written.append(str(path))

    _write_csv(trade_exec_df, "trade_executions.csv")
    _write_csv(strategy_runs_df, "strategy_runs.csv")
    _write_csv(charges_df, "charges.csv")

    return {"success": True, "files": files_written}
