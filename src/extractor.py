import os
import json
from google import genai
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


class InvoiceExtractor:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        self.model = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

    def extract_from_path(self, file_path: Path) -> ExtractedInvoice:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()

        response = self.client.models.generate_content(
            model=self.model,
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

        if isinstance(response.parsed, ExtractedInvoice):
            return response.parsed
        return ExtractedInvoice(**json.loads(response.text))
