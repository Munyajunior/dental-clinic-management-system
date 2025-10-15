# src/routes/appointments.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from datetime import date
from db.database import get_db
from schemas.appointment_schemas import (
    AppointmentCreate,
    AppointmentUpdate,
    AppointmentPublic,
    AppointmentDetail,
    AppointmentSearch,
    AppointmentSlot,
    AppointmentStatusUpdate,
)
from services.appointment_service import appointment_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get(
    "/",
    response_model=List[AppointmentPublic],
    summary="List appointments",
    description="Get list of appointments with search and filters",
)
async def list_appointments(
    skip: int = 0,
    limit: int = 50,
    dentist_id: Optional[UUID] = Query(None, description="Filter by dentist"),
    patient_id: Optional[UUID] = Query(None, description="Filter by patient"),
    status: Optional[str] = Query(None, description="Filter by status"),
    appointment_type: Optional[str] = Query(None, description="Filter by type"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List appointments endpoint"""
    search_params = AppointmentSearch(
        dentist_id=dentist_id,
        patient_id=patient_id,
        status=status,
        appointment_type=appointment_type,
        date_from=date_from,
        date_to=date_to,
    )
    appointments = await appointment_service.search_appointments(
        db, search_params, skip, limit
    )
    return [AppointmentPublic.from_orm(appointment) for appointment in appointments]


@router.post(
    "/",
    response_model=AppointmentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create appointment",
    description="Create a new appointment with conflict checking",
)
async def create_appointment(
    appointment_data: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create appointment endpoint"""
    appointment = await appointment_service.create_appointment(db, appointment_data)
    return AppointmentPublic.from_orm(appointment)


@router.get(
    "/{appointment_id}",
    response_model=AppointmentDetail,
    summary="Get appointment",
    description="Get appointment details by ID",
)
async def get_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get appointment by ID endpoint"""
    appointment = await appointment_service.get(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found"
        )

    # Include related data
    appointment_detail = AppointmentDetail.from_orm(appointment)
    # Add dentist and patient names
    appointment_detail.dentist_name = (
        f"{appointment.dentist.first_name} {appointment.dentist.last_name}"
    )
    appointment_detail.patient_name = (
        f"{appointment.patient.first_name} {appointment.patient.last_name}"
    )
    appointment_detail.patient_contact = appointment.patient.contact_number

    return appointment_detail


@router.put(
    "/{appointment_id}",
    response_model=AppointmentPublic,
    summary="Update appointment",
    description="Update appointment information",
)
async def update_appointment(
    appointment_id: UUID,
    appointment_data: AppointmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update appointment endpoint"""
    appointment = await appointment_service.update(db, appointment_id, appointment_data)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found"
        )
    return AppointmentPublic.from_orm(appointment)


@router.patch(
    "/{appointment_id}/status",
    response_model=AppointmentPublic,
    summary="Update appointment status",
    description="Update appointment status (confirm, complete, cancel, etc.)",
)
async def update_appointment_status(
    appointment_id: UUID,
    status_data: AppointmentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update appointment status endpoint"""
    appointment = await appointment_service.update_status(
        db, appointment_id, status_data.status, status_data.cancellation_reason
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found"
        )
    return AppointmentPublic.from_orm(appointment)


@router.get(
    "/slots/available",
    response_model=List[AppointmentSlot],
    summary="Get available slots",
    description="Get available appointment slots for a dentist on a specific date",
)
async def get_available_slots(
    dentist_id: UUID,
    date: date,
    duration_minutes: int = Query(
        30, ge=15, le=240, description="Slot duration in minutes"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get available slots endpoint"""
    slots = await appointment_service.get_available_slots(
        db, dentist_id, date, duration_minutes
    )
    return slots


@router.get(
    "/upcoming/{days}",
    response_model=List[AppointmentPublic],
    summary="Get upcoming appointments",
    description="Get upcoming appointments within the next N days",
)
async def get_upcoming_appointments(
    days: int = Query(7, ge=1, le=30, description="Number of days to look ahead"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get upcoming appointments endpoint"""
    appointments = await appointment_service.get_upcoming_appointments(db, days)
    return [AppointmentPublic.from_orm(appointment) for appointment in appointments]


@router.delete(
    "/{appointment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel appointment",
    description="Cancel appointment (soft delete by updating status)",
)
async def cancel_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> None:
    """Cancel appointment endpoint"""
    status_data = AppointmentStatusUpdate(status="cancelled")
    appointment = await appointment_service.update_status(
        db, appointment_id, status_data.status
    )
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found"
        )
