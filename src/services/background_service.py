import asyncio
from typing import Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from utils.logger import setup_logger
from services.patient_service import patient_service

logger = setup_logger("BACKGROUND_SERVICE")


class BackgroundService:
    """Service for handling background tasks like patient count updates"""

    def __init__(self):
        self._update_tasks: Dict[UUID, asyncio.Task] = {}

    async def schedule_patient_count_update(
        self,
        db: AsyncSession,
        dentist_id: UUID,
        tenant_id: UUID,
        delay_seconds: float = 1.0,
    ) -> None:
        """Schedule a patient count update for a dentist after a delay"""
        # Cancel any existing update task for this dentist
        if dentist_id in self._update_tasks:
            self._update_tasks[dentist_id].cancel()

        # Create new task
        task = asyncio.create_task(
            self._update_dentist_patient_count_delayed(
                db, dentist_id, tenant_id, delay_seconds
            )
        )
        self._update_tasks[dentist_id] = task

    async def _update_dentist_patient_count_delayed(
        self, db: AsyncSession, dentist_id: UUID, tenant_id: UUID, delay_seconds: float
    ) -> None:
        """Update dentist patient count after a delay"""
        try:
            await asyncio.sleep(delay_seconds)
            await patient_service._update_dentist_patient_count(db, dentist_id)
            logger.debug(f"Updated patient count for dentist {dentist_id} after delay")
        except asyncio.CancelledError:
            logger.debug(f"Cancelled patient count update for dentist {dentist_id}")
        except Exception as e:
            logger.error(f"Error in delayed patient count update for {dentist_id}: {e}")
        finally:
            # Remove task from tracking
            self._update_tasks.pop(dentist_id, None)

    async def update_all_dentist_counts(
        self, db: AsyncSession, tenant_id: UUID
    ) -> None:
        """Update patient counts for all dental professionals in a tenant"""
        try:
            await patient_service.update_dentist_patient_counts(db, tenant_id)
            logger.info(f"Updated all dentist patient counts for tenant {tenant_id}")
        except Exception as e:
            logger.error(f"Error updating all dentist counts: {e}")


background_service = BackgroundService()
