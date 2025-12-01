# src/routes/treatments.py
from fastapi import (
    APIRouter,
    Depends,
    status as http_status,
    HTTPException,
    Query,
    BackgroundTasks,
    Request,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional, Any, Dict
from uuid import UUID
from datetime import datetime, timedelta
import json

from db.database import get_db
from models.patient import Patient
from schemas.treatment_schemas import (
    TreatmentCreate,
    TreatmentUpdate,
    TreatmentPublic,
    TreatmentDetail,
    TreatmentProgressNote,
    TreatmentItemCreate,
    TreatmentItemPublic,
    TreatmentSearch,
    TreatmentBulkUpdate,
    TreatmentExport,
    TreatmentAnalytics,
    TreatmentTemplate,
)
from models.treatment_item import TreatmentItem
from services.treatment_service import treatment_service
from services.treatment_template_service import treatment_template_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

logger = setup_logger("TREATMENT_ROUTES")

router = APIRouter(prefix="/treatments", tags=["treatments"])


@router.get(
    "/",
    response_model=List[TreatmentPublic],
    summary="List treatments",
    description="Get paginated list of treatments with filtering options",
)
@limiter.limit("100/minute")
async def list_treatments(
    request: Request,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=1000, description="Number of records to return"),
    patient_id: Optional[UUID] = Query(None, description="Filter by patient ID"),
    dentist_id: Optional[UUID] = Query(None, description="Filter by dentist ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    query: Optional[str] = Query(
        None, description="Search query for treatment name, patient or dentist"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List treatments with comprehensive filtering"""
    try:
        filters = {}
        if patient_id:
            filters["patient_id"] = patient_id
        if dentist_id:
            filters["dentist_id"] = dentist_id
        if status:
            filters["status"] = status
        if priority:
            filters["priority"] = priority

        treatments = await treatment_service.get_multi(
            db, skip=skip, limit=limit, filters=filters, search_query=query
        )

        treatment_list = []
        for treatment in treatments:
            treatment_public = TreatmentPublic.from_orm(treatment)
            # Add names to reponse
            treatment_public.dentist_name = (
                f"{treatment.dentist.first_name} {treatment.dentist.last_name}"
            )
            treatment_public.patient_name = (
                f"{treatment.patient.first_name} {treatment.patient.last_name}"
            )
            treatment_list.append(treatment_public)

        return treatment_list

    except Exception as e:
        logger.error(f"Error listing treatments: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve treatments",
        )


@router.post(
    "/",
    response_model=TreatmentPublic,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create treatment",
    description="Create a new treatment plan with items",
)
@limiter.limit("50/minute")
async def create_treatment(
    request: Request,
    treatment_data: TreatmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create treatment endpoint"""
    try:
        treatment_data.tenant_id = current_user.tenant_id
        treatment = await treatment_service.create_treatment(
            db, treatment_data, current_user
        )
        return TreatmentPublic.from_orm(treatment)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating treatment: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create treatment",
        )


@router.get(
    "/{treatment_id}",
    response_model=TreatmentDetail,
    summary="Get treatment",
    description="Get treatment details by ID including patient and dentist information",
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
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )

    try:
        treatment_detail = TreatmentDetail.from_orm(treatment)

        # Add names for better frontend display
        treatment_detail.dentist_name = (
            f"{treatment.dentist.first_name} {treatment.dentist.last_name}"
        )
        treatment_detail.patient_name = (
            f"{treatment.patient.first_name} {treatment.patient.last_name}"
        )

        return treatment_detail

    except Exception as e:
        logger.error(f"Error formatting treatment details: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve treatment details",
        )


@router.put(
    "/{treatment_id}",
    response_model=TreatmentPublic,
    summary="Update treatment",
    description="Update treatment information and items",
)
@limiter.limit("100/minute")
async def update_treatment(
    request: Request,
    treatment_id: UUID,
    treatment_data: TreatmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update treatment endpoint"""
    treatment = await treatment_service.update(db, treatment_id, treatment_data)
    if not treatment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )
    return TreatmentPublic.from_orm(treatment)


@router.delete(
    "/{treatment_id}",
    status_code=http_status.HTTP_200_OK,
    summary="Delete treatment",
    description="Soft delete a treatment plan",
)
async def delete_treatment(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Delete treatment endpoint"""
    try:
        success = await treatment_service.delete(db, treatment_id)
        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )

        return {"message": "Treatment deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting treatment: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete treatment",
        )


@router.post(
    "/{treatment_id}/progress",
    response_model=TreatmentPublic,
    summary="Add progress note",
    description="Add progress note to treatment",
)
@limiter.limit("200/minute")
async def add_progress_note(
    request: Request,
    treatment_id: UUID,
    progress_note: TreatmentProgressNote,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Add progress note endpoint"""
    try:
        treatment = await treatment_service.add_progress_note(
            db, treatment_id, progress_note, current_user.id
        )
        if not treatment:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )
        return TreatmentPublic.from_orm(treatment)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding progress note: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add progress note",
        )


@router.get(
    "/{treatment_id}/progress",
    response_model=List[Dict[str, Any]],
    summary="Get progress notes",
    description="Get all progress notes for a treatment",
)
async def get_progress_notes(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get progress notes endpoint"""
    try:
        treatment = await treatment_service.get(db, treatment_id)
        if not treatment:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )

        progress_notes = treatment.progress_notes or []

        # Enhance progress notes with user names if available
        enhanced_notes = []
        for note in progress_notes:
            enhanced_note = note.copy()

            # Try to get user name if we have a recorded_by ID
            recorded_by = note.get("recorded_by")
            if recorded_by:
                try:
                    from models.user import User

                    user_result = await db.execute(
                        select(User).where(User.id == UUID(recorded_by))
                    )
                    user = user_result.scalar_one_or_none()
                    if user:
                        enhanced_note["recorded_by_name"] = (
                            f"{user.first_name} {user.last_name}"
                        )
                except Exception as e:
                    logger.debug(f"Could not fetch user for progress note: {e}")
                    enhanced_note["recorded_by_name"] = "Unknown"

            enhanced_notes.append(enhanced_note)

        return enhanced_notes

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting progress notes: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve progress notes",
        )


