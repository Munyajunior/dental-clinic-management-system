# src/services/prescription_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from models.prescription import Prescription, PrescriptionStatus
from models.audit_log import AuditLog, AuditAction
from models.patient import Patient, PatientStatus
from models.user import User
from models.treatment import Treatment
from schemas.prescription_schemas import (
    PrescriptionCreate,
    PrescriptionUpdate,
    PrescriptionRenew,
)
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("PRESCRIPTION_SERVICE")


class PrescriptionService(BaseService):
    def __init__(self):
        super().__init__(Prescription)

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Prescription]:
        """Get multiple Prescriptions with pagination, filtering, and relationships"""
        try:
            query = select(Prescription).options(
                selectinload(Prescription.dentist), selectinload(Prescription.patient)
            )

            if filters:
                conditions = []
                for field, value in filters.items():
                    if hasattr(Prescription, field):
                        conditions.append(getattr(Prescription, field) == value)
                if conditions:
                    query = query.where(and_(*conditions))

            query = (
                query.order_by(Prescription.created_at.desc()).offset(skip).limit(limit)
            )
            result = await db.execute(query)
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting multiple prescriptions: {e}")
            return []

    async def renew_prescription(
        self,
        db: AsyncSession,
        original_prescription_id: UUID,
        renew_data: PrescriptionRenew,
        dentist_id: UUID,
    ) -> Dict[str, Any]:
        """
        Renew a prescription with enterprise features:
        1. Mark original as RENEWED
        2. Create new prescription
        3. Link them in renewal chain
        4. Update refills if needed
        """
        try:
            # Get original prescription
            original_result = await db.execute(
                select(Prescription).where(Prescription.id == original_prescription_id)
            )
            original = original_result.scalar_one_or_none()

            if not original:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Original prescription not found",
                )

            # Validate original can be renewed
            if original.status not in [
                PrescriptionStatus.ACTIVE,
                PrescriptionStatus.DISPENSED,
            ]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot renew prescription with status: {original.status}",
                )

            # Check if original is already renewed
            if original.status == PrescriptionStatus.RENEWED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This prescription has already been renewed",
                )

            # Calculate renewal number and chain ID
            renewal_number = 1
            renewal_chain_id = original.renewal_chain_id or original.id

            if original.renewal_number > 0:
                # This is already a renewal, increment the number
                renewal_number = original.renewal_number + 1

            # Update original prescription status
            original.status = PrescriptionStatus.RENEWED
            original.updated_at = datetime.now(timezone.utc)

            # Decrease original refills if configured
            if renew_data.adjust_original_refills and original.refills_remaining > 0:
                original.refills_remaining = original.refills_remaining - 1
                original.refills = max(0, original.refills - 1)

            # Create new prescription data
            new_prescription_data = {
                "tenant_id": original.tenant_id,
                "patient_id": original.patient_id,
                "dentist_id": dentist_id,
                "treatment_id": original.treatment_id,
                "original_prescription_id": original.id,
                "renewal_number": renewal_number,
                "renewal_chain_id": renewal_chain_id,
                "renewal_reason": renew_data.renewal_reason,
                "renewal_notes": renew_data.renewal_notes,
                # Use custom values or original values
                "medication_name": renew_data.custom_medication_name
                or original.medication_name,
                "dosage": renew_data.custom_dosage or original.dosage,
                "frequency": renew_data.custom_frequency or original.frequency,
                "duration": renew_data.custom_duration or original.duration,
                "instructions": renew_data.custom_instructions
                or (original.instructions if renew_data.copy_instructions else ""),
                "quantity": original.quantity,
                "refills": original.refills,  # Start with same refills
                "refills_remaining": original.refills_remaining,
                # Set expiration
                "expires_at": datetime.now(timezone.utc)
                + timedelta(days=renew_data.new_expiration_days or 30),
                "status": PrescriptionStatus.ACTIVE,
            }

            # Create new prescription
            new_prescription = Prescription(**new_prescription_data)
            db.add(new_prescription)

            # Add renewal audit note to original
            renewal_note = f"Renewed on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} by dentist {dentist_id}"
            if original.instructions:
                original.instructions = (
                    f"{original.instructions}\n\n--- RENEWED ---\n{renewal_note}"
                )
                if renew_data.renewal_reason:
                    original.instructions += f"\nReason: {renew_data.renewal_reason}"
            else:
                original.instructions = renewal_note

            await db.commit()
            await db.refresh(original)
            await db.refresh(new_prescription)

            # Log the renewal
            await self._log_renewal_audit(
                db, original, new_prescription, renew_data, dentist_id
            )

            return {
                "success": True,
                "original_prescription": original,
                "new_prescription": new_prescription,
                "message": "Prescription renewed successfully",
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error renewing prescription: {e}")
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to renew prescription: {str(e)}",
            )

    async def bulk_renew_prescriptions(
        self,
        db: AsyncSession,
        prescription_ids: List[UUID],
        renew_data: PrescriptionRenew,
        dentist_id: UUID,
    ) -> Dict[str, Any]:
        """
        Bulk renew multiple prescriptions with rollback on failure
        """
        results = {
            "total": len(prescription_ids),
            "successful": 0,
            "failed": 0,
            "failed_details": [],
            "renewed_prescriptions": [],
        }

        for prescription_id in prescription_ids:
            try:
                result = await self.renew_prescription(
                    db, prescription_id, renew_data, dentist_id
                )
                results["successful"] += 1
                results["renewed_prescriptions"].append(
                    {
                        "original_id": prescription_id,
                        "new_id": result["new_prescription"].id,
                        "medication_name": result["new_prescription"].medication_name,
                    }
                )

            except Exception as e:
                results["failed"] += 1
                results["failed_details"].append(
                    {"prescription_id": prescription_id, "error": str(e)}
                )

        return results

    async def get_renewal_history(
        self, db: AsyncSession, prescription_id: UUID, include_original: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get complete renewal history for a prescription
        """
        try:
            # Get renewal chain ID
            prescription_result = await db.execute(
                select(Prescription).where(Prescription.id == prescription_id)
            )
            prescription = prescription_result.scalar_one_or_none()

            if not prescription:
                return []

            chain_id = prescription.renewal_chain_id or prescription.id

            # Get all prescriptions in the chain
            query = (
                select(Prescription)
                .where(
                    or_(
                        Prescription.renewal_chain_id == chain_id,
                        Prescription.id == chain_id,
                    )
                )
                .order_by(Prescription.renewal_number, Prescription.created_at)
            )

            result = await db.execute(query)
            prescriptions = result.scalars().all()

            # Format history
            history = []
            for rx in prescriptions:
                history.append(
                    {
                        "id": rx.id,
                        "medication_name": rx.medication_name,
                        "dosage": rx.dosage,
                        "status": rx.status,
                        "renewal_number": rx.renewal_number,
                        "created_at": rx.created_at,
                        "expires_at": rx.expires_at,
                        "is_current": rx.status == PrescriptionStatus.ACTIVE,
                        "dentist_name": (
                            f"{rx.dentist.first_name} {rx.dentist.last_name}"
                            if rx.dentist
                            else None
                        ),
                    }
                )

            return history

        except Exception as e:
            logger.error(f"Error getting renewal history: {e}")
            return []

    async def _log_renewal_audit(
        self,
        db: AsyncSession,
        original: Prescription,
        new_prescription: Prescription,
        renew_data: PrescriptionRenew,
        dentist_id: UUID,
    ):
        """Log renewal for audit trail"""
        try:
            audit_log = AuditLog(
                tenant_id=original.tenant_id,
                user_id=dentist_id,
                action=AuditAction.RENEWED,
                entity_type="prescription",
                entity_id=new_prescription.id,
                details={
                    "original_prescription_id": str(original.id),
                    "renewal_reason": renew_data.renewal_reason,
                    "renewal_notes": renew_data.renewal_notes,
                    "original_medication": original.medication_name,
                    "new_medication": new_prescription.medication_name,
                    "patient_id": str(original.patient_id),
                    "adjust_original_refills": renew_data.adjust_original_refills,
                    "copy_instructions": renew_data.copy_instructions,
                },
                ip_address=None,
                user_agent=None,
            )

            db.add(audit_log)
            await db.flush()

        except Exception as e:
            logger.error(f"Failed to log renewal audit: {e}")
            # Don't fail the renewal if audit logging fails

    async def create_prescription(
        self, db: AsyncSession, prescription_data: PrescriptionCreate
    ) -> Prescription:
        """Create new prescription with validation"""
        # Verify patient exists and is active
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == prescription_data.patient_id,
                Patient.status == PatientStatus.ACTIVE,
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
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

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
        prescription.dispensed_at = datetime.now(timezone.utc)

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
        """Get active (not archived/expired) prescriptions for a patient"""
        try:
            result = await db.execute(
                select(Prescription)
                .where(
                    Prescription.patient_id == patient_id,
                    Prescription.status == PrescriptionStatus.ACTIVE,
                    Prescription.expires_at > datetime.now(timezone.utc),
                )
                .order_by(Prescription.expires_at)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting active prescriptions: {e}")
            return []

    async def get_archived_prescriptions(
        self, db: AsyncSession, patient_id: UUID, limit: int = 50
    ) -> List[Prescription]:
        """Get archived prescriptions for a patient"""
        try:
            result = await db.execute(
                select(Prescription)
                .where(
                    Prescription.patient_id == patient_id,
                    Prescription.status.in_(
                        [PrescriptionStatus.RENEWED, PrescriptionStatus.ARCHIVED]
                    ),
                )
                .order_by(Prescription.updated_at.desc())
                .limit(limit)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting archived prescriptions: {e}")
            return []

    async def archive_prescription(
        self, db: AsyncSession, prescription_id: UUID, reason: str = None
    ) -> Prescription:
        """Archive a prescription (manual archive)"""
        prescription = await self.get(db, prescription_id)
        if not prescription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found"
            )

        prescription.status = PrescriptionStatus.ARCHIVED
        prescription.archived_at = datetime.now(timezone.utc)

        if reason:
            archive_note = f"\n\n--- ARCHIVED ---\nArchived on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
            archive_note += f"\nReason: {reason}"
            prescription.instructions = (prescription.instructions or "") + archive_note

        await db.commit()
        await db.refresh(prescription)

        return prescription

    async def check_prescription_expiry(self, db: AsyncSession) -> Dict[str, Any]:
        """Check for expired prescriptions"""
        try:
            # Get expired prescriptions
            expired_result = await db.execute(
                select(Prescription).where(
                    Prescription.expires_at <= datetime.now(timezone.utc),
                    Prescription.is_dispensed == False,
                )
            )
            expired_prescriptions = expired_result.scalars().all()

            # Get prescriptions expiring soon (within 7 days)
            soon_threshold = datetime.now(timezone.utc) + timedelta(days=7)
            expiring_soon_result = await db.execute(
                select(Prescription).where(
                    Prescription.expires_at <= soon_threshold,
                    Prescription.expires_at > datetime.now(timezone.utc),
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
