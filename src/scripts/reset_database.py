# scripts/reset_database.py
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db.database import engine
from utils.logger import setup_logger
from core.config import settings

logger = setup_logger("DB_RESET")


async def reset_database():
    """Reset database for development (DANGEROUS - use only in development)"""
    if settings.ENVIRONMENT == "production":
        logger.error("Cannot reset database in production!")
        return

    async with engine.begin() as conn:
        try:
            # Drop all tables
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))

            logger.info("Database reset completed")

        except Exception as e:
            logger.error(f"Database reset failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(reset_database())
