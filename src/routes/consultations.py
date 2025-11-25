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
    description="Get list of consultations that the user is authorized to view",
)
async def list_consultations(
    skip: int = 0,
    limit: int = 50,
    patient_id: Optional[UUID] = Query(None, description="Filter by patient"),
    dentist_id: Optional[UUID] = Query(None, description="Filter by dentist"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List consultations endpoint - only shows consultations user is authorized to see"""
    filters = {}
    if patient_id:
        filters["patient_id"] = patient_id
    if dentist_id:
        # Non-admin users can only filter by their own ID
        if current_user.role != "admin" and dentist_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own consultations",
            )
        filters["dentist_id"] = dentist_id
    else:
        # If no dentist_id specified, non-admin users only see their own consultations
        if current_user.role != "admin":
            filters["dentist_id"] = current_user.id

    consultations = await consultation_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    # Convert to response model with names
    consultation_list = []
    for consultation in consultations:
        consultation_public = ConsultationPublic.from_orm(consultation)
        # Add names to the response
        consultation_public.dentist_name = (
            f"{consultation.dentist.first_name} {consultation.dentist.last_name}"
        )
        consultation_public.patient_name = (
            f"{consultation.patient.first_name} {consultation.patient.last_name}"
        )
        consultation_list.append(consultation_public)

    return consultation_list


@router.post(
    "/",
    response_model=ConsultationPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create consultation",
    description="Create a new consultation record. User must be assigned to the patient.",
)
async def create_consultation(
    consultation_data: ConsultationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create consultation endpoint with authorization check"""
    consultation_data.tenant_id = current_user.tenant_id
    consultation = await consultation_service.create_consultation(
        db, consultation_data, current_user
    )
    return ConsultationPublic.from_orm(consultation)


@router.get(
    "/{consultation_id}",
    response_model=ConsultationDetail,
    summary="Get consultation",
    description="Get consultation details by ID. User must be authorized to view this consultation.",
)
async def get_consultation(
    consultation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get consultation by ID endpoint with authorization check"""
    consultation = await consultation_service.get(db, consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found"
        )

    # Check if user can view this consultation
    can_view = await consultation_service._can_user_modify_consultation(
        db, current_user, consultation
    )
    if not can_view:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this consultation",
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
    description="Update consultation information. User must be authorized to modify this consultation.",
)
async def update_consultation(
    consultation_id: UUID,
    consultation_data: ConsultationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update consultation endpoint with authorization check"""
    consultation = await consultation_service.get(db, consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found"
        )

    # Check if user can modify this consultation
    can_modify = await consultation_service._can_user_modify_consultation(
        db, current_user, consultation
    )
    if not can_modify:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to modify this consultation",
        )

    updated_consultation = await consultation_service.update(
        db, consultation_id, consultation_data
    )
    return ConsultationPublic.from_orm(updated_consultation)


@router.get(
    "/patient/{patient_id}",
    response_model=List[ConsultationPublic],
    summary="Get patient consultations",
    description="Get all consultations for a specific patient that the user is authorized to view",
)
async def get_patient_consultations(
    patient_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get patient consultations with authorization check"""
    consultations = await consultation_service.get_patient_consultations(
        db, patient_id, current_user, skip, limit
    )
    # Convert to response model with names
    consultation_list = []
    for consultation in consultations:
        consultation_public = ConsultationPublic.from_orm(consultation)
        consultation_public.dentist_name = (
            f"{consultation.dentist.first_name} {consultation.dentist.last_name}"
        )
        consultation_public.patient_name = (
            f"{consultation.patient.first_name} {consultation.patient.last_name}"
        )
        consultation_list.append(consultation_public)

    return consultation_list


@router.get(
    "/dentist/{dentist_id}",
    response_model=List[ConsultationPublic],
    summary="Get dentist consultations",
    description="Get all consultations for a specific dentist that the user is authorized to view",
)
async def get_dentist_consultations(
    dentist_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get dentist consultations with authorization check"""
    consultations = await consultation_service.get_dentist_consultations(
        db, dentist_id, current_user, skip, limit
    )
    # Convert to response model with names
    consultation_list = []
    for consultation in consultations:
        consultation_public = ConsultationPublic.from_orm(consultation)
        consultation_public.dentist_name = (
            f"{consultation.dentist.first_name} {consultation.dentist.last_name}"
        )
        consultation_public.patient_name = (
            f"{consultation.patient.first_name} {consultation.patient.last_name}"
        )
        consultation_list.append(consultation_public)

    return consultation_list
