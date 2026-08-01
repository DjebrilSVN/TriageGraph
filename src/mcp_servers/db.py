"""Database initialization and seed data for TriageGraph MCP servers.

Provides persistent SQLite tables for:
- CRM: Customers, Orders, Invoices, Refunds
- Knowledge Base: Documentation articles and Operational Runbooks
- Tickets: Ticket records, Internal notes, Department escalations
"""

import os
import sqlite3
from typing import Optional

DEFAULT_DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "triage_data.db")
)


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> str:
    path = db_path or DEFAULT_DB_PATH
    conn = get_db_connection(path)
    cursor = conn.cursor()

    # --- CRM Tables ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            tier TEXT NOT NULL, -- Free, Pro, Enterprise
            status TEXT NOT NULL, -- Active, Suspended, Delinquent
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            item_description TEXT NOT NULL,
            order_date TEXT NOT NULL,
            status TEXT NOT NULL, -- Paid, Refunded, Disputed
            FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS refunds (
            refund_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL, -- Approved, Auto-Approved, Pending_Review, Rejected
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(order_id) REFERENCES orders(order_id),
            FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
        )
        """
    )

    # --- Knowledge Base Tables ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_docs (
            doc_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            tags TEXT NOT NULL,
            content TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS runbooks (
            runbook_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applicable_scenario TEXT NOT NULL,
            steps_markdown TEXT NOT NULL
        )
        """
    )

    # --- Ticket Tables ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL, -- billing, technical, account, general
            urgency TEXT NOT NULL, -- low, medium, high, urgent
            status TEXT NOT NULL, -- open, pending_approval, resolved, escalated
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_notes (
            note_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL,
            author TEXT NOT NULL,
            note_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS escalations (
            escalation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL,
            target_department TEXT NOT NULL,
            reason TEXT NOT NULL,
            escalated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id)
        )
        """
    )

    conn.commit()
    seed_data(conn)
    conn.close()
    return path


def seed_data(conn: sqlite3.Connection):
    cursor = conn.cursor()

    # Seed Customers
    customers = [
        ("cust_001", "Alice Johnson", "alice@enterprise.com", "Enterprise", "Active"),
        ("cust_002", "Bob Smith", "bob@smith.org", "Pro", "Active"),
        ("cust_003", "Charlie Davis", "charlie@startup.io", "Free", "Suspended"),
        ("cust_004", "Diana Prince", "diana@themyscira.net", "Pro", "Active"),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO customers (customer_id, name, email, tier, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        customers,
    )

    # Seed Orders
    orders = [
        ("ord_101", "cust_001", 120.00, "USD", "Annual Enterprise Addon", "2026-09-15", "Paid"),
        ("ord_102", "cust_002", 15.00, "USD", "Storage Expansion 50GB", "2026-10-10", "Paid"),
        ("ord_103", "cust_002", 85.00, "USD", "Team Seat Upgrade", "2026-10-01", "Paid"),
        ("ord_104", "cust_004", 250.00, "USD", "Dedicated IP Address", "2026-10-05", "Paid"),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO orders (order_id, customer_id, amount, currency, item_description, order_date, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        orders,
    )

    # Seed Knowledge Base Docs
    kb_docs = [
        (
            "doc_001",
            "Troubleshooting 504 Gateway Timeouts",
            "technical",
            "gateway, 504, timeout, proxy, load balancer",
            "A 504 Gateway Timeout occurs when upstream workers exceed the 30s response window. "
            "1. Verify upstream host health via `/healthz`.\n"
            "2. Check if complex SQL queries on `/v1/reports` are triggering full table scans.\n"
            "3. Recommend asynchronous batch export endpoint `/v1/reports/async` for queries spanning >30 days.",
        ),
        (
            "doc_002",
            "Webhook Signature Verification & Retries",
            "technical",
            "webhook, retry, signature, hmac, sha256",
            "Webhooks are signed using HMAC-SHA256 with your webhook secret. Retries occur with exponential backoff: "
            "1m, 5m, 15m, 1h, 6h up to 24h. Check endpoint HTTPS certificate validity and ensure HTTP 200 is returned within 5s.",
        ),
        (
            "doc_003",
            "Billing Cycles, Proration and Refunds",
            "billing",
            "billing, refund, proration, cancellation, invoice",
            "Invoices are billed on the 1st of each month. Downgrades take effect at the end of the billing period. "
            "Refund policy: Unused portions within 14 days are eligible for full refund upon request. "
            "Refunds under $20 can be issued automatically; refunds over $20 require Senior Billing approval.",
        ),
        (
            "doc_004",
            "Resetting 2-Factor Authentication & Account Recovery",
            "account",
            "2fa, mfa, locked, password, reset, security",
            "If a customer loses access to their authenticator device:\n"
            "1. Use recovery codes provided at registration.\n"
            "2. If recovery codes are unavailable, an account verification email and identity confirmation is required before manual 2FA reset.\n"
            "3. Suspended accounts must settle unpaid dues before security access can be reinstated.",
        ),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO kb_docs (doc_id, title, category, tags, content)
        VALUES (?, ?, ?, ?, ?)
        """,
        kb_docs,
    )

    # Seed Runbooks
    runbooks = [
        (
            "rb_api_latency",
            "API Latency and Timeout Diagnostic Runbook",
            "Customer reports high latency or 504 errors on API endpoints",
            "## Steps:\n"
            "1. Fetch customer tier from CRM to check if dedicated rate limit applies.\n"
            "2. Inspect recent query filters in the request body.\n"
            "3. Direct customer to `/v1/reports/async` if querying date ranges > 14 days.\n"
            "4. If upstream service is down, escalate to Infrastructure On-Call.",
        ),
        (
            "rb_duplicate_charge",
            "Duplicate Billing & Disputed Charges Runbook",
            "Customer reports double charge or unauthorized debit",
            "## Steps:\n"
            "1. Call `crm.get_order_history(customer_id)` to review transactions within the last 30 days.\n"
            "2. Check for identical charges within a 48-hour window.\n"
            "3. If legitimate duplicate: call `crm.issue_refund` for the redundant charge.\n"
            "4. Post internal ticket note with transaction reference.",
        ),
        (
            "rb_account_compromise",
            "Account Security & Unauthorized Access Runbook",
            "Suspicious logins, credential stuffing, or locked out admin",
            "## Steps:\n"
            "1. Freeze active sessions and API keys immediately.\n"
            "2. Require human review before issuing any password or email change.\n"
            "3. Escalate ticket to Security Operations team.",
        ),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO runbooks (runbook_id, name, applicable_scenario, steps_markdown)
        VALUES (?, ?, ?, ?)
        """,
        runbooks,
    )

    # Seed Sample Tickets
    tickets = [
        ("tkt_5001", "cust_002", "Double charged for storage addon", "billing", "high", "open"),
        ("tkt_5002", "cust_001", "Frequent 504 Gateway Timeout on /v1/reports", "technical", "urgent", "open"),
        ("tkt_5003", "cust_003", "Locked out of account and 2FA lost", "account", "medium", "open"),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO tickets (ticket_id, customer_id, title, category, urgency, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        tickets,
    )

    conn.commit()


if __name__ == "__main__":
    db_file = init_db()
    print(f"Database successfully initialized and seeded at: {db_file}")
