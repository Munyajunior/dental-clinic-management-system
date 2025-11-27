# src/db/database.py
from core.config import settings
from fastapi import HTTPException
from typing import AsyncGenerator, Dict, Any
from contextvars import ContextVar
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
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
    future=True,
)


# Sync engine for Alembic migrations
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
)

# Sync session factory
SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_sync_db():
    """
    Synchronous database session for Alembic migrations
    """
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()


# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session with tenant context"""
    tenant_id = tenant_id_var.get()

    if not tenant_id:
        raise TenantNotFoundError("Tenant context is required for database operations")

    # Validate UUID format
    try:
        UUID(tenant_id)
    except ValueError:
        raise TenantNotFoundError(f"Invalid tenant ID format: {tenant_id}")

    async with AsyncSessionLocal() as session:
        try:
            # Set tenant ID for RLS - use validated UUID directly
            await session.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

            # Verify the setting was applied
            result = await session.execute(text("SHOW app.tenant_id"))
            actual_tenant_id = result.scalar()

            if actual_tenant_id != tenant_id:
                logger.error(
                    f"Tenant ID mismatch: set {tenant_id}, got {actual_tenant_id}"
                )
                raise RLSConfigurationError("Failed to set tenant context")

            # DEBUG: Log session creation
            logger.debug(f"Database session created for tenant: {tenant_id}")

            yield session

            await session.commit()

        except HTTPException as http_exc:
            await session.rollback()
            # Re-raise HTTP exceptions (like 401 Unauthorized)
            raise http_exc

        except Exception as exc:
            await session.rollback()
            logger.error(f"Database session error: {exc}", exc_info=True)

            # DEBUG: Add more detailed error information
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")

            # Check if it's the specific tuple error
            if "'tuple' object has no attribute 'id'" in str(exc):
                logger.error(
                    "TUPLE ERROR DETECTED - This indicates a query returning tuple instead of model"
                )
                # Add additional debugging for this specific case
                await _debug_tuple_error(session, tenant_id)

            raise
        finally:
            # Reset tenant context
            try:
                await session.execute(text("RESET app.tenant_id"))
            except:
                pass  # Ignore reset errors
            await session.close()


async def _debug_tuple_error(session: AsyncSession, tenant_id: str):
    """Debug function to identify where tuples are being returned"""
    try:
        logger.error("=== TUPLE ERROR DEBUGGING ===")
        logger.error(f"Tenant ID: {tenant_id}")

        # Check common tables that might be returning tuples
        tables_to_check = ["patients", "users", "tenants", "appointments", "services"]

        for table in tables_to_check:
            try:
                # Try to query each table and see what's returned
                result = await session.execute(
                    text(
                        f"SELECT * FROM {table} WHERE tenant_id = '{tenant_id}' LIMIT 1"
                    )
                )
                first_row = result.first()

                if first_row:
                    logger.error(f"Table {table}: first row type: {type(first_row)}")
                    logger.error(f"Table {table}: first row: {first_row}")

                    # Check if it's a tuple
                    if isinstance(first_row, tuple):
                        logger.error(f"TABLE {table} IS RETURNING TUPLES!")
                        # Check the structure
                        for i, item in enumerate(first_row):
                            logger.error(f"  Item {i}: type={type(item)}, value={item}")

            except Exception as table_error:
                logger.error(f"Error checking table {table}: {table_error}")

        logger.error("=== END TUPLE DEBUGGING ===")

    except Exception as debug_error:
        logger.error(f"Error in tuple debugging: {debug_error}")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session without tenant context (for system operations)"""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(f"Database session error: {exc}")
        raise
    finally:
        await session.close()  # Ensure session is always closed


async def setup_rls():
    """Setup Row-Level Security policies for multi-tenancy"""
    async with engine.begin() as conn:
        try:
            # Create schema for application settings
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))

            # Create function to set tenant context
            await conn.execute(
                text(
                    """
                CREATE OR REPLACE FUNCTION app.set_tenant_id(tenant_id TEXT)
                RETURNS VOID AS $$
                BEGIN
                    -- Validate UUID format
                    IF tenant_id !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' THEN
                        RAISE EXCEPTION 'Invalid tenant ID format: %', tenant_id;
                    END IF;
                    
                    PERFORM set_config('app.tenant_id', tenant_id, false);
                END;
                $$ LANGUAGE plpgsql;
            """
                )
            )

            logger.info("Created app.set_tenant_id function")

        except Exception as e:
            logger.warning(f"Schema creation warning: {e}")

        # Enable RLS on all tenant-aware tables with proper error handling
        tables_with_tenant = [
            "users",
            "refresh_tokens",
            "password_reset_tokens",
            "tenant_settings",
            "settings_audit",
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
            "security_events",
            "user_sessions",
            "patient_sharing",
            "treatment_templates",
        ]

        for table in tables_with_tenant:
            try:
                # First check if the table exists
                result = await conn.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = :table_name
                        )
                    """
                    ),
                    {"table_name": table},
                )
                table_exists = result.scalar()

                if not table_exists:
                    logger.warning(f"Table {table} does not exist, skipping RLS setup")
                    continue

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
                logger.error(f"Failed to setup RLS for {table}: {e}")
                # Continue with other tables instead of aborting

        # Special policy for tenants table
        try:
            # Check if tenants table exists
            result = await conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'tenants'
                    )
                """
                )
            )
            tenants_exists = result.scalar()

            if not tenants_exists:
                logger.warning("Tenants table does not exist, skipping RLS setup")
                return

            await conn.execute(text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY"))

            # Drop existing policies
            await conn.execute(
                text("DROP POLICY IF EXISTS tenant_self_policy ON tenants")
            )
            await conn.execute(
                text("DROP POLICY IF EXISTS tenant_lookup_policy ON tenants")
            )

            # Policy for tenants to see only themselves
            await conn.execute(
                text(
                    """
                CREATE POLICY tenant_self_policy ON tenants
                FOR ALL USING (id::text = current_setting('app.tenant_id', true))
            """
                )
            )

            # Allow read access to all tenants for lookup
            await conn.execute(
                text(
                    """
                CREATE POLICY tenant_lookup_policy ON tenants
                FOR SELECT USING (true)
            """
                )
            )

            logger.info("RLS policies created for tenants table")

        except Exception as e:
            logger.error(f"Failed to setup RLS for tenants table: {e}")

        logger.info("RLS policies configuration completed")


async def verify_rls_health():
    """Verify RLS is working correctly"""
    async with AsyncSessionLocal() as session:
        try:
            # Test with a dummy tenant ID
            test_tenant_id = "00000000-0000-0000-0000-000000000000"

            await session.execute(text(f"SET app.tenant_id = '{test_tenant_id}'"))

            # Try to query a tenant-aware table
            result = await session.execute(text("SELECT count(*) FROM patients"))
            count = result.scalar()

            logger.info(f"RLS health check passed - patients count: {count}")
            return True

        except Exception as e:
            logger.error(f"RLS health check failed: {e}")
            return False
        finally:
            try:
                await session.execute(text("RESET app.tenant_id"))
            except:
                pass


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
        try:
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
        except Exception as e:
            logger.warning(f"Could not create tenant config: {e}")
            # Don't raise, as this is not critical for startup


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
