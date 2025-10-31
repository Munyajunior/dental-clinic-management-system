# src/main.py
import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator
import logging
import uvicorn as uv
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from core.cache import init_redis
from core.config import settings
from db.database import (
    AsyncSessionLocal,
    create_tables,
    setup_rls,
    engine,
    disconnect_db,
)
from utils.exception_handler import setup_exception_handlers
from utils.logger import setup_logger
from utils.rate_limiter import limiter
from routes import (
    auth_router,
    users_router,
    medical_records_router,
    tenants_router,
    email_router,
    invoices_router,
    patients_router,
    services_router,
    dashboard_router,
    treatments_router,
    newsletters_router,
    appointments_router,
    consultations_router,
    prescriptions_router,
    settings_router,
    password_reset_router,
    public_router,
    sessions_router,
)
from middleware.tenant_middleware import TenantMiddleware
from dependencies.tenant_deps import get_current_tenant
from utils.database_migration import verify_table_structure, add_missing_columns
from services.email_service import email_service

# Disable specific loggers
for log in ["watchfiles", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"]:
    logging.getLogger(log).setLevel(logging.WARNING)
# Create separate file handler for complete logs
file_handler = logging.FileHandler("app.log")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

# Get root logger and add file handler
root_logger = logging.getLogger()
root_logger.addHandler(file_handler)

# Disable uvicorn access logs
uvicorn_access = logging.getLogger("uvicorn.access")
uvicorn_access.propagate = True

# Disable watchfiles logs if using reload
try:
    watchfiles_logger = logging.getLogger("watchfiles")
    watchfiles_logger.setLevel(logging.CRITICAL)
except ImportError:
    pass


logger = setup_logger("SERVER")


async def run_migrations():
    """Run database migrations with async support"""
    try:
        logger.info("Running database migrations...")
        alembic_cfg = Config("alembic.ini")

        # Run migrations synchronously but with timeout
        def sync_migrations():
            command.upgrade(alembic_cfg, "head")

        await asyncio.to_thread(sync_migrations)
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Database migration failed: {str(e)}")


async def initialize_database():
    """Initialize database with proper error handling"""
    try:
        # Create tables
        await create_tables()
        logger.info("Database tables created")

        # Verify table structure with proper session management
        async with AsyncSessionLocal() as session:
            try:
                structure_ok = await verify_table_structure(session)
                if not structure_ok:
                    logger.warning(
                        "Table structure issues detected, running migration..."
                    )
                    await add_missing_columns(session)
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise

        # Setup RLS after tables are created
        logger.info("Setting up Row-Level Security policies...")
        await setup_rls()
        logger.info("RLS policies configured successfully")

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def check_db_connection() -> bool:
    """Check database connection health with proper cleanup"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Async context manager with proper error handling"""
    logger.info("Starting Dental Clinic Management System...")

    try:
        # Database initialization
        logger.info("Initializing database...")
        # await initialize_database()

        # Database check
        await check_db_connection()
        if check_db_connection:
            logger.info("Database connection verified")

        # Create initial tenant for development
        # if settings.ENVIRONMENT in ["development", "staging"]:
        #     await create_default_tenant()

        # Redis initialization
        if settings.REQUIRE_REDIS:
            logger.info("Initializing Redis Server")
            if settings.CACHE_ENABLED:
                try:
                    await init_redis(app)
                    logger.info("Redis initialized")
                except Exception as e:
                    logger.error(f"Redis initialization failed: {e}")
            else:
                logger.warning("Redis cache disabled in config, skipping init")
        else:
            logger.warning("Redis not required, skipping init")

        # Start migrations in background without waiting
        # asyncio.create_task(run_migrations())

        logger.info("Application startup complete")
        yield

    except Exception as e:
        logger.error(f"Startup failed: {str(e)}")
        raise
    finally:
        # Close db connection
        logger.info("Closing database connection")
        await disconnect_db()
        logger.info("Shutting down application...")


# Initialize the FastAPI application with lifespan management
app = FastAPI(
    title="Dental Clinic Management System",
    description="Multi-tenant SaaS for dental practice management",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# Add Tenant Middleware for multi-tenancy
app.add_middleware(TenantMiddleware)

# Rate limiting configuration
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Exception handling
setup_exception_handlers(app)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Tenant-ID", "X-Tenant-Slug"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-Tenant-ID"],
)


