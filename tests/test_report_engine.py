from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.report_engine import (
    DailyReportGenerator,
    export_excel,
    export_pdf_playwright,
)

# FR-13 disclaimer (exact substring for assertion)
_FR13_DISCLAIMER = (
    "CONFIDENTIAL \u2014 Internal Founder Audit Report. Not investment/financial advice. "
    "Capital Deployed sourced from Tradetron operator card / manual review. "
    "REALIZED charges from Zerodha Virtual Contract Note screenshot (exact). "
    "FORMULA charges estimated per Zerodha fee schedule effective 2026-04-01. "
    "SPAN + Exposure margins are secondary audit-only approximations and are NEVER used "
    "as ROI denominators. Always reconcile against official broker contract note. "
    "Past performance does not guarantee future results."
)


# ---------------------------------------------------------------------------
# Shared synthetic data helpers
# ---------------------------------------------------------------------------

def _make_strategy_runs_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "strategy_run_id": "SR001",
            "strategy_name": "Iron Condor NIFTY",
            "deployment_status": "LIVE",
            "multiplier": 2,
            "capital_deployed_allocated": 500000.0,
            "booked_gross_pnl": 12500.0,
            "allocated_charges_total": 1850.0,
            "net_pnl": 10650.0,
            "net_roi_pct": 2.13,
            "underlying_segment": "NIFTY",
        },
        {
            "strategy_run_id": "SR002",
            "strategy_name": "Straddle BANKNIFTY",
            "deployment_status": "PAUSED",
            "multiplier": 1,
            "capital_deployed_allocated": 300000.0,
            "booked_gross_pnl": -4200.0,
            "allocated_charges_total": 920.0,
            "net_pnl": -5120.0,
            "net_roi_pct": -1.71,
            "underlying_segment": "BANKNIFTY",
        },
    ])


def _make_trades_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"trade_id": "T1", "strategy_run_id": "SR001", "instrument": "NIFTY 25000 CE", "side": "BUY", "qty": 50, "price": 120.0, "gross_pnl": 5000.0, "segment": "NIFTY"},
        {"trade_id": "T2", "strategy_run_id": "SR001", "instrument": "NIFTY 25000 PE", "side": "SELL", "qty": 50, "price": 80.0, "gross_pnl": 7500.0, "segment": "NIFTY"},
        {"trade_id": "T3", "strategy_run_id": "SR002", "instrument": "BANKNIFTY 52000 CE", "side": "BUY", "qty": 30, "price": 250.0, "gross_pnl": -2000.0, "segment": "BANKNIFTY"},
        {"trade_id": "T4", "strategy_run_id": "SR002", "instrument": "BANKNIFTY 52000 PE", "side": "SELL", "qty": 30, "price": 180.0, "gross_pnl": -2200.0, "segment": "BANKNIFTY"},
    ])


def _make_charges_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"charge_type": "Brokerage", "amount": 80.0, "source": "FORMULA"},
        {"charge_type": "STT", "amount": 450.0, "source": "FORMULA"},
        {"charge_type": "Exchange Txn", "amount": 120.0, "source": "FORMULA"},
        {"charge_type": "SEBI Fee", "amount": 5.50, "source": "FORMULA"},
        {"charge_type": "Stamp Duty", "amount": 35.0, "source": "FORMULA"},
        {"charge_type": "GST", "amount": 36.0, "source": "FORMULA"},
    ])


def _make_daily_summary() -> dict:
    return {
        "report_date": str(date(2026, 9, 19)),
        "total_net_pnl": 5530.0,
        "net_roi_pct": 0.69,
        "winning_strategies": 1,
        "losing_strategies": 1,
        "total_capital_deployed": 800000.0,
        "total_charges": 2770.0,
        "strategy_count": 2,
    }


def _make_chart_divs() -> dict:
    return {
        "Segment Contribution": '<div id="plotly-chart-donut" class="plotly-graph-div">mock donut</div>',
        "Gross vs Net P&L": '<div id="plotly-chart-bars" class="plotly-graph-div">mock bars</div>',
        "Transaction Cost Waterfall": '<div id="plotly-chart-waterfall" class="plotly-graph-div">mock waterfall</div>',
    }


# ---------------------------------------------------------------------------
# TR-10.1: HTML has 6 sections + FR-13 disclaimer + plotly chart div
# ---------------------------------------------------------------------------

