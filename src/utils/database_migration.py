# src/utils/database_migration.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from utils.logger import setup_logger

logger = setup_logger("DATABASE_MIGRATION")


# async def add_missing_columns(db: AsyncSession):
#     """Add missing tenant_id columns to tables"""
#     try:
#         # Tables that need tenant_id column
#         tables_to_update = [
#             "refresh_tokens",
#             "treatment_items",
#             "medical_records",
#             "prescriptions",
#             "invoices",
#             "invoice_items",
#             "payments",
#             "newsletters",
#             "newsletter_subscriptions",
#         ]

#         for table in tables_to_update:
#             try:
#                 # Check if tenant_id column exists
#                 result = await db.execute(
#                     text(
#                         f"""
#                     SELECT column_name
#                     FROM information_schema.columns
#                     WHERE table_name = '{table}' AND column_name = 'tenant_id'
#                 """
#                     )
#                 )

#                 if not result.scalar():
#                     # Add tenant_id column with a default value (first tenant)
#                     await db.execute(
#                         text(
#                             f"""
#                         ALTER TABLE {table}
#                         ADD COLUMN tenant_id UUID NOT NULL REFERENCES tenants(id) DEFAULT (
#                             SELECT id FROM tenants ORDER BY created_at LIMIT 1
#                         )
#                     """
#                         )
#                     )

#                     # Create index for better performance
#                     await db.execute(
#                         text(
#                             f"""
#                         CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id
#                         ON {table} (tenant_id)
#                     """
#                         )
#                     )

#                     logger.info(f"Added tenant_id column to {table}")
#                 else:
#                     logger.info(f"tenant_id column already exists in {table}")

#             except Exception as e:
#                 logger.error(f"Failed to add tenant_id to {table}: {e}")
#                 continue

#         await db.commit()
#         logger.info("Database migration completed successfully")

#     except Exception as e:
#         await db.rollback()
#         logger.error(f"Database migration failed: {e}")
#         raise


# async def verify_table_structure(db: AsyncSession):
#     """Verify all tables have required columns"""
#     try:
#         required_columns = {
#             "users": ["id", "tenant_id", "email", "hashed_password"],
#             "refresh_tokens": ["id", "tenant_id", "user_id"],
#             "patients": ["id", "tenant_id", "first_name", "last_name"],
#             "services": ["id", "tenant_id", "name", "code"],
#             "appointments": ["id", "tenant_id", "patient_id", "dentist_id"],
#             "consultations": ["id", "tenant_id", "patient_id", "dentist_id"],
#             "treatments": ["id", "tenant_id", "patient_id", "dentist_id"],
#             "treatment_items": ["id", "tenant_id", "treatment_id", "service_id"],
#             "medical_records": ["id", "tenant_id", "patient_id", "record_type"],
#             "prescriptions": ["id", "tenant_id", "patient_id", "dentist_id"],
#             "invoices": ["id", "tenant_id", "patient_id", "invoice_number"],
#             "invoice_items": ["id", "tenant_id", "invoice_id", "description"],
#             "payments": ["id", "tenant_id", "invoice_id", "amount"],
#             "newsletters": ["id", "tenant_id", "subject", "content"],
#             "newsletter_subscriptions": ["id", "tenant_id", "patient_id", "email"],
#             "tenant_settings": ["id", "tenant_id", "category", "settings_key"],
#             "tenants": ["id", "name", "slug", "status"],
#         }

#         missing_columns = {}

#         for table, columns in required_columns.items():
#             try:
#                 result = await db.execute(
#                     text(
#                         f"""
#                     SELECT column_name
#                     FROM information_schema.columns
#                     WHERE table_name = '{table}'
#                 """
#                     )
#                 )

#                 existing_columns = {row[0] for row in result}
#                 missing = [col for col in columns if col not in existing_columns]

#                 if missing:
#                     missing_columns[table] = missing

#             except Exception as e:
#                 logger.error(f"Failed to check columns for {table}: {e}")
#                 missing_columns[table] = ["check_failed"]

#         if missing_columns:
#             logger.warning(f"Missing columns found: {missing_columns}")
#             return False
#         else:
#             logger.info("All tables have required columns")
#             return True

#     except Exception as e:
#         logger.error(f"Table structure verification failed: {e}")
#         return False


async def add_missing_columns(session: AsyncSession):
    """Add missing columns to existing tables for backward compatibility"""
    try:
        # Check and add missing columns to users table
        await session.execute(
            text(
                """
            DO $$ 
            BEGIN
                -- Add login_count if not exists
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='login_count') THEN
                    ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0;
                END IF;
                
                -- Add failed_login_attempts if not exists
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='failed_login_attempts') THEN
                    ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0;
                END IF;
                
                -- Add last_failed_login if not exists
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='last_failed_login') THEN
                    ALTER TABLE users ADD COLUMN last_failed_login TIMESTAMP WITH TIME ZONE;
                END IF;
                
                -- Add password_changed_at if not exists
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                              WHERE table_name='users' AND column_name='password_changed_at') THEN
                    ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP WITH TIME ZONE;
                END IF;
            END $$;
        """
            )
        )

        await session.commit()
        logger.info("Database migration completed successfully")
        return True

    except Exception as e:
        await session.rollback()
        logger.error(f"Database migration failed: {e}")
        return False


async def verify_table_structure(session):
    """Verify that all required tables and columns exist"""
    try:
        # Check users table structure
        result = await session.execute(
            text(
                """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name IN ('login_count', 'failed_login_attempts', 'last_failed_login', 'password_changed_at')
        """
            )
        )

        existing_columns = {row[0] for row in result}
        required_columns = {
            "login_count",
            "failed_login_attempts",
            "last_failed_login",
            "password_changed_at",
        }

        missing_columns = required_columns - existing_columns

        if missing_columns:
            logger.warning(f"Missing columns in users table: {missing_columns}")
            return False

        logger.info("Table structure verification passed")
        return True

    except Exception as e:
        logger.error(f"Table structure verification failed: {e}")
        return False
