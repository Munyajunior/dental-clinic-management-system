# src/services/treatment_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status
from models.treatment import Treatment, TreatmentStatus
from models.treatment_item import TreatmentItem
from models.patient import Patient
from models.user import User
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

    async def create_treatment(
        self, db: AsyncSession, treatment_data: TreatmentCreate
    ) -> Treatment:
        """Create new treatment with validation"""
        # Verify patient exists and is active
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == treatment_data.patient_id, Patient.is_active
            )
        )
        patient = patient_result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient not found or inactive",
            )

        # Verify dentist exists and is active
        dentist_result = await db.execute(
            select(User).where(User.id == treatment_data.dentist_id, User.is_active)
        )
        dentist = dentist_result.scalar_one_or_none()
        if not dentist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dentist not found or inactive",
            )

        # If consultation_id is provided, verify it exists
        if treatment_data.consultation_id:
            from models.consultation import Consultation

            consultation_result = await db.execute(
                select(Consultation).where(
                    Consultation.id == treatment_data.consultation_id
                )
            )
            consultation = consultation_result.scalar_one_or_none()
            if not consultation:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Consultation not found",
                )

        treatment = Treatment(**treatment_data.dict())
        db.add(treatment)
        await db.commit()
        await db.refresh(treatment)

        logger.info(f"Created new treatment: {treatment.id} for patient {patient.id}")
        return treatment

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


treatment_service = TreatmentService()
