# src/routes/prescriptions.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from db.database import get_db
from schemas.prescription_schemas import (
    PrescriptionCreate,
    PrescriptionUpdate,
    PrescriptionPublic,
    PrescriptionDetail,
)
from services.prescription_service import prescription_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


@router.get(
    "/",
    response_model=List[PrescriptionPublic],
    summary="List prescriptions",
    description="Get list of prescriptions",
)
async def list_prescriptions(
    skip: int = 0,
    limit: int = 50,
    patient_id: Optional[UUID] = Query(None, description="Filter by patient"),
    dentist_id: Optional[UUID] = Query(None, description="Filter by dentist"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List prescriptions endpoint"""
    filters = {}
    if patient_id:
        filters["patient_id"] = patient_id
    if dentist_id:
        filters["dentist_id"] = dentist_id

    prescriptions = await prescription_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    return [PrescriptionPublic.from_orm(prescription) for prescription in prescriptions]


@router.post(
    "/",
    response_model=PrescriptionPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create prescription",
    description="Create a new prescription",
)
async def create_prescription(
    prescription_data: PrescriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create prescription endpoint"""
    prescription = await prescription_service.create_prescription(db, prescription_data)
    return PrescriptionPublic.from_orm(prescription)


@router.get(
    "/{prescription_id}",
    response_model=PrescriptionDetail,
    summary="Get prescription",
    description="Get prescription details by ID",
)
async def get_prescription(
    prescription_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get prescription by ID endpoint"""
    prescription = await prescription_service.get(db, prescription_id)
    if not prescription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found"
        )

    prescription_detail = PrescriptionDetail.from_orm(prescription)
    prescription_detail.dentist_name = (
        f"{prescription.dentist.first_name} {prescription.dentist.last_name}"
    )
    prescription_detail.patient_name = (
        f"{prescription.patient.first_name} {prescription.patient.last_name}"
    )

    return prescription_detail


@router.put(
    "/{prescription_id}",
    response_model=PrescriptionPublic,
    summary="Update prescription",
    description="Update prescription information",
)
async def update_prescription(
    prescription_id: UUID,
    prescription_data: PrescriptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update prescription endpoint"""
    prescription = await prescription_service.update(
        db, prescription_id, prescription_data
    )
    if not prescription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found"
        )
    return PrescriptionPublic.from_orm(prescription)


@router.patch(
    "/{prescription_id}/dispense",
    response_model=PrescriptionPublic,
    summary="Mark prescription as dispensed",
    description="Mark prescription as dispensed",
)
async def dispense_prescription(
    prescription_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Dispense prescription endpoint"""
    prescription = await prescription_service.mark_dispensed(db, prescription_id)
    if not prescription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found"
        )
    return PrescriptionPublic.from_orm(prescription)
