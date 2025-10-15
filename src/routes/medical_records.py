# src/routes/medical_records.py
from fastapi import APIRouter, Depends, status, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
import base64
from db.database import get_db
from schemas.medical_record_schemas import (
    MedicalRecordCreate,
    MedicalRecordUpdate,
    MedicalRecordPublic,
    MedicalRecordDetail,
)
from services.medical_record_service import medical_record_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/medical-records", tags=["medical-records"])


@router.get(
    "/",
    response_model=List[MedicalRecordPublic],
    summary="List medical records",
    description="Get list of medical records for a patient",
)
async def list_medical_records(
    patient_id: UUID,
    record_type: Optional[str] = Query(None, description="Filter by record type"),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List medical records endpoint"""
    filters = {"patient_id": patient_id}
    if record_type:
        filters["record_type"] = record_type

    records = await medical_record_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    return [MedicalRecordPublic.from_orm(record) for record in records]


@router.post(
    "/",
    response_model=MedicalRecordPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create medical record",
    description="Create a new medical record",
)
async def create_medical_record(
    record_data: MedicalRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create medical record endpoint"""
    record_data.created_by = current_user.id
    record = await medical_record_service.create_medical_record(db, record_data)
    return MedicalRecordPublic.from_orm(record)


@router.post(
    "/upload",
    response_model=MedicalRecordPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Upload medical record file",
    description="Upload and create medical record with file attachment",
)
async def upload_medical_record(
    patient_id: UUID = Query(...),
    record_type: str = Query(...),
    title: str = Query(...),
    description: Optional[str] = Query(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Upload medical record file endpoint"""
    # Read file content
    file_content = await file.read()
    file_data = base64.b64encode(file_content).decode("utf-8")

    record_data = MedicalRecordCreate(
        patient_id=patient_id,
        record_type=record_type,
        title=title,
        description=description,
        file_data=file_data,
        file_name=file.filename,
        mime_type=file.content_type,
    )
    record_data.created_by = current_user.id

    record = await medical_record_service.create_medical_record(db, record_data)
    return MedicalRecordPublic.from_orm(record)


@router.get(
    "/{record_id}",
    response_model=MedicalRecordDetail,
    summary="Get medical record",
    description="Get medical record details by ID",
)
async def get_medical_record(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get medical record by ID endpoint"""
    record = await medical_record_service.get(db, record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Medical record not found"
        )

    record_detail = MedicalRecordDetail.from_orm(record)
    record_detail.created_by_name = (
        f"{record.creator.first_name} {record.creator.last_name}"
    )

    return record_detail


@router.get(
    "/{record_id}/download",
    summary="Download medical record file",
    description="Download medical record file attachment",
)
async def download_medical_record(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Download medical record file endpoint"""
    file_data = await medical_record_service.get_file_data(db, record_id)
    if not file_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    # Return file data (implementation depends on storage strategy)
    return {"message": "File download endpoint - implement based on storage"}
