# src/db/rls_policies.py
from sqlalchemy import text
from .database import db_manager


def setup_rls_policies():
    """Setup Row Level Security policies for all tables"""

    with db_manager.shared_engine.connect() as conn:
        # Enable RLS on all tables
        tables = [
            "tenants",
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
            # Enable RLS
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))

            # Create policy for tenants table (only see own tenant)
            if table == "tenants":
                conn.execute(
                    text(
                        """
                    CREATE POLICY tenant_isolation_policy ON tenants
                    USING (id::text = current_setting('app.current_tenant_id', true));
                """
                    )
                )
            else:
                # Create policy for all other tables
                conn.execute(
                    text(
                        f"""
                    CREATE POLICY tenant_isolation_policy ON {table}
                    USING (tenant_id::text = current_setting('app.current_tenant_id', true));
                """
                    )
                )

        # Additional policies for users to see their own data
        conn.execute(
            text(
                """
            CREATE POLICY user_see_own_data ON users
            USING (id::text = current_setting('app.current_user_id', true));
        """
            )
        )

        conn.execute(
            text(
                """
            CREATE POLICY patient_see_own_data ON patients
            USING (id::text = current_setting('app.current_user_id', true));
        """
            )
        )

        conn.commit()
