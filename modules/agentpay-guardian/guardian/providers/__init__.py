"""Multi-rail payment provider adapters for AgentPay Guardian."""

from guardian.providers.ap2 import (
    AP2CheckoutMandate,
    AP2MandateAdapter,
    AP2PaymentMandate,
)
from guardian.providers.base import (
    ProviderAdapterError,
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderSignatureError,
    ProviderValidationError,
    RetryingHTTPClient,
)
from guardian.providers.deflection import (
    DeflectionAlertAdapter,
    DeflectionHandlingResult,
    DeflectionSource,
)
from guardian.providers.stripe import StripeProviderAdapter
from guardian.providers.tap import (
    TAPNetwork,
    TAPProvenanceAdapter,
    TAPProvenanceResult,
)
from guardian.providers.x402 import (
    X402SettlementAdapter,
    X402VerificationResult,
)

__all__ = [
    "AP2CheckoutMandate",
    "AP2MandateAdapter",
    "AP2PaymentMandate",
    "DeflectionAlertAdapter",
    "DeflectionHandlingResult",
    "DeflectionSource",
    "ProviderAPIError",
    "ProviderAdapterError",
    "ProviderConfigurationError",
    "ProviderSignatureError",
    "ProviderValidationError",
    "RetryingHTTPClient",
    "StripeProviderAdapter",
    "TAPNetwork",
    "TAPProvenanceAdapter",
    "TAPProvenanceResult",
    "X402SettlementAdapter",
    "X402VerificationResult",
]
