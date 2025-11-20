# src/services/consultation_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status
from models.consultation import Consultation
from models.patient import Patient
from models.patient_sharing import PatientSharing
from models.user import User, StaffRole
from schemas.consultation_schemas import ConsultationCreate, ConsultationUpdate
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("CONSULTATION_SERVICE")


class ConsultationService(BaseService):
    def __init__(self):
        super().__init__(Consultation)

    async def create_consultation(
        self,
        db: AsyncSession,
        consultation_data: ConsultationCreate,
        current_user: User,
    ) -> Consultation:
        """Create new consultation with validation for patient assignment"""
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

        # Check if current user is assigned to this patient or has permission to consult
        can_consult = await self._can_user_consult_patient(
            db, current_user, patient, consultation_data.dentist_id
        )
        if not can_consult:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to consult this patient",
            )

        # Verify dentist exists and is active (if different from current user)
        if consultation_data.dentist_id != current_user.id:
            dentist_result = await db.execute(
                select(User).where(
                    User.id == consultation_data.dentist_id,
                    User.is_active == True,
                    User.role.in_(
                        [
                            StaffRole.DENTIST,
                            StaffRole.DENTAL_THERAPIST,
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
            f"Created new consultation: {consultation.id} for patient {patient.id} by user {current_user.id}"
        )
        return consultation

    async def _can_user_consult_patient(
        self, db: AsyncSession, user: User, patient: Patient, requested_dentist_id: UUID
    ) -> bool:
        """Check if user can consult with this patient"""
        # Admin users can consult any patient
        if user.role == StaffRole.ADMIN:
            return True

        # Check if user is the assigned dental professional
        if patient.assigned_dentist_id == user.id:
            return True

        # Check if user is the requested dentist (for shared consultations)
        if requested_dentist_id == user.id:
            # Verify that the patient is shared with this user
            # This would require a patient_sharing table in a real implementation
            is_shared = await self._is_patient_shared_with_user(db, patient.id, user.id)
            return is_shared

        return False

    async def _is_patient_shared_with_user(
        self, db: AsyncSession, patient_id: UUID, user_id: UUID
    ) -> bool:
        """Check if patient is shared with this user"""
        # In a real implementation, this would query a patient_sharing table
        # For now, return False - you'll need to implement patient sharing logic
        return False

    async def get_patient_consultations(
        self,
        db: AsyncSession,
        patient_id: UUID,
        current_user: User,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Consultation]:
        """Get all consultations for a specific patient that the user can access"""
        try:
            # First verify the user can access this patient
            patient_result = await db.execute(
                select(Patient).where(Patient.id == patient_id)
            )
            patient = patient_result.scalar_one_or_none()

            if not patient:
                return []

            can_access = await self._can_user_consult_patient(
                db, current_user, patient, current_user.id
            )
            if not can_access:
                return []

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
        self,
        db: AsyncSession,
        dentist_id: UUID,
        current_user: User,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Consultation]:
        """Get all consultations for a specific dentist that the user can access"""
        try:
            # Users can only see their own consultations unless they're admin
            if current_user.role != StaffRole.ADMIN and current_user.id != dentist_id:
                return []

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
        current_user: User,
    ) -> Optional[Consultation]:
        """Add or update treatment plan for consultation"""
        consultation = await self.get(db, consultation_id)
        if not consultation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found"
            )

        # Verify user can modify this consultation
        can_modify = await self._can_user_modify_consultation(
            db, current_user, consultation
        )
        if not can_modify:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to modify this consultation",
            )

        consultation.treatment_plan = treatment_plan
        await db.commit()
        await db.refresh(consultation)

        logger.info(f"Updated treatment plan for consultation: {consultation_id}")
        return consultation

    async def _can_user_modify_consultation(
        self, db: AsyncSession, user: User, consultation: Consultation
    ) -> bool:
        """Check if user can modify this consultation"""
        # Admin users can modify any consultation
        if user.role == StaffRole.ADMIN:
            return True

        # The dentist who created the consultation can modify it
        if consultation.dentist_id == user.id:
            return True

        # Check if user is currently assigned to the patient
        patient_result = await db.execute(
            select(Patient).where(Patient.id == consultation.patient_id)
        )
        patient = patient_result.scalar_one_or_none()

        if patient and patient.assigned_dentist_id == user.id:
            return True

        return False

    async def get_consultation_stats(
        self,
        db: AsyncSession,
        dentist_id: Optional[UUID] = None,
        current_user: User = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Get consultation statistics for authorized users"""
        try:
            from sqlalchemy import func
            from datetime import datetime, timedelta

            start_date = datetime.utcnow() - timedelta(days=days)

            # Base query
            query = select(func.count(Consultation.id)).where(
                Consultation.created_at >= start_date
            )

            # Apply filters based on user role
            if current_user.role != StaffRole.ADMIN:
                # Non-admin users can only see their own stats
                if dentist_id and dentist_id != current_user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You can only view your own statistics",
                    )
                query = query.where(Consultation.dentist_id == current_user.id)
            elif dentist_id:
                # Admin can filter by specific dentist
                query = query.where(Consultation.dentist_id == dentist_id)

            result = await db.execute(query)
            total_consultations = result.scalar()

            return {
                "total_consultations": total_consultations,
                "period_days": days,
                "average_per_day": total_consultations / days if days > 0 else 0,
            }
        except Exception as e:
            logger.error(f"Error getting consultation stats: {e}")
            return {}

    async def _can_user_consult_patient(
        self, db: AsyncSession, user: User, patient: Patient, requested_dentist_id: UUID
    ) -> bool:
        """Check if user can consult with this patient"""
        # Admin users can consult any patient
        if user.role == StaffRole.ADMIN:
            return True

        # Check if user is the assigned dental professional
        if patient.assigned_dentist_id == user.id:
            return True

        # Check if user is the requested dentist (for shared consultations)
        if requested_dentist_id == user.id:
            # Verify that the patient is shared with this user
            is_shared = await self._is_patient_shared_with_user(db, patient.id, user.id)
            return is_shared

        return False

    async def _is_patient_shared_with_user(
        self, db: AsyncSession, patient_id: UUID, user_id: UUID
    ) -> bool:
        """Check if patient is shared with this user"""
        result = await db.execute(
            select(PatientSharing).where(
                PatientSharing.patient_id == patient_id,
                PatientSharing.shared_with_dentist_id == user_id,
                PatientSharing.is_active == True,
                PatientSharing.permission_level.in_(["consult", "modify"]),
                or_(
                    PatientSharing.expires_at.is_(None),
                    PatientSharing.expires_at > datetime.now(timezone.utc),
                ),
            )
        )

        return result.scalar_one_or_none() is not None


consultation_service = ConsultationService()
