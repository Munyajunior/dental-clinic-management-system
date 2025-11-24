# src/routes/patient_sharing.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from db.database import get_db
from schemas.patient_sharing_schemas import (
    PatientSharingCreate,
    PatientSharingUpdate,
    PatientSharingPublic,
)
from models.patient import Patient
from models.user import User
from services.patient_service import patient_service
from services.auth_service import auth_service
from services.background_service import background_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

router = APIRouter(prefix="/patient-sharing", tags=["patient-sharing"])
logger = setup_logger("PATIENT_SHARING_ROUTES")


@router.post(
    "/share",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Share patient with another dental professional",
    description="Share a patient with another dental professional for consultation",
)
async def share_patient(
    patient_id: UUID,
    shared_with_dentist_id: UUID,
    permission_level: str = "consult",
    expires_at: Optional[datetime] = None,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Share patient endpoint with count updates"""
    try:
        result = await patient_service.share_patient(
            db,
            patient_id,
            shared_with_dentist_id,
            permission_level,
            current_user.id,
            expires_at,
            notes,
        )

        # Schedule background count update for the shared dentist
        # (even though it's sharing not assignment, we update for workload display)
        await background_service.schedule_patient_count_update(
            db, shared_with_dentist_id, current_user.tenant_id
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to share patient: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to share patient",
        )


@router.post(
    "/revoke/{sharing_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Revoke patient sharing",
    description="Revoke sharing of a patient with another dental professional",
)
async def revoke_patient_sharing(
    sharing_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Revoke patient sharing endpoint with count updates"""
    try:
        # Get sharing record first to know which dentist to update
        from models.patient_sharing import PatientSharing

        sharing_result = await db.execute(
            select(PatientSharing).where(PatientSharing.id == sharing_id)
        )
        sharing = sharing_result.scalar_one_or_none()

        if not sharing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sharing record not found"
            )

        shared_with_dentist_id = sharing.shared_with_dentist_id

        result = await patient_service.revoke_patient_sharing(
            db, sharing_id, current_user.id
        )

        # Schedule background count update for the dentist who lost access
        await background_service.schedule_patient_count_update(
            db, shared_with_dentist_id, current_user.tenant_id
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke patient sharing: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke patient sharing",
        )


@router.get(
    "/shared-with-me",
    response_model=List[Dict[str, Any]],
    summary="Get patients shared with me",
    description="Get all patients that are shared with the current user",
)
async def get_shared_patients_with_me(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get patients shared with current user endpoint"""
    try:
        shared_patients = await patient_service.get_shared_patients(
            db, current_user.id, skip, limit
        )
        return shared_patients

    except Exception as e:
        logger.error(f"Failed to get shared patients: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get shared patients",
        )


@router.get(
    "/shared-by-me",
    response_model=List[Dict[str, Any]],
    summary="Get patients shared by me",
    description="Get all patients that I have shared with others",
)
async def get_patients_shared_by_me(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get patients shared by current user endpoint"""
    try:
        from models.patient_sharing import PatientSharing

        result = await db.execute(
            select(PatientSharing, Patient)
            .join(Patient, PatientSharing.patient_id == Patient.id)
            .where(
                PatientSharing.shared_by_dentist_id == current_user.id,
                PatientSharing.is_active == True,
            )
            .offset(skip)
            .limit(limit)
        )

        shared_patients = []
        for sharing, patient in result.all():
            # Get shared with dentist name
            shared_with_result = await db.execute(
                select(User).where(User.id == sharing.shared_with_dentist_id)
            )
            shared_with_dentist = shared_with_result.scalar_one_or_none()

            shared_patients.append(
                {
                    "sharing_id": sharing.id,
                    "patient": patient,
                    "shared_with_dentist_id": sharing.shared_with_dentist_id,
                    "shared_with_dentist_name": (
                        f"{shared_with_dentist.first_name} {shared_with_dentist.last_name}"
                        if shared_with_dentist
                        else "Unknown"
                    ),
                    "permission_level": sharing.permission_level,
                    "shared_at": sharing.created_at,
                    "expires_at": sharing.expires_at,
                }
            )

        return shared_patients

    except Exception as e:
        logger.error(f"Failed to get patients shared by me: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get patients shared by me",
        )


@router.post(
    "/transfer",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Transfer patient to another dental professional",
    description="Completely transfer patient to another dental professional",
)
async def transfer_patient(
    patient_id: UUID,
    new_dentist_id: UUID,
    transfer_reason: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Transfer patient endpoint with count updates"""
    try:
        result = await patient_service.transfer_patient(
            db, patient_id, new_dentist_id, transfer_reason, current_user.id
        )

        # Schedule background count updates for both previous and new dentist
        if result.get("previous_dentist_id"):
            await background_service.schedule_patient_count_update(
                db, result["previous_dentist_id"], current_user.tenant_id
            )
        await background_service.schedule_patient_count_update(
            db, result["new_dentist_id"], current_user.tenant_id
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to transfer patient: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to transfer patient",
        )
