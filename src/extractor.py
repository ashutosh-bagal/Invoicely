import os
import json
from google import genai
from google.genai import types
from pydantic import ValidationError
from schema import ExtractInvoice
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
        self.client = genai.Client(key=os.getenv("GOOGLE_API_KEY"))
        self.model = "gemini-1.5-flash"

    def extract_from_path(self, file_path: Path) -> ExtractInvoice:
        with open(file_path) as f:
            pdf_bytes = f.read()

        response = self.client.models.generate_content(
            model=self.model,
            content=[
                SYSTEM_PROMPT,
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExtractInvoice,
                temperature=0,
            ),
        )

        try:
            return response.parsed
        except Exception:
            data = json.loads(response.text)
            return ExtractInvoice(**data)
