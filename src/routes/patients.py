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

router = APIRouter(prefix="/patients", tags=["patients"])


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
    search_params = PatientSearch(query=query, status=status)
    patients = await patient_service.search_patients(db, search_params, skip, limit)
    return [PatientPublic.from_orm(patient) for patient in patients]


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
    patient = await patient_service.create_patient(db, patient_data, current_user.id)
    return PatientPublic.from_orm(patient)


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