@router.post(
    "/{treatment_id}/items",
    response_model=TreatmentPublic,
    summary="Add treatment item",
    description="Add item to treatment plan",
)
@limiter.limit("200/minute")
async def add_treatment_item(
    request: Request,
    treatment_id: UUID,
    item_data: TreatmentItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Add treatment item endpoint"""
    treatment = await treatment_service.add_treatment_item(db, treatment_id, item_data)
    if not treatment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )
    return TreatmentPublic.from_orm(treatment)


@router.post(
    "/{treatment_id}/items/bulk",
    response_model=List[TreatmentItemPublic],
    summary="Bulk create treatment items",
    description="Create multiple treatment items for a treatment",
)
@limiter.limit("100/minute")
async def bulk_create_treatment_items(
    request: Request,
    treatment_id: UUID,
    items_data: List[TreatmentItemCreate],
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Bulk create treatment items endpoint"""
    try:
        treatment = await treatment_service.get(db, treatment_id)
        if not treatment:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )

        created_items = []
        for item_data in items_data:
            treatment_item = await treatment_service.add_treatment_item(
                db, treatment_id, item_data
            )
            if treatment_item:
                # Get the created item with service details
                item_result = await db.execute(
                    select(TreatmentItem)
                    .options(selectinload(TreatmentItem.service))
                    .where(TreatmentItem.id == treatment_item.id)
                )
                item_with_service = item_result.scalar_one_or_none()
                if item_with_service:
                    created_items.append(item_with_service)

        return [TreatmentItemPublic.from_orm(item) for item in created_items]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk creating treatment items: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create treatment items",
        )


@router.get(
    "/{treatment_id}/items",
    response_model=List[TreatmentItemPublic],
    summary="Get treatment items",
    description="Get all treatment items for a treatment",
)
async def get_treatment_items(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get treatment items endpoint"""
    try:
        items = await treatment_service.get_treatment_items(db, treatment_id)

        # Convert to public schema with service details
        treatment_items_public = []
        for item in items:
            # Create the public schema instance
            item_public = TreatmentItemPublic(
                id=item.id,
                treatment_id=item.treatment_id,
                service_id=item.service_id,
                service_name=item.service.name if item.service else "Unknown Service",
                service_code=item.service.code if item.service else "N/A",
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                status=item.status,
                tooth_number=item.tooth_number,
                surface=item.surface,
                notes=item.notes,
                created_at=item.created_at,
                completed_at=item.completed_at,
            )
            treatment_items_public.append(item_public)

        return treatment_items_public

    except Exception as e:
        logger.error(f"Error getting treatment items: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve treatment items",
        )


@router.patch(
    "/{treatment_id}/status/{status}",
    response_model=TreatmentPublic,
    summary="Update treatment status",
    description="Update treatment status (planned, in_progress, completed, cancelled, postponed)",
)
@limiter.limit("100/minute")
async def update_treatment_status(
    request: Request,
    treatment_id: UUID,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update treatment status endpoint"""
    treatment = await treatment_service.update_status(db, treatment_id, status)
    if not treatment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
        )
    return TreatmentPublic.from_orm(treatment)


