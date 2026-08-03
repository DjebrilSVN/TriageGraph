"""Supervisor Agent for TriageGraph.

Classifies incoming tickets into structured categories, evaluates urgency,
sentiment, and confidence, and routes to specialist workers or human triage.
"""

import os
import re
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from src.graph.state import TriageState


class SupervisorClassification(BaseModel):
    category: Literal["billing", "technical", "account", "general"] = Field(
        description="Ticket category."
    )
    urgency: Literal["low", "medium", "high", "urgent"] = Field(
        description="Assessed customer urgency."
    )
    sentiment: Literal["frustrated", "neutral", "satisfied", "angry"] = Field(
        description="Customer emotional tone."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0."
    )
    route: Literal["billing_worker", "tech_worker", "account_worker", "human_triage"] = Field(
        description="Target destination. Low confidence (< 0.70) must route to 'human_triage'."
    )
    reasoning: str = Field(
        description="Short rationale for the classification and routing decision."
    )


SUPERVISOR_SYSTEM_PROMPT = """You are an expert customer support supervisor.
Your job is to analyze the customer's support ticket and classify it accurately.

Routing rules:
1. "billing_worker": Invoices, duplicate charges, payment failures, subscription pricing, refund requests.
2. "tech_worker": API errors, 504 timeouts, webhooks, bugs, system latency, code integrations.
3. "account_worker": Password resets, 2FA recovery, changing account owners, compromised credentials.
4. "human_triage": Use when the ticket is ambiguous, contains conflicting complaints, expresses severe escalation risk, or your confidence is below 0.70.

Confidence Guidelines:
- If the ticket clearly matches one domain: confidence >= 0.85.
- If the ticket touches multiple domains or is vague: confidence < 0.70 -> route to "human_triage".

Return structured output matching the schema.
"""


def _rule_based_fallback(title: str, body: str) -> SupervisorClassification:
    """Deterministic fallback classifier when no API key is set or during offline testing."""
    text = f"{title} {body}".lower()

    # 1. Prompt Injection & Adversarial Attack Gate
    injection_signatures = [
        "ignore your rules",
        "ignore previous",
        "ignore all",
        "system override",
        "developer mode",
        "executive bypass",
        "disregard standard",
        "grant full admin",
        "print your initial system prompt",
        "hidden instructions",
        "<script",
        "alert(",
        "bypass policy",
    ]
    if any(sig in text for sig in injection_signatures):
        return SupervisorClassification(
            category="general",
            urgency="urgent",
            sentiment="frustrated",
            confidence=0.30,
            route="human_triage",
            reasoning="Adversarial prompt injection pattern detected in ticket body. Flagged for security triage.",
        )

    # 2. Domain Keyword Detection
    billing_keywords = [
        "refund", "charge", "charged", "invoice", "payment", "billing",
        "billed", "disputed", "overcharged", "discrepancy", "renewed",
        "line item", "credit card", "prorated", "subscription fee"
    ]
    tech_keywords = [
        "504", "api", "timeout", "latency", "bug", "error", "webhook",
        "gateway", "hmac", "response times", "connection pool", "rate limit",
        "429", "endpoint", "pipeline", "signature header", "traffic"
    ]
    account_keywords = [
        "password", "2fa", "mfa", "login", "account", "locked", "compromise",
        "authenticator", "invite", "license limit", "credentials", "admin dashboard",
        "suspicious login", "forgot password", "reset link", "ownership", "open seats"
    ]

    has_billing = any(k in text for k in billing_keywords)
    has_tech = any(k in text for k in tech_keywords)
    has_account = any(k in text for k in account_keywords)

    detected_count = sum([has_billing, has_tech, has_account])

    # Ambiguous or cross-domain complaints -> human triage
    if detected_count > 1 or detected_count == 0:
        return SupervisorClassification(
            category="general",
            urgency="high" if detected_count > 1 else "low",
            sentiment="frustrated",
            confidence=0.55 if detected_count > 1 else 0.45,
            route="human_triage",
            reasoning="Ambiguous or multi-domain inquiry detected. Escalated to human triage queue.",
        )

    if has_billing:
        urgency = "high" if any(w in text for w in ["urgent", "double", "overcharge", "immediately", "disputed"]) else "medium"
        sentiment = "frustrated" if any(w in text for w in ["double", "wrong", "disputed", "unfamiliar"]) else "neutral"
        return SupervisorClassification(
            category="billing",
            urgency=urgency,
            sentiment=sentiment,
            confidence=0.94,
            route="billing_worker",
            reasoning="Clear billing inquiry regarding invoices, duplicate charges, or refunds.",
        )

    if has_tech:
        urgency = "urgent" if any(w in text for w in ["504", "down", "failing", "timeout", "latency spike"]) else "high"
        return SupervisorClassification(
            category="technical",
            urgency=urgency,
            sentiment="frustrated",
            confidence=0.92,
            route="tech_worker",
            reasoning="Technical service degradation, API error, or webhook anomaly reported.",
        )

    if has_account:
        return SupervisorClassification(
            category="account",
            urgency="high" if any(w in text for w in ["lost", "locked", "suspicious", "compromise"]) else "medium",
            sentiment="frustrated",
            confidence=0.90,
            route="account_worker",
            reasoning="User authentication, 2FA credential, or team permission management inquiry.",
        )

    return SupervisorClassification(
        category="general",
        urgency="low",
        sentiment="neutral",
        confidence=0.50,
        route="human_triage",
        reasoning="Insufficient specifics to route to a specialist worker.",
    )


def classify_ticket(title: str, body: str) -> SupervisorClassification:
    """Classifies a ticket using LLM structured output, falling back to heuristic engine if unavailable."""
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or api_key.startswith("your_"):
        return _rule_based_fallback(title, body)

    try:
        from langchain_openai import ChatOpenAI

        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        llm = ChatOpenAI(model=model_name, temperature=0.0)
        structured_llm = llm.with_structured_output(SupervisorClassification)

        prompt = ChatPromptTemplate.from_messages([
            ("system", SUPERVISOR_SYSTEM_PROMPT),
            ("user", "Title: {title}\n\nTicket Body:\n{body}")
        ])
        chain = prompt | structured_llm
        result: SupervisorClassification = chain.invoke({"title": title, "body": body})

        # Enforce confidence rule
        if result.confidence < 0.70:
            result.route = "human_triage"

        return result
    except Exception:
        # Fall back cleanly on network/API failure
        return _rule_based_fallback(title, body)


def supervisor_node(state: TriageState) -> Dict[str, Any]:
    """LangGraph node execution for the supervisor agent."""
    title = state.get("title", "")
    body = state.get("body", "")

    classification = classify_ticket(title, body)

    return {
        "category": classification.category,
        "urgency": classification.urgency,
        "sentiment": classification.sentiment,
        "confidence": classification.confidence,
        "route": classification.route,
        "routing_reason": classification.reasoning,
        "ticket_status": "human_triage" if classification.route == "human_triage" else "open",
    }
