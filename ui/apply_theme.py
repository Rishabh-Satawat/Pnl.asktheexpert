from __future__ import annotations

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]


def inject_custom_css() -> None:
    """Inject the custom dark trading-desk CSS theme into the Streamlit app."""
    if st is None:
        return  # graceful degradation when streamlit is not installed

    css = """
    <style>
    /* ── Google Fonts ─────────────────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
    }
    code, pre, .stCode, [data-testid="stCode"] {
        font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace !important;
    }

    /* ── Accent Bar ───────────────────────────────────────────── */
    .accent-bar {
        height: 3px;
        background: linear-gradient(90deg, #6366F1, #A855F7, #06B6D4);
        border-radius: 2px;
        margin-bottom: 1rem;
    }

    /* ── KPI Card (glassmorphism) ─────────────────────────────── */
    .kpi-card {
        background: rgba(18, 31, 61, 0.72);
        backdrop-filter: blur(18px) saturate(150%);
        -webkit-backdrop-filter: blur(18px) saturate(150%);
        border: 1px solid rgba(99, 102, 241, 0.22);
        border-radius: 16px;
        padding: 1.2rem 1.4rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.45);
    }

    /* ── P&L Colors ───────────────────────────────────────────── */
    .pnl-positive {
        color: #10B981;
        text-shadow: 0 0 12px rgba(16, 185, 129, 0.22);
    }
    .pnl-negative {
        color: #EF4444;
        text-shadow: 0 0 12px rgba(239, 68, 68, 0.22);
    }

    /* ── Strategy Card (glassmorphism) ────────────────────────── */
    .strategy-card {
        background: rgba(18, 31, 61, 0.72);
        backdrop-filter: blur(18px) saturate(150%);
        -webkit-backdrop-filter: blur(18px) saturate(150%);
        border: 1px solid rgba(99, 102, 241, 0.22);
        border-radius: 16px;
        padding: 1rem 1.2rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
        margin-bottom: 0.8rem;
    }
    .strategy-card .strategy-name {
        font-weight: 700;
        font-size: 1.05rem;
        color: #E5E7EB;
    }
    .strategy-card .multiplier-chip {
        display: inline-block;
        background: rgba(99, 102, 241, 0.18);
        color: #A5B4FC;
        border-radius: 999px;
        padding: 0.15rem 0.6rem;
        font-size: 0.78rem;
        font-weight: 600;
        margin-left: 0.4rem;
    }
    .strategy-card .deploy-status-pill {
        display: inline-block;
        border-radius: 999px;
        padding: 0.15rem 0.6rem;
        font-size: 0.72rem;
        font-weight: 600;
        margin-left: 0.4rem;
    }
    .strategy-card .deploy-status-pill.active {
        background: rgba(16, 185, 129, 0.18);
        color: #10B981;
    }
    .strategy-card .deploy-status-pill.paused {
        background: rgba(245, 158, 11, 0.18);
        color: #F59E0B;
    }

    /* ── Disclaimer Footer ────────────────────────────────────── */
    .disclaimer-footer {
        font-size: 10px;
        font-weight: bold;
        color: #64748B;
        line-height: 1.5;
    }

    /* ── Custom Scrollbar ─────────────────────────────────────── */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: #0B1426;
    }
    ::-webkit-scrollbar-thumb {
        background: #1E3A5F;
        border-radius: 3px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #2D4A6F;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
