"""Ticket FastMCP Server for TriageGraph.

Provides tools for:
- get_ticket: Read-only ticket details
- update_ticket: Write tool to modify ticket state/urgency
- add_note: Write tool to append internal audit / investigation notes
- escalate: Write tool to route to an internal engineering/finance team
"""

from typing import Any, Dict, Optional
from fastmcp import FastMCP

from src.mcp_servers.db import get_db_connection, init_db

# Initialize FastMCP Server
mcp = FastMCP(
    name="Ticket-Server"
)


@mcp.tool(
    name="get_ticket",
    description="Fetch ticket details and notes by ticket_id. Read-only.",
    annotations={"read_only": True, "risk_level": "none", "action_type": "read"}
)
def get_ticket(ticket_id: str) -> Dict[str, Any]:
    """Retrieve ticket details and associated notes."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    ticket_row = cursor.fetchone()
    if not ticket_row:
        conn.close()
        return {"error": f"Ticket '{ticket_id}' not found."}

    cursor.execute(
        "SELECT author, note_text, created_at FROM ticket_notes WHERE ticket_id = ? ORDER BY created_at ASC",
        (ticket_id,),
    )
    notes = [dict(r) for r in cursor.fetchall()]
    conn.close()

    result = dict(ticket_row)
    result["notes"] = notes
    return result


@mcp.tool(
    name="update_ticket",
    description="Update ticket status or urgency. Write tool with medium risk.",
    annotations={"read_only": False, "risk_level": "medium", "action_type": "write"}
)
def update_ticket(
    ticket_id: str,
    status: Optional[str] = None,
    urgency: Optional[str] = None
) -> Dict[str, Any]:
    """Update ticket attributes."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    ticket = cursor.fetchone()
    if not ticket:
        conn.close()
        return {"error": f"Ticket '{ticket_id}' not found."}

    fields = []
    params = []
    if status:
        fields.append("status = ?")
        params.append(status)
    if urgency:
        fields.append("urgency = ?")
        params.append(urgency)

    if not fields:
        conn.close()
        return {"message": "No updates requested."}

    params.append(ticket_id)
    cursor.execute(f"UPDATE tickets SET {', '.join(fields)} WHERE ticket_id = ?", params)
    conn.commit()
    conn.close()

    return {
        "ticket_id": ticket_id,
        "updated_status": status or ticket["status"],
        "updated_urgency": urgency or ticket["urgency"],
        "message": f"Ticket {ticket_id} updated successfully."
    }


@mcp.tool(
    name="add_note",
    description="Add an internal investigation note to a ticket. Write tool.",
    annotations={"read_only": False, "risk_level": "low", "action_type": "write"}
)
def add_note(
    ticket_id: str,
    author: str,
    note_text: str
) -> Dict[str, Any]:
    """Append an internal note to a ticket."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    if not cursor.fetchone():
        conn.close()
        return {"error": f"Ticket '{ticket_id}' not found."}

    cursor.execute(
        """
        INSERT INTO ticket_notes (ticket_id, author, note_text)
        VALUES (?, ?, ?)
        """,
        (ticket_id, author, note_text),
    )
    note_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "note_id": note_id,
        "ticket_id": ticket_id,
        "author": author,
        "message": f"Note recorded for ticket {ticket_id}."
    }


@mcp.tool(
    name="escalate",
    description="Escalate a ticket to a specialized engineering or security department. Write tool.",
    annotations={"read_only": False, "risk_level": "medium", "action_type": "write"}
)
def escalate(
    ticket_id: str,
    department: str,
    reason: str
) -> Dict[str, Any]:
    """Escalate a ticket to another department."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    if not cursor.fetchone():
        conn.close()
        return {"error": f"Ticket '{ticket_id}' not found."}

    cursor.execute(
        """
        INSERT INTO escalations (ticket_id, target_department, reason)
        VALUES (?, ?, ?)
        """,
        (ticket_id, department, reason),
    )
    cursor.execute(
        "UPDATE tickets SET status = 'escalated' WHERE ticket_id = ?",
        (ticket_id,),
    )
    conn.commit()
    conn.close()

    return {
        "ticket_id": ticket_id,
        "department": department,
        "status": "escalated",
        "message": f"Ticket {ticket_id} escalated to {department}: {reason}"
    }


if __name__ == "__main__":
    init_db()
    mcp.run()
