# src/routes/newsletters.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from db.database import get_db
from schemas.newsletter_schemas import (
    NewsletterCreate,
    NewsletterUpdate,
    NewsletterPublic,
    NewsletterDetail,
    SubscriptionCreate,
    SubscriptionPublic,
    NewsletterSend,
)
from services.newsletter_service import newsletter_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/newsletters", tags=["newsletters"])


@router.get(
    "/",
    response_model=List[NewsletterPublic],
    summary="List newsletters",
    description="Get list of newsletters",
)
async def list_newsletters(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List newsletters endpoint"""
    filters = {}
    if status:
        filters["status"] = status

    newsletters = await newsletter_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    return [NewsletterPublic.from_orm(newsletter) for newsletter in newsletters]


@router.post(
    "/",
    response_model=NewsletterPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create newsletter",
    description="Create a new newsletter",
)
async def create_newsletter(
    newsletter_data: NewsletterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create newsletter endpoint"""
    newsletter_data.created_by = current_user.id
    newsletter = await newsletter_service.create_newsletter(db, newsletter_data)
    return NewsletterPublic.from_orm(newsletter)


@router.get(
    "/{newsletter_id}",
    response_model=NewsletterDetail,
    summary="Get newsletter",
    description="Get newsletter details by ID",
)
async def get_newsletter(
    newsletter_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get newsletter by ID endpoint"""
    newsletter = await newsletter_service.get(db, newsletter_id)
    if not newsletter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Newsletter not found"
        )

    newsletter_detail = NewsletterDetail.from_orm(newsletter)
    newsletter_detail.created_by_name = (
        f"{newsletter.creator.first_name} {newsletter.creator.last_name}"
    )

    return newsletter_detail


@router.post(
    "/{newsletter_id}/send",
    summary="Send newsletter",
    description="Send newsletter to subscribers",
)
async def send_newsletter(
    newsletter_id: UUID,
    send_data: NewsletterSend = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send newsletter endpoint"""
    result = await newsletter_service.send_newsletter(db, newsletter_id, send_data)
    return result


@router.get(
    "/subscriptions/",
    response_model=List[SubscriptionPublic],
    summary="List subscriptions",
    description="Get list of newsletter subscriptions",
)
async def list_subscriptions(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List subscriptions endpoint"""
    filters = {}
    if status:
        filters["status"] = status

    subscriptions = await newsletter_service.get_subscriptions(
        db, skip=skip, limit=limit, filters=filters
    )
    return [SubscriptionPublic.from_orm(subscription) for subscription in subscriptions]


@router.post(
    "/subscriptions/",
    response_model=SubscriptionPublic,
    summary="Create subscription",
    description="Create a new newsletter subscription",
)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create subscription endpoint"""
    subscription = await newsletter_service.create_subscription(db, subscription_data)
    return SubscriptionPublic.from_orm(subscription)
