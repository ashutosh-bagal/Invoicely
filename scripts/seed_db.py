# scripts/seed_db.py
import sys
from pathlib import Path

# This line allows us to import from the 'src' folder
sys.path.append(str(Path(__file__).parent.parent))

from src.db import get_connection, init_db
from decimal import Decimal


def seed_data():
    init_db()  # Ensure tables exist

    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Insert Vendors
        vendors = [
            ("Acme Corp", "Acme, Acme Co", "TX-12345"),
            ("Global Tech Solutions", "Global Tech, GTS", "TX-99999"),
            ("Cyberdyne Systems", "Cyberdyne", "TX-00001"),
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO vendors (name, alias, tax_id) VALUES (?, ?, ?)",
            vendors,
        )

        # 2. Insert Purchase Orders
        pos = [
            ("PO-2024-001", 1, 1000.00, 1000.00, "USD", "OPEN"),
            ("PO-2024-002", 2, 500.00, 500.00, "USD", "OPEN"),
            ("PO-2024-003", 1, 5000.00, 5000.00, "USD", "OPEN"),
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO purchase_orders (po_number, vendor_id, total_amount, remaining_balance, currency, status) VALUES (?, ?, ?, ?, ?, ?)",
            pos,
        )

        conn.commit()
        print("🌱 Database seeded successfully!")


if __name__ == "__main__":
    seed_data()
