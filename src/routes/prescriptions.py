# src/routes/prescriptions.py
from fastapi import APIRouter, Depends, status, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any, Dict
from uuid import UUID
from db.database import get_db
from schemas.prescription_schemas import (
    PrescriptionCreate,
    PrescriptionUpdate,
    PrescriptionPublic,
    PrescriptionDetail,
    PrescriptionRenew,
)
from services.prescription_service import prescription_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])

logger = setup_logger("PRESCRIPTIONS_ROUTES")


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

    prescription_list: list = []
    for prescription in prescriptions:
        prescription_public = PrescriptionPublic.from_orm(prescription)
        prescription_public.dentist_name = (
            f"{prescription.dentist.first_name} {prescription.dentist.last_name}"
        )

        prescription_public.patient_name = (
            f"{prescription.patient.first_name} {prescription.patient.last_name}"
        )
        prescription_list.append(prescription_public)

    return prescription_list


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
    try:
        prescription_data.tenant_id = current_user.tenant_id
        prescription = await prescription_service.create_prescription(
            db, prescription_data
        )
        return PrescriptionPublic.from_orm(prescription)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_prescription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


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


@router.post(
    "/{prescription_id}/renew",
    response_model=Dict[str, Any],
    summary="Renew prescription",
    description="Renew a prescription with tracking and audit trail",
)
async def renew_prescription(
    prescription_id: UUID,
    renew_data: PrescriptionRenew,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Renew prescription endpoint"""
    try:
        result = await prescription_service.renew_prescription(
            db, prescription_id, renew_data, current_user.id
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in renew_prescription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/bulk-renew",
    response_model=Dict[str, Any],
    summary="Bulk renew prescriptions",
    description="Renew multiple prescriptions at once",
)
async def bulk_renew_prescriptions(
    prescription_ids: List[UUID] = Body(..., embed=True),
    renew_data: PrescriptionRenew = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Bulk renew prescriptions endpoint"""
    try:
        result = await prescription_service.bulk_renew_prescriptions(
            db, prescription_ids, renew_data, current_user.id
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk_renew_prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/{prescription_id}/renewal-history",
    response_model=List[Dict[str, Any]],
    summary="Get renewal history",
    description="Get complete renewal history for a prescription",
)
async def get_renewal_history(
    prescription_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get renewal history endpoint"""
    try:
        history = await prescription_service.get_renewal_history(db, prescription_id)
        return history

    except Exception as e:
        logger.error(f"Error in get_renewal_history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/{prescription_id}/archive",
    response_model=PrescriptionPublic,
    summary="Archive prescription",
    description="Manually archive a prescription",
)
async def archive_prescription(
    prescription_id: UUID,
    reason: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Archive prescription endpoint"""
    try:
        prescription = await prescription_service.archive_prescription(
            db, prescription_id, reason
        )
        return PrescriptionPublic.from_orm(prescription)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in archive_prescription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/patients/{patient_id}/active",
    response_model=List[PrescriptionPublic],
    summary="Get active prescriptions",
    description="Get active prescriptions for a patient",
)
async def get_active_patient_prescriptions(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get active patient prescriptions endpoint"""
    try:
        prescriptions = await prescription_service.get_active_prescriptions(
            db, patient_id
        )
        return [PrescriptionPublic.from_orm(p) for p in prescriptions]

    except Exception as e:
        logger.error(f"Error in get_active_patient_prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/patients/{patient_id}/archived",
    response_model=List[PrescriptionPublic],
    summary="Get archived prescriptions",
    description="Get archived prescriptions for a patient",
)
async def get_archived_patient_prescriptions(
    patient_id: UUID,
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get archived patient prescriptions endpoint"""
    try:
        prescriptions = await prescription_service.get_archived_prescriptions(
            db, patient_id, limit
        )
        return [PrescriptionPublic.from_orm(p) for p in prescriptions]

    except Exception as e:
        logger.error(f"Error in get_archived_patient_prescriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


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
