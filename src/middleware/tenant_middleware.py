# src/middleware/tenant_middleware.py
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from db.database import tenant_id_var
from typing import Optional
from sqlalchemy import select
from models.tenant import Tenant
from utils.logger import setup_logger

logger = setup_logger("TENANT_MIDDLEWARE")


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware to extract and set tenant context from requests"""

    async def dispatch(self, request: Request, call_next):
        # Skip tenant extraction for public endpoints
        if await self._is_public_endpoint(request):
            response = await call_next(request)
            return response

        # Extract tenant identifier
        tenant_identifier = await self._extract_tenant_identifier(request)

        if not tenant_identifier:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "detail": "Tenant identifier required. Use X-Tenant-ID or X-Tenant-Slug header"
                },
            )

        # Validate tenant exists and is active
        tenant = await self._validate_tenant(tenant_identifier, request)
        if not tenant:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "Tenant not found or inactive"},
            )

        # Set tenant context
        token = tenant_id_var.set(str(tenant.id))

        try:
            response = await call_next(request)

            # Add tenant info to response headers for debugging
            response.headers["X-Tenant-ID"] = str(tenant.id)
            response.headers["X-Tenant-Name"] = tenant.name
            response.headers["X-Tenant-Slug"] = tenant.slug

            return response

        except Exception as e:
            logger.error(f"Request processing failed: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            tenant_id_var.reset(token)

    async def _extract_tenant_identifier(self, request: Request) -> Optional[str]:
        """Extract tenant identifier from headers only - DO NOT read request body"""

        # 1. Check headers first (highest priority)
        tenant_id = request.headers.get("x-tenant-id")
        if tenant_id:
            logger.debug(f"Found tenant ID in header: {tenant_id}")
            return tenant_id

        tenant_slug = request.headers.get("x-tenant-slug")
        if tenant_slug:
            logger.debug(f"Found tenant slug in header: {tenant_slug}")
            return tenant_slug

        # 2. Check subdomain
        subdomain_identifier = self._extract_tenant_from_subdomain(request)
        if subdomain_identifier:
            return subdomain_identifier

        logger.warning(f"No tenant identifier found for request to {request.url.path}")
        return None

    def _extract_tenant_from_subdomain(self, request: Request) -> Optional[str]:
        """Extract tenant identifier from subdomain"""
        host = request.headers.get("host", "").split(":")[0]  # Remove port

        if "." in host:
            parts = host.split(".")
            if len(parts) >= 3:  # tenant.domain.com
                subdomain = parts[0]
                if subdomain and subdomain not in ["www", "api", "localhost", "127"]:
                    logger.debug(f"Found tenant in subdomain: {subdomain}")
                    return subdomain

        return None

    async def _validate_tenant(
        self, tenant_identifier: str, request: Request
    ) -> Optional[Tenant]:
        """Validate tenant exists and is active"""
        from db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            try:
                import uuid

                # Try as UUID first
                try:
                    tenant_uuid = uuid.UUID(tenant_identifier)
                    result = await session.execute(
                        select(Tenant).where(
                            Tenant.id == tenant_uuid, Tenant.status == "active"
                        )
                    )
                except ValueError:
                    # Try as slug
                    result = await session.execute(
                        select(Tenant).where(
                            Tenant.slug == tenant_identifier, Tenant.status == "active"
                        )
                    )

                tenant = result.scalar_one_or_none()

                if tenant:
                    logger.debug(f"Validated tenant: {tenant.name} ({tenant.slug})")
                    return tenant

                logger.warning(f"Tenant not found or inactive: {tenant_identifier}")
                return None

            except Exception as e:
                logger.error(f"Tenant validation error: {e}")
                return None

    async def _is_public_endpoint(self, request: Request) -> bool:
        """Check if the endpoint is public and doesn't require tenant context"""
        public_paths = [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v2/health",
            "/api/v2/openapi.json",
            "/api/v2/startup-check",
            "/api/v2/public/tenants/register",
            "/api/v2/public/tenants",
            "/api/v2/auth/login",  # Login is public but will handle tenant differently
            "/api/v2/auth/refresh",
            "/api/v2/password-reset/request",
            "/api/v2/password-reset/verify",
            "/api/v2/password-reset/complete",
        ]

        path = request.url.path

        # Exact matches
        if path in public_paths:
            return True

        # Prefix matches
        for public_path in public_paths:
            if path.startswith(public_path + "/"):
                return True

        return False
