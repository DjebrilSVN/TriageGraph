"""Unit tests for FastMCP servers and database interactions."""

import os
import pytest
from src.mcp_servers.db import init_db
from src.mcp_servers.crm_server import get_customer, get_order_history, issue_refund
from src.mcp_servers.kb_server import search_docs, get_runbook
from src.mcp_servers.ticket_server import get_ticket, update_ticket, add_note, escalate

TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_triage.db"))


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Set up a fresh test database for each test run."""
    import src.mcp_servers.db as db_mod

    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", TEST_DB_PATH)
    init_db(TEST_DB_PATH)

    yield

    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except PermissionError:
            pass


def test_crm_get_customer():
    cust = get_customer("cust_001")
    assert cust["customer_id"] == "cust_001"
    assert cust["tier"] == "Enterprise"
    assert cust["status"] == "Active"

    not_found = get_customer("cust_non_existent")
    assert "error" in not_found


def test_crm_order_history_and_refund():
    orders = get_order_history("cust_002")
    assert len(orders) >= 2
    order_102 = next(o for o in orders if o["order_id"] == "ord_102")
    assert order_102["amount"] == 15.00

    # Overcharge refund test
    over_res = issue_refund(
        order_id="ord_102",
        customer_id="cust_002",
        amount=50.00,
        reason="Test over-refund"
    )
    assert "error" in over_res

    # Legitimate refund
    res = issue_refund(
        order_id="ord_102",
        customer_id="cust_002",
        amount=15.00,
        reason="Storage quota issue"
    )
    assert res["status"] == "Approved"
    assert res["amount"] == 15.00
    assert "refund_id" in res


def test_kb_search_and_runbook():
    docs = search_docs("504")
    assert len(docs) > 0
    assert "Gateway Timeout" in docs[0]["title"]

    runbook = get_runbook("rb_duplicate_charge")
    assert runbook["runbook_id"] == "rb_duplicate_charge"
    assert "Duplicate Billing" in runbook["name"]


def test_ticket_lifecycle():
    tkt = get_ticket("tkt_5001")
    assert tkt["ticket_id"] == "tkt_5001"
    assert tkt["category"] == "billing"

    # Add note
    note_res = add_note(
        ticket_id="tkt_5001",
        author="Agent_Billing",
        note_text="Investigated order history. Refund warranted."
    )
    assert "note_id" in note_res

    # Update ticket status
    up_res = update_ticket(ticket_id="tkt_5001", status="resolved")
    assert up_res["updated_status"] == "resolved"

    # Escalation
    esc_res = escalate(
        ticket_id="tkt_5001",
        department="Tier-3 Engineering",
        reason="Systemic pricing sync bug"
    )
    assert esc_res["status"] == "escalated"
