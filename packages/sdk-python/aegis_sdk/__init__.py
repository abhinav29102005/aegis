"""Official Python SDK for AEGIS — The Financial Black Box for AI Agents."""

from aegis_sdk.client import (
    AegisAPIError,
    AegisClient,
    AgentAuthorizationTool,
    AsyncAegisClient,
    AsyncAgentAuthorizationTool,
)
from aegis_sdk.integrations import (
    AegisPurchaseInput,
    AegisSpendingTool,
    OpenAIPurchaseGuard,
    ahandle_openai_purchase_call,
    create_aegis_spending_tool,
    get_openai_purchase_tool_spec,
    handle_openai_purchase_call,
)
from aegis_sdk.pagination import (
    AsyncPaginationIterator,
    PaginationIterator,
    paginate,
    paginate_async,
)
from aegis_sdk.webhook import verify_aegis_signature, verify_webhook_signature

__all__ = [
    "AegisAPIError",
    "AegisClient",
    "AegisPurchaseInput",
    "AegisSpendingTool",
    "AgentAuthorizationTool",
    "AsyncAegisClient",
    "AsyncAgentAuthorizationTool",
    "AsyncPaginationIterator",
    "OpenAIPurchaseGuard",
    "PaginationIterator",
    "ahandle_openai_purchase_call",
    "create_aegis_spending_tool",
    "get_openai_purchase_tool_spec",
    "handle_openai_purchase_call",
    "paginate",
    "paginate_async",
    "verify_aegis_signature",
    "verify_webhook_signature",
]
