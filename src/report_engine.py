"""Report generation engine: HTML, PDF (Playwright), Excel, CSV exports."""
from __future__ import annotations

import csv
import html as html_module
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
    sign = "" if val >= 0 else "-"
    formatted = f"{abs(val):,.2f}"
    return f"{sign}\u20b9{formatted}"


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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: #0B1426; color: #E2E8F0;
  font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
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

/* Strategy cards */
.strategy-cards-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
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
  .page { padding: 0; }
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
    ) -> str:
        """Return a complete HTML string with 6 sections."""
        report_date = daily_summary.get("report_date", str(date.today()))

        # --- KPI strip ---
        total_net = daily_summary.get("total_net_pnl", 0.0)
        net_roi = daily_summary.get("net_roi_pct", 0.0)
        wins = daily_summary.get("winning_strategies", 0)
        losses = daily_summary.get("losing_strategies", 0)
        capital = daily_summary.get("total_capital_deployed", 0.0)
        txn_drag = daily_summary.get("total_charges", 0.0)
        strat_count = daily_summary.get("strategy_count", 0)

        kpis_html = self._render_kpi_strip([
            {"label": "Total Net P&L", "value": _rupee(total_net), "color": _pnl_color(total_net)},
            {"label": "Net ROI", "value": _pct(net_roi), "color": _pnl_color(net_roi)},
            {"label": "Win / Loss", "value": f"{wins}W / {losses}L", "color": "#E2E8F0"},
            {"label": "Capital Deployed", "value": _rupee(capital), "color": "#E2E8F0"},
            {"label": "Txn Cost Drag", "value": _rupee(txn_drag), "color": "#EF4444"},
            {"label": "Strategies", "value": str(strat_count), "color": "#E2E8F0"},
        ])

        # --- Strategy cards ---
        strat_html = self._render_strategy_cards(strategy_runs_df)

        # --- Charts ---
        charts_html = self._render_charts_section(chart_divs)

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
  <div class="kpi-value" style="color:{k['color']}">{html_module.escape(k["value"])}</div>
  {sub_html}
</div>""")
        return f'<div class="kpi-tiles-grid">{"".join(tiles)}</div>'

    def _render_strategy_cards(self, strategy_runs_df: Any) -> str:
        if strategy_runs_df is None or (HAS_PANDAS and isinstance(strategy_runs_df, pd.DataFrame) and strategy_runs_df.empty):
            return '<div style="color:#64748B;">No strategy data available.</div>'

        cards = []
        rows = strategy_runs_df.to_dict("records") if HAS_PANDAS else []
        for row in rows:
            name = row.get("strategy_name", "Unknown")
            multiplier = row.get("multiplier", 1)
            status = row.get("deployment_status", "LIVE")
            gross = row.get("booked_gross_pnl", 0.0)
            charges = row.get("allocated_charges_total", 0.0)
            net = row.get("net_pnl", gross - charges)
            cap = row.get("capital_deployed_allocated", 0.0)
            roi = row.get("net_roi_pct", 0.0)
            segment = row.get("underlying_segment", "UNKNOWN")
            seg_color = self.segment_palette.get(segment, "#94A3B8")

            status_bg, status_color = _status_pill_styles(status)

            cards.append(f"""<div class="strategy-card">
  <div class="strategy-header">
    <div>
      <span class="strategy-name">{html_module.escape(str(name))}</span>
      <span class="multiplier-chip">{multiplier}x</span>
    </div>
    <span class="status-pill" style="background:{status_bg};color:{status_color};">{html_module.escape(str(status))}</span>
  </div>
  <div class="metrics-grid">
    <div><div class="metric-label">Gross P&amp;L</div><div style="color:{_pnl_color(gross)};font-weight:600;">{_rupee(gross)}</div></div>
    <div><div class="metric-label">Charges</div><div style="color:#EF4444;font-weight:600;">{_rupee(charges)}</div></div>
    <div><div class="metric-label">Net P&amp;L</div><div style="color:{_pnl_color(net)};font-weight:600;">{_rupee(net)}</div></div>
    <div><div class="metric-label">Capital Deployed</div><div style="color:#E2E8F0;font-weight:600;">{_rupee(cap)}</div></div>
    <div><div class="metric-label">Net ROI</div><div style="color:{_pnl_color(roi)};font-weight:600;">{_pct(roi)}</div></div>
    <div><div class="metric-label">Segment</div><div style="color:{seg_color};font-weight:600;">{html_module.escape(str(segment))}</div></div>
  </div>
</div>""")
        return "\n".join(cards)

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

        cols = list(matched_trades_df.columns)
        header = "".join(f"<th>{html_module.escape(str(c))}</th>" for c in cols)
        rows_html = []
        for _, row in matched_trades_df.iterrows():
            cells = "".join(f"<td>{html_module.escape(str(row[c]))}</td>" for c in cols)
            rows_html.append(f"<tr>{cells}</tr>")
        return f'<table class="trade-table"><thead><tr>{header}</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'

    def _render_charges_table(self, charges_df: Any) -> str:
        if charges_df is None or (HAS_PANDAS and isinstance(charges_df, pd.DataFrame) and charges_df.empty):
            return '<div style="color:#64748B;">No charges data.</div>'

        cols = list(charges_df.columns)
        header = "".join(f"<th>{html_module.escape(str(c))}</th>" for c in cols)
        rows_html = []
        for _, row in charges_df.iterrows():
            cells = "".join(f"<td>{html_module.escape(str(row[c]))}</td>" for c in cols)
            rows_html.append(f"<tr>{cells}</tr>")
        return f'<table class="charges-table"><thead><tr>{header}</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'


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
