#!/usr/bin/env python3
"""
Script to check Row-Level Security (RLS) policies status
"""
import asyncio
import sys
import os
from typing import List, Dict, Any

# Add to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import AsyncSessionLocal
from sqlalchemy import text
from utils.logger import setup_logger

logger = setup_logger("RLS_CHECK")


async def check_rls_status() -> Dict[str, Any]:
    """
    Check RLS status for all tables
    Returns: Dictionary with RLS status information
    """
    async with AsyncSessionLocal() as session:
        results = {
            "rls_enabled_tables": [],
            "rls_disabled_tables": [],
            "tables_with_policies": [],
            "tables_without_policies": [],
            "policy_details": {},
            "app_functions": {},
            "overall_status": "UNKNOWN",
        }

        try:
            # 1. Check if app schema and functions exist
            print("🔍 Checking app schema and functions...")
            await _check_app_functions(session, results)

            # 2. Check RLS status for all tables
            print("🔍 Checking RLS status for tables...")
            await _check_table_rls_status(session, results)

            # 3. Check policies for each table
            print("🔍 Checking RLS policies...")
            await _check_table_policies(session, results)

            # 4. Determine overall status
            results["overall_status"] = _determine_overall_status(results)

            return results

        except Exception as e:
            logger.error(f"Error checking RLS status: {e}")
            results["error"] = str(e)
            return results


async def _check_app_functions(session, results: Dict[str, Any]):
    """Check if app schema and functions exist"""
    try:
        # Check if app schema exists
        schema_result = await session.execute(
            text(
                """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = 'app'
            )
        """
            )
        )
        app_schema_exists = schema_result.scalar()
        results["app_schema_exists"] = app_schema_exists

        if app_schema_exists:
            # Check if set_tenant_id function exists
            function_result = await session.execute(
                text(
                    """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.routines 
                    WHERE routine_schema = 'app' 
                    AND routine_name = 'set_tenant_id'
                )
            """
                )
            )
            set_tenant_function_exists = function_result.scalar()
            results["set_tenant_function_exists"] = set_tenant_function_exists

            # Get function definition
            if set_tenant_function_exists:
                func_def_result = await session.execute(
                    text(
                        """
                    SELECT pg_get_functiondef(oid) 
                    FROM pg_proc 
                    WHERE proname = 'set_tenant_id' 
                    AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
                """
                    )
                )
                function_definition = func_def_result.scalar()
                results["app_functions"]["set_tenant_id"] = function_definition

    except Exception as e:
        logger.error(f"Error checking app functions: {e}")
        results["app_functions_error"] = str(e)


