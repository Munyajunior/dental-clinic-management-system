# src/services/newsletter_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status
from models.newsletter import (
    Newsletter,
    NewsletterStatus,
    NewsletterSubscription,
    SubscriptionStatus,
)
from models.patient import Patient
from models.user import User
from schemas.newsletter_schemas import (
    NewsletterCreate,
    NewsletterUpdate,
    SubscriptionCreate,
    NewsletterSend,
)
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("NEWSLETTER_SERVICE")


class NewsletterService(BaseService):
    def __init__(self):
        super().__init__(Newsletter)

    async def create_newsletter(
        self, db: AsyncSession, newsletter_data: NewsletterCreate
    ) -> Newsletter:
        """Create new newsletter"""
        # Verify creator exists
        creator_result = await db.execute(
            select(User).where(User.id == newsletter_data.created_by, User.is_active)
        )
        creator = creator_result.scalar_one_or_none()
        if not creator:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Creator not found or inactive",
            )

        newsletter = Newsletter(**newsletter_data.dict())
        db.add(newsletter)
        await db.commit()
        await db.refresh(newsletter)

        logger.info(f"Created new newsletter: {newsletter.id}")
        return newsletter

    async def create_subscription(
        self, db: AsyncSession, subscription_data: SubscriptionCreate
    ) -> NewsletterSubscription:
        """Create new newsletter subscription"""
        # Verify patient exists
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == subscription_data.patient_id, Patient.is_active
            )
        )
        patient = patient_result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient not found or inactive",
            )

        # Check if subscription already exists
        existing_result = await db.execute(
            select(NewsletterSubscription).where(
                NewsletterSubscription.patient_id == subscription_data.patient_id,
                NewsletterSubscription.email == subscription_data.email,
            )
        )
        existing_subscription = existing_result.scalar_one_or_none()

        if existing_subscription:
            # Update existing subscription
            existing_subscription.status = SubscriptionStatus.SUBSCRIBED
            existing_subscription.preferences = subscription_data.preferences or {}
            await db.commit()
            await db.refresh(existing_subscription)
            return existing_subscription

        subscription = NewsletterSubscription(**subscription_data.dict())
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)

        logger.info(f"Created new subscription for patient: {patient.id}")
        return subscription

    async def get_subscriptions(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[NewsletterSubscription]:
        """Get newsletter subscriptions with filters"""
        try:
            query = select(NewsletterSubscription)

            if filters:
                if filters.get("status"):
                    query = query.where(
                        NewsletterSubscription.status == filters["status"]
                    )

            query = (
                query.offset(skip)
                .limit(limit)
                .order_by(NewsletterSubscription.created_at.desc())
            )

            result = await db.execute(query)
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting subscriptions: {e}")
            return []

    async def send_newsletter(
        self,
        db: AsyncSession,
        newsletter_id: UUID,
        send_data: Optional[NewsletterSend] = None,
    ) -> Dict[str, Any]:
        """Send newsletter to subscribers"""
        newsletter = await self.get(db, newsletter_id)
        if not newsletter:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Newsletter not found"
            )

        if newsletter.status == NewsletterStatus.SENT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Newsletter has already been sent",
            )

        # Get subscribers based on filters
        subscribers = await self._get_recipients(db, newsletter.recipient_filters)

        if send_data and send_data.test_emails:
            # Send test emails
            test_results = await self._send_test_emails(
                send_data.test_emails, newsletter
            )
            return {
                "message": "Test emails sent",
                "test_emails": send_data.test_emails,
                "test_results": test_results,
            }

        if send_data and send_data.send_immediately:
            # Send immediately to all subscribers
            send_results = await self._send_to_subscribers(subscribers, newsletter)

            # Update newsletter status
            newsletter.status = NewsletterStatus.SENT
            newsletter.sent_at = datetime.utcnow()
            newsletter.total_recipients = len(subscribers)
            newsletter.total_sent = send_results["success_count"]

            await db.commit()

            return {
                "message": "Newsletter sent successfully",
                "total_recipients": len(subscribers),
                "success_count": send_results["success_count"],
                "failed_count": send_results["failed_count"],
            }
        else:
            # Schedule for later sending
            newsletter.status = NewsletterStatus.SCHEDULED
            newsletter.total_recipients = len(subscribers)
            await db.commit()

            return {
                "message": "Newsletter scheduled for sending",
                "scheduled_for": newsletter.scheduled_for,
                "total_recipients": len(subscribers),
            }

    async def _get_recipients(
        self, db: AsyncSession, recipient_filters: Optional[Dict[str, Any]]
    ) -> List[NewsletterSubscription]:
        """Get recipients based on filters"""
        try:
            query = select(NewsletterSubscription).where(
                NewsletterSubscription.status == SubscriptionStatus.SUBSCRIBED
            )

            if recipient_filters:
                # Implement filter logic based on your requirements
                # Example: filter by patient status, last visit date, etc.
                pass

            result = await db.execute(query)
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting recipients: {e}")
            return []

    async def _send_test_emails(
        self, test_emails: List[str], newsletter: Newsletter
    ) -> Dict[str, Any]:
        """Send test emails"""
        # Implement email sending logic
        # This is a placeholder - integrate with your email service
        logger.info(f"Sending test emails to: {test_emails}")

        return {
            "success_count": len(test_emails),
            "failed_count": 0,
            "sent_to": test_emails,
        }

    async def _send_to_subscribers(
        self, subscribers: List[NewsletterSubscription], newsletter: Newsletter
    ) -> Dict[str, Any]:
        """Send newsletter to subscribers"""
        success_count = 0
        failed_count = 0

        # Implement actual email sending logic
        # This is a placeholder - integrate with your email service (SendGrid, Mailgun, etc.)
        for subscriber in subscribers:
            try:
                # Send email to subscriber.email
                # Update subscriber.last_sent_at
                subscriber.last_sent_at = datetime.utcnow()
                success_count += 1
                logger.info(f"Sent newsletter to: {subscriber.email}")
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to send newsletter to {subscriber.email}: {e}")

        return {"success_count": success_count, "failed_count": failed_count}

    async def unsubscribe(self, db: AsyncSession, subscription_id: UUID) -> bool:
        """Unsubscribe from newsletter"""
        subscription = await db.get(NewsletterSubscription, subscription_id)
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found"
            )

        subscription.status = SubscriptionStatus.UNSUBSCRIBED
        subscription.unsubscribed_at = datetime.utcnow()

        await db.commit()

        logger.info(f"Unsubscribed: {subscription.email}")
        return True

    async def get_newsletter_stats(self, db: AsyncSession) -> Dict[str, Any]:
        """Get newsletter statistics"""
        try:
            from sqlalchemy import func

            # Total newsletters
            total_result = await db.execute(select(func.count(Newsletter.id)))
            total_newsletters = total_result.scalar()

            # Total subscribers
            subscribers_result = await db.execute(
                select(func.count(NewsletterSubscription.id)).where(
                    NewsletterSubscription.status == SubscriptionStatus.SUBSCRIBED
                )
            )
            total_subscribers = subscribers_result.scalar()

            # Sent newsletters
            sent_result = await db.execute(
                select(func.count(Newsletter.id)).where(
                    Newsletter.status == NewsletterStatus.SENT
                )
            )
            sent_newsletters = sent_result.scalar()

            return {
                "total_newsletters": total_newsletters,
                "total_subscribers": total_subscribers,
                "sent_newsletters": sent_newsletters,
            }
        except Exception as e:
            logger.error(f"Error getting newsletter stats: {e}")
            return {}


newsletter_service = NewsletterService()
