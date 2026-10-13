import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from src.db import get_connection, init_db
from src.extractor import InvoiceExtractor
from src.matcher import BusinessRulesEngine
from src.schema import Outcome

STAGES = ["INGEST", "EXTRACT", "DECIDE", "SAVE"]


class ProcessingPipeline:
    def __init__(self):
        init_db()  # make sure all tables (incl. run history) exist
        self.extractor = InvoiceExtractor()

    def _calculate_hash(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            hasher.update(f.read())
        return hasher.hexdigest()

    def _find_duplicate(self, file_hash: str) -> Optional[str]:
        """Returns the invoice number of an earlier invoice with this hash."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT invoice_number FROM processed_invoices WHERE file_hash = ?",
                (file_hash,),
            ).fetchone()
        return row[0] if row else None

    def run(
        self, file_path: Path, filename: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Executes the full end-to-end process.

        Yields an event before (RUNNING) and after (COMPLETED / FAILED) every
        stage so the UI can show live progress. The last event is always
        {"stage": "DONE", ...} carrying the id of the recorded run.
        """
        filename = filename or Path(file_path).name
        started = time.perf_counter()
        stage_log = []  # [{stage, status, duration_s, detail}]
        ctx: Dict[str, Any] = {
            "filename": filename,
            "status": "COMPLETED",
            "extracted": None,
            "decision": None,
            "error": None,
            "file_hash": None,
        }

        def finish(event):
            stage_log.append(
                {
                    "stage": event["stage"],
                    "status": event["status"],
                    "duration_s": round(event.get("duration", 0), 2),
                    "detail": event.get("detail") or event.get("error") or "",
                }
            )
            return event

        # --- STAGE 1: INGEST ---
        yield {"stage": "INGEST", "status": "RUNNING"}
        t = time.perf_counter()
        ctx["file_hash"] = self._calculate_hash(file_path)
        original = self._find_duplicate(ctx["file_hash"])
        detail = f"SHA-256 {ctx['file_hash'][:12]}…"
        if original:
            ctx["status"] = "DUPLICATE"
            ctx["error"] = f"Duplicate of already-processed invoice {original}."
            detail = ctx["error"]
        yield finish(
            {
                "stage": "INGEST",
                "status": "FAILED" if original else "COMPLETED",
                "duration": time.perf_counter() - t,
                "detail": detail,
                "error": ctx["error"],
            }
        )

        # --- STAGE 2: EXTRACT (AI) ---
        if ctx["status"] == "COMPLETED":
            yield {"stage": "EXTRACT", "status": "RUNNING"}
            t = time.perf_counter()
            try:
                ctx["extracted"] = self.extractor.extract_from_path(file_path)
                x = ctx["extracted"]
                yield finish(
                    {
                        "stage": "EXTRACT",
                        "status": "COMPLETED",
                        "duration": time.perf_counter() - t,
                        "detail": f"{x.vendor_name} · {x.invoice_number} · "
                        f"{x.total} {x.currency}",
                        "data": x,
                    }
                )
            except Exception as e:
                ctx["status"], ctx["error"] = "FAILED", str(e)
                yield finish(
                    {
                        "stage": "EXTRACT",
                        "status": "FAILED",
                        "duration": time.perf_counter() - t,
                        "error": str(e),
                    }
                )

        # --- STAGE 3: DECIDE (Rules Engine) ---
        if ctx["status"] == "COMPLETED":
            yield {"stage": "DECIDE", "status": "RUNNING"}
            t = time.perf_counter()
            try:
                ctx["decision"] = BusinessRulesEngine(ctx["extracted"]).evaluate()
                d = ctx["decision"]
                yield finish(
                    {
                        "stage": "DECIDE",
                        "status": "COMPLETED",
                        "duration": time.perf_counter() - t,
                        "detail": f"{d.outcome.value} — {len(d.trace)} rules checked",
                        "data": d,
                    }
                )
            except Exception as e:
                ctx["status"], ctx["error"] = "FAILED", str(e)
                yield finish(
                    {
                        "stage": "DECIDE",
                        "status": "FAILED",
                        "duration": time.perf_counter() - t,
                        "error": str(e),
                    }
                )

        # --- STAGE 4: SAVE (Database) ---
        if ctx["status"] == "COMPLETED":
            yield {"stage": "SAVE", "status": "RUNNING"}
            t = time.perf_counter()
            try:
                note = self._save_invoice(ctx)
                yield finish(
                    {
                        "stage": "SAVE",
                        "status": "COMPLETED",
                        "duration": time.perf_counter() - t,
                        "detail": note,
                    }
                )
            except Exception as e:
                ctx["status"], ctx["error"] = "FAILED", str(e)
                yield finish(
                    {
                        "stage": "SAVE",
                        "status": "FAILED",
                        "duration": time.perf_counter() - t,
                        "error": str(e),
                    }
                )

        run_id = self._record_run(ctx, stage_log, time.perf_counter() - started)
        yield {"stage": "DONE", "status": ctx["status"], "run_id": run_id}

    def _save_invoice(self, ctx) -> str:
        """Records the invoice and, if approved, draws down the PO balance."""
        extracted, decision = ctx["extracted"], ctx["decision"]
        with get_connection() as conn:
            row = conn.execute(
                "SELECT vendor_id FROM purchase_orders WHERE po_number = ?",
                (extracted.po_number,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO processed_invoices
                (invoice_number, vendor_id, total, file_hash)
                VALUES (?, ?, ?, ?)
                """,
                (
                    extracted.invoice_number,
                    row[0] if row else None,
                    float(extracted.total or 0),
                    ctx["file_hash"],
                ),
            )
            note = "Invoice recorded."
            if decision.outcome == Outcome.APPROVE and extracted.po_number:
                conn.execute(
                    """
                    UPDATE purchase_orders
                    SET remaining_balance = remaining_balance - ?
                    WHERE po_number = ?
                    """,
                    (float(extracted.total), extracted.po_number),
                )
                note = f"Invoice recorded; {extracted.po_number} balance reduced."
            conn.commit()
        return note

    def _record_run(self, ctx, stage_log, duration_s) -> int:
        x, d = ctx["extracted"], ctx["decision"]
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs
                (filename, file_hash, status, outcome, summary, error, vendor_name,
                 invoice_number, po_number, total, duration_s, extracted_json,
                 trace_json, stages_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ctx["filename"],
                    ctx["file_hash"],
                    ctx["status"],
                    d.outcome.value if d else None,
                    d.summary if d else None,
                    ctx["error"],
                    x.vendor_name if x else None,
                    x.invoice_number if x else None,
                    x.po_number if x else None,
                    float(x.total) if x and x.total is not None else None,
                    round(duration_s, 2),
                    x.model_dump_json() if x else None,
                    json.dumps([r.model_dump(mode="json") for r in d.trace])
                    if d
                    else None,
                    json.dumps(stage_log),
                ),
            )
            conn.commit()
            return cur.lastrowid
