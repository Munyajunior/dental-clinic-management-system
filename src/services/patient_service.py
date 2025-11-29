# src/services/patient_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import date, datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, update
from fastapi import HTTPException, status
from models.patient import Patient, PatientStatus, AssignmentReason
from models.patient_sharing import PatientSharing
from models.user import User, StaffRole
from schemas.patient_schemas import (
    PatientCreate,
    PatientUpdate,
    PatientSearch,
    DentistWorkload,
)
from services.auth_service import auth_service
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
            hashed_password = auth_service.get_password_hash(patient_data.password)
            patient_dict = patient_data.model_dump(exclude={"password"})
            patient_dict["created_by"] = created_by
            patient_dict["hashed_password"] = hashed_password

            # Handle dentist assignment
            if patient_data.assigned_dentist_id:
                await self._validate_dentist_assignment(
                    db, patient_data.assigned_dentist_id, patient_data.tenant_id
                )
                patient_dict["dentist_assignment_date"] = datetime.now(timezone.utc)

            # Create patient
            patient = Patient(**patient_dict)
            db.add(patient)
            await db.flush()

            await db.commit()
            await db.refresh(patient)

            logger.info(
                f"Created new patient: {patient.first_name} {patient.last_name}"
            )
            return patient

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to create patient: {e}", exc_info=True)
            raise

    async def assign_dentist_to_patient(
        self,
        db: AsyncSession,
        patient_id: UUID,
        dentist_id: UUID,
        assignment_reason: AssignmentReason,
        assigned_by: UUID,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assign a specific dentist to a patient and update counts"""
        # Get patient and current assigned dentist
        patient = await self.get(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        previous_dentist_id = patient.assigned_dentist_id

        # Validate new dentist
        new_dentist = await self._validate_dentist_assignment(
            db, dentist_id, patient.tenant_id
        )

        # Update patient assignment
        patient.assigned_dentist_id = dentist_id
        patient.assignment_reason = assignment_reason
        patient.dentist_assignment_date = datetime.now(timezone.utc)
        patient.updated_by = assigned_by

        # Update dentist patient counts
        if previous_dentist_id:
            await self._update_dentist_patient_count(db, previous_dentist_id)
        await self._update_dentist_patient_count(db, dentist_id)

        await db.commit()
        await db.refresh(patient)

        logger.info(f"Assigned dentist {dentist_id} to patient {patient_id}")

        return {
            "patient_id": patient_id,
            "dentist_id": dentist_id,
            "assignment_reason": assignment_reason.value,
            "assignment_date": patient.dentist_assignment_date,
            "previous_dentist_id": previous_dentist_id,
        }

    async def reassign_patient_to_dentist(
        self,
        db: AsyncSession,
        patient_id: UUID,
        new_dentist_id: UUID,
        assignment_reason: AssignmentReason,
        reassigned_by: UUID,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reassign patient to a different dentist and update counts"""
        # Get patient
        patient = await self.get(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        previous_dentist_id = patient.assigned_dentist_id

        # Validate new dentist
        new_dentist = await self._validate_dentist_assignment(
            db, new_dentist_id, patient.tenant_id
        )

        # Update patient assignment
        patient.assigned_dentist_id = new_dentist_id
        patient.assignment_reason = assignment_reason
        patient.dentist_assignment_date = datetime.now(timezone.utc)
        patient.updated_by = reassigned_by

        # Update dentist patient counts
        if previous_dentist_id:
            await self._update_dentist_patient_count(db, previous_dentist_id)
        await self._update_dentist_patient_count(db, new_dentist_id)

        await db.commit()
        await db.refresh(patient)

        logger.info(
            f"Reassigned patient {patient_id} from {previous_dentist_id} to {new_dentist_id}"
        )

        return {
            "patient_id": patient_id,
            "dentist_id": new_dentist_id,
            "assignment_reason": assignment_reason.value,
            "assignment_date": patient.dentist_assignment_date,
            "previous_dentist_id": previous_dentist_id,
        }

    async def remove_dentist_assignment(
        self, db: AsyncSession, patient_id: UUID, removed_by: UUID
    ) -> None:
        """Remove dentist assignment from patient and update count"""
        # Get patient
        patient = await self.get(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        previous_dentist_id = patient.assigned_dentist_id

        # Remove assignment
        patient.assigned_dentist_id = None
        patient.assignment_reason = None
        patient.dentist_assignment_date = None
        patient.updated_by = removed_by

        # Update previous dentist's patient count
        if previous_dentist_id:
            await self._update_dentist_patient_count(db, previous_dentist_id)

        await db.commit()

        logger.info(f"Removed dentist assignment from patient {patient_id}")

    async def auto_assign_dentist(
        self,
        db: AsyncSession,
        patient_id: UUID,
        assignment_reason: str,
        assigned_by: UUID,
    ) -> Dict[str, Any]:
        """Auto-assign the least busy available dentist to a patient"""
        # Get patient
        patient = await self.get(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        # Find the least busy available dentist
        available_dentists = await self._get_available_dentists_with_workload(
            db, patient.tenant_id
        )

        if not available_dentists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No available dentists found",
            )

        # Find dentist with minimum utilization
        available_dentists.sort(key=lambda x: x["utilization"])
        best_dentist = available_dentists[0]

        # Assign the dentist
        patient.assigned_dentist_id = best_dentist["id"]
        patient.assignment_reason = AssignmentReason(assignment_reason)
        patient.dentist_assignment_date = datetime.now(timezone.utc)
        patient.updated_by = assigned_by

        await db.commit()
        await db.refresh(patient)

        logger.info(
            f"Auto-assigned dentist {best_dentist['id']} to patient {patient_id}"
        )

        return {
            "patient_id": patient_id,
            "dentist_id": best_dentist["id"],
            "assignment_reason": assignment_reason,
            "assignment_date": patient.dentist_assignment_date,
        }

    async def _get_available_dentists_with_workload(
        self, db: AsyncSession, tenant_id: UUID
    ) -> List[Dict[str, Any]]:
        """Get available dentists with their current workload"""
        try:
            # Get all active dentists
            result = await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.role == StaffRole.DENTIST,
                    User.is_active == True,
                    User.is_available == True,
                )
            )
            dentists = result.scalars().all()

            available_dentists = []
            for dentist in dentists:
                # Count assigned patients
                patient_count_result = await db.execute(
                    select(func.count()).where(
                        Patient.assigned_dentist_id == dentist.id,
                        Patient.status == PatientStatus.ACTIVE,
                    )
                )
                current_patient_count = patient_count_result.scalar()

                max_patients = dentist.max_patients or 50
                utilization = (
                    (current_patient_count / max_patients) * 100
                    if max_patients > 0
                    else 0
                )

                # Only include dentists with capacity
                if current_patient_count < max_patients:
                    available_dentists.append(
                        {
                            "id": dentist.id,
                            "name": f"{dentist.first_name} {dentist.last_name}",
                            "specialization": dentist.specialization,
                            "current_patient_count": current_patient_count,
                            "max_patients": max_patients,
                            "utilization": utilization,
                        }
                    )

            return available_dentists

        except Exception as e:
            logger.error(f"Error getting available dentists: {e}")
            return []

    async def _validate_dentist_assignment(
        self, db: AsyncSession, dentist_id: UUID, tenant_id: UUID
    ) -> User:
        """Validate that a dentist can be assigned to a patient and return dentist object"""
        # Check if dentist exists and is active
        result = await db.execute(
            select(User).where(
                User.id == dentist_id,
                User.tenant_id == tenant_id,
                User.role.in_(
                    [StaffRole.DENTIST, StaffRole.THERAPIST, StaffRole.HYGIENIST]
                ),
                User.is_active == True,
            )
        )
        dentist = result.scalar_one_or_none()

        if not dentist:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dental professional not found or not available",
            )

        # Check if dental professional is available for new patients
        if not dentist.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dental professional is not currently available for new patients",
            )

        # Check workload using real-time count
        current_patient_count = await self._get_current_patient_count(db, dentist_id)
        max_patients = dentist.max_patients or 50

        if current_patient_count >= max_patients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dental professional has reached maximum patient capacity ({max_patients})",
            )

        return dentist

    async def _get_current_patient_count(
        self, db: AsyncSession, dentist_id: UUID
    ) -> int:
        """Get real-time count of active patients assigned to a dental professional"""
        result = await db.execute(
            select(func.count()).where(
                Patient.assigned_dentist_id == dentist_id,
                Patient.status == PatientStatus.ACTIVE,
            )
        )
        return result.scalar() or 0

    async def _update_dentist_patient_count(
        self, db: AsyncSession, dentist_id: UUID
    ) -> None:
        """Update the dentist's current patient count in their settings"""
        try:
            # Get current real-time count
            current_count = await self._get_current_patient_count(db, dentist_id)

            # Update dentist's settings with current count
            result = await db.execute(select(User).where(User.id == dentist_id))
            dentist = result.scalar_one_or_none()

            if dentist:
                # Update settings with current patient count
                settings = dentist.settings or {}
                settings["current_patient_count"] = current_count
                settings["patient_count_updated_at"] = datetime.now(
                    timezone.utc
                ).isoformat()

                # Update workload percentage
                max_patients = dentist.max_patients or 50
                workload_percentage = (
                    (current_count / max_patients) * 100 if max_patients > 0 else 0
                )
                settings["workload_percentage"] = workload_percentage

                # Update is_accepting_new_patients based on workload
                if workload_percentage >= 100:
                    dentist.is_accepting_new_patients = False
                elif workload_percentage < 85:  # Allow buffer for new patients
                    dentist.is_accepting_new_patients = True

                dentist.settings = settings
                await db.flush()

                logger.debug(
                    f"Updated patient count for dentist {dentist_id}: {current_count}"
                )

        except Exception as e:
            logger.error(f"Error updating dentist patient count for {dentist_id}: {e}")

    async def update_dentist_patient_counts(
        self, db: AsyncSession, tenant_id: UUID
    ) -> None:
        """Update patient counts for all dental professionals in a tenant"""
        try:
            # Get all dental professionals
            result = await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.role.in_(
                        [StaffRole.DENTIST, StaffRole.THERAPIST, StaffRole.HYGIENIST]
                    ),
                    User.is_active == True,
                )
            )
            dental_professionals = result.scalars().all()

            for professional in dental_professionals:
                await self._update_dentist_patient_count(db, professional.id)

            await db.commit()
            logger.info(
                f"Updated patient counts for {len(dental_professionals)} dental professionals"
            )

        except Exception as e:
            await db.rollback()
            logger.error(f"Error updating all dentist patient counts: {e}")

    async def get_dentist_workload(
        self, db: AsyncSession, dentist_id: UUID
    ) -> DentistWorkload:
        """Get workload information for a specific dentist using real-time data"""
        # Get dentist
        result = await db.execute(select(User).where(User.id == dentist_id))
        dentist = result.scalar_one_or_none()

        if not dentist or dentist.role not in [
            StaffRole.DENTIST,
            StaffRole.THERAPIST,
            StaffRole.HYGIENIST,
        ]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dental professional not found",
            )

        # Get real-time patient count
        current_patient_count = await self._get_current_patient_count(db, dentist_id)

        max_patients = dentist.max_patients or 50
        workload_percentage = (
            (current_patient_count / max_patients) * 100 if max_patients > 0 else 0
        )
        is_accepting_new_patients = (
            dentist.is_available
            and current_patient_count < max_patients
            and dentist.is_active
        )

        return DentistWorkload(
            dentist_id=dentist_id,
            dentist_name=f"{dentist.first_name} {dentist.last_name}",
            current_patient_count=current_patient_count,
            max_patients=max_patients,
            workload_percentage=workload_percentage,
            is_accepting_new_patients=is_accepting_new_patients,
            specialization=dentist.specialization,
        )

    async def get_all_dentists_workloads(
        self, db: AsyncSession, tenant_id: UUID
    ) -> List[DentistWorkload]:
        """Get workload information for all dental professionals using real-time data"""
        try:
            # Get all dental professionals
            result = await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.role.in_(
                        [StaffRole.DENTIST, StaffRole.THERAPIST, StaffRole.HYGIENIST]
                    ),
                )
            )
            dental_professionals = result.scalars().all()

            workloads = []
            for professional in dental_professionals:
                # Get real-time patient count
                current_patient_count = await self._get_current_patient_count(
                    db, professional.id
                )

                max_patients = professional.max_patients or 50
                workload_percentage = (
                    (current_patient_count / max_patients) * 100
                    if max_patients > 0
                    else 0
                )
                is_accepting_new_patients = (
                    professional.is_available
                    and current_patient_count < max_patients
                    and professional.is_active
                )

                workloads.append(
                    DentistWorkload(
                        dentist_id=professional.id,
                        dentist_name=f"{professional.first_name} {professional.last_name}",
                        current_patient_count=current_patient_count,
                        max_patients=max_patients,
                        workload_percentage=workload_percentage,
                        is_accepting_new_patients=is_accepting_new_patients,
                        specialization=professional.specialization,
                    )
                )

            return workloads

        except Exception as e:
            logger.error(f"Error getting all dental professionals workloads: {e}")
            return []

    async def get_patients_by_dentist(
        self, db: AsyncSession, dentist_id: UUID, skip: int = 0, limit: int = 50
    ) -> List[Patient]:
        """Get all patients assigned to a specific dentist"""
        try:
            result = await db.execute(
                select(Patient)
                .where(
                    Patient.assigned_dentist_id == dentist_id,
                    Patient.status == PatientStatus.ACTIVE,
                )
                .offset(skip)
                .limit(limit)
                .order_by(Patient.last_name, Patient.first_name)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting patients by dentist: {e}")
            return []

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
            patient.last_visit_at = datetime.now(timezone.utc)
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

    async def share_patient(
        self,
        db: AsyncSession,
        patient_id: UUID,
        shared_with_dentist_id: UUID,
        permission_level: str,
        shared_by_dentist_id: UUID,
        expires_at: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Share a patient with another dental professional"""
        # Get patient
        patient = await self.get(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        # Verify sharing dentist is assigned to patient
        if patient.assigned_dentist_id != shared_by_dentist_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the assigned dental professional can share this patient",
            )

        # Validate target dentist
        await self._validate_dentist_assignment(
            db, shared_with_dentist_id, patient.tenant_id
        )

        # Check if sharing already exists
        existing_sharing = await db.execute(
            select(PatientSharing).where(
                PatientSharing.patient_id == patient_id,
                PatientSharing.shared_with_dentist_id == shared_with_dentist_id,
                PatientSharing.is_active == True,
            )
        )
        if existing_sharing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Patient is already shared with this dental professional",
            )

        # Create sharing record
        sharing = PatientSharing(
            tenant_id=patient.tenant_id,
            patient_id=patient_id,
            shared_by_dentist_id=shared_by_dentist_id,
            shared_with_dentist_id=shared_with_dentist_id,
            permission_level=permission_level,
            expires_at=expires_at,
            notes=notes,
        )

        db.add(sharing)
        await db.commit()
        await db.refresh(sharing)

        logger.info(
            f"Shared patient {patient_id} with dentist {shared_with_dentist_id}"
        )

        return {
            "success": True,
            "sharing_id": sharing.id,
            "patient_id": patient_id,
            "shared_with_dentist_id": shared_with_dentist_id,
            "permission_level": permission_level,
        }

    async def revoke_patient_sharing(
        self,
        db: AsyncSession,
        sharing_id: UUID,
        revoked_by_dentist_id: UUID,
    ) -> Dict[str, Any]:
        """Revoke patient sharing"""

        sharing = await db.execute(
            select(PatientSharing).where(PatientSharing.id == sharing_id)
        )
        sharing = sharing.scalar_one_or_none()

        if not sharing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sharing record not found"
            )

        # Verify revoker has permission (either original sharer or admin)
        current_user_result = await db.execute(
            select(User).where(User.id == revoked_by_dentist_id)
        )
        current_user = current_user_result.scalar_one_or_none()

        if (
            current_user.role != "admin"
            and sharing.shared_by_dentist_id != revoked_by_dentist_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the original sharer or admin can revoke sharing",
            )

        sharing.is_active = False
        await db.commit()

        logger.info(f"Revoked patient sharing: {sharing_id}")

        return {"success": True, "message": "Patient sharing revoked successfully"}

    async def get_shared_patients(
        self,
        db: AsyncSession,
        dentist_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get patients shared with a dental professional"""

        result = await db.execute(
            select(PatientSharing, Patient)
            .join(Patient, PatientSharing.patient_id == Patient.id)
            .where(
                PatientSharing.shared_with_dentist_id == dentist_id,
                PatientSharing.is_active == True,
                Patient.status == PatientStatus.ACTIVE,
                or_(
                    PatientSharing.expires_at.is_(None),
                    PatientSharing.expires_at > datetime.now(timezone.utc),
                ),
            )
            .offset(skip)
            .limit(limit)
        )

        shared_patients = []
        for sharing, patient in result.all():
            shared_patients.append(
                {
                    "sharing_id": sharing.id,
                    "patient": patient,
                    "permission_level": sharing.permission_level,
                    "shared_by_dentist_id": sharing.shared_by_dentist_id,
                    "shared_at": sharing.created_at,
                    "expires_at": sharing.expires_at,
                }
            )

        return shared_patients

    async def transfer_patient(
        self,
        db: AsyncSession,
        patient_id: UUID,
        new_dentist_id: UUID,
        transfer_reason: str,
        transferred_by: UUID,
    ) -> Dict[str, Any]:
        """Transfer patient to another dental professional and update counts"""
        # Get patient
        patient = await self.get(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        # Verify transferrer has permission
        current_user_result = await db.execute(
            select(User).where(User.id == transferred_by)
        )
        current_user = current_user_result.scalar_one_or_none()

        if (
            current_user.role != "admin"
            and patient.assigned_dentist_id != transferred_by
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the assigned dental professional or admin can transfer this patient",
            )

        previous_dentist_id = patient.assigned_dentist_id

        # Validate new dentist
        new_dentist = await self._validate_dentist_assignment(
            db, new_dentist_id, patient.tenant_id
        )

        # Update patient assignment
        patient.assigned_dentist_id = new_dentist_id
        patient.assignment_reason = AssignmentReason.TRANSFER
        patient.dentist_assignment_date = datetime.now(timezone.utc)
        patient.updated_by = transferred_by

        # Deactivate any active sharing records for this patient
        from models.patient_sharing import PatientSharing

        await db.execute(
            update(PatientSharing)
            .where(
                PatientSharing.patient_id == patient_id,
                PatientSharing.is_active == True,
            )
            .values(is_active=False)
        )

        # Update dentist patient counts
        if previous_dentist_id:
            await self._update_dentist_patient_count(db, previous_dentist_id)
        await self._update_dentist_patient_count(db, new_dentist_id)

        await db.commit()
        await db.refresh(patient)

        logger.info(
            f"Transferred patient {patient_id} from {previous_dentist_id} to {new_dentist_id}"
        )

        return {
            "success": True,
            "patient_id": patient_id,
            "previous_dentist_id": previous_dentist_id,
            "new_dentist_id": new_dentist_id,
            "transfer_reason": transfer_reason,
            "transferred_at": patient.dentist_assignment_date,
        }

    async def delete_patient(
        self, db: AsyncSession, patient_id: UUID, deleted_by: UUID
    ) -> bool:
        """Soft delete patient and update dentist count"""
        patient = await self.get(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        previous_dentist_id = patient.assigned_dentist_id

        # Soft delete by updating status
        patient.status = PatientStatus.INACTIVE
        patient.updated_by = deleted_by

        # Update dentist patient count if patient was assigned
        if previous_dentist_id:
            await self._update_dentist_patient_count(db, previous_dentist_id)

        await db.commit()

        logger.info(f"Deleted patient {patient_id}")
        return True


patient_service = PatientService()
