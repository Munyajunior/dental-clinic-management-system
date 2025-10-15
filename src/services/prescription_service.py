# src/services/prescription_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status
from models.prescription import Prescription
from models.patient import Patient
from models.user import User
from models.treatment import Treatment
from schemas.prescription_schemas import PrescriptionCreate, PrescriptionUpdate
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("PRESCRIPTION_SERVICE")


class PrescriptionService(BaseService):
    def __init__(self):
        super().__init__(Prescription)

    async def create_prescription(
        self, db: AsyncSession, prescription_data: PrescriptionCreate
    ) -> Prescription:
        """Create new prescription with validation"""
        # Verify patient exists and is active
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == prescription_data.patient_id, Patient.is_active
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
            select(User).where(User.id == prescription_data.dentist_id, User.is_active)
        )
        dentist = dentist_result.scalar_one_or_none()
        if not dentist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dentist not found or inactive",
            )

        # If treatment_id is provided, verify it exists
        if prescription_data.treatment_id:
            treatment_result = await db.execute(
                select(Treatment).where(Treatment.id == prescription_data.treatment_id)
            )
            treatment = treatment_result.scalar_one_or_none()
            if not treatment:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Treatment not found",
                )

        # Set expiration date (default: 30 days from now)
        expires_at = datetime.utcnow() + timedelta(days=30)

        prescription = Prescription(**prescription_data.dict(), expires_at=expires_at)

        db.add(prescription)
        await db.commit()
        await db.refresh(prescription)

        logger.info(
            f"Created new prescription: {prescription.id} for patient {patient.id}"
        )
        return prescription

    async def mark_dispensed(
        self, db: AsyncSession, prescription_id: UUID
    ) -> Optional[Prescription]:
        """Mark prescription as dispensed"""
        prescription = await self.get(db, prescription_id)
        if not prescription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found"
            )

        if prescription.is_dispensed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prescription is already dispensed",
            )

        prescription.is_dispensed = True
        prescription.dispensed_at = datetime.utcnow()

        await db.commit()
        await db.refresh(prescription)

        logger.info(f"Marked prescription as dispensed: {prescription_id}")
        return prescription

    async def get_patient_prescriptions(
        self,
        db: AsyncSession,
        patient_id: UUID,
        include_dispensed: bool = True,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Prescription]:
        """Get all prescriptions for a specific patient"""
        try:
            query = select(Prescription).where(Prescription.patient_id == patient_id)

            if not include_dispensed:
                query = query.where(Prescription.is_dispensed == False)

            query = (
                query.order_by(Prescription.created_at.desc()).offset(skip).limit(limit)
            )

            result = await db.execute(query)
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting patient prescriptions: {e}")
            return []

    async def get_dentist_prescriptions(
        self, db: AsyncSession, dentist_id: UUID, skip: int = 0, limit: int = 50
    ) -> List[Prescription]:
        """Get all prescriptions written by a specific dentist"""
        try:
            result = await db.execute(
                select(Prescription)
                .where(Prescription.dentist_id == dentist_id)
                .order_by(Prescription.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting dentist prescriptions: {e}")
            return []

    async def get_active_prescriptions(
        self, db: AsyncSession, patient_id: UUID
    ) -> List[Prescription]:
        """Get active (not expired and not fully dispensed) prescriptions for a patient"""
        try:
            result = await db.execute(
                select(Prescription)
                .where(
                    Prescription.patient_id == patient_id,
                    Prescription.expires_at > datetime.utcnow(),
                    Prescription.is_dispensed == False,
                )
                .order_by(Prescription.expires_at)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting active prescriptions: {e}")
            return []

    async def check_prescription_expiry(self, db: AsyncSession) -> Dict[str, Any]:
        """Check for expired prescriptions"""
        try:
            # Get expired prescriptions
            expired_result = await db.execute(
                select(Prescription).where(
                    Prescription.expires_at <= datetime.utcnow(),
                    Prescription.is_dispensed == False,
                )
            )
            expired_prescriptions = expired_result.scalars().all()

            # Get prescriptions expiring soon (within 7 days)
            soon_threshold = datetime.utcnow() + timedelta(days=7)
            expiring_soon_result = await db.execute(
                select(Prescription).where(
                    Prescription.expires_at <= soon_threshold,
                    Prescription.expires_at > datetime.utcnow(),
                    Prescription.is_dispensed == False,
                )
            )
            expiring_soon_prescriptions = expiring_soon_result.scalars().all()

            return {
                "expired_count": len(expired_prescriptions),
                "expiring_soon_count": len(expiring_soon_prescriptions),
                "expired_prescriptions": [str(p.id) for p in expired_prescriptions],
                "expiring_soon_prescriptions": [
                    str(p.id) for p in expiring_soon_prescriptions
                ],
            }
        except Exception as e:
            logger.error(f"Error checking prescription expiry: {e}")
            return {}


prescription_service = PrescriptionService()
