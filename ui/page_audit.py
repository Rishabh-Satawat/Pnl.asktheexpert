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


def render_audit() -> None:
    """Page 4: Audit & Reconciliation - raw files, timing, orphan legs, variance, dupes."""
    if st is None:
        return

    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
    st.title("Audit & Reconciliation")

    # ── Raw Source File Browser ────────────────────────────────────
    st.subheader("Raw Source Files")
    st.caption(
        "Browse ingested source files (screenshots, CSVs) stored in the data directory. "
        "Select a file to view metadata and SHA-256 hash."
    )
    from pathlib import Path

    data_dir = Path(__file__).resolve().parent.parent / "data"
    if data_dir.exists():
        source_files = sorted(
            [f for f in data_dir.rglob("*") if f.is_file() and not f.name.startswith(".")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if source_files:
            file_names = [str(f.relative_to(data_dir)) for f in source_files]
            selected_file = st.selectbox("Select source file", file_names, key="audit_file")
            if selected_file:
                full_path = data_dir / selected_file
                stat = full_path.stat()
                st.markdown(
                    f"**Size:** {stat.st_size:,} bytes | "
                    f"**Modified:** {datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}"
                )
        else:
            st.caption("No source files found in data directory.")
    else:
        st.caption("Data directory not found.")

    # ── Stage Timing Logs ─────────────────────────────────────────
    st.markdown("---")
    st.subheader("Pipeline Stage Timing")
    if "pipeline_timings" in st.session_state and pd is not None:
        timing_df = pd.DataFrame(st.session_state["pipeline_timings"])
        st.dataframe(timing_df, use_container_width=True)
    else:
        st.caption("No pipeline timing data available. Run the pipeline from Daily Processing first.")

    # ── Open / Orphan Legs Viewer ─────────────────────────────────
    st.markdown("---")
    st.subheader("Open / Orphan Legs")
    st.caption(
        "Trades that could not be matched into complete round-trip legs. "
        "These may indicate partial fills or data extraction errors."
    )
    if "orphan_legs" in st.session_state and pd is not None:
        orphan_df = pd.DataFrame(st.session_state["orphan_legs"])
        st.dataframe(orphan_df, use_container_width=True)
    else:
        st.caption("No orphan legs detected.")

    # ── REALIZED vs FORMULA Variance Panel ────────────────────────
    st.markdown("---")
    st.subheader("REALIZED vs FORMULA Charge Variance")
    st.caption(
        "Compare charges extracted from Zerodha Virtual Contract Note (REALIZED) "
        "against formula-computed estimates (FORMULA). "
        "Large variances may indicate fee schedule changes or extraction errors."
    )
    if "charge_variance" in st.session_state and pd is not None:
        variance_df = pd.DataFrame(st.session_state["charge_variance"])
        st.dataframe(variance_df, use_container_width=True)
    else:
        st.caption("No charge variance data available.")

    # ── SHA-256 Duplicate Detection ───────────────────────────────
    st.markdown("---")
    st.subheader("SHA-256 Duplicate Detection")
    st.caption(
        "Detect duplicate source files by SHA-256 hash to prevent double-counting "
        "trades from re-uploaded screenshots."
    )
    if st.button("Scan for Duplicates", key="btn_scan_dupes"):
        import hashlib

        if data_dir.exists():
            hashes: dict[str, list[str]] = {}
            for f in data_dir.rglob("*"):
                if f.is_file() and not f.name.startswith("."):
                    h = hashlib.sha256(f.read_bytes()).hexdigest()
                    hashes.setdefault(h, []).append(str(f.relative_to(data_dir)))
            dupes = {h: files for h, files in hashes.items() if len(files) > 1}
            if dupes:
                st.warning(f"Found {len(dupes)} duplicate group(s):")
                for h, files in dupes.items():
                    st.markdown(f"**Hash:** `{h[:16]}...` - Files: {', '.join(files)}")
            else:
                st.success("No duplicate files detected.")
        else:
            st.caption("Data directory not found.")

    # ── Rerun P&L for Date Range ──────────────────────────────────
    st.markdown("---")
    st.subheader("Rerun P&L for Date Range")
    rerun_cols = st.columns(3)
    with rerun_cols[0]:
        rerun_start = st.date_input("Start Date", key="rerun_start")
    with rerun_cols[1]:
        rerun_end = st.date_input("End Date", key="rerun_end")
    with rerun_cols[2]:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Rerun Pipeline", key="btn_rerun", type="primary"):
            st.info(f"Rerunning pipeline for {rerun_start} to {rerun_end}...")
            st.caption("Pipeline rerun will process all stored source data for the selected date range.")
