"""TriageGraph Core StateGraph Definition with HITL Approval Gate and Durable Checkpointing."""

import os
import sqlite3
from typing import Any, Dict, Literal, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver

from src.graph.state import TriageState, ToolCallRecord
from src.agents.supervisor import supervisor_node
from src.agents.billing_worker import billing_worker_node
from src.agents.tech_worker import tech_worker_node
from src.agents.account_worker import account_worker_node
from src.agents.reply_writer import reply_writer_node
from src.mcp_servers.crm_server import issue_refund
from src.mcp_servers.ticket_server import update_ticket, escalate

DEFAULT_CHECKPOINT_DB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "triage_checkpoints.db")
)


def human_triage_node(state: TriageState) -> Dict[str, Any]:
    """Human-in-the-loop triage queue when supervisor confidence is low or ticket is ambiguous."""
    interrupt_payload = {
        "type": "human_triage_decision",
        "ticket_id": state.get("ticket_id"),
        "title": state.get("title"),
        "body": state.get("body"),
        "confidence": state.get("confidence"),
        "routing_reason": state.get("routing_reason"),
    }

    # Pause execution and wait for human triage operator
    human_input = interrupt(interrupt_payload)

    target_route = human_input.get("route", "billing_worker")
    return {
        "route": target_route,
        "routing_reason": f"Manual human routing override: routed to {target_route}.",
        "ticket_status": "open",
    }


def approval_gate_node(state: TriageState) -> Dict[str, Any]:
    """Human-in-the-loop approval gate for write actions (e.g. refunds > $20, password resets)."""
    pending_action = state.get("pending_action")
    if not pending_action:
        return {}

    interrupt_payload = {
        "type": "tool_approval",
        "ticket_id": state.get("ticket_id"),
        "customer_id": state.get("customer_id"),
        "pending_action": pending_action,
        "worker_findings": state.get("worker_findings"),
    }

    # Halt execution: persist state to checkpointer and await human Command(resume=...)
    decision = interrupt(interrupt_payload)

    approved = decision.get("approved", False)
    modified_args = decision.get("modified_args")
    reviewer_notes = decision.get("reviewer_notes", "Reviewed by support lead.")

    tool_history = list(state.get("tool_history") or [])
    tool_name = pending_action["tool_name"]
    exec_args = modified_args if modified_args is not None else pending_action["args"]

    if approved:
        # Execute approved action
        result = None
        if tool_name == "issue_refund":
            result = issue_refund(**exec_args)
        elif tool_name == "escalate":
            result = escalate(**exec_args)
        elif tool_name == "reset_password":
            result = {
                "status": "Success",
                "message": f"Password reset link generated and transmitted to verified email for {exec_args.get('customer_id')}.",
            }
        else:
            result = {"status": "Executed", "message": f"Tool {tool_name} executed with approval."}

        tool_history.append({
            "tool_name": tool_name,
            "args": exec_args,
            "result": result,
            "requires_approval": True,
            "approved": True,
        })
        findings = (
            f"{state.get('worker_findings', '')} | Human Reviewer APPROVED action ({reviewer_notes}). Result: {result.get('message', 'Done')}."
        )
        return {
            "worker_findings": findings,
            "tool_history": tool_history,
            "pending_action": None,
            "human_decision": {"approved": True, "reviewer_notes": reviewer_notes, "modified_args": modified_args},
            "ticket_status": "resolved",
        }
    else:
        # Human rejected the action
        tool_history.append({
            "tool_name": tool_name,
            "args": exec_args,
            "result": {"status": "Rejected", "message": f"Action rejected by reviewer: {reviewer_notes}"},
            "requires_approval": True,
            "approved": False,
        })
        findings = (
            f"{state.get('worker_findings', '')} | Human Reviewer REJECTED action. Reason: {reviewer_notes}."
        )
        return {
            "worker_findings": findings,
            "tool_history": tool_history,
            "pending_action": None,
            "human_decision": {"approved": False, "reviewer_notes": reviewer_notes},
            "ticket_status": "open",
        }


def route_supervisor(state: TriageState) -> str:
    """Conditional routing from supervisor."""
    route = state.get("route")
    if route == "billing_worker":
        return "billing_worker"
    elif route == "tech_worker":
        return "tech_worker"
    elif route == "account_worker":
        return "account_worker"
    return "human_triage"


def route_from_human_triage(state: TriageState) -> str:
    """Routing after human assigns route in human triage queue."""
    route = state.get("route")
    if route == "billing_worker":
        return "billing_worker"
    elif route == "tech_worker":
        return "tech_worker"
    elif route == "account_worker":
        return "account_worker"
    return "reply_writer"


def route_worker_output(state: TriageState) -> str:
    """Route to approval gate if an action is pending; otherwise proceed to reply writer."""
    if state.get("pending_action"):
        return "approval_gate"
    return "reply_writer"


def build_triage_graph(checkpointer: Optional[Any] = None):
    """Build and compile the TriageGraph StateGraph."""
    builder = StateGraph(TriageState)

    # Add Nodes
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("human_triage", human_triage_node)
    builder.add_node("billing_worker", billing_worker_node)
    builder.add_node("tech_worker", tech_worker_node)
    builder.add_node("account_worker", account_worker_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("reply_writer", reply_writer_node)

    # Add Edges
    builder.add_edge(START, "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "billing_worker": "billing_worker",
            "tech_worker": "tech_worker",
            "account_worker": "account_worker",
            "human_triage": "human_triage",
        },
    )

    builder.add_conditional_edges(
        "human_triage",
        route_from_human_triage,
        {
            "billing_worker": "billing_worker",
            "tech_worker": "tech_worker",
            "account_worker": "account_worker",
            "reply_writer": "reply_writer",
        },
    )

    # Worker output conditional routing
    builder.add_conditional_edges(
        "billing_worker",
        route_worker_output,
        {"approval_gate": "approval_gate", "reply_writer": "reply_writer"},
    )
    builder.add_conditional_edges(
        "tech_worker",
        route_worker_output,
        {"approval_gate": "approval_gate", "reply_writer": "reply_writer"},
    )
    builder.add_conditional_edges(
        "account_worker",
        route_worker_output,
        {"approval_gate": "approval_gate", "reply_writer": "reply_writer"},
    )

    builder.add_edge("approval_gate", "reply_writer")
    builder.add_edge("reply_writer", END)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()


def get_sqlite_checkpointer(db_path: Optional[str] = None):
    """Returns a context manager or instance for SqliteSaver."""
    path = db_path or DEFAULT_CHECKPOINT_DB
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)
