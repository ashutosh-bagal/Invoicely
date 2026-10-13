import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from src.db import get_connection, init_db, reset_demo_state
from src.pipeline import STAGES, ProcessingPipeline

st.set_page_config(page_title="Invoicely — AP Invoice Processor", page_icon="🧾", layout="wide")

SAMPLE_DIR = Path("data/inputs")
UPLOAD_DIR = Path("data/uploads")

STAGE_LABELS = {
    "INGEST": ("📥 Ingest", "Hash the file and check for duplicates"),
    "EXTRACT": ("🤖 Extract", "Gemini reads the PDF into structured data"),
    "DECIDE": ("⚖️ Decide", "Business rules: PO, vendor and amount checks"),
    "SAVE": ("💾 Save", "Record the invoice and update the PO balance"),
}
STATE_ICON = {"PENDING": "⚪", "RUNNING": "⏳", "COMPLETED": "✅", "FAILED": "❌"}
OUTCOME_STYLE = {
    "APPROVE": ("green", "✅"),
    "REVIEW": ("orange", "⚠️"),
    "REJECT": ("red", "⛔"),
}
RULE_ICON = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}


# ----------------------------------------------------------------- data access
def load_runs() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM runs ORDER BY id DESC", conn)


def load_run(run_id: int):
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def load_pos() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT po.po_number AS "PO", v.name AS "Vendor",
                   po.total_amount AS "Total", po.remaining_balance AS "Remaining"
            FROM purchase_orders po LEFT JOIN vendors v ON v.id = po.vendor_id
            ORDER BY po.po_number
            """,
            conn,
        )


def result_label(status: str, outcome: str | None) -> str:
    if status == "COMPLETED" and outcome:
        return f"{OUTCOME_STYLE[outcome][1]} {outcome}"
    return {"FAILED": "💥 FAILED", "DUPLICATE": "♻️ DUPLICATE"}.get(status, status)


# ------------------------------------------------------------------ live view
def render_stage(slot, stage: str, state: str, detail: str = "", duration=None):
    label, hint = STAGE_LABELS[stage]
    timing = f" · {duration:.1f}s" if duration is not None else ""
    text = f"{STATE_ICON[state]} **{label}**{timing}"
    if state == "PENDING":
        text += f"  \n:gray[{hint}]"
    elif state == "RUNNING":
        text += f"  \n:gray[{hint}…]"
    elif detail:
        text += f"  \n:{'red' if state == 'FAILED' else 'gray'}[{detail}]"
    slot.markdown(text)


def run_pipeline(pipeline, path: Path, name: str, container) -> int | None:
    """Runs one file, updating one stage card per pipeline stage as it happens."""
    container.markdown(f"**📄 {name}**")
    cols = container.columns(len(STAGES))
    slots = {}
    for col, stage in zip(cols, STAGES):
        with col:
            slots[stage] = st.container(border=True).empty()
        render_stage(slots[stage], stage, "PENDING")

    run_id = None
    for event in pipeline.run(path, filename=name):
        stage, status = event["stage"], event["status"]
        if stage == "DONE":
            run_id = event["run_id"]
        elif status == "RUNNING":
            render_stage(slots[stage], stage, "RUNNING")
        else:
            render_stage(
                slots[stage],
                stage,
                status,
                event.get("detail") or event.get("error") or "",
                event.get("duration"),
            )
    return run_id


# ------------------------------------------------------------------ run detail
def render_run(run: dict):
    """Full outputs of one run — used by the live view and the dashboard."""
    status, outcome = run["status"], run["outcome"]
    if outcome:
        color, icon = OUTCOME_STYLE[outcome]
        st.markdown(f"### {icon} :{color}[{outcome}]")
        st.write(run["summary"])
    elif status == "DUPLICATE":
        st.warning(f"♻️ {run['error']} Nothing was processed or saved.")
    else:
        st.error(f"💥 Run failed: {run['error']}")

    if run["extracted_json"]:
        m = st.columns(4)
        m[0].metric("Vendor", run["vendor_name"] or "—")
        m[1].metric("Invoice #", run["invoice_number"] or "—")
        m[2].metric("PO", run["po_number"] or "—")
        m[3].metric("Total", f"${run['total']:,.2f}" if run["total"] is not None else "—")

    left, right = st.columns(2)
    with left:
        st.markdown("**Audit trail**")
        if run["trace_json"]:
            for rule in json.loads(run["trace_json"]):
                st.write(f"{RULE_ICON[rule['status']]} **{rule['rule_name']}** — {rule['message']}")
        else:
            st.caption("No rules were evaluated.")
    with right:
        st.markdown("**Extracted data**")
        if run["extracted_json"]:
            st.json(json.loads(run["extracted_json"]), expanded=False)
        else:
            st.caption("Nothing extracted.")

    if run["stages_json"]:
        with st.expander(f"Stage timings · total {run['duration_s']}s"):
            st.dataframe(pd.DataFrame(json.loads(run["stages_json"])), hide_index=True, use_container_width=True)


# ------------------------------------------------------------------- dashboard
def render_dashboard():
    runs = load_runs()
    if runs.empty:
        st.info("No runs yet. Process an invoice from the **Live Run** tab and it will show up here.")
        return

    done = runs[runs["status"] == "COMPLETED"]
    approved = done[done["outcome"] == "APPROVE"]
    k = st.columns(6)
    k[0].metric("Total runs", len(runs))
    k[1].metric("✅ Approved", len(approved))
    k[2].metric("⚠️ Review", int((done["outcome"] == "REVIEW").sum()))
    k[3].metric("⛔ Rejected", int((done["outcome"] == "REJECT").sum()))
    k[4].metric("💥 Failed / ♻️ Dup", int((runs["status"] != "COMPLETED").sum()))
    k[5].metric("Approved value", f"${approved['total'].sum():,.0f}")

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Outcomes**")
        counts = runs.assign(r=[result_label(s, o) for s, o in zip(runs["status"], runs["outcome"])])["r"].value_counts()
        st.bar_chart(counts, height=240)
    with c2:
        st.markdown("**Purchase order utilisation**")
        pos = load_pos()
        pos["Used"] = (pos["Total"] - pos["Remaining"]) / pos["Total"]
        st.dataframe(
            pos,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Total": st.column_config.NumberColumn(format="$%.2f"),
                "Remaining": st.column_config.NumberColumn(format="$%.2f"),
                "Used": st.column_config.ProgressColumn("Used", min_value=0.0, max_value=1.0, format="%.0f%%"),
            },
        )

    st.markdown("**Run history**")
    runs["Result"] = [result_label(s, o) for s, o in zip(runs["status"], runs["outcome"])]
    options = sorted(runs["Result"].unique())
    chosen = st.multiselect("Filter by result", options, default=options)
    view = runs[runs["Result"].isin(chosen)]
    st.dataframe(
        view[["id", "created_at", "filename", "vendor_name", "invoice_number", "po_number", "total", "Result", "duration_s"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "id": st.column_config.NumberColumn("Run", width="small"),
            "created_at": "Time (UTC)",
            "filename": "File",
            "vendor_name": "Vendor",
            "invoice_number": "Invoice #",
            "po_number": "PO",
            "total": st.column_config.NumberColumn("Total", format="$%.2f"),
            "duration_s": st.column_config.NumberColumn("Seconds", format="%.1f"),
        },
    )

    st.markdown("**Inspect a run**")
    if view.empty:
        return
    labels = {f"#{r.id} · {r.filename} · {r.Result}": int(r.id) for r in view.itertuples()}
    picked = st.selectbox("Run", list(labels), label_visibility="collapsed")
    with st.container(border=True):
        render_run(load_run(labels[picked]))


# ------------------------------------------------------------------------ main
def main():
    init_db()
    st.title("🧾 Invoicely")
    st.caption("AI-assisted accounts-payable: extract → match against purchase orders → decide.")

    # ---- sidebar: inputs
    st.sidebar.header("Process invoices")
    uploaded = st.sidebar.file_uploader("Upload an invoice PDF", type=["pdf"])
    samples = sorted(SAMPLE_DIR.glob("*.pdf")) if SAMPLE_DIR.exists() else []
    sample_name = st.sidebar.selectbox(
        "…or pick a demo sample", ["—"] + [f.name for f in samples], disabled=uploaded is not None
    )

    to_run: list[tuple[Path, str]] = []
    if uploaded is not None:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path = UPLOAD_DIR / Path(uploaded.name).name
        path.write_bytes(uploaded.getbuffer())
        source = (path, uploaded.name)
    elif sample_name != "—":
        source = (SAMPLE_DIR / sample_name, sample_name)
    else:
        source = None

    if st.sidebar.button("▶ Run pipeline", type="primary", disabled=source is None, use_container_width=True):
        to_run = [source]
    if st.sidebar.button("⏩ Run all demo samples", disabled=not samples, use_container_width=True):
        to_run = [(p, p.name) for p in samples]

    st.sidebar.divider()
    if st.sidebar.button("🗑️ Reset demo state", use_container_width=True):
        reset_demo_state()
        st.session_state.pop("last_run_id", None)
        st.sidebar.success("History cleared and PO balances restored.")

    # ---- main area
    live_tab, dash_tab = st.tabs(["▶ Live Run", "📊 Dashboard"])

    with live_tab:
        if to_run:
            pipeline = ProcessingPipeline()
            for i, (path, name) in enumerate(to_run, start=1):
                box = st.container(border=len(to_run) > 1)
                st.session_state["last_run_id"] = run_pipeline(pipeline, path, name, box)
            if len(to_run) > 1:
                st.toast(f"Processed {len(to_run)} invoices — see the Dashboard tab.", icon="📊")
        else:
            cols = st.columns(len(STAGES))
            for col, stage in zip(cols, STAGES):
                with col:
                    render_stage(st.container(border=True).empty(), stage, "PENDING")

        run = load_run(st.session_state["last_run_id"]) if st.session_state.get("last_run_id") else None
        if run:
            st.divider()
            st.subheader(f"Result · {run['filename']}")
            render_run(run)
        elif not to_run:
            st.info("Upload an invoice or pick a demo sample in the sidebar, then press **Run pipeline**.")

    with dash_tab:
        render_dashboard()


if __name__ == "__main__":
    main()
