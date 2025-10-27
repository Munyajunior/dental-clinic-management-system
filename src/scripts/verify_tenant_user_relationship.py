import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from db.database import AsyncSessionLocal
from sqlalchemy import select
from models.tenant import Tenant
from models.user import User
from utils.logger import setup_logger

logger = setup_logger("VERIFY_RELATIONSHIP")


# Quick test script to verify database state
async def verify_tenant_user_relationship():

    async with AsyncSessionLocal() as session:
        # Check tenant
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.slug == "emmanuel-total-dental-care")
        )
        tenant = tenant_result.scalar_one_or_none()
        logger.info(f"Tenant: {tenant}")

        # Check user
        user_result = await session.execute(
            select(User).where(User.email == "ivojunior671@gmail.com")
        )
        user = user_result.scalar_one_or_none()
        logger.info(f"User: {user}")

        if tenant and user:
            logger.info(f"User tenant_id: {user.tenant_id}")
            logger.info(f"Tenant id: {tenant.id}")
            logger.info(f"Match: {user.tenant_id == tenant.id}")


if __name__ == "__main__":
    asyncio.run(verify_tenant_user_relationship())
