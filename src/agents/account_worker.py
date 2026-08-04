"""Account Worker Agent for TriageGraph.

Specialist agent for:
- Account recovery, 2FA resets, and plan modifications.
- High-risk operations requiring identity verification and human approval.
"""

from typing import Any, Dict
from src.graph.state import TriageState
from src.mcp_servers.crm_server import get_customer
from src.mcp_servers.kb_server import search_docs
from src.mcp_servers.ticket_server import add_note
from src.graph.policy import evaluate_tool_policy


def account_worker_node(state: TriageState) -> Dict[str, Any]:
    customer_id = state.get("customer_id", "cust_003")
    ticket_id = state.get("ticket_id", "tkt_5003")
    body = state.get("body", "")

    tool_history = list(state.get("tool_history") or [])

    # 1. Fetch Customer Record
    customer = get_customer(customer_id)
    tool_history.append({
        "tool_name": "get_customer",
        "args": {"customer_id": customer_id},
        "result": customer,
        "requires_approval": False,
        "approved": True,
    })

    # 2. Search Security & 2FA Recovery Policy
    docs = search_docs("2fa mfa reset security")
    tool_history.append({
        "tool_name": "search_docs",
        "args": {"query": "2fa mfa reset security"},
        "result": docs,
        "requires_approval": False,
        "approved": True,
    })

    # High-risk action: Reset password / Reset 2FA
    proposed_action = {
        "tool_name": "reset_password",
        "args": {
            "customer_id": customer_id,
            "account_status": customer.get("status", "Unknown"),
            "requires_id_verification": True,
        },
    }

    policy_decision = evaluate_tool_policy(
        proposed_action["tool_name"], proposed_action["args"]
    )

    # Add audit note
    note_text = (
        f"Account Worker checked security state for {customer_id}. Status: {customer.get('status')}. "
        "High-risk action flagged: manual 2FA reset requested."
    )
    add_note(ticket_id=ticket_id, author="Agent_AccountWorker", note_text=note_text)

    findings = (
        f"Account Worker identified security request for {customer.get('name', customer_id)} "
        f"(Account Status: {customer.get('status')}). Action '{proposed_action['tool_name']}' requires manual review: "
        f"{policy_decision.reason}"
    )

    return {
        "worker_findings": findings,
        "tool_history": tool_history,
        "pending_action": proposed_action,
        "ticket_status": "pending_approval",
    }
