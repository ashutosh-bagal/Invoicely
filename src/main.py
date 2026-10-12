import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from src.db import get_connection
from src.pipeline import ProcessingPipeline
from src.schema import Outcome, RuleStatus

st.set_page_config(page_title="Zamp AI Invoice Processor", layout="wide")


def render_rule_result(result):
    """Translates a technical RuleResult into a simple UI row."""
    icon = (
        "✅"
        if result.status == RuleStatus.PASS
        else "⚠️"
        if result.status == RuleStatus.WARN
        else "❌"
    )
    st.write(f"{icon} **{result.rule_name}**: {result.message}")


def main():
    st.title("🛡️ Invoicely — AP Invoice Processor")
    st.write("Upload an invoice PDF to see the automated decision pipeline in action.")

    st.sidebar.header("Controls")
    pipeline = ProcessingPipeline()

    # 1. File Selection
    uploaded_file = st.sidebar.file_uploader("Upload Invoice PDF", type=["pdf"])

    # 2. Demo Shortcuts (Senior move: makes the live demo faster)
    st.sidebar.subheader("Demo Samples")
    sample_dir = Path("data/inputs")
    selected_sample = "None"
    if sample_dir.exists():
        sample_files = list(sample_dir.glob("*.pdf"))
        selected_sample = st.sidebar.selectbox(
            "Quick Select Sample", ["None"] + [f.name for f in sample_files]
        )

    if st.sidebar.button("🗑️ Reset Demo State"):
        # seed_db.py uses INSERT OR IGNORE, so it can't undo processed runs;
        # clear them directly and restore PO balances.
        with get_connection() as conn:
            conn.execute("DELETE FROM processed_invoices")
            conn.execute("UPDATE purchase_orders SET remaining_balance = total_amount")
            conn.commit()
        st.sidebar.success("Database reset to original state!")

    # Logic to decide which file to process
    file_to_process = None
    if uploaded_file:
        # Save uploaded file temporarily
        temp_path = Path("data/uploads") / Path(uploaded_file.name).name
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        file_to_process = temp_path
    elif selected_sample != "None":
        file_to_process = sample_dir / selected_sample

    if file_to_process:
        decision = None
        extracted_data = None
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("Pipeline Execution")
            status_container = st.container(border=True)

            # RUN THE PIPELINE
            # This is where the 'Generator' magic happens
            for event in pipeline.run(file_to_process):
                stage = event["stage"]
                status = event["status"]

                if stage == "SAVE" and status == "COMPLETED":
                    if event["data"]["duplicate"]:
                        status_container.warning(
                            "Duplicate file: already processed, not saved again."
                        )
                        continue
                if status == "COMPLETED":
                    status_container.write(f"✔️ {stage} stage finished.")
                elif status == "FAILED":
                    status_container.error(
                        f"❌ {stage} stage failed: {event.get('error')}"
                    )

                # If we finished DECIDE stage, store the decision for column 2
                if stage == "DECIDE" and status == "COMPLETED":
                    decision = event["data"]
                if stage == "EXTRACT" and status == "COMPLETED":
                    extracted_data = event["data"]

        with col2:
            st.subheader("System Decision")
            if decision is not None:
                # Display the Outcome with a clean Badge
                color = (
                    "green"
                    if decision.outcome == Outcome.APPROVE
                    else "orange"
                    if decision.outcome == Outcome.REVIEW
                    else "red"
                )
                st.markdown(f"### Outcome: :{color}[{decision.outcome.value}]")
                st.info(f"**Summary:** {decision.summary}")

                with st.expander("View Audit Trail (Rules)", expanded=True):
                    for rule in decision.trace:
                        render_rule_result(rule)

                with st.expander("View Extracted Data"):
                    st.json(extracted_data.model_dump(mode="json"))


if __name__ == "__main__":
    main()