@router.get(
    "/{treatment_id}/cost",
    summary="Calculate treatment cost",
    description="Calculate detailed cost breakdown for treatment",
)
async def calculate_treatment_cost(
    treatment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Calculate treatment cost endpoint"""
    try:
        cost_data = await treatment_service.calculate_treatment_cost(db, treatment_id)
        return cost_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating treatment cost: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate treatment cost",
        )


@router.post(
    "/search",
    response_model=List[TreatmentPublic],
    summary="Search treatments",
    description="Search treatments by name, patient name, or dentist name",
)
@limiter.limit("100/minute")
async def search_treatments(
    request: Request,
    search_data: TreatmentSearch,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Search treatments endpoint"""
    try:
        treatments = await treatment_service.search_treatments(
            db, search_data.query, skip=search_data.skip, limit=search_data.limit
        )
        return [TreatmentPublic.from_orm(treatment) for treatment in treatments]

    except Exception as e:
        logger.error(f"Error searching treatments: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search treatments",
        )


@router.post(
    "/{treatment_id}/duplicate",
    response_model=TreatmentPublic,
    summary="Duplicate treatment",
    description="Duplicate an existing treatment plan",
)
@limiter.limit("50/minute")
async def duplicate_treatment(
    request: Request,
    treatment_id: UUID,
    new_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Duplicate treatment endpoint"""
    try:
        treatment = await treatment_service.duplicate_treatment(
            db, treatment_id, new_name, current_user.id
        )
        if not treatment:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Treatment not found"
            )
        return TreatmentPublic.from_orm(treatment)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error duplicating treatment: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to duplicate treatment",
        )


@router.get(
    "/statistics/overview",
    summary="Get treatment statistics",
    description="Get overview statistics for treatments",
)
async def get_treatment_statistics(
    days: int = Query(
        30, ge=1, le=365, description="Number of days to include in statistics"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get treatment statistics endpoint"""
    try:
        stats = await treatment_service.get_treatment_statistics(db, days)
        return stats

    except Exception as e:
        logger.error(f"Error getting treatment statistics: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve treatment statistics",
        )


@router.post(
    "/bulk/update",
    summary="Bulk update treatments",
    description="Update multiple treatments in a single operation",
)
@limiter.limit("50/minute")
async def bulk_update_treatments(
    request: Request,
    bulk_data: TreatmentBulkUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Bulk update treatments endpoint"""
    try:
        results = await treatment_service.bulk_update_treatments(
            db, bulk_data.updates, current_user.id
        )
        return results

    except Exception as e:
        logger.error(f"Error in bulk update: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to perform bulk update",
        )


@router.get(
    "/analytics/overview",
    response_model=TreatmentAnalytics,
    summary="Get treatment analytics",
    description="Get comprehensive analytics for treatments",
)
async def get_treatment_analytics(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    group_by: str = Query("month", description="Group by day, week, or month"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get treatment analytics endpoint"""
    try:
        analytics = await treatment_service.get_treatment_analytics(
            db, start_date, end_date, group_by
        )
        return analytics

    except Exception as e:
        logger.error(f"Error getting treatment analytics: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve treatment analytics",
        )


@router.get(
    "/dentists/{dentist_id}/statistics",
    summary="Get dentist treatment statistics",
    description="Get treatment statistics for a specific dentist",
)
async def get_dentist_treatment_statistics(
    dentist_id: UUID,
    months: int = Query(12, ge=1, le=60, description="Number of months to include"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get dentist treatment statistics endpoint"""
    try:
        stats = await treatment_service.get_dentist_treatment_stats(
            db, dentist_id, months
        )
        return stats

    except Exception as e:
        logger.error(f"Error getting dentist statistics: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dentist statistics",
        )


@router.get(
    "/patients/{patient_id}/can-create-treatment",
    summary="Check if user can create treatment for patient",
    description="Check if current user is authorized to create treatment for specified patient",
)
async def can_create_treatment_for_patient(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Dict[str, Any]:
    """Check if user can create treatment for patient"""
    try:
        # Verify patient exists
        patient_result = await db.execute(
            select(Patient).where(Patient.id == patient_id)
        )
        patient = patient_result.scalar_one_or_none()

        if not patient:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Patient not found"
            )

        # Check authorization using the same logic as treatment creation
        can_create = await treatment_service._can_user_create_treatment(
            db, current_user, patient
        )

        return {
            "can_create": can_create,
            "patient_id": patient_id,
            "user_id": current_user.id,
            "user_role": current_user.role.value,
            "patient_assigned_to": patient.assigned_dentist_id,
        }

    except Exception as e:
        logger.error(f"Error checking treatment creation authorization: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check treatment creation authorization",
        )


# ===== TREATMENT TEMPLATES ENDPOINTS =====


@router.get(
    "/templates/",
    response_model=List[TreatmentTemplate],
    summary="List treatment templates",
    description="Get available treatment templates",
)
async def list_treatment_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List treatment templates endpoint"""
    try:
        templates = await treatment_template_service.get_templates(db, category)
        return [TreatmentTemplate.from_orm(template) for template in templates]

    except Exception as e:
        logger.error(f"Error listing treatment templates: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve treatment templates",
        )


@router.post(
    "/templates/",
    response_model=TreatmentTemplate,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create treatment template",
    description="Create a new treatment template",
)
async def create_treatment_template(
    template_data: TreatmentTemplate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create treatment template endpoint"""
    try:
        template = await treatment_template_service.create_template(db, template_data)
        return TreatmentTemplate.from_orm(template)

    except Exception as e:
        logger.error(f"Error creating treatment template: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create treatment template",
        )


@router.post(
    "/from-template/{template_id}",
    response_model=TreatmentPublic,
    summary="Create treatment from template",
    description="Create a new treatment plan from a template",
)
async def create_treatment_from_template(
    template_id: UUID,
    patient_id: UUID,
    dentist_id: UUID,
    customizations: Optional[Dict[str, Any]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create treatment from template endpoint"""
    try:
        treatment = await treatment_service.create_treatment_from_template(
            db, template_id, patient_id, dentist_id, customizations
        )
        return TreatmentPublic.from_orm(treatment)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating treatment from template: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create treatment from template",
        )


# ===== EXPORT ENDPOINTS =====


@router.get(
    "/export/",
    summary="Export treatments",
    description="Export treatments to various formats",
)
async def export_treatments(
    format: str = Query("csv", description="Export format: csv, json, excel"),
    start_date: Optional[str] = Query(None, description="Start date for filtering"),
    end_date: Optional[str] = Query(None, description="End date for filtering"),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Export treatments endpoint"""
    try:
        filters = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date
        if status:
            filters["status"] = status
        if priority:
            filters["priority"] = priority

        export_data = await treatment_service.export_treatments(
            db, format, filters, current_user.id
        )

        return export_data

    except Exception as e:
        logger.error(f"Error exporting treatments: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export treatments",
        )


# ===== DASHBOARD ENDPOINTS =====


@router.get(
    "/dashboard/overview",
    summary="Get dashboard overview",
    description="Get treatment data for dashboard display",
)
async def get_treatment_dashboard_overview(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get treatment dashboard overview"""
    try:
        overview = await treatment_service.get_dashboard_overview(db)
        return overview

    except Exception as e:
        logger.error(f"Error getting dashboard overview: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard overview",
        )


@router.get(
    "/dashboard/upcoming",
    summary="Get upcoming treatments",
    description="Get treatments scheduled to start soon",
)
async def get_upcoming_treatments(
    days: int = Query(7, ge=1, le=30, description="Number of days to look ahead"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get upcoming treatments endpoint"""
    try:
        treatments = await treatment_service.get_upcoming_treatments(db, days)
        return [TreatmentPublic.from_orm(treatment) for treatment in treatments]

    except Exception as e:
        logger.error(f"Error getting upcoming treatments: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve upcoming treatments",
        )
