import stripe
from typing import Optional
from core.config import settings
from utils.logger import setup_logger

logger = setup_logger("PAYMENT_SERVICE")


class PaymentService:
    """Service for handling payment provider integration"""

    def __init__(self):
        stripe.api_key = settings.STRIPE_SECRET_KEY

    async def get_subscription_status(self, subscription_id: str) -> Optional[str]:
        """Get subscription status from Stripe"""
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            return subscription.status
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving subscription {subscription_id}: {e}")
            return None
