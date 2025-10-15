# src/db/database.py
from core.config import settings
from typing import AsyncGenerator, Dict, Any
from contextvars import ContextVar
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import text, event
from sqlalchemy.pool import NullPool
from utils.logger import setup_logger

logger = setup_logger("DATABASE")

# Context var for tenant ID
tenant_id_var: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)


class TenantNotFoundError(Exception):
    """Raised when tenant context is not available"""

    pass


class RLSConfigurationError(Exception):
    """Raised when RLS configuration fails"""

    pass


# Create SQLAlchemy engine with async support
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool if settings.ENVIRONMENT == "testing" else None,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args=(
        {
            # "ssl": "require",
            "server_settings": {
                "jit": "off",
                "application_name": "dental_saas",
            },
        }
        if "postgresql" in settings.DATABASE_URL
        else {}
    ),
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session with tenant context"""
    tenant_id = tenant_id_var.get()

    if not tenant_id:
        raise TenantNotFoundError("Tenant context is required for database operations")

    async with AsyncSessionLocal() as session:
        try:
            # Set tenant ID for RLS
            await session.execute(
                text("SET app.tenant_id = :tenant_id"), {"tenant_id": tenant_id}
            )
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(f"Database session error: {exc}")
            raise
        finally:
            await session.close()


async def get_db_session() -> AsyncSession:
    """Get a database session without tenant context (for system operations)"""
    return AsyncSessionLocal()


async def setup_rls():
    """Setup Row-Level Security policies for multi-tenancy"""
    async with engine.begin() as conn:
        # Create schema for application settings
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))

        # Create function to set tenant context
        await conn.execute(
            text(
                """
            CREATE OR REPLACE FUNCTION app.set_tenant_id(tenant_id UUID)
            RETURNS VOID AS $$
            BEGIN
                PERFORM set_config('app.tenant_id', tenant_id::text, false);
            END;
            $$ LANGUAGE plpgsql;
        """
            )
        )

        # Enable RLS on all tenant-aware tables
        tables = [
            "users",
            "patients",
            "services",
            "appointments",
            "consultations",
            "treatments",
            "treatment_items",
            "medical_records",
            "prescriptions",
            "invoices",
            "invoice_items",
            "payments",
            "newsletters",
            "newsletter_subscriptions",
        ]

        for table in tables:
            try:
                # Enable RLS on table
                await conn.execute(
                    text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                )

                # Drop existing policy if exists
                await conn.execute(
                    text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}")
                )

                # Create policy for tenant isolation
                await conn.execute(
                    text(
                        f"""
                    CREATE POLICY tenant_isolation_policy ON {table}
                    FOR ALL USING (tenant_id::text = current_setting('app.tenant_id', true))
                    WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
                """
                    )
                )

                logger.info(f"RLS policy created for table: {table}")

            except Exception as e:
                logger.warning(f"Failed to setup RLS for {table}: {e}")
                continue

        # Special policy for tenants table
        try:
            await conn.execute(text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY"))

            # Policy for tenants to see only themselves
            await conn.execute(
                text(
                    """
                DROP POLICY IF EXISTS tenant_self_policy ON tenants;
                CREATE POLICY tenant_self_policy ON tenants
                FOR ALL USING (id::text = current_setting('app.tenant_id', true))
            """
                )
            )

            # Allow read access to all tenants for lookup
            await conn.execute(
                text(
                    """
                DROP POLICY IF EXISTS tenant_lookup_policy ON tenants;
                CREATE POLICY tenant_lookup_policy ON tenants
                FOR SELECT USING (true)
            """
                )
            )

        except Exception as e:
            logger.warning(f"Failed to setup RLS for tenants table: {e}")

        logger.info("RLS policies configured successfully")


async def create_tables():
    """Create all tables and setup RLS"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")

        # Setup RLS after tables are created
        await setup_rls()

    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        raise


async def create_tenant_config(tenant_id: str):
    """Create tenant-specific configuration"""
    async with engine.begin() as conn:
        # Ensure tenant config table exists
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS app.tenant_config (
                id SERIAL PRIMARY KEY,
                tenant_id UUID NOT NULL,
                config_key VARCHAR(100) NOT NULL,
                config_value JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(tenant_id, config_key)
            )
        """
            )
        )

        # Insert tenant configuration
        await conn.execute(
            text(
                """
                INSERT INTO app.tenant_config (tenant_id, config_key, config_value)
                VALUES (:tenant_id, 'isolation_level', '"shared"')
                ON CONFLICT (tenant_id, config_key) DO NOTHING
            """
            ),
            {"tenant_id": tenant_id},
        )


async def get_tenant_config(tenant_id: str) -> Dict[str, Any]:
    """Get tenant configuration"""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT config_key, config_value 
                FROM app.tenant_config 
                WHERE tenant_id = :tenant_id
            """
            ),
            {"tenant_id": tenant_id},
        )

        config = {}
        for row in result:
            config[row[0]] = row[1]
        return config


async def disconnect_db():
    """Disconnect from database"""
    await engine.dispose()
