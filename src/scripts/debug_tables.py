#!/usr/bin/env python3
"""
Debug script to check why tables aren't being created
"""
import asyncio
import sys
import os

# Add to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import engine, Base
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession


async def debug_table_creation():
    """Debug why tables aren't being created"""
    print("=== DEBUGGING TABLE CREATION ===")

    # Check if models are imported and registered
    print("1. Checking if models are registered...")
    print(f"Number of tables in metadata: {len(Base.metadata.tables)}")
    for table_name in Base.metadata.tables.keys():
        print(f"  - {table_name}")

    # Try to create tables with explicit echo
    print("\n2. Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Check what tables actually exist
    print("\n3. Checking existing tables...")
    async with AsyncSession(engine) as session:
        result = await session.execute(
            text(
                """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
            )
        )
        existing_tables = [row[0] for row in result]
        print(f"Existing tables: {existing_tables}")

        if not existing_tables:
            print("❌ NO TABLES EXIST IN DATABASE!")
        else:
            print("✅ Tables found in database:")
            for table in existing_tables:
                print(f"  - {table}")


if __name__ == "__main__":
    asyncio.run(debug_table_creation())
