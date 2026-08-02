"""Knowledge Base FastMCP Server for TriageGraph.

Provides tools for:
- search_docs: Read-only search over technical and billing documentation
- get_runbook: Read-only retrieval of step-by-step diagnostic runbooks
"""

from typing import Any, Dict, List
from fastmcp import FastMCP

from src.mcp_servers.db import get_db_connection, init_db

# Initialize FastMCP Server
mcp = FastMCP(
    name="KB-Server"
)


@mcp.tool(
    name="search_docs",
    description="Search documentation and articles by keyword query. Read-only.",
    annotations={"read_only": True, "risk_level": "none", "action_type": "read"}
)
def search_docs(query: str) -> List[Dict[str, Any]]:
    """Search knowledge base articles matching a query."""
    conn = get_db_connection()
    cursor = conn.cursor()
    like_query = f"%{query.lower()}%"
    cursor.execute(
        """
        SELECT doc_id, title, category, tags, content
        FROM kb_docs
        WHERE LOWER(title) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(content) LIKE ?
        """,
        (like_query, like_query, like_query),
    )
    rows = cursor.fetchall()
    conn.close()

    return [dict(r) for r in rows]


@mcp.tool(
    name="get_runbook",
    description="Retrieve a specific diagnostic runbook by runbook_id. Read-only.",
    annotations={"read_only": True, "risk_level": "none", "action_type": "read"}
)
def get_runbook(runbook_id: str) -> Dict[str, Any]:
    """Retrieve full runbook instructions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM runbooks WHERE runbook_id = ?",
        (runbook_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"error": f"Runbook '{runbook_id}' not found."}

    return dict(row)


if __name__ == "__main__":
    init_db()
    mcp.run()
