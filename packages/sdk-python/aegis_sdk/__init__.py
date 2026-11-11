"""Official Python SDK for AEGIS — The Financial Black Box for AI Agents."""

from aegis_sdk.client import (
    AegisAPIError,
    AegisClient,
    AgentAuthorizationTool,
    verify_webhook_signature,
)

__all__ = [
    "AegisAPIError",
    "AegisClient",
    "AgentAuthorizationTool",
    "verify_webhook_signature",
]
