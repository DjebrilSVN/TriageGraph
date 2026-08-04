"""Billing Worker Agent for TriageGraph.

Specialist agent for:
- Querying customer profiles & order transactions via CRM MCP tools.
- Evaluating refund eligibility.
- Submitting refund proposals to the policy approval gate.
"""

from typing import Any, Dict
from src.graph.state import TriageState, ToolCallRecord
from src.graph.policy import evaluate_tool_policy
from src.mcp_servers.crm_server import get_customer, get_order_history, issue_refund


def billing_worker_node(state: TriageState) -> Dict[str, Any]:
    customer_id = state.get("customer_id", "cust_002")
    body = state.get("body", "")
    ticket_id = state.get("ticket_id", "tkt_unknown")

    tool_history = list(state.get("tool_history") or [])

    # 1. Inspect Customer Record
    customer = get_customer(customer_id)
    tool_history.append({
        "tool_name": "get_customer",
        "args": {"customer_id": customer_id},
        "result": customer,
        "requires_approval": False,
        "approved": True,
    })

    # 2. Inspect Recent Orders
    orders = get_order_history(customer_id)
    tool_history.append({
        "tool_name": "get_order_history",
        "args": {"customer_id": customer_id},
        "result": orders,
        "requires_approval": False,
        "approved": True,
    })

    # 3. Determine if refund is requested and calculate amount
    # Search for monetary amounts or match latest order
    refund_amount = 0.0
    target_order_id = None
    reason = "Customer dispute / duplicate charge request"

    # Match orders
    if orders:
        latest_order = orders[0]
        target_order_id = latest_order.get("order_id")
        refund_amount = float(latest_order.get("amount", 0.0))

    # Check if a specific amount was mentioned in body (e.g. $15, $85, $500)
    import re
    amount_matches = re.findall(r"\$(\d+(?:\.\d{2})?)", body)
    if amount_matches:
        try:
            refund_amount = float(amount_matches[0])
        except ValueError:
            pass

    # Evaluate action through Policy Gate
    proposed_action = {
        "tool_name": "issue_refund",
        "args": {
            "order_id": target_order_id or "ord_102",
            "customer_id": customer_id,
            "amount": refund_amount,
            "reason": reason,
        },
    }

    policy_decision = evaluate_tool_policy(
        proposed_action["tool_name"], proposed_action["args"]
    )

    findings = (
        f"Billing Worker evaluated customer '{customer.get('name', customer_id)}' (Tier: {customer.get('tier')}). "
        f"Identified target order {target_order_id} for ${refund_amount:.2f}. "
        f"Policy check: {policy_decision.reason}"
    )

    if policy_decision.requires_approval:
        # Halt execution: pending approval in human-in-the-loop gate
        return {
            "worker_findings": findings,
            "tool_history": tool_history,
            "pending_action": proposed_action,
            "ticket_status": "pending_approval",
        }
    else:
        # Auto-approved: execute immediately
        result = issue_refund(**proposed_action["args"])
        tool_history.append({
            "tool_name": "issue_refund",
            "args": proposed_action["args"],
            "result": result,
            "requires_approval": False,
            "approved": True,
        })
        return {
            "worker_findings": findings + f" Auto-issued refund: {result.get('refund_id')}.",
            "tool_history": tool_history,
            "pending_action": None,
            "ticket_status": "resolved",
        }
