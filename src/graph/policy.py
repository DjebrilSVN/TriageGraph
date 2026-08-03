"""Approval Policy Engine for TriageGraph.

Determines whether a proposed tool action can be automatically approved
or must be gated by a human-in-the-loop review.
"""

import os
from typing import Any, Dict, NamedTuple


class PolicyDecision(NamedTuple):
    requires_approval: bool
    reason: str
    risk_level: str  # "none", "low", "medium", "high"


# Default auto-approval threshold for refunds
AUTO_APPROVE_REFUND_MAX = float(os.getenv("AUTO_APPROVE_REFUND_MAX", "20.00"))

# Known read-only tools
READ_ONLY_TOOLS = {
    "get_customer",
    "get_order_history",
    "search_docs",
    "get_runbook",
    "get_ticket",
}


def evaluate_tool_policy(tool_name: str, args: Dict[str, Any]) -> PolicyDecision:
    """Evaluates whether a tool call requires human review based on risk and parameters."""

    # 1. Read-only tools never require approval
    if tool_name in READ_ONLY_TOOLS:
        return PolicyDecision(
            requires_approval=False,
            reason="Read-only diagnostic query.",
            risk_level="none",
        )

    # 2. Refunds: Auto-approve under threshold, require human review above
    if tool_name == "issue_refund":
        amount = float(args.get("amount", 0.0))
        if amount <= AUTO_APPROVE_REFUND_MAX:
            return PolicyDecision(
                requires_approval=False,
                reason=f"Refund amount ${amount:.2f} is within auto-approval threshold (${AUTO_APPROVE_REFUND_MAX:.2f}).",
                risk_level="low",
            )
        else:
            return PolicyDecision(
                requires_approval=True,
                reason=f"Refund amount ${amount:.2f} exceeds auto-approval threshold (${AUTO_APPROVE_REFUND_MAX:.2f}). Requires manager approval.",
                risk_level="high",
            )

    # 3. Escalations: require human approval if escalations are high-priority
    if tool_name == "escalate":
        return PolicyDecision(
            requires_approval=True,
            reason=f"Department escalation to {args.get('department')} requires human triage confirmation.",
            risk_level="medium",
        )

    # 4. Account modifications (e.g., plan changes, password resets)
    if tool_name in {"reset_password", "change_plan", "modify_account"}:
        return PolicyDecision(
            requires_approval=True,
            reason=f"Account modification ({tool_name}) poses security risk and requires identity verification.",
            risk_level="high",
        )

    # 5. Low risk updates like internal notes
    if tool_name == "add_note":
        return PolicyDecision(
            requires_approval=False,
            reason="Internal audit note addition is low risk.",
            risk_level="low",
        )

    if tool_name == "update_ticket":
        # Status change to 'resolved' is medium risk
        if args.get("status") == "resolved":
            return PolicyDecision(
                requires_approval=False,
                reason="Auto-updating ticket status following resolution.",
                risk_level="low",
            )
        return PolicyDecision(
            requires_approval=False,
            reason="Standard ticket metadata update.",
            risk_level="low",
        )

    # Default fallback: unknown write actions require approval
    return PolicyDecision(
        requires_approval=True,
        reason=f"Unrecognized tool '{tool_name}' defaults to strict approval gate.",
        risk_level="high",
    )
