"""AI agent framework integrations and middleware guards for AEGIS."""

from aegis_sdk.integrations.langchain import (
    AegisPurchaseInput,
    AegisSpendingTool,
    create_aegis_spending_tool,
)
from aegis_sdk.integrations.openai_agents import (
    OpenAIPurchaseGuard,
    ahandle_openai_purchase_call,
    get_openai_purchase_tool_spec,
    handle_openai_purchase_call,
)

__all__ = [
    "AegisPurchaseInput",
    "AegisSpendingTool",
    "OpenAIPurchaseGuard",
    "ahandle_openai_purchase_call",
    "create_aegis_spending_tool",
    "get_openai_purchase_tool_spec",
    "handle_openai_purchase_call",
]
