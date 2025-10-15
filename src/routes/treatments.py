# src/routes/treatments.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from db.database import get_db
from schemas.treatment_schemas import (
    TreatmentCreate,
    TreatmentUpdate,
    TreatmentPublic,
    TreatmentDetail,
    TreatmentProgressNote,
    TreatmentItemCreate,
)
from services.treatment_service import treatment_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/treatments", tags=["treatments"])


@router.get(
    "/",
    response_model=List[TreatmentPublic],
    summary="List treatments",
    description="Get list of treatments",
)
async def list_treatments(
    skip: int = 0,
    limit: int = 50,
    patient_id: Optional[UUID] = Query(None, description="Filter by patient"),
    dentist_id: Optional[UUID] = Query(None, description="Filter by dentist"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List treatments endpoint"""
    filters = {}
    if patient_id:
        filters["patient_id"] = patient_id
    if dentist_id:
        filters["dentist_id"] = dentist_id
    if status:
        filters["status"] = status

    treatments = await treatment_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    return [TreatmentPublic.from_orm(treatment) for treatment in treatments]


@router.post(
    "/",
    response_model=TreatmentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create treatment",
    description="Create a new treatment plan",
)
async def create_treatment(
    treatment_data: TreatmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create treatment endpoint"""
    treatment = await treatment_service.create_treatment(db, treatment_data)
    return TreatmentPublic.from_orm(treatment)


@router.get(
    "/{treatment_id}",
    response_model=TreatmentDetail,
    summary="Get treatment",
    description="Get treatment details by ID",
)
async def get_treatment(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get treatment by ID endpoint"""
    treatment = await treatment_service.get(db, treatment_id)
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )

    treatment_detail = TreatmentDetail.from_orm(treatment)
    treatment_detail.dentist_name = (
        f"{treatment.dentist.first_name} {treatment.dentist.last_name}"
    )
    treatment_detail.patient_name = (
        f"{treatment.patient.first_name} {treatment.patient.last_name}"
    )

    return treatment_detail


@router.put(
    "/{treatment_id}",
    response_model=TreatmentPublic,
    summary="Update treatment",
    description="Update treatment information",
)
async def update_treatment(
    treatment_id: UUID,
    treatment_data: TreatmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update treatment endpoint"""
    treatment = await treatment_service.update(db, treatment_id, treatment_data)
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )
    return TreatmentPublic.from_orm(treatment)


@router.post(
    "/{treatment_id}/progress",
    response_model=TreatmentPublic,
    summary="Add progress note",
    description="Add progress note to treatment",
)
async def add_progress_note(
    treatment_id: UUID,
    progress_note: TreatmentProgressNote,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Add progress note endpoint"""
    treatment = await treatment_service.add_progress_note(
        db, treatment_id, progress_note, current_user.id
    )
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )
    return TreatmentPublic.from_orm(treatment)


@router.post(
    "/{treatment_id}/items",
    response_model=TreatmentPublic,
    summary="Add treatment item",
    description="Add item to treatment",
)
async def add_treatment_item(
    treatment_id: UUID,
    item_data: TreatmentItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Add treatment item endpoint"""
    treatment = await treatment_service.add_treatment_item(db, treatment_id, item_data)
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )
    return TreatmentPublic.from_orm(treatment)


@router.patch(
    "/{treatment_id}/status/{status}",
    response_model=TreatmentPublic,
    summary="Update treatment status",
    description="Update treatment status (in_progress, completed, etc.)",
)
async def update_treatment_status(
    treatment_id: UUID,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update treatment status endpoint"""
    treatment = await treatment_service.update_status(db, treatment_id, status)
    if not treatment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )
    return TreatmentPublic.from_orm(treatment)
