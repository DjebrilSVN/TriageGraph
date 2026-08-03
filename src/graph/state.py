"""State definition for TriageGraph."""

from typing import Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict


class HumanDecision(TypedDict, total=False):
    approved: bool
    modified_args: Optional[Dict[str, Any]]
    reviewer_notes: Optional[str]


class ToolCallRecord(TypedDict):
    tool_name: str
    args: Dict[str, Any]
    result: Any
    requires_approval: bool
    approved: Optional[bool]


class TriageState(TypedDict, total=False):
    # Ticket inputs
    ticket_id: str
    customer_id: str
    title: str
    body: str

    # Supervisor Classification
    category: Literal["billing", "technical", "account", "general"]
    urgency: Literal["low", "medium", "high", "urgent"]
    sentiment: Literal["frustrated", "neutral", "satisfied", "angry"]
    confidence: float
    route: Literal["billing_worker", "tech_worker", "account_worker", "human_triage"]
    routing_reason: str

    # Worker investigation & actions
    worker_findings: str
    tool_history: List[ToolCallRecord]

    # Human-in-the-loop Gate
    pending_action: Optional[Dict[str, Any]]  # Tool call awaiting review
    human_decision: Optional[HumanDecision]  # Resume input from reviewer

    # Final drafted reply and resolution
    draft_reply: str
    ticket_status: Literal["open", "pending_approval", "resolved", "escalated", "human_triage"]
