# src/db/database.py
from core.config import settings
from typing import AsyncGenerator, Dict, Any
from contextvars import ContextVar
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import text, event
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


# Create SQLAlchemy engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={
        "ssl": "require" if "neon" in settings.DATABASE_URL else None,
        "command_timeout": 60,
        "server_settings": {
            "jit": "off",
        },
    },
)


# Session factory with async support
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    class_=AsyncSession,
)


# Base class for models
Base = declarative_base()


class TenantAwareSession(AsyncSession):
    """Custom session that automatically sets tenant context"""

    async def __aenter__(self):
        await super().__aenter__()
        tenant_id = tenant_id_var.get()
        if tenant_id:
            await self.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
        return self


def get_session(tenant_id: str = None) -> AsyncSession:
    """Get database session for tenant with RLS"""
    session = AsyncSessionLocal()

    # Set tenant context if provided
    if tenant_id:
        tenant_id_var.set(tenant_id)

    return session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session with tenant context"""
    tenant_id = tenant_id_var.get()
    if not tenant_id:
        raise TenantNotFoundError("Tenant context is required for database operations")

    async with AsyncSessionLocal() as session:
        try:
            # Set tenant ID for RLS
            await session.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(f"Database error: {exc}")
            raise exc
        finally:
            await session.close()


async def setup_rls():
    """Setup Row-Level Security policies for multi-tenancy"""
    async with engine.begin() as conn:
        # Create schema for application settings
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))

        # Create configuration table for tenant settings
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

        # Enable RLS on all tenant-aware tables
        tables = [
            "tenants",
            "users",
            "patients",
            "appointments",
            "consultations",
            "treatments",
            "treatment_items",
            "services",
            "medical_records",
            "invoices",
            "invoice_items",
            "payments",
            "prescriptions",
            "newsletters",
            "newsletter_subscriptions",
        ]

        for table in tables:
            # Enable RLS on table
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))

            # Create policy for tenant isolation
            await conn.execute(
                text(
                    f"""
                CREATE POLICY tenant_isolation_policy ON {table}
                FOR ALL
                USING (tenant_id = current_setting('app.tenant_id')::UUID)
                WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)
            """
                )
            )

        # Special policy for tenants table (allow read access to all tenants)
        await conn.execute(
            text(
                """
            DROP POLICY IF EXISTS tenant_isolation_policy ON tenants;
            CREATE POLICY tenant_read_policy ON tenants
            FOR SELECT
            USING (true);
            
            CREATE POLICY tenant_modify_policy ON tenants
            FOR ALL
            USING (id = current_setting('app.tenant_id')::UUID)
            WITH CHECK (id = current_setting('app.tenant_id')::UUID);
        """
            )
        )


async def create_tables():
    """Create all tables and setup RLS"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Setup RLS after tables are created
    await setup_rls()
    logger.info("Database tables and RLS policies created successfully")


async def create_tenant_database(tenant_id: str):
    """Create tenant-specific configuration"""
    async with engine.begin() as conn:
        # Insert tenant configuration
        await conn.execute(
            text(
                """
            INSERT INTO app.tenant_config (tenant_id, config_key, config_value)
            VALUES (:tenant_id, 'database.isolation_level', '"shared"')
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


# Event listeners for automatic tenant context
@event.listens_for(engine.sync_engine, "connect")
def set_tenant_context(dbapi_connection, connection_record):
    """Set default tenant context for each connection"""
    cursor = dbapi_connection.cursor()
    cursor.execute("SET app.tenant_id = '00000000-0000-0000-0000-000000000000'")
    cursor.close()
