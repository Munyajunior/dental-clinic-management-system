# src/routes/treatment_templates.py
from fastapi import APIRouter, Depends, status, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID

from db.database import get_db
from schemas.treatment_schemas import (
    TreatmentTemplateT,
    TreatmentTemplateCreate,
    TreatmentTemplateUpdate,
    TreatmentTemplateSearch,
    TreatmentTemplateExport,
)
from services.treatment_template_service import treatment_template_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

logger = setup_logger("TREATMENT_TEMPLATE_ROUTES")

router = APIRouter(prefix="/treatment-templates", tags=["treatment-templates"])


@router.get(
    "/",
    response_model=List[TreatmentTemplateT],
    summary="List treatment templates",
    description="Get paginated list of treatment templates with filtering",
)
async def list_treatment_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    is_active: bool = Query(True, description="Filter by active status"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List treatment templates endpoint"""
    try:
        templates = await treatment_template_service.get_templates(
            db, category=category, is_active=is_active, skip=skip, limit=limit
        )

        # Convert to schema and add computed fields
        template_schemas = []
        for template in templates:
            schema = TreatmentTemplateT.from_orm(template)
            schema.items_count = len(template.template_items)
            if template.created_by_user:
                schema.created_by_name = f"{template.created_by_user.first_name} {template.created_by_user.last_name}"
            template_schemas.append(schema)

        return template_schemas

    except Exception as e:
        logger.error(f"Error listing treatment templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve treatment templates",
        )


@router.get(
    "/{template_id}",
    response_model=TreatmentTemplateT,
    summary="Get treatment template",
    description="Get treatment template details by ID",
)
async def get_treatment_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get treatment template by ID endpoint"""
    template = await treatment_template_service.get_template(db, template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment template not found"
        )

    try:
        schema = TreatmentTemplateT.from_orm(template)
        schema.items_count = len(template.template_items)
        if template.created_by_user:
            schema.created_by_name = f"{template.created_by_user.first_name} {template.created_by_user.last_name}"
        return schema

    except Exception as e:
        logger.error(f"Error formatting template details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve template details",
        )


@router.post(
    "/",
    response_model=TreatmentTemplateT,
    status_code=status.HTTP_201_CREATED,
    summary="Create treatment template",
    description="Create a new treatment template",
)
@limiter.limit("50/minute")
async def create_treatment_template(
    request: Request,
    template_data: TreatmentTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create treatment template endpoint"""
    try:
        template = await treatment_template_service.create_template(
            db, template_data, current_user.id
        )
        schema = TreatmentTemplateT.from_orm(template)
        schema.items_count = len(template.template_items)
        if template.created_by_user:
            schema.created_by_name = f"{template.created_by_user.first_name} {template.created_by_user.last_name}"
        return schema

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating treatment template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create treatment template",
        )


@router.put(
    "/{template_id}",
    response_model=TreatmentTemplateT,
    summary="Update treatment template",
    description="Update treatment template information and items",
)
@limiter.limit("100/minute")
async def update_treatment_template(
    request: Request,
    template_id: UUID,
    template_data: TreatmentTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update treatment template endpoint"""
    template = await treatment_template_service.update_template(
        db, template_id, template_data.dict()
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment template not found"
        )

    try:
        schema = TreatmentTemplateT.from_orm(template)
        schema.items_count = len(template.template_items)
        if template.created_by_user:
            schema.created_by_name = f"{template.created_by_user.first_name} {template.created_by_user.last_name}"
        return schema

    except Exception as e:
        logger.error(f"Error formatting updated template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update treatment template",
        )


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete treatment template",
    description="Soft delete a treatment template",
)
async def delete_treatment_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Delete treatment template endpoint"""
    success = await treatment_template_service.delete_template(db, template_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment template not found"
        )

    return {"message": "Treatment template deleted successfully"}


@router.post(
    "/{template_id}/duplicate",
    response_model=TreatmentTemplateT,
    summary="Duplicate treatment template",
    description="Duplicate an existing treatment template",
)
@limiter.limit("50/minute")
async def duplicate_treatment_template(
    request: Request,
    template_id: UUID,
    new_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Duplicate treatment template endpoint"""
    template = await treatment_template_service.duplicate_template(
        db, template_id, new_name, current_user.id
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Treatment template not found"
        )

    try:
        schema = TreatmentTemplateT.from_orm(template)
        schema.items_count = len(template.template_items)
        if template.created_by_user:
            schema.created_by_name = f"{template.created_by_user.first_name} {template.created_by_user.last_name}"
        return schema

    except Exception as e:
        logger.error(f"Error formatting duplicated template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to duplicate treatment template",
        )


@router.get(
    "/categories/list",
    summary="Get template categories",
    description="Get all unique template categories",
)
async def get_template_categories(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get template categories endpoint"""
    try:
        categories = await treatment_template_service.get_template_categories(db)
        return {"categories": categories}

    except Exception as e:
        logger.error(f"Error getting template categories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve template categories",
        )


@router.post(
    "/search",
    response_model=List[TreatmentTemplateT],
    summary="Search treatment templates",
    description="Search treatment templates by name or description",
)
@limiter.limit("100/minute")
async def search_treatment_templates(
    request: Request,
    search_data: TreatmentTemplateSearch,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Search treatment templates endpoint"""
    try:
        templates = await treatment_template_service.search_templates(
            db,
            search_data.query,
            search_data.category,
            search_data.skip,
            search_data.limit,
        )

        template_schemas = []
        for template in templates:
            schema = TreatmentTemplateT.from_orm(template)
            schema.items_count = len(template.template_items)
            if template.created_by_user:
                schema.created_by_name = f"{template.created_by_user.first_name} {template.created_by_user.last_name}"
            template_schemas.append(schema)

        return template_schemas

    except Exception as e:
        logger.error(f"Error searching treatment templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search treatment templates",
        )


@router.get(
    "/statistics/overview",
    summary="Get template statistics",
    description="Get overview statistics for treatment templates",
)
async def get_template_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get template statistics endpoint"""
    try:
        stats = await treatment_template_service.get_template_statistics(db)
        return stats

    except Exception as e:
        logger.error(f"Error getting template statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve template statistics",
        )


@router.get(
    "/export/",
    summary="Export treatment templates",
    description="Export treatment templates to various formats",
)
async def export_treatment_templates(
    format: str = Query("json", description="Export format: json, csv"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Export treatment templates endpoint"""
    try:
        export_data = await treatment_template_service.export_templates(
            db, format, category
        )
        return export_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting treatment templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export treatment templates",
        )


@router.post(
    "/from-treatment/{treatment_id}",
    response_model=TreatmentTemplateT,
    summary="Create template from treatment",
    description="Create a treatment template from an existing treatment",
)
@limiter.limit("50/minute")
async def create_template_from_treatment(
    request: Request,
    treatment_id: UUID,
    template_name: str,
    category: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create template from treatment endpoint"""
    try:
        template = await treatment_template_service.create_template_from_treatment(
            db, treatment_id, template_name, category, current_user.id
        )
        schema = TreatmentTemplateT.from_orm(template)
        schema.items_count = len(template.template_items)
        if template.created_by_user:
            schema.created_by_name = f"{template.created_by_user.first_name} {template.created_by_user.last_name}"
        return schema

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating template from treatment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create template from treatment",
        )
