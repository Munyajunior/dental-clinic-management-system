# src/services/treatment_template_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from models.treatment_template import TreatmentTemplate, TreatmentTemplateItem
from models.user import User
from schemas.treatment_schemas import TreatmentTemplate as TreatmentTemplateSchema
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("TREATMENT_TEMPLATE_SERVICE")


class TreatmentTemplateService(BaseService):
    def __init__(self):
        super().__init__(TreatmentTemplate)

    async def get_templates(
        self,
        db: AsyncSession,
        category: Optional[str] = None,
        is_active: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[TreatmentTemplate]:
        """Get treatment templates with optional filtering"""
        try:
            query = select(TreatmentTemplate).options(
                selectinload(TreatmentTemplate.template_items),
                selectinload(TreatmentTemplate.created_by_user),
            )

            conditions = []
            if category:
                conditions.append(TreatmentTemplate.category == category)
            if is_active is not None:
                conditions.append(TreatmentTemplate.is_active == is_active)

            if conditions:
                query = query.where(and_(*conditions))

            query = query.offset(skip).limit(limit).order_by(TreatmentTemplate.name)

            result = await db.execute(query)
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error getting treatment templates: {e}")
            return []

    async def get_template(
        self, db: AsyncSession, template_id: UUID
    ) -> Optional[TreatmentTemplate]:
        """Get a single treatment template by ID with all related data"""
        try:
            result = await db.execute(
                select(TreatmentTemplate)
                .options(
                    selectinload(TreatmentTemplate.template_items),
                    selectinload(TreatmentTemplate.created_by_user),
                )
                .where(TreatmentTemplate.id == template_id)
            )
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"Error getting treatment template {template_id}: {e}")
            return None

    async def create_template(
        self, db: AsyncSession, template_data: TreatmentTemplateSchema, created_by: UUID
    ) -> TreatmentTemplate:
        """Create a new treatment template"""
        try:
            # Validate template data
            validation_result = await self._validate_template_data(
                db, template_data.dict()
            )
            if not validation_result["is_valid"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid template data: {', '.join(validation_result['errors'])}",
                )

            # Create template
            template_dict = template_data.dict(
                exclude={"id", "template_items", "created_by"}
            )
            template = TreatmentTemplate(**template_dict, created_by=created_by)
            db.add(template)
            await db.flush()  # Get the template ID

            # Create template items
            if template_data.template_items:
                for item_data in template_data.template_items:
                    template_item = TreatmentTemplateItem(
                        template_id=template.id,
                        service_id=item_data.get("service_id"),
                        quantity=item_data.get("quantity", 1),
                        tooth_number=item_data.get("tooth_number"),
                        surface=item_data.get("surface"),
                        notes=item_data.get("notes"),
                        order_index=item_data.get("order_index", 0),
                    )
                    db.add(template_item)

            await db.commit()
            await db.refresh(template)

            logger.info(
                f"Created new treatment template: {template.id} by user {created_by}"
            )
            return template

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating treatment template: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create treatment template",
            )

    async def update_template(
        self, db: AsyncSession, template_id: UUID, template_data: Dict[str, Any]
    ) -> Optional[TreatmentTemplate]:
        """Update an existing treatment template"""
        try:
            template = await self.get_template(db, template_id)
            if not template:
                return None

            # Update template fields
            update_fields = [
                "name",
                "description",
                "category",
                "estimated_cost",
                "estimated_duration",
                "is_active",
            ]

            for field in update_fields:
                if field in template_data:
                    setattr(template, field, template_data[field])

            # Update template items if provided
            if "template_items" in template_data:
                # Remove existing items
                await db.execute(
                    TreatmentTemplateItem.__table__.delete().where(
                        TreatmentTemplateItem.template_id == template_id
                    )
                )

                # Add new items
                for item_data in template_data["template_items"]:
                    template_item = TreatmentTemplateItem(
                        template_id=template_id,
                        service_id=item_data.get("service_id"),
                        quantity=item_data.get("quantity", 1),
                        tooth_number=item_data.get("tooth_number"),
                        surface=item_data.get("surface"),
                        notes=item_data.get("notes"),
                        order_index=item_data.get("order_index", 0),
                    )
                    db.add(template_item)

            template.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(template)

            logger.info(f"Updated treatment template: {template_id}")
            return template

        except Exception as e:
            await db.rollback()
            logger.error(f"Error updating treatment template {template_id}: {e}")
            return None

    async def delete_template(self, db: AsyncSession, template_id: UUID) -> bool:
        """Soft delete a treatment template"""
        try:
            template = await self.get(db, template_id)
            if not template:
                return False

            template.is_active = False
            template.updated_at = datetime.utcnow()

            await db.commit()
            logger.info(f"Soft deleted treatment template: {template_id}")
            return True

        except Exception as e:
            await db.rollback()
            logger.error(f"Error deleting treatment template {template_id}: {e}")
            return False

    async def duplicate_template(
        self, db: AsyncSession, template_id: UUID, new_name: str, created_by: UUID
    ) -> Optional[TreatmentTemplate]:
        """Duplicate an existing treatment template"""
        try:
            original_template = await self.get_template(db, template_id)
            if not original_template:
                return None

            # Create new template data
            template_data = {
                "name": new_name,
                "description": original_template.description,
                "category": original_template.category,
                "estimated_cost": original_template.estimated_cost,
                "estimated_duration": original_template.estimated_duration,
                "is_active": True,
            }

            # Create new template
            new_template = TreatmentTemplate(**template_data, created_by=created_by)
            db.add(new_template)
            await db.flush()

            # Duplicate template items
            for original_item in original_template.template_items:
                new_item = TreatmentTemplateItem(
                    template_id=new_template.id,
                    service_id=original_item.service_id,
                    quantity=original_item.quantity,
                    tooth_number=original_item.tooth_number,
                    surface=original_item.surface,
                    notes=original_item.notes,
                    order_index=original_item.order_index,
                )
                db.add(new_item)

            await db.commit()
            await db.refresh(new_template)

            logger.info(f"Duplicated template {template_id} to {new_template.id}")
            return new_template

        except Exception as e:
            await db.rollback()
            logger.error(f"Error duplicating treatment template: {e}")
            return None

    async def get_template_categories(self, db: AsyncSession) -> List[str]:
        """Get all unique template categories"""
        try:
            result = await db.execute(
                select(TreatmentTemplate.category)
                .where(TreatmentTemplate.is_active == True)
                .distinct()
                .order_by(TreatmentTemplate.category)
            )
            categories = [row[0] for row in result.all() if row[0]]
            return categories

        except Exception as e:
            logger.error(f"Error getting template categories: {e}")
            return []

    async def get_templates_by_category(
        self, db: AsyncSession, category: str
    ) -> List[TreatmentTemplate]:
        """Get all templates in a specific category"""
        try:
            result = await db.execute(
                select(TreatmentTemplate)
                .options(
                    selectinload(TreatmentTemplate.template_items),
                    selectinload(TreatmentTemplate.created_by_user),
                )
                .where(
                    and_(
                        TreatmentTemplate.category == category,
                        TreatmentTemplate.is_active == True,
                    )
                )
                .order_by(TreatmentTemplate.name)
            )
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error getting templates by category {category}: {e}")
            return []

    async def search_templates(
        self,
        db: AsyncSession,
        query: str,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[TreatmentTemplate]:
        """Search treatment templates by name or description"""
        try:
            search_conditions = or_(
                TreatmentTemplate.name.ilike(f"%{query}%"),
                TreatmentTemplate.description.ilike(f"%{query}%"),
            )

            base_conditions = [TreatmentTemplate.is_active == True]
            if category:
                base_conditions.append(TreatmentTemplate.category == category)

            result = await db.execute(
                select(TreatmentTemplate)
                .options(
                    selectinload(TreatmentTemplate.template_items),
                    selectinload(TreatmentTemplate.created_by_user),
                )
                .where(and_(search_conditions, *base_conditions))
                .offset(skip)
                .limit(limit)
                .order_by(TreatmentTemplate.name)
            )
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error searching treatment templates: {e}")
            return []

    async def get_template_usage_stats(
        self, db: AsyncSession, template_id: UUID
    ) -> Dict[str, Any]:
        """Get usage statistics for a template"""
        try:
            # This would typically query a usage tracking table
            # For now, return basic template info
            template = await self.get_template(db, template_id)
            if not template:
                return {}

            return {
                "template_id": str(template_id),
                "name": template.name,
                "usage_count": 0,  # Placeholder - would come from usage tracking
                "last_used": None,  # Placeholder
                "average_rating": None,  # Placeholder for future rating system
                "items_count": (
                    len(template.template_items) if template.template_items else 0
                ),
            }

        except Exception as e:
            logger.error(f"Error getting template usage stats for {template_id}: {e}")
            return {}

    async def get_popular_templates(
        self, db: AsyncSession, limit: int = 10
    ) -> List[TreatmentTemplate]:
        """Get most popular treatment templates (by usage)"""
        try:
            # Placeholder implementation - would use actual usage data
            result = await db.execute(
                select(TreatmentTemplate)
                .options(
                    selectinload(TreatmentTemplate.template_items),
                    selectinload(TreatmentTemplate.created_by_user),
                )
                .where(TreatmentTemplate.is_active == True)
                .order_by(TreatmentTemplate.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Error getting popular templates: {e}")
            return []

    async def validate_template_for_patient(
        self, db: AsyncSession, template_id: UUID, patient_id: UUID
    ) -> Dict[str, Any]:
        """Validate if a template is appropriate for a specific patient"""
        try:
            template = await self.get_template(db, template_id)
            if not template:
                return {
                    "is_valid": False,
                    "errors": ["Template not found"],
                    "warnings": [],
                }

            # Basic validation logic
            # In a real implementation, this would check:
            # - Patient age restrictions
            # - Medical contraindications
            # - Insurance coverage
            # - Previous treatments

            warnings = []
            errors = []

            # Example validations:
            if template.estimated_cost and template.estimated_cost > 10000:
                warnings.append("This template has a high estimated cost")

            if template.estimated_duration and template.estimated_duration > 240:
                warnings.append("This template requires significant chair time")

            return {
                "is_valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "template": template,
            }

        except Exception as e:
            logger.error(f"Error validating template for patient: {e}")
            return {
                "is_valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": [],
            }

    async def create_template_from_treatment(
        self,
        db: AsyncSession,
        treatment_id: UUID,
        template_name: str,
        category: str,
        created_by: UUID,
    ) -> Optional[TreatmentTemplate]:
        """Create a template from an existing treatment"""
        try:
            from services.treatment_service import treatment_service

            treatment = await treatment_service.get(db, treatment_id)
            if not treatment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Treatment not found"
                )

            # Calculate estimated cost from treatment items
            treatment_items = await treatment_service.get_treatment_items(
                db, treatment_id
            )
            estimated_cost = sum(
                item.quantity * item.unit_price for item in treatment_items
            )

            # Create template
            template = TreatmentTemplate(
                name=template_name,
                description=f"Created from treatment: {treatment.name}",
                category=category,
                estimated_cost=estimated_cost,
                estimated_duration=120,  # Default value
                is_active=True,
                created_by=created_by,
            )
            db.add(template)
            await db.flush()

            # Create template items from treatment items
            for treatment_item in treatment_items:
                template_item = TreatmentTemplateItem(
                    template_id=template.id,
                    service_id=treatment_item.service_id,
                    quantity=treatment_item.quantity,
                    tooth_number=treatment_item.tooth_number,
                    surface=treatment_item.surface,
                    notes=treatment_item.notes,
                    order_index=0,
                )
                db.add(template_item)

            await db.commit()
            await db.refresh(template)

            logger.info(f"Created template {template.id} from treatment {treatment_id}")
            return template

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating template from treatment: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create template from treatment",
            )

    async def _validate_template_data(
        self, db: AsyncSession, template_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate template data before creation/update"""
        errors = []

        # Required fields
        required_fields = ["name", "category"]
        for field in required_fields:
            if not template_data.get(field):
                errors.append(f"{field.replace('_', ' ').title()} is required")

        # Name uniqueness (within same category)
        if template_data.get("name") and template_data.get("category"):
            existing_query = select(TreatmentTemplate).where(
                and_(
                    TreatmentTemplate.name == template_data["name"],
                    TreatmentTemplate.category == template_data["category"],
                    TreatmentTemplate.is_active == True,
                )
            )
            if "id" in template_data:  # For updates, exclude current template
                existing_query = existing_query.where(
                    TreatmentTemplate.id != template_data["id"]
                )

            result = await db.execute(existing_query)
            existing_template = result.scalar_one_or_none()
            if existing_template:
                errors.append(
                    f"A template with name '{template_data['name']}' already exists in category '{template_data['category']}'"
                )

        # Validate template items
        if template_data.get("template_items"):
            for i, item in enumerate(template_data["template_items"]):
                if not item.get("service_id"):
                    errors.append(f"Template item {i + 1}: Service ID is required")
                if item.get("quantity", 0) <= 0:
                    errors.append(f"Template item {i + 1}: Quantity must be positive")

        # Validate cost and duration
        if template_data.get("estimated_cost") and template_data["estimated_cost"] < 0:
            errors.append("Estimated cost cannot be negative")

        if (
            template_data.get("estimated_duration")
            and template_data["estimated_duration"] <= 0
        ):
            errors.append("Estimated duration must be positive")

        return {"is_valid": len(errors) == 0, "errors": errors}

    async def get_template_statistics(self, db: AsyncSession) -> Dict[str, Any]:
        """Get statistics about treatment templates"""
        try:
            # Total templates
            total_result = await db.execute(
                select(func.count(TreatmentTemplate.id)).where(
                    TreatmentTemplate.is_active == True
                )
            )
            total_templates = total_result.scalar()

            # Templates by category
            category_result = await db.execute(
                select(TreatmentTemplate.category, func.count(TreatmentTemplate.id))
                .where(TreatmentTemplate.is_active == True)
                .group_by(TreatmentTemplate.category)
                .order_by(func.count(TreatmentTemplate.id).desc())
            )
            templates_by_category = dict(category_result.all())

            # Average items per template
            items_result = await db.execute(
                select(func.avg(func.count(TreatmentTemplateItem.id)))
                .select_from(TreatmentTemplate)
                .join(TreatmentTemplateItem)
                .where(TreatmentTemplate.is_active == True)
                .group_by(TreatmentTemplate.id)
            )
            avg_items = items_result.scalar() or 0

            # Recent templates (last 30 days)
            recent_start = datetime.utcnow() - timedelta(days=30)
            recent_result = await db.execute(
                select(func.count(TreatmentTemplate.id)).where(
                    TreatmentTemplate.is_active == True,
                    TreatmentTemplate.created_at >= recent_start,
                )
            )
            recent_templates = recent_result.scalar()

            return {
                "total_templates": total_templates,
                "templates_by_category": templates_by_category,
                "average_items_per_template": round(avg_items, 2),
                "recent_templates": recent_templates,
                "categories_count": len(templates_by_category),
            }

        except Exception as e:
            logger.error(f"Error getting template statistics: {e}")
            return {}

    async def export_templates(
        self, db: AsyncSession, format: str = "json", category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Export treatment templates"""
        try:
            templates = await self.get_templates(db, category=category, is_active=True)

            export_data = []
            for template in templates:
                template_data = {
                    "id": str(template.id),
                    "name": template.name,
                    "description": template.description,
                    "category": template.category,
                    "estimated_cost": float(template.estimated_cost or 0),
                    "estimated_duration": template.estimated_duration,
                    "is_active": template.is_active,
                    "created_by": str(template.created_by),
                    "created_at": template.created_at.isoformat(),
                    "template_items": [],
                }

                if template.template_items:
                    for item in template.template_items:
                        item_data = {
                            "service_id": str(item.service_id),
                            "quantity": item.quantity,
                            "tooth_number": item.tooth_number,
                            "surface": item.surface,
                            "notes": item.notes,
                            "order_index": item.order_index,
                        }
                        template_data["template_items"].append(item_data)

                export_data.append(template_data)

            # Format export content
            if format == "json":
                import json

                content = json.dumps(export_data, indent=2, default=str)
            elif format == "csv":
                import csv
                import io

                output = io.StringIO()
                if export_data:
                    # Flatten data for CSV
                    flat_data = []
                    for template in export_data:
                        base_data = {
                            k: v for k, v in template.items() if k != "template_items"
                        }
                        if template["template_items"]:
                            for item in template["template_items"]:
                                row = {
                                    **base_data,
                                    **{f"item_{k}": v for k, v in item.items()},
                                }
                                flat_data.append(row)
                        else:
                            flat_data.append(base_data)

                    if flat_data:
                        writer = csv.DictWriter(output, fieldnames=flat_data[0].keys())
                        writer.writeheader()
                        writer.writerows(flat_data)
                content = output.getvalue()
            else:
                content = str(export_data)

            return {
                "format": format,
                "template_count": len(export_data),
                "content": content,
                "exported_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error exporting templates: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to export templates",
            )


# Global instance
treatment_template_service = TreatmentTemplateService()
