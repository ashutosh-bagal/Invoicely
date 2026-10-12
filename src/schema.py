from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from enum import Enum
from datetime import date


class Outcome(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class RuleStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class RuleResult(BaseModel):
    rule_name: str
    status: RuleStatus
    message: str


class ExtractedInvoice(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    po_number: Optional[str] = None
    total: Optional[Decimal] = None
    currency: str = "USD"
    extraction_notes: Optional[str] = None


class Decision(BaseModel):
    outcome: Outcome
    summary: str
    trace: List[RuleResult]
