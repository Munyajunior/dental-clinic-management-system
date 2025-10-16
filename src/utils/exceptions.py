# src/utils/exceptions.py
from fastapi import HTTPException, status
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from .logger import setup_logger

logger = setup_logger("EXCEPTIONS")


class BaseAPIException(HTTPException):
    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Optional[dict] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.custom_property = "value"  # Example custom property


class NotFoundException(BaseAPIException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ConflictException(BaseAPIException):
    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class UnprocessableEntityException(BaseAPIException):
    def __init__(self, detail: str = "Unprocessable entity"):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )


class UnauthorizedException(BaseAPIException):
    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(BaseAPIException):
    def __init__(self, detail: str = "Operation not authorized"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class BadRequestException(BaseAPIException):
    def __init__(self, detail: str = "Bad Request"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


async def handle_db_exception(
    db: AsyncSession, logger: logger, operation: str, exception: Exception
):
    """Handle database exceptions with consistent logging and rollback"""
    await db.rollback()
    logger.error(f"Database error during {operation}: {str(exception)}", exc_info=True)

    # Re-raise custom exceptions
    if isinstance(
        exception, (NotFoundException, ConflictException, UnprocessableEntityException)
    ):
        raise exception

    # Convert other exceptions to HTTP 500
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Internal server error during {operation}",
    )
