# src/routes/patients.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from db.database import get_db
from schemas.patient_schemas import (
    PatientCreate,
    PatientUpdate,
    PatientPublic,
    PatientDetail,
    PatientSearch,
)
from services.patient_service import patient_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

router = APIRouter(prefix="/patients", tags=["patients"])
logger = setup_logger("PATIENT_ROUTES")


@router.get(
    "/",
    response_model=List[PatientPublic],
    summary="List patients",
    description="Get list of patients with optional search and filters",
)
async def list_patients(
    skip: int = 0,
    limit: int = 50,
    query: Optional[str] = Query(None, description="Search term"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List patients endpoint"""
    try:
        search_params = PatientSearch(query=query, status=status)
        patients = await patient_service.search_patients(
            db, search_params, current_user.tenant_id, skip, limit
        )

        # Convert to public schema and return as list
        patient_list = [PatientPublic.from_orm(patient) for patient in patients]

        # Return direct list for consistent API response
        return patient_list

    except Exception as e:
        logger.error(f"Error listing patients: {e}")
        # Return empty list on error
        return []


@router.post(
    "/",
    response_model=PatientPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create patient",
    description="Create a new patient record",
)
async def create_patient(
    patient_data: PatientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create patient endpoint"""
    try:
        logger.info(f"Creating patient for tenant: {current_user.tenant_id}")
        logger.debug(f"Patient data: {patient_data}")
        logger.debug(
            f"Current user: {current_user.email}, tenant: {current_user.tenant_id}"
        )

        # Add tenant_id to patient data if not provided
        if not hasattr(patient_data, "tenant_id") or not patient_data.tenant_id:
            patient_data.tenant_id = current_user.tenant_id

        # DEBUG: Check database session state
        logger.debug("About to call patient_service.create...")
        patient = await patient_service.create_patient(
            db, patient_data, current_user.id
        )
        # DEBUG: Check what's returned
        logger.debug(f"Patient creation returned - type: {type(patient)}")
        logger.debug(f"Patient creation returned - value: {patient}")

        if patient is None:
            logger.error("Patient creation returned None!")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create patient - returned None",
            )
        if isinstance(patient, tuple):
            logger.error("PATIENT CREATION RETURNED TUPLE INSTEAD OF PATIENT OBJECT!")
            logger.error(f"Tuple contents: {patient}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error - data integrity issue",
            )

        logger.info(f"Successfully created patient: {patient.id}")
        return PatientPublic.from_orm(patient)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_patient endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create patient",
        )


@router.get(
    "/{patient_id}",
    response_model=PatientDetail,
    summary="Get patient",
    description="Get patient details by ID",
)
async def get_patient(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get patient by ID endpoint"""
    patient = await patient_service.get(db, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
        )

    # Calculate age for the response
    patient_detail = PatientDetail.from_orm(patient)
    patient_detail.age = patient.calculate_age()

    return patient_detail


@router.put(
    "/{patient_id}",
    response_model=PatientPublic,
    summary="Update patient",
    description="Update patient information",
)
async def update_patient(
    patient_id: UUID,
    patient_data: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update patient endpoint"""
    patient = await patient_service.update(db, patient_id, patient_data)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
        )
    return PatientPublic.from_orm(patient)


@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate patient",
    description="Deactivate patient record",
)
async def deactivate_patient(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> None:
    """Deactivate patient endpoint"""
    # Soft delete by updating status
    update_data = PatientUpdate(status="inactive")
    patient = await patient_service.update(db, patient_id, update_data)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
        )
