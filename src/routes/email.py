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
from sqlalchemy.future import select
from typing import Optional, Any, Dict
from pydantic import EmailStr
from uuid import UUID

from db.database import get_db
from schemas.email_schemas import (
    EmailRequest,
    BulkEmailRequest,
    EmailResponse,
    HealthCheckResponse,
    TestEmailRequest,
    TestEmailResponse,
)
from models.user import User
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
    "/staff/{staff_id}/welcome",
    summary="Send welcome email to staff",
    description="Send welcome email to new staff member with credentials",
)
async def send_welcome_staff_email(
    staff_id: UUID,
    temporary_password: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Send welcome email to staff endpoint"""
    # Only admins and managers can send staff welcome emails
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to send staff welcome emails",
        )

    # Check if the staff member exists and belongs to the same tenant
    staff_result = await db.execute(
        select(User).where(
            User.id == staff_id, User.tenant_id == current_user.tenant_id
        )
    )
    staff_user = staff_result.scalar_one_or_none()

    if not staff_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staff member not found",
        )

    # Send welcome email
    success = await email_integration_service.send_welcome_email_to_staff(
        db, staff_id, temporary_password
    )

    if success:
        logger.info(f"Welcome email sent to staff {staff_id} by {current_user.email}")
        return {
            "message": "Staff welcome email sent successfully",
            "staff_email": staff_user.email,
            "staff_name": f"{staff_user.first_name} {staff_user.last_name}",
        }
    else:
        logger.error(f"Failed to send welcome email to staff {staff_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send staff welcome email",
        )


@router.post(
    "/preview",
    summary="Preview email template",
    description="Render email template with data for preview without sending",
)
async def preview_email_template(
    preview_request: Dict[str, Any],
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Preview email template with data"""
    try:
        template_name = preview_request.get("template_name")
        template_data = preview_request.get("template_data", {})

        if not template_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Template name is required",
            )

        # Render the template to generate preview
        html_content, text_content = email_service.template_manager.render_template(
            template_name, template_data
        )

        return {
            "success": True,
            "preview": {
                "html": html_content,
                "text": text_content,
                "template_name": template_name,
                "template_data": template_data,
            },
        }
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template not found: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Template preview error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview template: {str(e)}",
        )


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


# Testing
@router.get("/health", response_model=HealthCheckResponse)
async def email_health_check():
    """Check email service health and connectivity"""
    connectivity = await email_service.check_connectivity()
    health_verification = await email_service.verify_service_health()

    # Count available templates
    template_health = health_verification.get("template_health", {})
    available_templates = sum(
        1 for template in template_health.values() if template.get("exists", False)
    )

    return HealthCheckResponse(
        service="resend",
        status=health_verification.get("service_status", "unknown"),
        dns_resolution=connectivity.get("dns_resolution", False),
        api_key_configured=health_verification.get("configuration", {}).get(
            "api_key_configured", False
        ),
        templates_available=available_templates,
        consecutive_failures=connectivity.get("consecutive_failures", 0),
        last_success=connectivity.get("last_success"),
        details=health_verification,
    )


@router.post("/test", response_model=TestEmailResponse)
async def send_test_email(
    test_request: TestEmailRequest, background_tasks: BackgroundTasks
):
    """Send a test email to verify email service functionality"""
    try:
        logger.info(f"Received test email request for {test_request.email}")

        # Send test email
        response = await email_service.send_test_email(
            to_email=test_request.email,
            test_type=test_request.test_type,
            test_tenant=True,
        )

        if response.success:
            return TestEmailResponse(
                success=True,
                message=f"Test email sent successfully to {test_request.email}",
                test_id=response.message_id,
                details={
                    "recipient": test_request.email,
                    "test_type": test_request.test_type,
                    "message_id": response.message_id,
                    "service_used": "resend",
                },
            )
        else:
            return TestEmailResponse(
                success=False,
                message="Failed to send test email",
                error=response.error,
                details={
                    "recipient": test_request.email,
                    "test_type": test_request.test_type,
                    "error_details": response.error,
                },
            )

    except Exception as e:
        logger.error(f"Test email endpoint failed: {e}")
        return TestEmailResponse(
            success=False,
            message="Internal server error during test email",
            error=str(e),
        )


@router.post("/test-bulk")
async def send_bulk_test_emails(
    emails: list[EmailStr], background_tasks: BackgroundTasks
):
    """Send test emails to multiple addresses"""
    results = []

    for email in emails:
        try:
            response = await email_service.send_test_email(
                to_email=email, test_type="bulk_test"
            )

            results.append(
                {
                    "email": email,
                    "success": response.success,
                    "message_id": response.message_id if response.success else None,
                    "error": response.error if not response.success else None,
                }
            )

        except Exception as e:
            results.append({"email": email, "success": False, "error": str(e)})

    return {
        "total_emails": len(emails),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results,
    }


@router.get("/test/templates")
async def list_email_templates_testing():
    """List all available email templates and their status"""
    health_verification = await email_service.verify_service_health()
    template_health = health_verification.get("template_health", {})

    return {
        "total_templates": len(template_health),
        "available_templates": [
            {
                "type": template_type,
                "template_name": details["template"],
                "subject": details["subject"],
                "exists": details["exists"],
            }
            for template_type, details in template_health.items()
            if details["exists"]
        ],
        "missing_templates": [
            {
                "type": template_type,
                "template_name": details["template"],
                "subject": details["subject"],
            }
            for template_type, details in template_health.items()
            if not details["exists"]
        ],
    }


@router.get("/configuration")
async def get_email_configuration():
    """Get current email service configuration (without sensitive data)"""
    health_verification = await email_service.verify_service_health()
    config = health_verification.get("configuration", {})

    return {
        "from_email": config.get("from_email"),
        "from_name": config.get("from_name"),
        "send_emails_enabled": config.get("send_emails_enabled"),
        "log_emails_enabled": config.get("log_emails_enabled"),
        "api_key_configured": config.get("api_key_configured"),
        "service_status": health_verification.get("service_status"),
    }
