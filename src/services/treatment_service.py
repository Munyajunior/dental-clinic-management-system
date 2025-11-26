# src/services/treatment_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, text
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from models.treatment import Treatment, TreatmentStatus
from models.treatment_item import TreatmentItem
from models.consultation import Consultation
from models.patient import Patient, PatientStatus
from models.user import User, StaffRole
from models.service import Service
from schemas.treatment_schemas import (
    TreatmentCreate,
    TreatmentUpdate,
    TreatmentProgressNote,
    TreatmentItemCreate,
)
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("TREATMENT_SERVICE")


class TreatmentService(BaseService):
    def __init__(self):
        super().__init__(Treatment)
        self.search_fields = ["name", "description"]  # Define searchable fields

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
        search_query: Optional[str] = None,
        search_fields: Optional[List[str]] = None,
    ) -> List[Treatment]:
        """Get treatments with advanced search including patient and dentist names"""
        try:
            query = select(Treatment)

            # Apply basic filters
            if filters:
                conditions = []
                for field, value in filters.items():
                    if hasattr(Treatment, field):
                        conditions.append(getattr(Treatment, field) == value)
                if conditions:
                    query = query.where(and_(*conditions))

            # Apply advanced search
            if search_query:
                search_conditions = []

                # Search in treatment fields
                if search_fields or self.search_fields:
                    fields_to_search = search_fields or self.search_fields
                    for field in fields_to_search:
                        if hasattr(Treatment, field):
                            search_conditions.append(
                                getattr(Treatment, field).ilike(f"%{search_query}%")
                            )

                # Search in patient name (if relationship exists)
                if hasattr(Treatment, "patient"):
                    search_conditions.extend(
                        [
                            Treatment.patient.has(
                                Patient.first_name.ilike(f"%{search_query}%")
                            ),
                            Treatment.patient.has(
                                Patient.last_name.ilike(f"%{search_query}%")
                            ),
                        ]
                    )

                # Search in dentist name (if relationship exists)
                if hasattr(Treatment, "dentist"):
                    search_conditions.extend(
                        [
                            Treatment.dentist.has(
                                User.first_name.ilike(f"%{search_query}%")
                            ),
                            Treatment.dentist.has(
                                User.last_name.ilike(f"%{search_query}%")
                            ),
                        ]
                    )

                if search_conditions:
                    query = query.where(or_(*search_conditions))

            query = query.offset(skip).limit(limit)
            result = await db.execute(query)
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error in treatment service get_multi: {e}")
            return []

    async def create_treatment(
        self, db: AsyncSession, treatment_data: TreatmentCreate, current_user: User
    ) -> Treatment:
        """Create new treatment with authorization check"""
        try:
            # Verify patient exists and is active
            patient_result = await db.execute(
                select(Patient).where(
                    Patient.id == treatment_data.patient_id,
                    Patient.status == PatientStatus.ACTIVE,
                )
            )
            patient = patient_result.scalar_one_or_none()
            if not patient:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Patient not found or inactive",
                )

            # AUTHORIZATION CHECK: Verify user can create treatment for this patient
            can_create_treatment = await self._can_user_create_treatment(
                db, current_user, patient
            )
            if not can_create_treatment:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to create treatments for this patient. "
                    "You must be assigned to the patient and have conducted a consultation.",
                )

            # Verify dentist exists and is active
            dentist_result = await db.execute(
                select(User).where(
                    User.id == treatment_data.dentist_id,
                    User.is_active == True,
                    User.role.in_(
                        [
                            StaffRole.DENTIST,
                            StaffRole.THERAPIST,
                            StaffRole.HYGIENIST,
                        ]
                    ),
                )
            )
            dentist = dentist_result.scalar_one_or_none()
            if not dentist:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Dental professional not found or inactive",
                )

            # If consultation_id is provided, verify it exists and belongs to this patient
            if treatment_data.consultation_id:
                consultation_result = await db.execute(
                    select(Consultation).where(
                        Consultation.id == treatment_data.consultation_id,
                        Consultation.patient_id == treatment_data.patient_id,
                    )
                )
                consultation = consultation_result.scalar_one_or_none()
                if not consultation:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Consultation not found for this patient",
                    )

            # Convert to dict and handle UUID serialization
            treatment_dict = treatment_data.model_dump()

            # Ensure proper UUID handling
            for field in [
                "patient_id",
                "dentist_id",
                "consultation_id",
                "appointment_id",
            ]:
                if field in treatment_dict and treatment_dict[field]:
                    if isinstance(treatment_dict[field], str):
                        try:
                            treatment_dict[field] = UUID(treatment_dict[field])
                        except ValueError:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Invalid {field} format",
                            )

            treatment = Treatment(**treatment_dict)
            db.add(treatment)
            await db.commit()
            await db.refresh(treatment)

            logger.info(
                f"Created new treatment: {treatment.id} for patient {patient.id} by user {current_user.id}"
            )
            return treatment

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating treatment: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create treatment",
            )

    async def _can_user_create_treatment(
        self, db: AsyncSession, user: User, patient: Patient
    ) -> bool:
        """Check if user can create treatment for this patient"""

        # Admin and manager users have all privileges
        if user.role in [StaffRole.ADMIN, StaffRole.MANAGER]:
            return True

        # Dental professionals (dentist, therapist, hygienist) need to meet conditions
        if user.role in [StaffRole.DENTIST, StaffRole.THERAPIST, StaffRole.HYGIENIST]:
            # Condition 1: Must be assigned to the patient
            if patient.assigned_dentist_id != user.id:
                logger.warning(
                    f"User {user.id} not assigned to patient {patient.id}. "
                    f"Patient assigned to: {patient.assigned_dentist_id}"
                )
                return False

            # Condition 2: Must have conducted at least one consultation for this patient
            consultation_count = await self._get_user_consultation_count_for_patient(
                db, user.id, patient.id
            )

            if consultation_count == 0:
                logger.warning(
                    f"User {user.id} has not conducted any consultations for patient {patient.id}"
                )
                return False

            return True

        # Other roles cannot create treatments
        return False

    async def _get_user_consultation_count_for_patient(
        self, db: AsyncSession, user_id: UUID, patient_id: UUID
    ) -> int:
        """Get count of consultations conducted by user for this patient"""
        try:
            result = await db.execute(
                select(func.count(Consultation.id)).where(
                    Consultation.dentist_id == user_id,
                    Consultation.patient_id == patient_id,
                )
            )
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting consultation count: {e}")
            return 0

    async def add_progress_note(
        self,
        db: AsyncSession,
        treatment_id: UUID,
        progress_note: TreatmentProgressNote,
        recorded_by: UUID,
    ) -> Optional[Treatment]:
        """Add progress note to treatment"""
        treatment = await self.get(db, treatment_id)
        if not treatment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )

        # Initialize progress_notes if None
        if treatment.progress_notes is None:
            treatment.progress_notes = []

        # Add the new progress note
        progress_note_dict = progress_note.dict()
        progress_note_dict["recorded_by"] = recorded_by
        progress_note_dict["recorded_at"] = datetime.utcnow()

        treatment.progress_notes.append(progress_note_dict)

        # Update current stage if provided
        if progress_note.stage:
            treatment.current_stage = progress_note.stage

        await db.commit()
        await db.refresh(treatment)

        logger.info(f"Added progress note to treatment: {treatment_id}")
        return treatment

    async def add_treatment_item(
        self, db: AsyncSession, treatment_id: UUID, item_data: TreatmentItemCreate
    ) -> Optional[Treatment]:
        """Add treatment item to treatment"""
        treatment = await self.get(db, treatment_id)
        if not treatment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )

        # Verify service exists
        service_result = await db.execute(
            select(Service).where(
                Service.id == item_data.service_id, Service.status == "active"
            )
        )
        service = service_result.scalar_one_or_none()
        if not service:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Service not found or inactive",
            )

        # Create treatment item
        treatment_item = TreatmentItem(
            treatment_id=treatment_id,
            service_id=item_data.service_id,
            quantity=item_data.quantity,
            unit_price=service.base_price,  # Use service base price
            tooth_number=item_data.tooth_number,
            surface=item_data.surface,
            notes=item_data.notes,
        )

        db.add(treatment_item)
        await db.commit()
        await db.refresh(treatment)

        logger.info(f"Added treatment item to treatment: {treatment_id}")
        return treatment

    async def update_status(
        self, db: AsyncSession, treatment_id: UUID, status: TreatmentStatus
    ) -> Optional[Treatment]:
        """Update treatment status"""
        treatment = await self.get(db, treatment_id)
        if not treatment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )

        treatment.status = status

        # Set timestamps based on status
        now = datetime.utcnow()
        if status == TreatmentStatus.IN_PROGRESS and not treatment.started_at:
            treatment.started_at = now
        elif status == TreatmentStatus.COMPLETED and not treatment.completed_at:
            treatment.completed_at = now

        await db.commit()
        await db.refresh(treatment)

        logger.info(f"Updated treatment {treatment_id} status to {status}")
        return treatment

    async def calculate_treatment_cost(
        self, db: AsyncSession, treatment_id: UUID
    ) -> Dict[str, Any]:
        """Calculate total cost for treatment"""
        treatment = await self.get(db, treatment_id)
        if not treatment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )

        # Calculate from treatment items
        result = await db.execute(
            select(TreatmentItem).where(TreatmentItem.treatment_id == treatment_id)
        )
        items = result.scalars().all()

        subtotal = sum(item.quantity * item.unit_price for item in items)

        # You can add tax calculation here if needed
        total = subtotal

        return {
            "subtotal": subtotal,
            "tax": 0,  # Add tax calculation if needed
            "total": total,
            "items_count": len(items),
        }

    async def get_treatment_items(
        self, db: AsyncSession, treatment_id: UUID
    ) -> List[TreatmentItem]:
        """Get all treatment items for a treatment"""
        try:
            result = await db.execute(
                select(TreatmentItem)
                .where(TreatmentItem.treatment_id == treatment_id)
                .order_by(TreatmentItem.created_at)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting treatment items: {e}")
            return []

    async def search_treatments(
        self, db: AsyncSession, query: str, skip: int = 0, limit: int = 50
    ) -> List[Treatment]:
        """Search treatments by name, patient name, or dentist name"""
        try:
            search_filter = or_(
                Treatment.name.ilike(f"%{query}%"),
                Treatment.patient.has(
                    or_(
                        Patient.first_name.ilike(f"%{query}%"),
                        Patient.last_name.ilike(f"%{query}%"),
                    )
                ),
                Treatment.dentist.has(
                    or_(
                        User.first_name.ilike(f"%{query}%"),
                        User.last_name.ilike(f"%{query}%"),
                    )
                ),
            )

            result = await db.execute(
                select(Treatment)
                .options(
                    selectinload(Treatment.patient), selectinload(Treatment.dentist)
                )
                .where(search_filter)
                .offset(skip)
                .limit(limit)
                .order_by(Treatment.created_at.desc())
            )

            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error searching treatments: {e}")
            return []

    async def duplicate_treatment(
        self,
        db: AsyncSession,
        treatment_id: UUID,
        new_name: Optional[str] = None,
        created_by: Optional[UUID] = None,
    ) -> Optional[Treatment]:
        """Duplicate an existing treatment"""
        try:
            original = await self.get(db, treatment_id)
            if not original:
                return None

            # Create new treatment data
            treatment_data = {
                "patient_id": original.patient_id,
                "dentist_id": original.dentist_id,
                "name": new_name or f"Copy of {original.name}",
                "description": original.description,
                "priority": original.priority,
                "teeth_involved": original.teeth_involved,
                "quadrants": original.quadrants,
                "total_stages": original.total_stages,
                "estimated_cost": original.estimated_cost,
            }

            new_treatment = Treatment(**treatment_data)
            db.add(new_treatment)
            await db.flush()  # Get the new treatment ID

            # Copy treatment items
            items = await self.get_treatment_items(db, treatment_id)
            for item in items:
                new_item = TreatmentItem(
                    treatment_id=new_treatment.id,
                    service_id=item.service_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    tooth_number=item.tooth_number,
                    surface=item.surface,
                    notes=item.notes,
                )
                db.add(new_item)

            await db.commit()
            await db.refresh(new_treatment)

            logger.info(f"Duplicated treatment {treatment_id} to {new_treatment.id}")
            return new_treatment

        except Exception as e:
            await db.rollback()
            logger.error(f"Error duplicating treatment: {e}")
            return None

    async def get_treatment_statistics(
        self, db: AsyncSession, days: int = 30
    ) -> Dict[str, Any]:
        """Get treatment statistics"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)

            # Total counts
            total_result = await db.execute(select(func.count(Treatment.id)))
            total_count = total_result.scalar()

            # Count by status
            status_result = await db.execute(
                select(Treatment.status, func.count(Treatment.id)).group_by(
                    Treatment.status
                )
            )
            by_status = dict(status_result.all())

            # Count by priority
            priority_result = await db.execute(
                select(Treatment.priority, func.count(Treatment.id)).group_by(
                    Treatment.priority
                )
            )
            by_priority = dict(priority_result.all())

            # Recent treatments
            recent_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.created_at >= start_date
                )
            )
            recent_treatments = recent_result.scalar()

            # Average cost
            cost_result = await db.execute(
                select(func.avg(Treatment.estimated_cost)).where(
                    Treatment.estimated_cost.isnot(None)
                )
            )
            average_cost = cost_result.scalar() or 0

            # Completion rate
            completed_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.status == TreatmentStatus.COMPLETED
                )
            )
            completed_count = completed_result.scalar()
            completion_rate = (
                (completed_count / total_count * 100) if total_count > 0 else 0
            )

            return {
                "total_count": total_count,
                "by_status": by_status,
                "by_priority": by_priority,
                "recent_treatments": recent_treatments,
                "average_cost": float(average_cost),
                "completion_rate": round(completion_rate, 2),
            }

        except Exception as e:
            logger.error(f"Error getting treatment statistics: {e}")
            return {}

    async def bulk_update_treatments(
        self, db: AsyncSession, updates: List[Dict[str, Any]], updated_by: UUID
    ) -> Dict[str, Any]:
        """Bulk update treatments"""
        try:
            results = {"successful": 0, "failed": 0, "errors": []}

            for update in updates:
                try:
                    treatment_id = update.get("id")
                    if not treatment_id:
                        continue

                    treatment_data = {k: v for k, v in update.items() if k != "id"}
                    treatment = await self.update(
                        db, UUID(treatment_id), treatment_data
                    )

                    if treatment:
                        results["successful"] += 1
                    else:
                        results["failed"] += 1
                        results["errors"].append(f"Treatment {treatment_id} not found")

                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append(
                        f"Error updating treatment {update.get('id')}: {str(e)}"
                    )

            await db.commit()
            return results

        except Exception as e:
            await db.rollback()
            logger.error(f"Error in bulk update: {e}")
            raise

    async def get_treatment_analytics(
        self, db: AsyncSession, start_date: str, end_date: str, group_by: str = "month"
    ) -> Dict[str, Any]:
        """Get comprehensive treatment analytics"""
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

            # Basic counts
            total_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.created_at.between(start_dt, end_dt)
                )
            )
            total_treatments = total_result.scalar()

            # Count by status
            status_result = await db.execute(
                select(Treatment.status, func.count(Treatment.id))
                .where(Treatment.created_at.between(start_dt, end_dt))
                .group_by(Treatment.status)
            )
            treatments_by_status = dict(status_result.all())

            # Revenue calculations
            revenue_result = await db.execute(
                select(func.sum(Treatment.estimated_cost)).where(
                    Treatment.created_at.between(start_dt, end_dt),
                    Treatment.estimated_cost.isnot(None),
                )
            )
            revenue_total = revenue_result.scalar() or 0

            # Revenue by status
            revenue_status_result = await db.execute(
                select(Treatment.status, func.sum(Treatment.estimated_cost))
                .where(
                    Treatment.created_at.between(start_dt, end_dt),
                    Treatment.estimated_cost.isnot(None),
                )
                .group_by(Treatment.status)
            )
            revenue_by_status = dict(revenue_status_result.all())

            # Treatments by time period
            if group_by == "month":
                date_format = "%Y-%m"
            elif group_by == "week":
                date_format = "%Y-%U"
            else:  # day
                date_format = "%Y-%m-%d"

            period_result = await db.execute(
                select(
                    func.to_char(Treatment.created_at, date_format).label("period"),
                    func.count(Treatment.id),
                )
                .where(Treatment.created_at.between(start_dt, end_dt))
                .group_by("period")
                .order_by("period")
            )
            treatments_by_period = dict(period_result.all())

            # Top services
            top_services_result = await db.execute(
                select(
                    TreatmentItem.service_id,
                    func.count(TreatmentItem.id).label("count"),
                )
                .join(Treatment)
                .where(Treatment.created_at.between(start_dt, end_dt))
                .group_by(TreatmentItem.service_id)
                .order_by(func.count(TreatmentItem.id).desc())
                .limit(10)
            )
            top_services = [
                {"service_id": row[0], "count": row[1]}
                for row in top_services_result.all()
            ]

            return {
                "total_treatments": total_treatments,
                "completed_treatments": treatments_by_status.get(
                    TreatmentStatus.COMPLETED, 0
                ),
                "in_progress_treatments": treatments_by_status.get(
                    TreatmentStatus.IN_PROGRESS, 0
                ),
                "planned_treatments": treatments_by_status.get(
                    TreatmentStatus.PLANNED, 0
                ),
                "cancelled_treatments": treatments_by_status.get(
                    TreatmentStatus.CANCELLED, 0
                ),
                "revenue_total": float(revenue_total),
                "revenue_by_status": {
                    k: float(v) for k, v in revenue_by_status.items()
                },
                "treatments_by_month": treatments_by_period,
                "top_services": top_services,
            }

        except Exception as e:
            logger.error(f"Error getting treatment analytics: {e}")
            return {}

    async def get_dentist_treatment_stats(
        self, db: AsyncSession, dentist_id: UUID, months: int = 12
    ) -> Dict[str, Any]:
        """Get treatment statistics for a specific dentist"""
        try:
            start_date = datetime.utcnow() - timedelta(days=months * 30)

            # Total treatments
            total_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.dentist_id == dentist_id,
                    Treatment.created_at >= start_date,
                )
            )
            total_treatments = total_result.scalar()

            # Treatments by status
            status_result = await db.execute(
                select(Treatment.status, func.count(Treatment.id))
                .where(
                    Treatment.dentist_id == dentist_id,
                    Treatment.created_at >= start_date,
                )
                .group_by(Treatment.status)
            )
            treatments_by_status = dict(status_result.all())

            # Average completion time
            completion_time_result = await db.execute(
                select(
                    func.avg(
                        func.extract(
                            "epoch", Treatment.completed_at - Treatment.started_at
                        )
                        / 86400
                    )
                ).where(
                    Treatment.dentist_id == dentist_id,
                    Treatment.started_at.isnot(None),
                    Treatment.completed_at.isnot(None),
                    Treatment.created_at >= start_date,
                )
            )
            avg_completion_days = completion_time_result.scalar() or 0

            # Revenue
            revenue_result = await db.execute(
                select(func.sum(Treatment.estimated_cost)).where(
                    Treatment.dentist_id == dentist_id,
                    Treatment.estimated_cost.isnot(None),
                    Treatment.created_at >= start_date,
                )
            )
            total_revenue = revenue_result.scalar() or 0

            return {
                "total_treatments": total_treatments,
                "treatments_by_status": treatments_by_status,
                "average_completion_days": round(avg_completion_days, 2),
                "total_revenue": float(total_revenue),
                "period_months": months,
            }

        except Exception as e:
            logger.error(f"Error getting dentist treatment stats: {e}")
            return {}

    async def export_treatments(
        self, db: AsyncSession, format: str, filters: Dict[str, Any], exported_by: UUID
    ) -> Dict[str, Any]:
        """Export treatments to specified format"""
        try:
            # Build query based on filters
            query = select(Treatment).options(
                selectinload(Treatment.patient),
                selectinload(Treatment.dentist),
                selectinload(Treatment.treatment_items),
            )

            conditions = []
            if filters.get("start_date"):
                start_date = datetime.fromisoformat(
                    filters["start_date"].replace("Z", "+00:00")
                )
                conditions.append(Treatment.created_at >= start_date)
            if filters.get("end_date"):
                end_date = datetime.fromisoformat(
                    filters["end_date"].replace("Z", "+00:00")
                )
                conditions.append(Treatment.created_at <= end_date)
            if filters.get("status"):
                conditions.append(Treatment.status == filters["status"])
            if filters.get("priority"):
                conditions.append(Treatment.priority == filters["priority"])

            if conditions:
                query = query.where(and_(*conditions))

            result = await db.execute(query)
            treatments = result.scalars().all()

            # Prepare export data
            export_data = []
            for treatment in treatments:
                treatment_data = {
                    "id": str(treatment.id),
                    "name": treatment.name,
                    "patient_name": f"{treatment.patient.first_name} {treatment.patient.last_name}",
                    "dentist_name": f"{treatment.dentist.first_name} {treatment.dentist.last_name}",
                    "status": treatment.status,
                    "priority": treatment.priority,
                    "estimated_cost": float(treatment.estimated_cost or 0),
                    "actual_cost": float(treatment.actual_cost or 0),
                    "started_at": (
                        treatment.started_at.isoformat()
                        if treatment.started_at
                        else None
                    ),
                    "completed_at": (
                        treatment.completed_at.isoformat()
                        if treatment.completed_at
                        else None
                    ),
                    "created_at": treatment.created_at.isoformat(),
                    "treatment_items_count": len(treatment.treatment_items),
                }
                export_data.append(treatment_data)

            # Generate export file based on format
            if format == "json":
                export_content = json.dumps(export_data, indent=2, default=str)
            elif format == "csv":
                import csv
                import io

                output = io.StringIO()
                if export_data:
                    writer = csv.DictWriter(output, fieldnames=export_data[0].keys())
                    writer.writeheader()
                    writer.writerows(export_data)
                export_content = output.getvalue()
            else:  # excel
                # For Excel, we'd typically save to a file and return the path
                # This is a simplified version
                export_content = "EXCEL_EXPORT_CONTENT"

            return {
                "format": format,
                "record_count": len(export_data),
                "exported_by": str(exported_by),
                "exported_at": datetime.utcnow().isoformat(),
                "content": export_content,
            }

        except Exception as e:
            logger.error(f"Error exporting treatments: {e}")
            raise

    async def get_dashboard_overview(self, db: AsyncSession) -> Dict[str, Any]:
        """Get treatment data for dashboard overview"""
        try:
            # Recent treatments (last 7 days)
            recent_start = datetime.utcnow() - timedelta(days=7)
            recent_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.created_at >= recent_start
                )
            )
            recent_treatments = recent_result.scalar()

            # Treatments in progress
            in_progress_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.status == TreatmentStatus.IN_PROGRESS
                )
            )
            in_progress_treatments = in_progress_result.scalar()

            # Upcoming treatments (starting in next 7 days)
            upcoming_start = datetime.utcnow()
            upcoming_end = datetime.utcnow() + timedelta(days=7)
            upcoming_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.started_at.between(upcoming_start, upcoming_end)
                )
            )
            upcoming_treatments = upcoming_result.scalar()

            # Recent revenue
            revenue_result = await db.execute(
                select(func.sum(Treatment.estimated_cost)).where(
                    Treatment.created_at >= recent_start,
                    Treatment.estimated_cost.isnot(None),
                )
            )
            recent_revenue = revenue_result.scalar() or 0

            return {
                "recent_treatments": recent_treatments,
                "in_progress_treatments": in_progress_treatments,
                "upcoming_treatments": upcoming_treatments,
                "recent_revenue": float(recent_revenue),
                "last_updated": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error getting dashboard overview: {e}")
            return {}

    async def get_upcoming_treatments(
        self, db: AsyncSession, days: int = 7
    ) -> List[Treatment]:
        """Get treatments scheduled to start soon"""
        try:
            start_date = datetime.utcnow()
            end_date = datetime.utcnow() + timedelta(days=days)

            result = await db.execute(
                select(Treatment)
                .options(
                    selectinload(Treatment.patient), selectinload(Treatment.dentist)
                )
                .where(
                    Treatment.started_at.between(start_date, end_date),
                    Treatment.status == TreatmentStatus.PLANNED,
                )
                .order_by(Treatment.started_at.asc())
                .limit(20)
            )

            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error getting upcoming treatments: {e}")
            return []

    async def create_treatment_from_template(
        self,
        db: AsyncSession,
        template_id: UUID,
        patient_id: UUID,
        dentist_id: UUID,
        customizations: Optional[Dict[str, Any]] = None,
    ) -> Optional[Treatment]:
        """Create treatment from template"""
        try:
            # This would integrate with a template service
            # For now, return a simple implementation
            from services.treatment_template_service import treatment_template_service

            template = await treatment_template_service.get_template(db, template_id)
            if not template:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Treatment template not found",
                )

            # Create treatment from template
            treatment_data = {
                "patient_id": patient_id,
                "dentist_id": dentist_id,
                "name": (
                    customizations.get("name", template.name)
                    if customizations
                    else template.name
                ),
                "description": (
                    customizations.get("description", template.description)
                    if customizations
                    else template.description
                ),
                "priority": "routine",
                "estimated_cost": template.estimated_cost,
                "total_stages": 1,
            }

            treatment = Treatment(**treatment_data)
            db.add(treatment)
            await db.flush()

            # Add treatment items from template
            for item_template in template.treatment_items or []:
                treatment_item = TreatmentItem(
                    treatment_id=treatment.id,
                    service_id=item_template.get("service_id"),
                    quantity=item_template.get("quantity", 1),
                    unit_price=item_template.get("unit_price", 0),
                    tooth_number=item_template.get("tooth_number"),
                    surface=item_template.get("surface"),
                    notes=item_template.get("notes"),
                )
                db.add(treatment_item)

            await db.commit()
            await db.refresh(treatment)

            return treatment

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating treatment from template: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create treatment from template",
            )


treatment_service = TreatmentService()
