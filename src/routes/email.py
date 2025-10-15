# src/routes/email.py
from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, any
from uuid import UUID

from db.database import get_db
from schemas.email_schemas import EmailRequest, BulkEmailRequest, EmailResponse
from services.email_service import email_service
from services.email_integration_service import email_integration_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/email", tags=["email"])


@router.post(
    "/send",
    response_model=EmailResponse,
    summary="Send email",
    description="Send a single email using templates",
)
async def send_email(
    email_request: EmailRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send email endpoint"""
    # Only allow specific roles to send emails
    if current_user.role not in ["admin", "manager", "receptionist"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to send emails",
        )

    response = await email_service.send_email(email_request)
    return response


@router.post(
    "/send-bulk",
    summary="Send bulk emails",
    description="Send multiple emails with rate limiting",
)
async def send_bulk_emails(
    bulk_request: BulkEmailRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send bulk emails endpoint"""
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to send bulk emails",
        )

    results = await email_service.send_bulk_emails(bulk_request)
    return {
        "total_emails": len(results),
        "success_count": sum(1 for r in results if r.success),
        "failure_count": sum(1 for r in results if not r.success),
        "results": results,
    }


@router.post(
    "/appointments/{appointment_id}/confirm",
    summary="Send appointment confirmation",
    description="Send appointment confirmation email to patient",
)
async def send_appointment_confirmation(
    appointment_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send appointment confirmation endpoint"""
    success = await email_integration_service.send_appointment_confirmation_email(
        db, appointment_id
    )

    if success:
        return {"message": "Appointment confirmation email sent successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send appointment confirmation email",
        )


@router.post(
    "/appointments/reminders",
    summary="Send appointment reminders",
    description="Send appointment reminder emails for upcoming appointments",
)
async def send_appointment_reminders(
    days_ahead: int = 1,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send appointment reminders endpoint"""
    if current_user.role not in ["admin", "manager", "receptionist"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to send appointment reminders",
        )

    # Run in background
    background_tasks.add_task(
        email_integration_service.send_appointment_reminder_emails, db, days_ahead
    )

    return {"message": "Appointment reminder process started in background"}


@router.post(
    "/patients/{patient_id}/welcome",
    summary="Send welcome email",
    description="Send welcome email to new patient",
)
async def send_welcome_email(
    patient_id: UUID,
    temporary_password: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send welcome email endpoint"""
    success = await email_integration_service.send_welcome_email_to_patient(
        db, patient_id, temporary_password
    )

    if success:
        return {"message": "Welcome email sent successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send welcome email",
        )


@router.post(
    "/invoices/{invoice_id}/send",
    summary="Send invoice email",
    description="Send invoice email to patient",
)
async def send_invoice_email(
    invoice_id: UUID,
    invoice_url: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send invoice email endpoint"""
    success = await email_integration_service.send_invoice_email(
        db, invoice_id, invoice_url
    )

    if success:
        return {"message": "Invoice email sent successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send invoice email",
        )


@router.get(
    "/templates",
    summary="List email templates",
    description="Get list of available email templates",
)
async def list_email_templates(
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List email templates endpoint"""
    templates = list(email_service.template_configs.keys())
    return {"templates": templates}
