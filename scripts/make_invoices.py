# scripts/make_invoices.py
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER
from pathlib import Path

OUTPUT_DIR = Path("data/inputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_invoice(
    filename,
    vendor_name,
    inv_number,
    amount,
    po_number=None,
    date="2024-05-01",
    layout="standard",
):
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=LETTER)

    # Simple Layout Logic
    if layout == "standard":
        c.setFont("Helvetica-Bold", 20)
        c.drawString(50, 750, vendor_name)
        c.setFont("Helvetica", 12)
        c.drawString(50, 735, "123 Business Lane, New York, NY")

        c.drawString(400, 750, f"INVOICE #: {inv_number}")
        c.drawString(400, 735, f"Date: {date}")
    else:
        c.setFont("Courier-Bold", 18)
        c.drawCentredString(300, 770, f"*** {vendor_name} ***")
        c.setFont("Courier", 11)
        c.drawString(50, 700, f"BILLING REF: {inv_number}")
        c.drawString(50, 685, f"ISSUED ON: {date}")

    # The Money Part
    c.line(50, 650, 550, 650)
    c.drawString(50, 630, "Description")
    c.drawString(450, 630, "Total")
    c.line(50, 620, 550, 620)

    c.drawString(50, 600, "Professional Services Rendered")
    c.drawString(450, 600, f"${amount:.2f}")

    if po_number:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, 500, f"PO REFERENCE: {po_number}")

    c.setFont("Helvetica-Bold", 14)
    c.drawString(350, 450, f"GRAND TOTAL: ${amount:.2f}")

    c.save()
    print(f"📄 Generated: {filename}")


def generate_all():
    create_invoice("01_happy.pdf", "Acme Corp", "INV-1001", 1000.00, "PO-2024-001")

    create_invoice(
        "02_tolerance.pdf", "Global Tech Solutions", "INV-2002", 515.00, "PO-2024-002"
    )

    create_invoice("03a_split.pdf", "Acme Corp", "INV-3001", 3000.00, "PO-2024-003")
    create_invoice("03b_split.pdf", "Acme Corp", "INV-3002", 2500.00, "PO-2024-003")

    create_invoice(
        "04_no_po.pdf", "Global Tech Solutions", "INV-4004", 500.00, layout="modern"
    )

    create_invoice(
        "06_missing_date.pdf",
        "Cyberdyne Systems",
        "INV-6006",
        99.00,
        po_number="PO-999",
        date="",
    )


if __name__ == "__main__":
    generate_all()
