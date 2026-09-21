from __future__ import annotations

import os
from pathlib import Path

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_first_run() -> bool:
    """Check if this is first-run (no .env or empty GEMINI_API_KEY)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return True
    content = env_path.read_text(encoding="utf-8")
    if "GEMINI_API_KEY" not in content:
        return True
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("GEMINI_API_KEY"):
            val = stripped.split("=", 1)[-1].strip().strip('"').strip("'")
            if not val:
                return True
    return False


def render_settings() -> None:
    """Page 3: Settings & Knowledge Base - wizard, knowledge editors, cost playground."""
    if st is None:
        return

    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("Settings & Knowledge Base")

    # ── First-Run Wizard ──────────────────────────────────────────
    if _is_first_run():
        st.warning("First-run setup detected. Complete the wizard below to get started.")
        wizard_step = st.session_state.get("wizard_step", 1)

        if wizard_step == 1:
            st.subheader("Step 1: Gemini API Key")
            gemini_key = st.text_input("Gemini API Key", type="password", key="wiz_gemini_key")
            col_test, col_next = st.columns(2)
            with col_test:
                if st.button("Test Connection", key="wiz_test"):
                    if gemini_key:
                        st.success("Connection test placeholder - key provided.")
                    else:
                        st.error("Please enter a valid API key.")
            with col_next:
                if st.button("Next", key="wiz_next_1"):
                    st.session_state["wizard_step"] = 2
                    st.rerun()

        elif wizard_step == 2:
            st.subheader("Step 2: Dhan API Keys (Optional)")
            dhan_client = st.text_input("Dhan Client ID", key="wiz_dhan_client")
            dhan_token = st.text_input("Dhan Access Token", type="password", key="wiz_dhan_token")
            col_skip, col_next = st.columns(2)
            with col_skip:
                if st.button("Skip", key="wiz_skip_2"):
                    st.session_state["wizard_step"] = 3
                    st.rerun()
            with col_next:
                if st.button("Next", key="wiz_next_2"):
                    st.session_state["wizard_step"] = 3
                    st.rerun()

        elif wizard_step == 3:
            st.subheader("Step 3: Desk Branding")
            desk_name = st.text_input("Desk Name", value="QUANT DESK", key="wiz_desk_name")
            salutation = st.text_input("Founder Salutation", value="Dear Founder,", key="wiz_salutation")
            if st.button("Complete Setup", key="wiz_complete", type="primary"):
                st.success("Setup complete! Configure remaining settings below.")
                st.session_state["wizard_step"] = 4
                st.rerun()

    # ── Knowledge Base Editors ────────────────────────────────────
    st.markdown("---")
    st.subheader("Market Knowledge")
    knowledge_path = PROJECT_ROOT / "config" / "market_knowledge.yaml"
    if knowledge_path.exists() and yaml is not None:
        try:
            knowledge_data = yaml.safe_load(knowledge_path.read_text(encoding="utf-8"))
            if knowledge_data and pd is not None:
                if isinstance(knowledge_data, dict):
                    for section_name, section_data in knowledge_data.items():
                        st.markdown(f"**{section_name}**")
                        if isinstance(section_data, (list, dict)):
                            try:
                                df = pd.DataFrame(section_data) if isinstance(section_data, list) else pd.DataFrame([section_data])
                                st.data_editor(df, use_container_width=True, key=f"mk_{section_name}")
                            except Exception:
                                st.json(section_data)
                        else:
                            st.write(section_data)
        except Exception as exc:
            st.error(f"Error loading market knowledge: {exc}")
    else:
        st.caption("Market knowledge file not found or PyYAML not installed.")

    st.subheader("Broker Charge Schedule")
    charges_path = PROJECT_ROOT / "config" / "broker_charges.yaml"
    if charges_path.exists() and yaml is not None:
        try:
            charges_data = yaml.safe_load(charges_path.read_text(encoding="utf-8"))
            if charges_data and pd is not None:
                if isinstance(charges_data, dict):
                    for section_name, section_data in charges_data.items():
                        st.markdown(f"**{section_name}**")
                        if isinstance(section_data, (list, dict)):
                            try:
                                df = pd.DataFrame(section_data) if isinstance(section_data, list) else pd.DataFrame([section_data])
                                st.data_editor(df, use_container_width=True, key=f"bc_{section_name}")
                            except Exception:
                                st.json(section_data)
                        else:
                            st.write(section_data)
        except Exception as exc:
            st.error(f"Error loading broker charges: {exc}")
    else:
        st.caption("Broker charge schedule file not found or PyYAML not installed.")

    # ── Cost Calculator Playground ────────────────────────────────
    st.markdown("---")
    st.subheader("Cost Calculator Playground")
    pg_cols = st.columns(3)
    with pg_cols[0]:
        pg_segment = st.selectbox("Segment", ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"], key="pg_seg")
        pg_side = st.selectbox("Side", ["BUY", "SELL"], key="pg_side")
    with pg_cols[1]:
        pg_price = st.number_input("Execution Price", min_value=0.0, value=100.0, step=0.5, key="pg_price")
        pg_lots = st.number_input("Lots", min_value=1, value=1, step=1, key="pg_lots")
    with pg_cols[2]:
        pg_lot_size = st.number_input("Lot Size", min_value=1, value=25, step=1, key="pg_lot_size")
        pg_option_type = st.selectbox("Option Type", ["CE", "PE", "FUT"], key="pg_opt")

    if st.button("Calculate Charges", key="btn_calc_charges"):
        st.markdown(
            '<div class="kpi-card">'
            "<b>Charges Breakdown</b><br>"
            "Brokerage: -- | STT: -- | Exchange Txn: -- | GST: -- | SEBI: -- | Stamp: --<br>"
            "<b>Total: --</b>"
            "</div>",
            unsafe_allow_html=True,
        )

    # ── Branding Section ──────────────────────────────────────────
    st.markdown("---")
    st.subheader("Branding")
    branding_path = PROJECT_ROOT / "config" / "report_branding.yaml"
    if branding_path.exists() and yaml is not None:
        try:
            branding = yaml.safe_load(branding_path.read_text(encoding="utf-8"))
            desk_cfg = branding.get("desk", {})
            st.text_input("Desk Name", value=desk_cfg.get("name", ""), key="brand_desk_name")
            st.text_input("Salutation", value=desk_cfg.get("founder_salutation", ""), key="brand_salutation")
            disclaimer_cfg = branding.get("disclaimer", {})
            st.text_area(
                "Disclaimer Text",
                value=disclaimer_cfg.get("text", ""),
                height=120,
                key="brand_disclaimer",
            )
        except Exception as exc:
            st.error(f"Error loading branding config: {exc}")
    else:
        st.caption("Branding config not found.")
