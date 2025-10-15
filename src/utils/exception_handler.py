# src/utils/exception_handler.py
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Union
from .logger import setup_logger
from .exceptions import BaseAPIException
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, NoResultFound
from slowapi.errors import RateLimitExceeded

logger = setup_logger("EXCEPTION HANDLER")


def setup_exception_handlers(app: FastAPI):
    @app.exception_handler(BaseAPIException)
    async def api_exception_handler(request: Request, exc: BaseAPIException):
        logger.warning(f"API Exception: {str(exc.detail)}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "message": exc.detail,
                "type": exc.__class__.__name__,
                "status": exc.status_code,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Standardize common HTTP error responses
        error_details = {
            status.HTTP_400_BAD_REQUEST: "Bad request",
            status.HTTP_401_UNAUTHORIZED: "Unauthorized - Authentication required",
            status.HTTP_403_FORBIDDEN: "Forbidden - You don't have permission",
            status.HTTP_404_NOT_FOUND: "Resource not found",
            status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed",
            status.HTTP_409_CONFLICT: "Conflict - Resource already exists",
            status.HTTP_422_UNPROCESSABLE_ENTITY: "Validation error",
            status.HTTP_500_INTERNAL_SERVER_ERROR: "Internal server error",
        }

        detail = exc.detail or error_details.get(exc.status_code, "An error occurred")

        if exc.status_code == status.HTTP_404_NOT_FOUND:
            logger.info(f"Not found: {detail}")
        else:
            logger.warning(f"HTTP Exception {exc.status_code}: {detail}")

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "message": detail,
                "type": "HTTPException",
                "status": exc.status_code,
            },
            headers=exc.headers if hasattr(exc, "headers") else None,
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        logger.error(f"Database error: {str(exc)}", exc_info=True)

        if isinstance(exc, IntegrityError):
            detail = (
                "Database integrity error - possible duplicate or constraint violation"
            )
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, NoResultFound):
            detail = "Requested resource not found in database"
            status_code = status.HTTP_404_NOT_FOUND
        else:
            detail = "Database operation failed"
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        return JSONResponse(
            status_code=status_code,
            content={"message": detail, "type": "DatabaseError", "status": status_code},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unexpected error: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Internal server error",
                "type": "InternalServerError",
                "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            },
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        logger.warning(f"Rate limit exceeded: {str(exc)}")

        # Default values
        detail_message = "Too many requests - please try again later"
        retry_after = None

        # Extract retry_after if available
        if hasattr(exc, "detail"):
            if isinstance(exc.detail, str):
                detail_message = exc.detail
            elif hasattr(exc.detail, "retry_after"):
                retry_after = exc.detail.retry_after
                detail_message = (
                    f"Too many requests - please try again in {retry_after} seconds"
                )

        # Prepare response
        response_content = {
            "message": detail_message,
            "type": "RateLimitExceeded",
            "status": status.HTTP_429_TOO_MANY_REQUESTS,
        }

        # Add retry_after if available
        if retry_after:
            response_content["retry_after"] = f"{retry_after} seconds"

        # Prepare headers
        headers = {}
        if retry_after:
            headers["Retry-After"] = str(retry_after)

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=response_content,
            headers=headers,
        )