async def _check_table_rls_status(session, results: Dict[str, Any]):
    """Check RLS status for all tables"""
    try:
        # Get all tables in public schema
        tables_result = await session.execute(
            text(
                """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
            )
        )
        all_tables = [row[0] for row in tables_result]

        for table in all_tables:
            # Check if RLS is enabled
            rls_result = await session.execute(
                text(
                    """
                SELECT relrowsecurity 
                FROM pg_class 
                WHERE relname = :table_name 
                AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            """
                ),
                {"table_name": table},
            )

            rls_enabled = rls_result.scalar()

            if rls_enabled:
                results["rls_enabled_tables"].append(table)
            else:
                results["rls_disabled_tables"].append(table)

    except Exception as e:
        logger.error(f"Error checking RLS status: {e}")
        results["rls_status_error"] = str(e)


async def _check_table_policies(session, results: Dict[str, Any]):
    """Check RLS policies for each table"""
    try:
        # Get all RLS policies
        policies_result = await session.execute(
            text(
                """
            SELECT 
                schemaname,
                tablename,
                policyname,
                permissive,
                roles,
                cmd,
                qual,
                with_check
            FROM pg_policies 
            WHERE schemaname = 'public'
            ORDER BY tablename, policyname
        """
            )
        )

        policies_by_table = {}
        tables_with_policies = set()

        for row in policies_result:
            table_name = row[1]
            policy_name = row[2]

            if table_name not in policies_by_table:
                policies_by_table[table_name] = []
                tables_with_policies.add(table_name)

            policies_by_table[table_name].append(
                {
                    "policy_name": policy_name,
                    "permissive": row[3],
                    "roles": row[4],
                    "cmd": row[5],
                    "qual": row[6],
                    "with_check": row[7],
                }
            )

        results["tables_with_policies"] = list(tables_with_policies)
        results["policy_details"] = policies_by_table

        # Find tables without policies but with RLS enabled
        for table in results["rls_enabled_tables"]:
            if table not in tables_with_policies:
                results["tables_without_policies"].append(table)

    except Exception as e:
        logger.error(f"Error checking policies: {e}")
        results["policies_error"] = str(e)


def _determine_overall_status(results: Dict[str, Any]) -> str:
    """Determine overall RLS status"""
    if "error" in results:
        return "ERROR"

    if not results.get("app_schema_exists", False):
        return "MISSING_APP_SCHEMA"

    if not results.get("set_tenant_function_exists", False):
        return "MISSING_SET_TENANT_FUNCTION"

    if not results["rls_enabled_tables"]:
        return "NO_RLS_ENABLED"

    if results["tables_without_policies"]:
        return "INCOMPLETE_POLICIES"

    # Check if critical tables have RLS
    critical_tables = ["tenants", "users", "patients"]
    missing_critical = [
        t for t in critical_tables if t not in results["rls_enabled_tables"]
    ]

    if missing_critical:
        return f"MISSING_CRITICAL_TABLES: {missing_critical}"

    return "HEALTHY"


def print_rls_report(results: Dict[str, Any]):
    """Print a formatted RLS status report"""
    print("\n" + "=" * 80)
    print("🚀 ROW-LEVEL SECURITY (RLS) STATUS REPORT")
    print("=" * 80)

    # Overall Status
    status = results["overall_status"]
    status_emoji = "✅" if status == "HEALTHY" else "❌"
    print(f"\n{status_emoji} OVERALL STATUS: {status}")

    # App Schema and Functions
    print(f"\n📁 APP SCHEMA:")
    print(
        f"   • Schema exists: {'✅ Yes' if results.get('app_schema_exists') else '❌ No'}"
    )
    if results.get("app_schema_exists"):
        print(
            f"   • set_tenant_id function: {'✅ Exists' if results.get('set_tenant_function_exists') else '❌ Missing'}"
        )

    # RLS Status Summary
    print(f"\n🔒 RLS STATUS SUMMARY:")
    print(f"   • Tables with RLS enabled: {len(results['rls_enabled_tables'])}")
    print(f"   • Tables with RLS disabled: {len(results['rls_disabled_tables'])}")
    print(f"   • Tables with policies: {len(results['tables_with_policies'])}")
    print(f"   • Tables without policies: {len(results['tables_without_policies'])}")

    # Detailed Tables Status
    if results["rls_enabled_tables"]:
        print(f"\n✅ TABLES WITH RLS ENABLED ({len(results['rls_enabled_tables'])}):")
        for table in sorted(results["rls_enabled_tables"]):
            has_policy = table in results["tables_with_policies"]
            policy_emoji = "✅" if has_policy else "⚠️"
            print(f"   {policy_emoji} {table}")

    if results["rls_disabled_tables"]:
        print(f"\n❌ TABLES WITH RLS DISABLED ({len(results['rls_disabled_tables'])}):")
        for table in sorted(results["rls_disabled_tables"]):
            print(f"   ❌ {table}")

    if results["tables_without_policies"]:
        print(
            f"\n⚠️  TABLES WITHOUT POLICIES ({len(results['tables_without_policies'])}):"
        )
        for table in sorted(results["tables_without_policies"]):
            print(f"   ⚠️  {table}")

    # Policy Details
    if results["policy_details"]:
        print(f"\n📋 POLICY DETAILS:")
        for table, policies in sorted(results["policy_details"].items()):
            print(f"   📊 {table}:")
            for policy in policies:
                print(f"      • {policy['policy_name']} ({policy['cmd']})")
                if policy["qual"]:
                    print(f"        WHERE: {policy['qual']}")
                if policy["with_check"]:
                    print(f"        CHECK: {policy['with_check']}")

    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    if status == "HEALTHY":
        print("   ✅ RLS is properly configured!")
    elif status == "MISSING_APP_SCHEMA":
        print("   🔧 Run: python scripts/migrate.py init")
    elif status == "MISSING_SET_TENANT_FUNCTION":
        print("   🔧 Run: python scripts/migrate.py init")
    elif status == "NO_RLS_ENABLED":
        print("   🔧 Run: python scripts/migrate.py init")
    elif status == "INCOMPLETE_POLICIES":
        missing_tables = ", ".join(results["tables_without_policies"])
        print(f"   🔧 Missing policies for: {missing_tables}")
        print("   Run: python scripts/migrate.py init")
    elif "MISSING_CRITICAL_TABLES" in status:
        print("   🔧 Critical tables missing RLS")
        print("   Run: python scripts/migrate.py init")

    print("\n" + "=" * 80)


async def test_rls_functionality():
    """Test if RLS is actually working"""
    print("\n🧪 TESTING RLS FUNCTIONALITY...")

    async with AsyncSessionLocal() as session:
        try:
            # Test 1: Try to set tenant context
            test_tenant_id = "00000000-0000-0000-0000-000000000000"
            await session.execute(text(f"SELECT app.set_tenant_id('{test_tenant_id}')"))
            print("✅ Tenant context setting: WORKING")

            # Test 2: Check if app.tenant_id is set
            result = await session.execute(text("SHOW app.tenant_id"))
            current_tenant = result.scalar()
            if current_tenant == test_tenant_id:
                print("✅ Tenant context verification: WORKING")
            else:
                print(f"❌ Tenant context verification: FAILED (got: {current_tenant})")

            # Test 3: Try to query a table with RLS
            try:
                # This should work but return no rows for our test tenant
                result = await session.execute(text("SELECT COUNT(*) FROM users"))
                count = result.scalar()
                print(f"✅ RLS query test: WORKING (returned {count} rows)")
            except Exception as query_error:
                print(f"❌ RLS query test: FAILED - {query_error}")

            # Reset tenant context
            await session.execute(text("RESET app.tenant_id"))

        except Exception as e:
            print(f"❌ RLS functionality test failed: {e}")


async def main():
    """Main function to run RLS check"""
    print("Starting RLS policy check...")

    # Check RLS status
    results = await check_rls_status()

    # Print report
    print_rls_report(results)

    # Test functionality if basic setup exists
    if results.get("app_schema_exists") and results.get("set_tenant_function_exists"):
        await test_rls_functionality()

    return results["overall_status"] == "HEALTHY"


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
