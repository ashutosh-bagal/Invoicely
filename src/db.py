import sqlite3
from pathlib import Path

DB_PATH = Path("data/procurement.db")


def get_connection():
    """Returns a connection to the SQLite database."""
    # Ensure the data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    """Sets up the database tables."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Vendors Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                alias TEXT, 
                tax_id TEXT UNIQUE,
                is_approved INTEGER DEFAULT 1
            )
        """)

        # 2. Purchase Orders Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                po_number TEXT PRIMARY KEY,
                vendor_id INTEGER,
                total_amount DECIMAL NOT NULL,
                remaining_balance DECIMAL NOT NULL,
                currency TEXT DEFAULT 'USD',
                status TEXT DEFAULT 'OPEN',
                FOREIGN KEY (vendor_id) REFERENCES vendors (id)
            )
        """)

        # 3. Processed Invoices (To detect duplicates)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT,
                vendor_id INTEGER,
                total DECIMAL,
                file_hash TEXT UNIQUE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


if __name__ == "__main__":
    init_db()
    print("✅ Database initialized at data/procurement.db")
