import os
import json
import time
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError
from src.schema import ExtractedInvoice
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

SYSTEM_PROMPT = """
You are an expert Accounts Payable (AP) specialist. 
Your task is to extract structured data from invoice documents.

RULES:
1. Output ONLY valid JSON matching the requested schema.
2. If a field is missing, set it to null.
3. For numeric values (total, subtotal, tax), do not include currency symbols.
4. Extract the PO Number specifically if it exists.
"""


FALLBACK_MODELS = ["gemini-flash-latest", "gemini-3.5-flash", "gemini-3.6-flash"]


class InvoiceExtractor:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        primary = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
        self.models = [primary] + [m for m in FALLBACK_MODELS if m != primary]

    def extract_from_path(self, file_path: Path) -> ExtractedInvoice:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()

        response = self._generate_with_retry(pdf_bytes)

        if isinstance(response.parsed, ExtractedInvoice):
            return response.parsed
        return ExtractedInvoice(**json.loads(response.text))

    def _generate_with_retry(self, pdf_bytes: bytes, rounds: int = 2):
        """Gemini intermittently answers 503 'high demand' per model, so walk
        the fallback chain (cheapest/fastest first) before giving up."""
        for round_no in range(rounds):
            for model in self.models:
                try:
                    return self._generate(pdf_bytes, model)
                except genai_errors.ServerError as e:
                    last_error = e
            time.sleep(2)
        raise last_error

    def _generate(self, pdf_bytes: bytes, model: str):
        return self.client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                "Extract the invoice data from this document.",
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ExtractedInvoice,
                temperature=0,
            ),
        )
