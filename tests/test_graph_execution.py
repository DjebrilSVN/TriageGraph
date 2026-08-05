"""Integration tests for TriageGraph end-to-end execution, HITL approval gate, and crash resilience."""

import os
import sqlite3
import pytest
from langgraph.types import Command
from langgraph.checkpoint.sqlite import SqliteSaver

from src.mcp_servers.db import init_db
from src.graph.triage_graph import build_triage_graph

TEST_DATA_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_data.db"))
TEST_CHECKPOINT_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_checkpoints.db"))


@pytest.fixture(autouse=True)
def setup_databases(monkeypatch):
    """Set up test databases and monkeypatch paths."""
    import src.mcp_servers.db as db_mod
    import src.graph.triage_graph as tg_mod

    monkeypatch.setattr(db_mod, "DEFAULT_DB_PATH", TEST_DATA_DB)
    monkeypatch.setattr(tg_mod, "DEFAULT_CHECKPOINT_DB", TEST_CHECKPOINT_DB)
    init_db(TEST_DATA_DB)

    yield

    for db_f in [TEST_DATA_DB, TEST_CHECKPOINT_DB]:
        if os.path.exists(db_f):
            try:
                os.remove(db_f)
            except PermissionError:
                pass


def test_auto_approval_flow():
    """Tickets with actions under policy threshold ($15 <= $20) execute to completion without interruption."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    graph = build_triage_graph(checkpointer=checkpointer)

    thread_id = "thread_auto_001"
    config = {"configurable": {"thread_id": thread_id}}

    initial_input = {
        "ticket_id": "tkt_auto_1",
        "customer_id": "cust_002",
        "title": "Double charge on storage addon $15",
        "body": "Hi, I see a charge of $15 on my card for storage. Can you please refund this?",
    }

    # Run the graph
    result = graph.invoke(initial_input, config=config)

    # State verification
    state = graph.get_state(config)
    # Graph should be finished (next is empty tuple)
    assert len(state.next) == 0
    assert result.get("category") == "billing"
    assert result.get("ticket_status") == "resolved"
    assert "draft_reply" in result
    assert any(t["tool_name"] == "issue_refund" and t["approved"] for t in result.get("tool_history", []))


def test_hitl_approval_gate_and_resume():
    """Tickets with high-risk actions ($85 > $20) pause at approval gate and resume on Command."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    graph = build_triage_graph(checkpointer=checkpointer)

    thread_id = "thread_hitl_002"
    config = {"configurable": {"thread_id": thread_id}}

    initial_input = {
        "ticket_id": "tkt_hitl_2",
        "customer_id": "cust_002",
        "title": "Requesting full refund for Team Seat Upgrade $85",
        "body": "We decided not to use the team seat upgrade of $85. Please refund it to our company card.",
    }

    # Run graph - expected to pause at approval gate
    result = graph.invoke(initial_input, config=config)

    # Verify paused state
    state = graph.get_state(config)
    assert len(state.next) > 0
    assert "approval_gate" in state.next
    assert len(state.tasks) > 0
    assert len(state.tasks[0].interrupts) > 0

    interrupt_data = state.tasks[0].interrupts[0].value
    assert interrupt_data["type"] == "tool_approval"
    assert interrupt_data["pending_action"]["args"]["amount"] == 85.0

    # Resume graph with Human Approval Command
    resume_decision = {
        "approved": True,
        "reviewer_notes": "Manager approved special customer concession.",
    }
    final_result = graph.invoke(Command(resume=resume_decision), config=config)

    # Verify resolution
    final_state = graph.get_state(config)
    assert len(final_state.next) == 0
    assert final_result.get("ticket_status") == "resolved"
    assert "Concession" in final_result.get("worker_findings", "") or "APPROVED" in final_result.get("worker_findings", "")


def test_crash_safe_persistence_and_resume():
    """Simulates a hard crash / process kill while waiting for approval, then resumes from disk checkpoint."""
    # Process 1: Starts graph backed by on-disk SQLite checkpointer
    conn1 = sqlite3.connect(TEST_CHECKPOINT_DB, check_same_thread=False)
    checkpointer1 = SqliteSaver(conn1)
    checkpointer1.setup()
    graph1 = build_triage_graph(checkpointer=checkpointer1)

    thread_id = "thread_crash_test_003"
    config = {"configurable": {"thread_id": thread_id}}

    initial_input = {
        "ticket_id": "tkt_crash_3",
        "customer_id": "cust_002",
        "title": "Refund $85 for team seat",
        "body": "Need refund of $85 for the team seat.",
    }

    # Invocation pauses at approval gate
    graph1.invoke(initial_input, config=config)

    # Record tool calls completed BEFORE crash
    state1 = graph1.get_state(config)
    tool_history_pre_crash = list(state1.values.get("tool_history", []))
    assert len(tool_history_pre_crash) == 2  # get_customer, get_order_history

    # SIMULATE HARD PROCESS TERMINATION
    conn1.close()
    del graph1
    del checkpointer1

    # Process 2: Brand new process instance opens the SQLite database
    conn2 = sqlite3.connect(TEST_CHECKPOINT_DB, check_same_thread=False)
    checkpointer2 = SqliteSaver(conn2)
    graph2 = build_triage_graph(checkpointer=checkpointer2)

    # Verify state was preserved perfectly across process death
    resumed_state = graph2.get_state(config)
    assert "approval_gate" in resumed_state.next
    assert resumed_state.values["pending_action"]["args"]["amount"] == 85.0

    # Resume the interrupted execution
    final_res = graph2.invoke(Command(resume={"approved": True, "reviewer_notes": "Post-crash approval"}), config=config)

    # Verify execution finished without redoing initial read calls
    tool_history_post_resume = final_res.get("tool_history", [])
    # 2 original reads + 1 executed write = 3 total tool calls
    assert len(tool_history_post_resume) == 3
    assert tool_history_post_resume[2]["tool_name"] == "issue_refund"
    assert tool_history_post_resume[2]["approved"] is True

    conn2.close()
