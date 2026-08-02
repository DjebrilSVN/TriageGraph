"""CRM FastMCP Server for TriageGraph.

Provides tools for:
- get_customer: Read-only customer profile
- get_order_history: Read-only purchase and billing transactions
- issue_refund: Write action (triggers HITL approval gate if > policy limit)
"""

import os
import uuid
from typing import Any, Dict, List
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Ensure database is present
from src.mcp_servers.db import get_db_connection, init_db

# Initialize FastMCP Server
mcp = FastMCP(
    name="CRM-Server"
)


class CustomerResult(BaseModel):
    customer_id: str
    name: str
    email: str
    tier: str
    status: str


class OrderResult(BaseModel):
    order_id: str
    customer_id: str
    amount: float
    currency: str
    item_description: str
    order_date: str
    status: str


class RefundResult(BaseModel):
    refund_id: str
    order_id: str
    customer_id: str
    amount: float
    status: str
    message: str


@mcp.tool(
    name="get_customer",
    description="Fetch customer account details by customer_id. Read-only.",
    annotations={"read_only": True, "risk_level": "none", "action_type": "read"}
)
def get_customer(customer_id: str) -> Dict[str, Any]:
    """Retrieve customer details by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"error": f"Customer '{customer_id}' not found."}

    return dict(row)


@mcp.tool(
    name="get_order_history",
    description="Fetch recent purchase and billing transactions for a customer. Read-only.",
    annotations={"read_only": True, "risk_level": "none", "action_type": "read"}
)
def get_order_history(customer_id: str) -> List[Dict[str, Any]]:
    """Retrieve order history for a customer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY order_date DESC",
        (customer_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    return [dict(r) for r in rows]


@mcp.tool(
    name="issue_refund",
    description="Issue a refund for an order. High-risk write action requiring policy validation / human approval.",
    annotations={"read_only": False, "risk_level": "high", "action_type": "write"}
)
def issue_refund(
    order_id: str,
    customer_id: str,
    amount: float,
    reason: str
) -> Dict[str, Any]:
    """Execute a refund against an existing order."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Validate order
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        return {"error": f"Order '{order_id}' not found."}

    if order["customer_id"] != customer_id:
        conn.close()
        return {"error": f"Order '{order_id}' does not belong to customer '{customer_id}'."}

    if amount > order["amount"]:
        conn.close()
        return {
            "error": f"Refund amount ${amount:.2f} exceeds original order amount ${order['amount']:.2f}."
        }

    refund_id = f"ref_{uuid.uuid4().hex[:8]}"
    cursor.execute(
        """
        INSERT INTO refunds (refund_id, order_id, customer_id, amount, reason, status)
        VALUES (?, ?, ?, ?, ?, 'Approved')
        """,
        (refund_id, order_id, customer_id, amount, reason),
    )
    cursor.execute(
        "UPDATE orders SET status = 'Refunded' WHERE order_id = ?",
        (order_id,),
    )
    conn.commit()
    conn.close()

    return {
        "refund_id": refund_id,
        "order_id": order_id,
        "customer_id": customer_id,
        "amount": amount,
        "status": "Approved",
        "message": f"Successfully issued refund of ${amount:.2f} for order {order_id}."
    }


if __name__ == "__main__":
    init_db()
    mcp.run()
