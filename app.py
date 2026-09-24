"""Private Quant Desk P&L Engine & Daily Founder Reporting System v1.0"""
from __future__ import annotations

import os
import subprocess
import sys

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("Streamlit is required. Install via: pip install streamlit")

# Load secrets from .env (GEMINI_API_KEY, DHAN_*, APP_ACCESS_PASSWORD)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# Install Playwright Chromium on first run (needed on Streamlit Cloud / fresh servers)
_chromium_flag = os.path.join(os.path.dirname(__file__), ".playwright_installed")
if not os.path.exists(_chromium_flag) and not st.session_state.get("_playwright_install_attempted"):
    st.session_state["_playwright_install_attempted"] = True
    try:
        install_result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False, capture_output=True, text=True,
        )
        if install_result.returncode == 0:
            with open(_chromium_flag, "w", encoding="utf-8"):
                pass
    except Exception:
        pass  # Non-blocking — PDF will show error if truly missing

st.set_page_config(page_title="Quant Desk P&L Engine", page_icon="\U0001f4ca", layout="wide")

# Import and inject theme
from ui.apply_theme import inject_custom_css

inject_custom_css()

# ---------------------------------------------------------------------------
# Access gate (protects the public subdomain). Disabled when APP_ACCESS_PASSWORD is blank.
# ---------------------------------------------------------------------------
_APP_PASSWORD = os.environ.get("APP_ACCESS_PASSWORD", "").strip()


def _access_gate() -> bool:
    """Return True if the user is allowed to view the app."""
    if not _APP_PASSWORD:
        return True  # gate disabled locally
    if st.session_state.get("_authed"):
        return True
    st.markdown(
        '<div style="text-align:center;padding:3rem 1rem;">'
        '<h2 style="color:#E5E7EB;">\U0001f512 Private Quant Desk</h2>'
        '<p style="color:#94A3B8;">Enter the access password to continue.</p>'
        "</div>",
        unsafe_allow_html=True,
    )
    with st.form("access_gate"):
        pw = st.text_input("Access Password", type="password")
        submitted = st.form_submit_button("Unlock")
    if submitted and pw == _APP_PASSWORD:
        st.session_state["_authed"] = True
        st.rerun()
    elif submitted:
        st.error("Incorrect password.")
    st.stop()
    return False


if not _access_gate():
    st.stop()

# Sidebar navigation
page = st.sidebar.radio(
    "Navigation",
    [
        "\U0001f4f8 Daily Processing",
        "\U0001f4ca Historical Dashboard",
        "\U0001f4c8 Market Charts & TradingView Terminal",
        "\U0001f9e0 Settings & Knowledge Base",
        "\u2699\ufe0f Audit & Reconciliation",
    ],
)

if page == "\U0001f4f8 Daily Processing":
    from ui.page_daily import render_daily_processing

    render_daily_processing()
elif page == "\U0001f4ca Historical Dashboard":
    from ui.page_historical import render_historical_dashboard

    render_historical_dashboard()
elif page == "\U0001f4c8 Market Charts & TradingView Terminal":
    from ui.page_market import render_market_terminal

    render_market_terminal()
elif page == "\U0001f9e0 Settings & Knowledge Base":
    from ui.page_settings import render_settings

    render_settings()
elif page == "\u2699\ufe0f Audit & Reconciliation":
    from ui.page_audit import render_audit

    render_audit()

# Disclaimer footer on every page
st.markdown("---")
st.markdown(
    '<p class="disclaimer-footer">'
    "CONFIDENTIAL -- Internal Founder Audit Report. Not investment/financial advice. "
    "Capital Deployed sourced from Tradetron operator card / manual review. "
    "REALIZED charges from Zerodha Virtual Contract Note screenshot (exact). "
    "FORMULA charges estimated per Zerodha fee schedule effective 2026-04-01. "
    "SPAN + Exposure margins are secondary audit-only approximations and are NEVER used as ROI denominators. "
    "Always reconcile against official broker contract note. "
    "Past performance does not guarantee future results."
    "</p>",
    unsafe_allow_html=True,
)