app.include_router(auth_router, prefix=settings.API_PREFIX)
app.include_router(tenants_router, prefix=settings.API_PREFIX)
app.include_router(users_router, prefix=settings.API_PREFIX)
app.include_router(email_router, prefix=settings.API_PREFIX)
app.include_router(patients_router, prefix=settings.API_PREFIX)
app.include_router(appointments_router, prefix=settings.API_PREFIX)
app.include_router(services_router, prefix=settings.API_PREFIX)
app.include_router(consultations_router, prefix=settings.API_PREFIX)
app.include_router(treatments_router, prefix=settings.API_PREFIX)
app.include_router(invoices_router, prefix=settings.API_PREFIX)
app.include_router(medical_records_router, prefix=settings.API_PREFIX)
app.include_router(prescriptions_router, prefix=settings.API_PREFIX)
app.include_router(newsletters_router, prefix=settings.API_PREFIX)
app.include_router(dashboard_router, prefix=settings.API_PREFIX)
app.include_router(settings_router, prefix=settings.API_PREFIX)
app.include_router(password_reset_router, prefix=settings.API_PREFIX)
app.include_router(public_router, prefix=settings.API_PREFIX)
app.include_router(sessions_router, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "message": "Dental Clinic Management System API",
        "status": "healthy",
        "version": app.version,
        "multi_tenant": True,
        "rls_enabled": True,
    }


@app.get("/api/v2/health")
async def health_check():
    """Detailed health check endpoint"""
    db_healthy = await check_db_connection()
    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
        "cache": "enabled" if settings.CACHE_ENABLED else "disabled",
        "multi_tenant": True,
        "rls_enabled": True,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/api/v2/tenant/health")
async def tenant_health_check(tenant=Depends(get_current_tenant)):
    """Tenant-specific health check"""
    return {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "tier": tenant.tier,
        "status": tenant.status,
    }


@app.get("/api/v2/startup-check")
async def startup_check():
    """Verify all critical services are running"""
    checks = {
        "database": await check_db_connection(),
        "redis": settings.REQUIRE_REDIS,
        "multi_tenant": True,
        "rls_enabled": True,
        "status": "ready",
    }
    return checks


@app.get("/api/v2/tenant-info")
async def tenant_info(tenant=Depends(get_current_tenant)):
    """Get current tenant information (requires tenant context)"""
    return {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "tier": tenant.tier,
        "status": tenant.status,
    }


@app.get("/api/v2/public/tenants")
async def list_tenants():
    """Public endpoint to list available tenants (no tenant context required)"""
    from sqlalchemy import select
    from models.tenant import Tenant

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Tenant).where(Tenant.status == "active"))
        tenants = result.scalars().all()

        return {
            "tenants": [
                {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "slug": tenant.slug,
                    "tier": tenant.tier,
                }
                for tenant in tenants
            ]
        }


@app.get("api/v2/email/simple/health")
async def email_health_check():
    """Check email service health and connectivity"""
    connectivity = await email_service.check_connectivity()
    return {
        "service": "resend",
        "status": connectivity.get("service_status", "unknown"),
        "dns_resolution": connectivity.get("dns_resolution", False),
        "api_key_configured": connectivity.get("api_key_configured", False),
        "consecutive_failures": connectivity.get("consecutive_failures", 0),
        "last_success": connectivity.get("last_success"),
        "details": connectivity,
    }


async def create_default_tenant():
    """Create default tenant for development"""
    from sqlalchemy import select
    from models.tenant import Tenant
    from db.database import AsyncSessionLocal, create_tenant_config

    async with AsyncSessionLocal() as session:
        try:
            # Check if default tenant exists
            result = await session.execute(
                select(Tenant).where(Tenant.slug == "default")
            )
            existing_tenant = result.scalar_one_or_none()

            if not existing_tenant and getattr(settings, "CREATE_DEFAULT_TENANT", True):
                logger.info("Creating default tenant...")
                default_tenant = Tenant(
                    name="Default Dental Clinic",
                    slug="default",
                    contact_email="admin@dentalclinic.com",
                    contact_phone="+1234567890",
                    address="123 Main Street, Dental City",
                    tier="basic",
                    status="active",
                )
                session.add(default_tenant)
                await session.commit()

                # Create tenant configuration
                await create_tenant_config(str(default_tenant.id))
                logger.info("Default tenant created successfully")

        except Exception as e:
            logger.warning(f"Could not create default tenant: {e}")


if __name__ == "__main__":
    # Configure reload directories more precisely
    watch_dirs = [
        os.path.join(".main.py"),
        os.path.join("core"),
        os.path.join("routes"),
        os.path.join("models"),
        os.path.join("schemas"),
        os.path.join("services"),
        os.path.join("utils"),
        os.path.join("middleware"),
        os.path.join("dependencies"),
        os.path.join("db"),
    ]

    uv.run(
        "main:app",
        host=settings.UVICORN_HOST,
        port=settings.UVICORN_PORT,
        reload=settings.RELOAD,
        reload_dirs=watch_dirs,
        reload_excludes=["*.pyc", "*.tmp", "*.swp"],
        workers=1 if settings.RELOAD else settings.WORKERS_COUNT,
        log_level="info",
        access_log=True,
        timeout_graceful_shutdown=10,
        limit_concurrency=100,
        limit_max_requests=1000,
    )
