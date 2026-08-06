"""Observability integration for TriageGraph.

Supports:
- LangSmith automatic tracing
- Custom metadata tagging for ticket metrics and latency reporting
"""

import os
from typing import Dict, Any


def configure_observability() -> Dict[str, Any]:
    """Inspects environment and activates tracing if credentials are present."""
    langchain_api_key = os.getenv("LANGCHAIN_API_KEY")
    langfuse_pk = os.getenv("LANGFUSE_PUBLIC_KEY")

    status = {
        "langsmith_active": False,
        "langfuse_active": False,
    }

    if langchain_api_key and not langchain_api_key.startswith("your_"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ.setdefault("LANGCHAIN_PROJECT", "TriageGraph")
        status["langsmith_active"] = True

    if langfuse_pk:
        status["langfuse_active"] = True

    return status
