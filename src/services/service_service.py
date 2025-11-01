# src/services/service_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status
from models.service import Service, ServiceCategory, ServiceStatus
from schemas.service_schemas import ServiceCreate, ServiceUpdate, ServiceCategorySummary
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("SERVICE_SERVICE")


class ServiceService(BaseService):
    def __init__(self):
        super().__init__(Service)

    async def create_service(
        self, db: AsyncSession, service_data: ServiceCreate
    ) -> Service:
        """Create a new service with validation"""
        try:
            # Check if service code already exists for this tenant
            result = await db.execute(
                select(Service).where(
                    Service.tenant_id == service_data.tenant_id,
                    Service.code == service_data.code,
                )
            )
            existing_service = result.scalar_one_or_none()

            if existing_service:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Service with code '{service_data.code}' already exists",
                )

            # Create the service
            service = Service(**service_data.dict())
            db.add(service)
            await db.commit()
            await db.refresh(service)

            logger.info(f"Created service: {service.code} ({service.name})")
            return service

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating service: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not create service",
            )

    async def get_by_code(
        self, db: AsyncSession, tenant_id: UUID, code: str
    ) -> Optional[Service]:
        """Get service by code within a tenant"""
        try:
            result = await db.execute(
                select(Service).where(
                    Service.tenant_id == tenant_id,
                    Service.code == code,
                    Service.status == ServiceStatus.ACTIVE,
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting service by code {code}: {e}")
            return None

    async def get_by_category(
        self,
        db: AsyncSession,
        category: ServiceCategory,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Service]:
        """Get services by category"""
        try:
            result = await db.execute(
                select(Service)
                .where(
                    Service.category == category, Service.status == ServiceStatus.ACTIVE
                )
                .offset(skip)
                .limit(limit)
                .order_by(Service.name)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting services by category {category}: {e}")
            return []

    async def search_services(
        self, db: AsyncSession, search_term: str, skip: int = 0, limit: int = 50
    ) -> List[Service]:
        """Search services by name or description"""
        try:
            result = await db.execute(
                select(Service)
                .where(
                    and_(
                        Service.status == ServiceStatus.ACTIVE,
                        or_(
                            Service.name.ilike(f"%{search_term}%"),
                            Service.description.ilike(f"%{search_term}%"),
                            Service.code.ilike(f"%{search_term}%"),
                        ),
                    )
                )
                .offset(skip)
                .limit(limit)
                .order_by(Service.name)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error searching services with term '{search_term}': {e}")
            return []

    async def get_active_services(
        self, db: AsyncSession, skip: int = 0, limit: int = 100
    ) -> List[Service]:
        """Get all active services"""
        try:
            result = await db.execute(
                select(Service)
                .where(Service.status == ServiceStatus.ACTIVE)
                .offset(skip)
                .limit(limit)
                .order_by(Service.category, Service.name)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting active services: {e}")
            return []

    async def update_service_price(
        self, db: AsyncSession, service_id: UUID, new_price: Decimal
    ) -> Optional[Service]:
        """Update service price"""
        try:
            if new_price < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Price cannot be negative",
                )

            update_data = ServiceUpdate(base_price=new_price)
            service = await self.update(db, service_id, update_data)

            if service:
                logger.info(f"Updated price for service {service.code}: {new_price}")

            return service

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating service price: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not update service price",
            )

    async def get_categories_summary(
        self, db: AsyncSession
    ) -> List[ServiceCategorySummary]:
        """Get summary of services by category"""
        try:
            # Count services per category and calculate average price
            result = await db.execute(
                select(
                    Service.category,
                    func.count(Service.id).label("total_services"),
                    func.count(Service.id)
                    .filter(Service.status == ServiceStatus.ACTIVE)
                    .label("active_services"),
                    func.avg(Service.base_price).label("average_price"),
                )
                .group_by(Service.category)
                .order_by(Service.category)
            )

            categories_data = result.all()

            summary = []
            for category_data in categories_data:
                summary.append(
                    ServiceCategorySummary(
                        category=category_data.category,
                        total_services=category_data.total_services,
                        active_services=category_data.active_services,
                        average_price=Decimal(str(category_data.average_price or 0)),
                    )
                )

            return summary

        except Exception as e:
            logger.error(f"Error getting categories summary: {e}")
            return []

    async def bulk_update_status(
        self, db: AsyncSession, service_ids: List[UUID], new_status: ServiceStatus
    ) -> Dict[str, Any]:
        """Bulk update service status"""
        try:
            updated_count = 0
            errors = []

            for service_id in service_ids:
                try:
                    update_data = ServiceUpdate(status=new_status)
                    service = await self.update(db, service_id, update_data)

                    if service:
                        updated_count += 1
                        logger.info(
                            f"Updated status for service {service_id} to {new_status}"
                        )
                    else:
                        errors.append(f"Service {service_id} not found")

                except Exception as e:
                    errors.append(f"Failed to update service {service_id}: {str(e)}")

            return {
                "success": len(errors) == 0,
                "processed": len(service_ids),
                "updated": updated_count,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"Error in bulk update status: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not perform bulk update",
            )

    async def get_services_with_filters(
        self,
        db: AsyncSession,
        category: Optional[ServiceCategory] = None,
        status: Optional[ServiceStatus] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Service]:
        """Get services with advanced filtering"""
        try:
            query = select(Service)

            # Build filter conditions
            conditions = []

            if category:
                conditions.append(Service.category == category)

            if status:
                conditions.append(Service.status == status)
            else:
                # Default to active services if no status specified
                conditions.append(Service.status == ServiceStatus.ACTIVE)

            if min_price is not None:
                conditions.append(Service.base_price >= min_price)

            if max_price is not None:
                conditions.append(Service.base_price <= max_price)

            if conditions:
                query = query.where(and_(*conditions))

            query = (
                query.offset(skip).limit(limit).order_by(Service.category, Service.name)
            )

            result = await db.execute(query)
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error getting services with filters: {e}")
            return []

    async def calculate_service_revenue(
        self, db: AsyncSession, service_id: UUID, period_days: int = 30
    ) -> Dict[str, Any]:
        """Calculate revenue for a specific service over a period"""
        try:
            from models.treatment_item import TreatmentItem
            from models.invoice_item import InvoiceItem
            from models.invoice import Invoice, InvoiceStatus
            from datetime import datetime, timedelta

            service = await self.get(db, service_id)
            if not service:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
                )

            # Calculate start date for the period
            start_date = datetime.utcnow() - timedelta(days=period_days)

            # Get revenue data from treatment items and invoices
            revenue_result = await db.execute(
                select(
                    func.sum(TreatmentItem.quantity * TreatmentItem.unit_price).label(
                        "total_revenue"
                    ),
                    func.count(TreatmentItem.id).label("total_treatments"),
                )
                .select_from(TreatmentItem)
                .join(InvoiceItem, InvoiceItem.treatment_item_id == TreatmentItem.id)
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .where(
                    TreatmentItem.service_id == service_id,
                    Invoice.status == InvoiceStatus.PAID,
                    Invoice.paid_date >= start_date,
                )
            )

            revenue_data = revenue_result.scalar_one_or_none()

            total_revenue = revenue_data.total_revenue or Decimal("0.00")
            total_treatments = revenue_data.total_treatments or 0
            average_revenue = (
                total_revenue / total_treatments
                if total_treatments > 0
                else Decimal("0.00")
            )

            return {
                "service_id": service_id,
                "service_name": service.name,
                "period_days": period_days,
                "total_revenue": total_revenue,
                "total_treatments": total_treatments,
                "average_revenue_per_treatment": average_revenue,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error calculating service revenue: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not calculate service revenue",
            )


# Create service instance
service_service = ServiceService()
