# src/services/base_service.py
from typing import Type, TypeVar, List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from fastapi import HTTPException, status
from pydantic import BaseModel
from utils.logger import setup_logger
from utils.exceptions import handle_db_exception

logger = setup_logger("BASE_SERVICE")

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class BaseService:
    def __init__(self, model: Type[ModelType]):
        self.model = model
        self.logger = setup_logger(f"SERVICE_{model.__name__}")

    async def get(self, db: AsyncSession, id: UUID) -> Optional[ModelType]:
        """Get a single item by ID"""
        try:
            result = await db.execute(select(self.model).where(self.model.id == id))
            item = result.scalar_one_or_none()

            return item
        except SQLAlchemyError as e:
            await handle_db_exception(db, self.logger, f"get {self.model.__name__}", e)
            return None

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[ModelType]:
        """Get multiple items with pagination and filtering"""
        try:
            query = select(self.model)

            if filters:
                conditions = []
                for field, value in filters.items():
                    if hasattr(self.model, field):
                        conditions.append(getattr(self.model, field) == value)
                if conditions:
                    query = query.where(and_(*conditions))

            query = query.offset(skip).limit(limit)
            result = await db.execute(query)
            return result.scalars().all()
        except SQLAlchemyError as e:
            await handle_db_exception(
                db, self.logger, f"get_multi {self.model.__name__}", e
            )
            return []

    async def create(self, db: AsyncSession, obj_in: CreateSchemaType) -> ModelType:
        """Create a new item"""
        try:
            logger.debug(f"BaseService.create - Model: {self.model.__name__}")

            obj_in_data = obj_in.model_dump(exclude_unset=True)
            logger.debug(f"BaseService.create - Input data: {obj_in_data}")

            db_obj = self.model(**obj_in_data)

            # DEBUG: Check the object before adding
            logger.debug(f"BaseService.create - DB object type: {type(db_obj)}")
            logger.debug(f"BaseService.create - DB object: {db_obj}")

            db.add(db_obj)

            # DEBUG: Before flush
            logger.debug("BaseService.create - About to flush...")
            await db.flush()

            # DEBUG: After flush
            logger.debug(
                f"BaseService.create - After flush, ID: {getattr(db_obj, 'id', 'NO ID')}"
            )

            await db.commit()
            await db.refresh(db_obj)

            # DEBUG: Final object
            logger.debug(f"BaseService.create - Final object: {db_obj}")
            logger.debug(f"BaseService.create - Final object type: {type(db_obj)}")

            self.logger.info(f"Created {self.model.__name__} with ID: {db_obj.id}")
            return db_obj

        except IntegrityError as e:
            await db.rollback()
            self.logger.warning(f"Integrity error creating {self.model.__name__}: {e}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{self.model.__name__} already exists",
            )
        except SQLAlchemyError as e:
            await handle_db_exception(
                db, self.logger, f"create {self.model.__name__}", e
            )
            return None

    async def update(
        self, db: AsyncSession, id: UUID, obj_in: UpdateSchemaType
    ) -> Optional[ModelType]:
        """Update an item"""
        try:
            obj_in_data = obj_in.dict(exclude_unset=True)

            result = await db.execute(
                update(self.model)
                .where(self.model.id == id)
                .values(**obj_in_data)
                .returning(self.model)
            )
            updated_obj = result.scalar_one_or_none()

            if updated_obj:
                await db.commit()
                await db.refresh(updated_obj)
                self.logger.info(f"Updated {self.model.__name__} with ID: {id}")

            return updated_obj
        except SQLAlchemyError as e:
            await handle_db_exception(
                db, self.logger, f"update {self.model.__name__}", e
            )
            return None

    async def delete(self, db: AsyncSession, id: UUID) -> bool:
        """Delete an item"""
        try:
            result = await db.execute(delete(self.model).where(self.model.id == id))
            await db.commit()

            deleted = result.rowcount > 0
            if deleted:
                self.logger.info(f"Deleted {self.model.__name__} with ID: {id}")

            return deleted
        except SQLAlchemyError as e:
            await handle_db_exception(
                db, self.logger, f"delete {self.model.__name__}", e
            )
            return False

    async def count(
        self, db: AsyncSession, filters: Optional[Dict[str, Any]] = None
    ) -> int:
        """Count items with optional filters"""
        try:
            query = select(self.model)

            if filters:
                conditions = []
                for field, value in filters.items():
                    if hasattr(self.model, field):
                        conditions.append(getattr(self.model, field) == value)
                if conditions:
                    query = query.where(and_(*conditions))

            result = await db.execute(
                select(func.count()).select_from(query.subquery())
            )
            return result.scalar_one()
        except SQLAlchemyError as e:
            await handle_db_exception(
                db, self.logger, f"count {self.model.__name__}", e
            )
            return 0
