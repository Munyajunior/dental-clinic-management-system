# src/middleware/tenant_middleware.py
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from db.database import tenant_id_var
from utils.logger import setup_logger

logger = setup_logger("TENANT_MIDDLEWARE")


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware to extract and set tenant context from requests"""

    async def dispatch(self, request: Request, call_next):
        # Extract tenant ID from various sources
        tenant_id = await self._extract_tenant_id(request)

        if not tenant_id:
            # For some public endpoints, tenant might not be required
            if not await self._is_public_endpoint(request):
                raise HTTPException(
                    status_code=400, detail="Tenant identifier required"
                )

        # Set tenant context
        token = tenant_id_var.set(tenant_id)

        try:
            response = await call_next(request)
            return response
        finally:
            tenant_id_var.reset(token)

    async def _extract_tenant_id(self, request: Request) -> str:
        """Extract tenant ID from request headers, subdomain, or JWT token"""
        # 1. Check X-Tenant-ID header
        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            return tenant_id

        # 2. Check subdomain (e.g., tenant1.dentalapp.com)
        host = request.headers.get("host", "")
        if "." in host:
            subdomain = host.split(".")[0]
            if subdomain and subdomain not in ["www", "api"]:
                # Here you might want to lookup tenant by subdomain/slug
                return subdomain

        # 3. Check JWT token (if implemented)
        # auth_header = request.headers.get("authorization")
        # if auth_header and auth_header.startswith("Bearer "):
        #     token = auth_header[7:]
        #     tenant_id = await self._extract_tenant_from_token(token)
        #     if tenant_id:
        #         return tenant_id

        return None

    async def _is_public_endpoint(self, request: Request) -> bool:
        """Check if the endpoint is public and doesn't require tenant context"""
        public_paths = [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/auth/",
            "/tenants/register",
        ]
        return any(request.url.path.startswith(path) for path in public_paths)
