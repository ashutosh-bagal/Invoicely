import hashlib
from pathlib import Path
from typing import Iterator, Dict, Any
from src.extractor import InvoiceExtractor
from src.matcher import BusinessRulesEngine
from src.db import get_connection


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
            self._save_run(file_path, file_hash, extracted_data, decision)
            yield {"stage": "SAVE", "status": "COMPLETED"}
        except Exception as e:
            yield {"stage": "SAVE", "status": "FAILED", "error": str(e)}

    def _save_run(self, file_path, file_hash, extracted, decision):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO processed_invoices 
                (invoice_number, vendor_id, total, file_hash)
                VALUES (?, ?, ?, ?)
            """,
                (
                    extracted.invoice_number,
                    1,  # In a real app, we'd look up the actual vendor ID
                    float(extracted.total),
                    file_hash,
                ),
            )
            conn.commit()
