"""DisputeOS PayPal adapter and webhook handler exports."""

from disputeos.paypal.adapter import PayPalDisputeAdapter
from disputeos.paypal.webhook_handler import handle_paypal_dispute_webhook

__all__ = [
    "PayPalDisputeAdapter",
    "handle_paypal_dispute_webhook",
]
