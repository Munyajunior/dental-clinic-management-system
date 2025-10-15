# src/routes/consultations.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from db.database import get_db
from schemas.consultation_schemas import (
    ConsultationCreate,
    ConsultationUpdate,
    ConsultationPublic,
    ConsultationDetail,
)
from services.consultation_service import consultation_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/consultations", tags=["consultations"])


@router.get(
    "/",
    response_model=List[ConsultationPublic],
    summary="List consultations",
    description="Get list of consultations",
)
async def list_consultations(
    skip: int = 0,
    limit: int = 50,
    patient_id: Optional[UUID] = Query(None, description="Filter by patient"),
    dentist_id: Optional[UUID] = Query(None, description="Filter by dentist"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List consultations endpoint"""
    filters = {}
    if patient_id:
        filters["patient_id"] = patient_id
    if dentist_id:
        filters["dentist_id"] = dentist_id

    consultations = await consultation_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    return [ConsultationPublic.from_orm(consultation) for consultation in consultations]


@router.post(
    "/",
    response_model=ConsultationPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create consultation",
    description="Create a new consultation record",
)
async def create_consultation(
    consultation_data: ConsultationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create consultation endpoint"""
    consultation = await consultation_service.create_consultation(db, consultation_data)
    return ConsultationPublic.from_orm(consultation)


@router.get(
    "/{consultation_id}",
    response_model=ConsultationDetail,
    summary="Get consultation",
    description="Get consultation details by ID",
)
async def get_consultation(
    consultation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get consultation by ID endpoint"""
    consultation = await consultation_service.get(db, consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found"
        )

    consultation_detail = ConsultationDetail.from_orm(consultation)
    consultation_detail.dentist_name = (
        f"{consultation.dentist.first_name} {consultation.dentist.last_name}"
    )
    consultation_detail.patient_name = (
        f"{consultation.patient.first_name} {consultation.patient.last_name}"
    )

    return consultation_detail


@router.put(
    "/{consultation_id}",
    response_model=ConsultationPublic,
    summary="Update consultation",
    description="Update consultation information",
)
async def update_consultation(
    consultation_id: UUID,
    consultation_data: ConsultationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update consultation endpoint"""
    consultation = await consultation_service.update(
        db, consultation_id, consultation_data
    )
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found"
        )
    return ConsultationPublic.from_orm(consultation)
