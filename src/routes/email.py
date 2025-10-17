# src/routes/email.py (Updated)
from fastapi import (
    APIRouter,
    Depends,
    status,
    HTTPException,
    BackgroundTasks,
    Query,
    Request,
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Any
from uuid import UUID

from db.database import get_db
from schemas.email_schemas import EmailRequest, BulkEmailRequest, EmailResponse
from services.email_service import email_service
from services.email_integration_service import email_integration_service
from services.appointment_service import appointment_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

logger = setup_logger("EMAIL_ROUTES")

router = APIRouter(prefix="/email", tags=["email"])


@router.post(
    "/send",
    response_model=EmailResponse,
    summary="Send email",
    description="Send a single email using templates",
)
@limiter.limit("10/minute")
async def send_email(
    request: Request,
    email_request: EmailRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send email endpoint with rate limiting"""
    if current_user.role not in ["admin", "manager", "receptionist"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to send emails",
        )

    # Validate email addresses
    for email in email_request.to:
        if not await email_service.verify_email(email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid email address: {email}",
            )

    response = await email_service.send_email(email_request)

    # Log email sending
    logger.info(f"Email sent by {current_user.email} to {email_request.to}")

    return response


@router.post(
    "/send-bulk",
    summary="Send bulk emails",
    description="Send multiple emails with rate limiting and background processing",
)
@limiter.limit("5/minute")
async def send_bulk_emails(
    request: Request,
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

    # Process in background to avoid timeout
    background_tasks.add_task(process_bulk_emails, bulk_request, current_user.email)

    return {
        "message": "Bulk email processing started in background",
        "total_emails": len(bulk_request.emails),
        "batch_size": bulk_request.batch_size,
    }


async def process_bulk_emails(bulk_request: BulkEmailRequest, user_email: str):
    """Process bulk emails in background"""
    try:
        results = await email_service.send_bulk_emails(bulk_request)

        success_count = sum(1 for r in results if r.success)
        failure_count = len(results) - success_count

        logger.info(
            f"Bulk email processing completed by {user_email}: "
            f"{success_count} successful, {failure_count} failed"
        )

    except Exception as e:
        logger.error(f"Bulk email processing failed: {e}")


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
        logger.info(
            f"Appointment confirmation sent for {appointment_id} by {current_user.email}"
        )
        return {"message": "Appointment confirmation email sent successfully"}
    else:
        logger.error(f"Failed to send appointment confirmation for {appointment_id}")
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
    days_ahead: int = Query(1, ge=1, le=7, description="Days ahead to send reminders"),
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

    logger.info(
        f"Appointment reminders scheduled for {days_ahead} days ahead by {current_user.email}"
    )

    return {
        "message": "Appointment reminder process started in background",
        "days_ahead": days_ahead,
    }


@router.post(
    "/appointments/reminders/auto",
    summary="Auto-send appointment reminders",
    description="Automatically send reminders for tomorrow's appointments",
)
async def auto_send_appointment_reminders(
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Auto-send appointment reminders endpoint (for scheduled tasks)"""
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to auto-send reminders",
        )

    # Run in background
    background_tasks.add_task(appointment_service.send_reminders_for_tomorrow, db)

    return {"message": "Auto-reminder process started in background"}


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
        logger.info(
            f"Welcome email sent to patient {patient_id} by {current_user.email}"
        )
        return {"message": "Welcome email sent successfully"}
    else:
        logger.error(f"Failed to send welcome email to patient {patient_id}")
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
        logger.info(f"Invoice email sent for {invoice_id} by {current_user.email}")
        return {"message": "Invoice email sent successfully"}
    else:
        logger.error(f"Failed to send invoice email for {invoice_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send invoice email",
        )


@router.get(
    "/templates",
    summary="List email templates",
    description="Get list of available email templates with descriptions",
)
async def list_email_templates(
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List email templates endpoint"""
    templates = []
    for email_type, config in email_service.template_configs.items():
        templates.append(
            {
                "type": email_type.value,
                "name": config["template"],
                "subject": config["subject"],
                "description": f"Template for {email_type.value.replace('_', ' ')}",
            }
        )

    return {"templates": templates}


@router.get(
    "/stats",
    summary="Get email statistics",
    description="Get email sending statistics",
)
async def get_email_stats(
    days: int = Query(30, ge=1, le=365, description="Number of days to include"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get email statistics endpoint"""
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view email statistics",
        )

    # This would typically query your email logs database
    # For now, return mock data
    return {
        "period_days": days,
        "total_sent": 150,
        "success_rate": 95.2,
        "emails_by_type": {
            "appointment_confirmation": 45,
            "appointment_reminder": 60,
            "welcome_email": 25,
            "invoice": 20,
        },
    }
