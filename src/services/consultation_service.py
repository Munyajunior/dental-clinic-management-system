# src/services/consultation_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status
from models.consultation import Consultation
from models.patient import Patient
from models.user import User
from schemas.consultation_schemas import ConsultationCreate, ConsultationUpdate
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("CONSULTATION_SERVICE")


class ConsultationService(BaseService):
    def __init__(self):
        super().__init__(Consultation)

    async def create_consultation(
        self, db: AsyncSession, consultation_data: ConsultationCreate
    ) -> Consultation:
        """Create new consultation with validation"""
        # Verify patient exists and is active
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == consultation_data.patient_id, Patient.is_active == True
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
            select(User).where(
                User.id == consultation_data.dentist_id, User.is_active == True
            )
        )
        dentist = dentist_result.scalar_one_or_none()
        if not dentist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dentist not found or inactive",
            )

        # If appointment_id is provided, verify it exists
        if consultation_data.appointment_id:
            from models.appointment import Appointment

            appointment_result = await db.execute(
                select(Appointment).where(
                    Appointment.id == consultation_data.appointment_id
                )
            )
            appointment = appointment_result.scalar_one_or_none()
            if not appointment:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Appointment not found",
                )

        consultation = Consultation(**consultation_data.dict())
        db.add(consultation)
        await db.commit()
        await db.refresh(consultation)

        logger.info(
            f"Created new consultation: {consultation.id} for patient {patient.id}"
        )
        return consultation

    async def get_patient_consultations(
        self, db: AsyncSession, patient_id: UUID, skip: int = 0, limit: int = 50
    ) -> List[Consultation]:
        """Get all consultations for a specific patient"""
        try:
            result = await db.execute(
                select(Consultation)
                .where(Consultation.patient_id == patient_id)
                .order_by(Consultation.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting patient consultations: {e}")
            return []

    async def get_dentist_consultations(
        self, db: AsyncSession, dentist_id: UUID, skip: int = 0, limit: int = 50
    ) -> List[Consultation]:
        """Get all consultations for a specific dentist"""
        try:
            result = await db.execute(
                select(Consultation)
                .where(Consultation.dentist_id == dentist_id)
                .order_by(Consultation.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting dentist consultations: {e}")
            return []

    async def add_treatment_plan(
        self,
        db: AsyncSession,
        consultation_id: UUID,
        treatment_plan: List[Dict[str, Any]],
    ) -> Optional[Consultation]:
        """Add or update treatment plan for consultation"""
        consultation = await self.get(db, consultation_id)
        if not consultation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found"
            )

        consultation.treatment_plan = treatment_plan
        await db.commit()
        await db.refresh(consultation)

        logger.info(f"Updated treatment plan for consultation: {consultation_id}")
        return consultation

    async def add_diagnosis(
        self, db: AsyncSession, consultation_id: UUID, diagnosis: List[str]
    ) -> Optional[Consultation]:
        """Add or update diagnosis for consultation"""
        consultation = await self.get(db, consultation_id)
        if not consultation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found"
            )

        consultation.diagnosis = diagnosis
        await db.commit()
        await db.refresh(consultation)

        logger.info(f"Updated diagnosis for consultation: {consultation_id}")
        return consultation

    async def get_consultation_stats(
        self, db: AsyncSession, dentist_id: Optional[UUID] = None, days: int = 30
    ) -> Dict[str, Any]:
        """Get consultation statistics"""
        try:
            from sqlalchemy import func
            from datetime import datetime, timedelta

            start_date = datetime.utcnow() - timedelta(days=days)

            query = select(func.count(Consultation.id)).where(
                Consultation.created_at >= start_date
            )

            if dentist_id:
                query = query.where(Consultation.dentist_id == dentist_id)

            result = await db.execute(query)
            total_consultations = result.scalar()

            # Get consultations by type (if you have types)
            # This is a simplified version - you can expand based on your needs

            return {
                "total_consultations": total_consultations,
                "period_days": days,
                "average_per_day": total_consultations / days if days > 0 else 0,
            }
        except Exception as e:
            logger.error(f"Error getting consultation stats: {e}")
            return {}


consultation_service = ConsultationService()
