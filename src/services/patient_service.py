# src/services/patient_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status
from models.patient import Patient, PatientStatus
from schemas.patient_schemas import PatientCreate, PatientUpdate, PatientSearch
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("PATIENT_SERVICE")


class PatientService(BaseService):
    def __init__(self):
        super().__init__(Patient)

    async def create_patient(
        self, db: AsyncSession, patient_data: PatientCreate, created_by: UUID
    ) -> Patient:
        """Create new patient"""
        try:
            logger.debug(f"Creating patient with data: {patient_data}")
            # Check if patient with email already exists
            if patient_data.email:
                result = await db.execute(
                    select(Patient).where(
                        Patient.email == patient_data.email,
                        Patient.tenant_id == patient_data.tenant_id,
                    )
                )
                existing_patient = result.scalar_one_or_none()
                if existing_patient:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Patient with this email already exists",
                    )

            patient_dict = patient_data.model_dump()
            patient_dict["created_by"] = created_by
            # DEBUG: Check what we're creating
            logger.debug(f"Patient dict before creation: {patient_dict}")

            patient = Patient(**patient_dict)
            # DEBUG: Check the patient object before adding to session
            logger.debug(f"Patient object created: {patient}")
            logger.debug(f"Patient object type: {type(patient)}")
            logger.debug(f"Patient ID: {getattr(patient, 'id', 'NO ID')}")
            logger.debug(
                f"Patient tenant_id: {getattr(patient, 'tenant_id', 'NO TENANT ID')}"
            )
            db.add(patient)

            # DEBUG: Check session state before flush
            logger.debug("About to flush session...")
            await db.flush()

            # DEBUG: Check patient after flush
            logger.debug(f"Patient after flush - ID: {patient.id}")
            logger.debug(f"Patient after flush - full object: {patient}")

            await db.commit()
            await db.refresh(patient)

            logger.info(
                f"Created new patient: {patient.first_name} {patient.last_name}"
            )
            return patient
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to create patient: {e}", exc_info=True)

            # Additional debugging for tuple error
            if "'tuple' object has no attribute 'id'" in str(e):
                logger.error("TUPLE ERROR IN PATIENT CREATION!")
                # Check if patient is a tuple
                if "patient" in locals() and isinstance(patient, tuple):
                    logger.error(f"Patient became a tuple: {patient}")

            raise

    async def search_patients(
        self,
        db: AsyncSession,
        search_params: PatientSearch,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Patient]:
        """Search patients with various filters"""
        try:
            query = select(Patient).where(
                Patient.status == PatientStatus.ACTIVE, Patient.tenant_id == tenant_id
            )

            # Text search
            if search_params.query:
                search_term = f"%{search_params.query}%"
                query = query.where(
                    or_(
                        Patient.first_name.ilike(search_term),
                        Patient.last_name.ilike(search_term),
                        Patient.email.ilike(search_term),
                        Patient.contact_number.ilike(search_term),
                    )
                )

            # Status filter
            if search_params.status:
                query = query.where(Patient.status == search_params.status)

            # Gender filter
            if search_params.gender:
                query = query.where(Patient.gender == search_params.gender)

            # Age filters
            if search_params.min_age or search_params.max_age:
                today = date.today()
                if search_params.max_age:
                    min_birth_date = today.replace(
                        year=today.year - search_params.max_age - 1
                    )
                    query = query.where(Patient.date_of_birth >= min_birth_date)
                if search_params.min_age:
                    max_birth_date = today.replace(
                        year=today.year - search_params.min_age
                    )
                    query = query.where(Patient.date_of_birth <= max_birth_date)

            query = (
                query.offset(skip)
                .limit(limit)
                .order_by(Patient.last_name, Patient.first_name)
            )
            result = await db.execute(query)
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error searching patients: {e}")
            return []

    async def update_last_visit(self, db: AsyncSession, patient_id: UUID) -> None:
        """Update patient's last visit timestamp"""
        patient = await self.get(db, patient_id)
        if patient:
            patient.last_visit_at = datetime.utcnow()
            await db.commit()
            logger.debug(f"Updated last visit for patient: {patient_id}")

    async def get_patient_stats(
        self, db: AsyncSession, tenant_id: UUID
    ) -> Dict[str, Any]:
        """Get patient statistics for dashboard"""
        try:
            # Total patients
            total_result = await db.execute(
                select(func.count()).where(Patient.tenant_id == tenant_id)
            )
            total_patients = total_result.scalar()

            # Active patients
            active_result = await db.execute(
                select(func.count()).where(
                    Patient.tenant_id == tenant_id,
                    Patient.status == PatientStatus.ACTIVE,
                )
            )
            active_patients = active_result.scalar()

            # New patients this month
            first_day = date.today().replace(day=1)
            new_this_month_result = await db.execute(
                select(func.count()).where(
                    Patient.tenant_id == tenant_id, Patient.created_at >= first_day
                )
            )
            new_this_month = new_this_month_result.scalar()

            return {
                "total_patients": total_patients,
                "active_patients": active_patients,
                "new_patients_this_month": new_this_month,
            }
        except Exception as e:
            logger.error(f"Error getting patient stats: {e}")
            return {}


patient_service = PatientService()
