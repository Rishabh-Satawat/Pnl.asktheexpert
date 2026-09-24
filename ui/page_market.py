"""Interactive TradingView index chart terminal."""
from __future__ import annotations

import json

try:
    import streamlit as st
    import streamlit.components.v1 as components
except ImportError:  # pragma: no cover
    st = components = None  # type: ignore[assignment]


MARKETS = {
    "🇮🇳 NIFTY 50": "NSE:NIFTY",
    "🏦 BANK NIFTY": "NSE:BANKNIFTY",
    "🏛️ BSE SENSEX": "BSE:SENSEX",
    "💳 FIN NIFTY": "NSE:FINNIFTY",
    "⚡ INDIA VIX": "NSE:INDIAVIX",
}


def render_market_terminal() -> None:
    if st is None or components is None:
        return
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("Market Charts & TradingView Terminal")
    st.caption("Interactive market chart provided by TradingView. Quotes, market coverage and delay depend on TradingView's data permissions and the exchange.")
    label = st.radio("Choose an index", list(MARKETS), horizontal=True, key="market_terminal_symbol")
    config = {
        "autosize": True,
        "symbol": MARKETS[label],
        "interval": "5",
        "timezone": "Asia/Kolkata",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "enable_publishing": False,
        "hide_top_toolbar": False,
        "allow_symbol_change": True,
        "calendar": False,
        "hide_side_toolbar": False,
        "withdateranges": True,
        "details": True,
        "hotlist": False,
        "studies": ["RSI@tv-basicstudies", "MASimple@tv-basicstudies"],
    }
    # json.dumps ensures symbols and widget settings cannot break the HTML/JS context.
    widget = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
    html = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;background:#0A1128">
<div class="tradingview-widget-container" style="height:650px;width:100%">
  <div class="tradingview-widget-container__widget" style="height:calc(100% - 32px);width:100%"></div>
  <div class="tradingview-widget-copyright" style="font:12px Arial;color:#94A3B8;padding:6px">
    <a href="https://www.tradingview.com/symbols/{MARKETS[label]}/" rel="noopener nofollow" target="_blank">{label} chart</a> by TradingView
  </div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>{widget}</script>
</div></body></html>"""
    components.html(html, height=675, scrolling=False)
    st.info("If the chart is blank, allow third-party TradingView content in your browser and check the symbol on TradingView. The ledger, report, and broker data remain available independently.")
