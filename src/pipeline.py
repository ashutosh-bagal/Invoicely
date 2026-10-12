import hashlib
from enum import Enum
from pathlib import Path
from typing import Iterator, Dict, Any
from src.extractor import InvoiceExtractor
from src.db import get_connection
from src.schema import *


try:
    from src.matcher import BusinessRulesEngine, Outcome
except ImportError:  # Fallback if the matcher module does not export Outcome
    from src.matcher import BusinessRulesEngine

    class Outcome(Enum):
        APPROVE = "APPROVE"
        REJECT = "REJECT"
        MANUAL_REVIEW = "MANUAL_REVIEW"


class ProcessingPipeline:
    def __init__(self):
        self.extractor = InvoiceExtractor()

    def _calculate_hash(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            hasher.update(f.read())
        return hasher.hexdigest()

    def run(self, file_path: Path) -> Iterator[Dict[str, Any]]:
        """
        Executes the full end-to-end process.
        Yields status updates for the UI to display.
        """
        # --- STAGE 1: INGEST ---
        file_hash = self._calculate_hash(file_path)
        yield {"stage": "INGEST", "status": "COMPLETED", "data": {"hash": file_hash}}

        # --- STAGE 2: EXTRACT (AI) ---
        try:
            extracted_data = self.extractor.extract_from_path(file_path)
            yield {"stage": "EXTRACT", "status": "COMPLETED", "data": extracted_data}
        except Exception as e:
            yield {"stage": "EXTRACT", "status": "FAILED", "error": str(e)}
            return

        # --- STAGE 3: DECIDE (Rules Engine) ---
        try:
            engine = BusinessRulesEngine(extracted_data)
            decision = engine.evaluate()
            yield {"stage": "DECIDE", "status": "COMPLETED", "data": decision}
        except Exception as e:
            yield {"stage": "DECIDE", "status": "FAILED", "error": str(e)}
            return

        # --- STAGE 4: PERSIST (Database) ---
        try:
            saved = self._save_run(file_path, file_hash, extracted_data, decision)
            yield {
                "stage": "SAVE",
                "status": "COMPLETED",
                "data": {"duplicate": not saved},
            }
        except Exception as e:
            yield {"stage": "SAVE", "status": "FAILED", "error": str(e)}

    def _save_run(self, file_path, file_hash, extracted, decision):
        """Saves the run and UPDATES the PO balance."""
        with get_connection() as conn:
            cursor = conn.cursor()

            # 1. Record the invoice
            cursor.execute(
                """
                INSERT INTO processed_invoices 
                (invoice_number, vendor_id, total, file_hash)
                VALUES (?, ?, ?, ?)
            """,
                (extracted.invoice_number, 1, float(extracted.total), file_hash),
            )

            # 2. IF APPROVED: Subtract the amount from the PO balance
            if decision.outcome == Outcome.APPROVE and extracted.po_number:
                cursor.execute(
                    """
                    UPDATE purchase_orders 
                    SET remaining_balance = remaining_balance - ?
                    WHERE po_number = ?
                """,
                    (float(extracted.total), extracted.po_number),
                )

            conn.commit()

    # def _save_run(self, file_path, file_hash, extracted, decision):
    #     with get_connection() as conn:
    #         cursor = conn.cursor()
    #         cursor.execute(
    #             "SELECT 1 FROM processed_invoices WHERE file_hash = ?", (file_hash,)
    #         )
    #         if cursor.fetchone():
    #             return False  # already processed; don't insert a duplicate
    #         row = cursor.execute(
    #             "SELECT vendor_id FROM purchase_orders WHERE po_number = ?",
    #             (extracted.po_number,),
    #         ).fetchone()
    #         vendor_id = row[0] if row else None
    #         cursor.execute(
    #             """
    #             INSERT INTO processed_invoices
    #             (invoice_number, vendor_id, total, file_hash)
    #             VALUES (?, ?, ?, ?)
    #         """,
    #             (
    #                 extracted.invoice_number,
    #                 vendor_id,
    #                 float(extracted.total),
    #                 file_hash,
    #             ),
    #         )
    #         conn.commit()
    #     return True
