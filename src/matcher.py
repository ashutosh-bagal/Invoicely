import sqlite3
from decimal import Decimal
from typing import List, Optional
from rapidfuzz import fuzz
from src.schema import ExtractedInvoice, Decision, Outcome, RuleResult, RuleStatus
from src.db import get_connection


class BusinessRulesEngine:
    def __init__(self, invoice: ExtractedInvoice):
        self.invoice = invoice
        self.trace: List[RuleResult] = []

    def _add_rule(self, name: str, status: RuleStatus, message: str):
        """Helper to log the outcome of each business rule."""
        self.trace.append(RuleResult(rule_name=name, status=status, message=message))

    def _lookup_po(self) -> Optional[dict]:
        """Queries the database to find the PO referenced in the invoice."""
        if not self.invoice.po_number:
            return None

        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT po.*, v.name as vendor_name 
                FROM purchase_orders po
                JOIN vendors v ON po.vendor_id = v.id
                WHERE po.po_number = ?
            """,
                (self.invoice.po_number,),
            )

            row = cursor.fetchone()
            return dict(row) if row else None

    def evaluate(self) -> Decision:
        # RULE 1: Integrity Check (Did the AI find the basics?)
        if (
            not self.invoice.invoice_number
            or self.invoice.total is None
            or not self.invoice.invoice_date
        ):
            self._add_rule(
                "Integrity",
                RuleStatus.FAIL,
                "Missing critical invoice information (Number, Total, or Date).",
            )
        else:
            self._add_rule("Integrity", RuleStatus.PASS, "All core fields present.")

        # RULE 2: PO Existence -  No PO means review
        po_data = self._lookup_po()
        if not po_data:
            return Decision(
                outcome=Outcome.REVIEW,
                summary="No matching Purchase Order found in the database.",
                trace=self.trace,
            )

        # RULE 3: Vendor Verification (Fuzzy Matching)
        # We compare extracted 'Acme' vs database 'Acme Corp'
        vendor_similarity = fuzz.token_set_ratio(
            self.invoice.vendor_name or "", po_data["vendor_name"]
        )
        if vendor_similarity < 85:
            self._add_rule(
                "Vendor Match",
                RuleStatus.FAIL,
                f"Vendor mismatch: '{self.invoice.vendor_name}' vs System '{po_data['vendor_name']}' ({vendor_similarity}% match)",
            )
        else:
            self._add_rule(
                "Vendor Match", RuleStatus.PASS, "Vendor name verified against PO."
            )

        # RULE 4: Amount Validation (The Money)
        inv_total = self.invoice.total or Decimal("0")
        po_balance = Decimal(str(po_data["remaining_balance"]))

        if inv_total <= po_balance:
            self._add_rule(
                "Amount",
                RuleStatus.PASS,
                f"Invoice total ${inv_total} is within PO balance of ${po_balance}.",
            )
        elif inv_total <= po_balance * Decimal("1.05"):
            # If within 5% tolerance, we flag it for REVIEW but don't REJECT
            self._add_rule(
                "Amount",
                RuleStatus.WARN,
                f"Invoice (${inv_total}) is slightly over balance (${po_balance}) but within 5% tolerance.",
            )
        else:
            self._add_rule(
                "Amount",
                RuleStatus.FAIL,
                f"Invoice total ${inv_total} exceeds PO balance of ${po_balance} significantly.",
            )

        # FINAL DECISION CALCULATION
        has_fail = any(r.status == RuleStatus.FAIL for r in self.trace)
        has_warn = any(r.status == RuleStatus.WARN for r in self.trace)

        if has_fail:
            return Decision(
                outcome=Outcome.REJECT,
                summary="Critical failures detected. Payment blocked.",
                trace=self.trace,
            )
        if has_warn:
            return Decision(
                outcome=Outcome.REVIEW,
                summary="Warnings found. Manual sign-off required.",
                trace=self.trace,
            )

        return Decision(
            outcome=Outcome.APPROVE,
            summary="Invoice matches PO. Ready for payment.",
            trace=self.trace,
        )
