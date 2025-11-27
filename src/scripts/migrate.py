#!/usr/bin/env python3
"""
Migration management script for Alembic
"""
import os
import sys
import subprocess
import asyncio
from pathlib import Path

# Add to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from db.database import create_tables, setup_rls, AsyncSessionLocal
from sqlalchemy import text


async def check_tables_exist():
    """Check if tables exist before setting up RLS"""
    async with AsyncSessionLocal() as session:
        try:
            # Check if users table exists
            result = await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'users'
                    )
                """
                )
            )
            users_exists = result.scalar()
            return users_exists
        except Exception as e:
            print(f"Error checking tables: {e}")
            return False


async def initialize_database():
    """Initialize database with proper error handling"""
    try:
        print("Creating database tables...")
        await create_tables()
        print("Database tables created successfully")

        # Verify tables exist before setting up RLS
        print("Verifying table creation...")
        tables_exist = await check_tables_exist()

        if not tables_exist:
            print("ERROR: Tables were not created properly")
            return False

        print("Setting up Row-Level Security policies...")
        await setup_rls()
        print("RLS policies configured successfully")

        return True

    except Exception as e:
        print(f"Database initialization failed: {e}")
        return False


def run_alembic_command(args):
    """Run alembic command with proper environment"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)

    cmd = ["alembic"] + args
    result = subprocess.run(cmd, env=env)
    return result.returncode


def main():
    if len(sys.argv) < 2:
        print("Usage: python migrate.py [command]")
        print("Commands:")
        print("  init          - Initialize database tables and RLS")
        print("  create [msg]  - Create new migration")
        print("  upgrade [rev] - Upgrade to revision (default: head)")
        print("  downgrade [rev] - Downgrade to revision")
        print("  history       - Show migration history")
        print("  current       - Show current revision")
        print("  check         - Check if tables exist")
        return

    command = sys.argv[1]

    if command == "init":
        # Initialize database tables and RLS
        success = asyncio.run(initialize_database())
        if success:
            print("Database initialized successfully")
        else:
            print("Database initialization failed")
            sys.exit(1)

    elif command == "check":
        # Check if tables exist
        async def check():
            exists = await check_tables_exist()
            if exists:
                print("Tables exist")
            else:
                print("Tables do not exist")

        asyncio.run(check())

    elif command == "create":
        message = sys.argv[2] if len(sys.argv) > 2 else "auto migration"
        run_alembic_command(["revision", "--autogenerate", "-m", message])

    elif command == "upgrade":
        revision = sys.argv[2] if len(sys.argv) > 2 else "head"
        run_alembic_command(["upgrade", revision])

    elif command == "downgrade":
        revision = sys.argv[2] if len(sys.argv) > 2 else "-1"
        run_alembic_command(["downgrade", revision])

    elif command == "history":
        run_alembic_command(["history"])

    elif command == "current":
        run_alembic_command(["current"])

    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
