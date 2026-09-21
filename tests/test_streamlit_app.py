from __future__ import annotations

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_PY = PROJECT_ROOT / "app.py"


def test_tr_12_1_smoke_import_no_crash():
    """TR-12.1: Import page functions without running Streamlit - no crash on import."""
    from ui.page_daily import render_daily_processing
    from ui.page_historical import render_historical_dashboard
    from ui.page_settings import render_settings
    from ui.page_audit import render_audit
    from ui.apply_theme import inject_custom_css

    # All imports succeed without crashing
    assert callable(render_daily_processing)
    assert callable(render_historical_dashboard)
    assert callable(render_settings)
    assert callable(render_audit)
    assert callable(inject_custom_css)


def test_tr_12_2_disclaimer_text_present():
    """TR-12.2: app.py contains the required disclaimer text."""
    content = APP_PY.read_text(encoding="utf-8")
    assert "CONFIDENTIAL" in content, "Disclaimer must contain 'CONFIDENTIAL'"
    assert "Internal Founder Audit Report" in content, (
        "Disclaimer must contain 'Internal Founder Audit Report'"
    )


def test_tr_12_3_four_page_labels_exact():
    """TR-12.3: app.py contains all 4 exact page labels."""
    content = APP_PY.read_text(encoding="utf-8")
    required_labels = [
        "Daily Processing",
        "Historical Dashboard",
        "Settings & Knowledge Base",
        "Audit & Reconciliation",
    ]
    for label in required_labels:
        assert label in content, f"Page label '{label}' not found in app.py"
