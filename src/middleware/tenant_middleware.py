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

        # Extract tenant ID
        tenant_id = await self._extract_tenant_id(request)

        if not tenant_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "detail": "Tenant identifier required. Use X-Tenant-ID header or subdomain"
                },
            )

        # Validate tenant exists and is active
        tenant = await self._validate_tenant(tenant_id, request)
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
            return response
        except Exception as e:
            logger.error(f"Request processing failed: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            tenant_id_var.reset(token)

    async def _extract_tenant_id(self, request: Request) -> str:
        """Extract tenant ID from request headers or subdomain"""
        # 1. Check X-Tenant-ID header
        tenant_id = request.headers.get("x-tenant-id")
        if tenant_id:
            return tenant_id

        # 2. Check X-Tenant-Slug header
        tenant_slug = request.headers.get("x-tenant-slug")
        if tenant_slug:
            return tenant_slug

        # 3. Check subdomain (e.g., tenant1.dentalapp.com)
        host = request.headers.get("host", "")
        if "." in host:
            subdomain = host.split(".")[0]
            if subdomain and subdomain not in ["www", "api", "localhost"]:
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
                        select(Tenant).where(Tenant.id == tenant_uuid)
                    )
                except ValueError:
                    # Try as slug
                    result = await session.execute(
                        select(Tenant).where(Tenant.slug == tenant_identifier)
                    )

                tenant = result.scalar_one_or_none()

                if tenant and tenant.status == "active":
                    return tenant
                return None

            except Exception as e:
                logger.error(f"Tenant validation error: {e}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    async def _is_public_endpoint(self, request: Request) -> bool:
        """Check if the endpoint is public and doesn't require tenant context"""
        public_paths = [
            "/api/v2/health",
            "/api/v2/docs",
            "/api/v2/redoc",
            "/api/v2/openapi.json",
            "/api/v2/auth/login",
            "/api/v2/auth/register",
            "/api/v2/public/tenants/register",  # Add public registration
            "/api/v2/public/tenants",  # List available tenants
            "/api/v2/startup-check",
        ]
        path = request.url.path
        return any(
            path == public_path or path.startswith(public_path + "/")
            for public_path in public_paths
        )
