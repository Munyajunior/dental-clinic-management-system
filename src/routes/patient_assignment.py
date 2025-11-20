# src/routes/patient_assignment.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from uuid import UUID
from db.database import get_db
from schemas.patient_schemas import (
    DentistAssignment,
    DentistReassignment,
    PatientAssignmentResponse,
    DentistWorkload,
    PatientPublic,
)
from services.patient_service import patient_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

router = APIRouter(prefix="/patient-assignments", tags=["patient-assignments"])
logger = setup_logger("PATIENT_ASSIGNMENT_ROUTES")


@router.post(
    "/assign",
    response_model=PatientAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign dentist to patient",
    description="Assign a specific dentist to a patient",
)
async def assign_dentist_to_patient(
    assignment_data: DentistAssignment,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Assign dentist to patient endpoint"""
    try:
        result = await patient_service.assign_dentist_to_patient(
            db,
            assignment_data.patient_id,
            assignment_data.dentist_id,
            assignment_data.assignment_reason,
            current_user.id,
            assignment_data.notes,
        )

        return PatientAssignmentResponse(
            success=True,
            message="Dentist assigned successfully",
            patient_id=result["patient_id"],
            dentist_id=result["dentist_id"],
            assignment_reason=result["assignment_reason"],
            assignment_date=result["assignment_date"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to assign dentist to patient: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign dentist to patient",
        )


@router.post(
    "/reassign",
    response_model=PatientAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Reassign patient to different dentist",
    description="Reassign a patient to a different dentist",
)
async def reassign_patient_to_dentist(
    reassignment_data: DentistReassignment,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Reassign patient to different dentist endpoint"""
    try:
        result = await patient_service.reassign_patient_to_dentist(
            db,
            reassignment_data.patient_id,
            reassignment_data.new_dentist_id,
            reassignment_data.assignment_reason,
            current_user.id,
            reassignment_data.notes,
        )

        return PatientAssignmentResponse(
            success=True,
            message="Patient reassigned successfully",
            patient_id=result["patient_id"],
            dentist_id=result["dentist_id"],
            assignment_reason=result["assignment_reason"],
            assignment_date=result["assignment_date"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reassign patient: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reassign patient",
        )


@router.delete(
    "/{patient_id}/dentist",
    status_code=status.HTTP_200_OK,
    summary="Remove dentist assignment",
    description="Remove dentist assignment from patient",
)
async def remove_dentist_assignment(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Remove dentist assignment endpoint"""
    try:
        await patient_service.remove_dentist_assignment(db, patient_id, current_user.id)

        return {"success": True, "message": "Dentist assignment removed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove dentist assignment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove dentist assignment",
        )


@router.get(
    "/dentists/{dentist_id}/workload",
    response_model=DentistWorkload,
    summary="Get dentist workload",
    description="Get current workload information for a dentist",
)
async def get_dentist_workload(
    dentist_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get dentist workload endpoint"""
    try:
        workload = await patient_service.get_dentist_workload(db, dentist_id)
        return workload

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get dentist workload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get dentist workload",
        )


@router.get(
    "/dentists/workloads",
    response_model=List[DentistWorkload],
    summary="Get all dentists workloads",
    description="Get workload information for all dentists",
)
async def get_all_dentists_workloads(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get all dentists workloads endpoint"""
    try:
        workloads = await patient_service.get_all_dentists_workloads(db)
        return workloads

    except Exception as e:
        logger.error(f"Failed to get dentists workloads: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get dentists workloads",
        )


@router.get(
    "/dentists/{dentist_id}/patients",
    response_model=List[PatientPublic],
    summary="Get dentist's patients",
    description="Get all patients assigned to a specific dentist",
)
async def get_dentist_patients(
    dentist_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get dentist's patients endpoint"""
    try:
        patients = await patient_service.get_patients_by_dentist(
            db, dentist_id, skip, limit
        )
        return patients

    except Exception as e:
        logger.error(f"Failed to get dentist's patients: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get dentist's patients",
        )


@router.post(
    "/auto-assign/{patient_id}",
    response_model=PatientAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Auto-assign dentist to patient",
    description="Automatically assign the least busy available dentist to a patient",
)
async def auto_assign_dentist(
    patient_id: UUID,
    assignment_reason: str = "automatic_assignment",
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Auto-assign dentist endpoint"""
    try:
        result = await patient_service.auto_assign_dentist(
            db, patient_id, assignment_reason, current_user.id
        )

        return PatientAssignmentResponse(
            success=True,
            message="Dentist auto-assigned successfully",
            patient_id=result["patient_id"],
            dentist_id=result["dentist_id"],
            assignment_reason=result["assignment_reason"],
            assignment_date=result["assignment_date"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to auto-assign dentist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to auto-assign dentist",
        )
