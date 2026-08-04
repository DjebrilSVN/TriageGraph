"""Technical Worker Agent for TriageGraph.

Specialist agent for:
- Querying knowledge base docs and diagnostic runbooks via KB MCP tools.
- Formulating technical remediation steps.
- Appending audit notes or escalating outages via Ticket MCP tools.
"""

from typing import Any, Dict
from src.graph.state import TriageState
from src.mcp_servers.kb_server import search_docs, get_runbook
from src.mcp_servers.ticket_server import add_note, escalate
from src.graph.policy import evaluate_tool_policy


def tech_worker_node(state: TriageState) -> Dict[str, Any]:
    ticket_id = state.get("ticket_id", "tkt_5002")
    title = state.get("title", "")
    body = state.get("body", "")
    urgency = state.get("urgency", "medium")

    tool_history = list(state.get("tool_history") or [])

    # 1. Search KB for matching technical documentation
    search_keywords = "504 timeout api error" if "504" in f"{title} {body}" else "webhook signature"
    docs = search_docs(search_keywords)
    tool_history.append({
        "tool_name": "search_docs",
        "args": {"query": search_keywords},
        "result": docs,
        "requires_approval": False,
        "approved": True,
    })

    # 2. Retrieve Diagnostic Runbook
    runbook_id = "rb_api_latency"
    runbook = get_runbook(runbook_id)
    tool_history.append({
        "tool_name": "get_runbook",
        "args": {"runbook_id": runbook_id},
        "result": runbook,
        "requires_approval": False,
        "approved": True,
    })

    # 3. Add Internal Investigation Note
    note_text = (
        f"Diagnosed against runbook {runbook_id}. Correlated with doc '{docs[0]['title'] if docs else 'General'}'. "
        "Recommend redirecting batch requests to /v1/reports/async."
    )
    note_res = add_note(
        ticket_id=ticket_id,
        author="Agent_TechnicalWorker",
        note_text=note_text
    )
    tool_history.append({
        "tool_name": "add_note",
        "args": {"ticket_id": ticket_id, "author": "Agent_TechnicalWorker", "note_text": note_text},
        "result": note_res,
        "requires_approval": False,
        "approved": True,
    })

    findings = (
        f"Technical Worker investigated error patterns. Matched KB Article: '{docs[0]['title'] if docs else 'N/A'}'. "
        f"Applied diagnostic runbook: '{runbook.get('name')}'. Proposed fix: use asynchronous batch reporting endpoint."
    )

    return {
        "worker_findings": findings,
        "tool_history": tool_history,
        "pending_action": None,
        "ticket_status": "open",
    }
