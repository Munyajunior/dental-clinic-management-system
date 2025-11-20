#!/usr/bin/env python3
"""
Migration management script for Alembic
"""
import os
import sys
import subprocess
from pathlib import Path

# Add to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from db.database import create_tables, setup_rls


def run_alembic_command(args):
    """Run alembic command with proper environment"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent / "src")

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
        return

    command = sys.argv[1]

    if command == "init":
        # Initialize database tables and RLS
        import asyncio

        async def init_db():
            await create_tables()
            await setup_rls()

        asyncio.run(init_db())
        print("Database initialized successfully")

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