class TestTR10_1_HTML:
    def test_tr_10_1_html_6_sections_and_disclaimer(self) -> None:
        gen = DailyReportGenerator()
        html_out = gen.render_daily_html(
            daily_summary=_make_daily_summary(),
            strategy_runs_df=_make_strategy_runs_df(),
            matched_trades_df=_make_trades_df(),
            charges_df=_make_charges_df(),
            chart_divs=_make_chart_divs(),
            disclaimer_text=_FR13_DISCLAIMER,
        )

        # Section heading checks (6 sections)
        assert "KPI" in html_out or "section-header-kpi" in html_out, "Missing KPI section"
        assert "Strategy" in html_out, "Missing Strategy section"
        assert "Analytics" in html_out or "Charts" in html_out, "Missing Analytics/Charts section"
        assert "Trade Log" in html_out, "Missing Trade Log section"
        assert "Charges" in html_out or "Reconciliation" in html_out, "Missing Charges/Reconciliation section"
        assert "Disclaimer" in html_out or "disclaimer" in html_out, "Missing Disclaimer section"

        # FR-13 disclaimer substring
        assert "Internal Founder Audit Report" in html_out, "FR-13 disclaimer text not found"
        assert "Past performance does not guarantee future results" in html_out, "FR-13 tail not found"

        # At least 1 plotly chart div present
        assert "plotly-graph-div" in html_out, "No plotly chart div found in HTML"

        print("[PASS] TR-10.1: HTML contains 6 sections, FR-13 disclaimer, and plotly chart div")

    def test_founder_report_uses_finite_multipliers_currency_entity_and_embedded_charts(self) -> None:
        runs = _make_strategy_runs_df()
        runs.loc[0, "multiplier_x"] = float("nan")
        runs.loc[0, "underlying_segment"] = "NIFTY"
        runs.loc[1, "strategy_name"] = "Test Strat"
        html_out = DailyReportGenerator().render_daily_html(
            daily_summary={**_make_daily_summary(), "total_gross_pnl": 8000, "gross_roi_pct": 1.0},
            strategy_runs_df=runs,
            matched_trades_df=_make_trades_df(),
            charges_df=_make_charges_df(),
            chart_divs={},
            disclaimer_text=_FR13_DISCLAIMER,
        )
        assert "nanx" not in html_out.lower()
        assert "Test Strat" not in html_out
        assert "&#8377;" in html_out
        assert "data:image/svg+xml;base64," in html_out
        assert "No charts generated." not in html_out


# ---------------------------------------------------------------------------
# TR-10.2: Excel has 5 sheets, Trade Log has data
# ---------------------------------------------------------------------------

class TestTR10_2_Excel:
    def test_tr_10_2_excel_5_sheets(self) -> None:
        try:
            import xlsxwriter  # noqa: F401
        except ImportError:
            pytest.skip("xlsxwriter not installed -- skipping Excel test")

        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not installed -- skipping Excel read-back test")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "test_report.xlsx"
            result = export_excel(
                output_path=out_path,
                daily_summary=_make_daily_summary(),
                strategy_runs_df=_make_strategy_runs_df(),
                matched_trades_df=_make_trades_df(),
                charges_df=_make_charges_df(),
                disclaimer_text=_FR13_DISCLAIMER,
            )
            assert result["success"], f"export_excel failed: {result.get('error')}"

            wb = openpyxl.load_workbook(str(out_path), read_only=True)
            sheet_names = wb.sheetnames
            wb.close()

            expected = ["KPI Header", "Strategy Cards", "Trade Log", "Charges Reconciliation", "Appendix Methodology"]
            for name in expected:
                assert name in sheet_names, f"Missing sheet: {name}"

            # Verify Trade Log has header + data rows
            wb2 = openpyxl.load_workbook(str(out_path), read_only=True)
            ws_trade = wb2["Trade Log"]
            row_count = sum(1 for _ in ws_trade.iter_rows())
            wb2.close()
            assert row_count >= 2, f"Trade Log should have header + data, got {row_count} rows"

        print("[PASS] TR-10.2: Excel has 5 sheets, Trade Log has header + data rows")


# ---------------------------------------------------------------------------
# TR-10.3: PDF smoke test (skip if playwright/chromium unavailable)
# ---------------------------------------------------------------------------

class TestTR10_3_PDF:
    def test_tr_10_3_pdf_smoke(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            pytest.skip("playwright not installed -- skipping PDF test")

        gen = DailyReportGenerator()
        html_out = gen.render_daily_html(
            daily_summary=_make_daily_summary(),
            strategy_runs_df=_make_strategy_runs_df(),
            matched_trades_df=_make_trades_df(),
            charges_df=_make_charges_df(),
            chart_divs=_make_chart_divs(),
            disclaimer_text=_FR13_DISCLAIMER,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "test_report.pdf"
            result = export_pdf_playwright(html_out, out_path)

            if not result["success"]:
                err = result.get("error", "")
                if "chromium" in err.lower() or "browser" in err.lower() or "executable" in err.lower():
                    pytest.skip(f"Chromium not available: {err}")
                pytest.fail(f"PDF export failed: {err}")

            assert out_path.exists(), "PDF file not created"
            size_kb = out_path.stat().st_size / 1024
            assert size_kb > 10, f"PDF too small ({size_kb:.1f} KB), expected > 10 KB"

        print("[PASS] TR-10.3: PDF generated successfully, size > 10KB")
