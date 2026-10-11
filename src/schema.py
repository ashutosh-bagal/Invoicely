from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from enum import Enum
from datetime import date


class Outcome(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class ExtractInvoice(BaseModel):
    vendor_name: str
    invoice_number: str
    invoice_date: Optional[date] = None
    po_number: Optional[str] = None
    total: Decimal
    currency: str = "USD"
