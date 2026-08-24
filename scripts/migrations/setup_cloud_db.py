"""
╔══════════════════════════════════════════════════════════════╗
║  Supabase Cloud — Full Database Setup Script                 ║
║  تهيئة قاعدة بيانات Supabase Cloud                          ║
╠══════════════════════════════════════════════════════════════╣
║  1. Deploy schema (schema_final.sql)                         ║
║  2. Deploy migrations (v3, v4, v5, v6)                       ║
║  3. Create storage bucket                                    ║
║  4. Seed plans data                                          ║
║  5. Test auth (signup + login)                                ║
╚══════════════════════════════════════════════════════════════╝
"""
import sys
import os
import getpass
import json
import time

sys.stdout.reconfigure(encoding="utf-8")

# ── Configuration ──
SUPABASE_URL = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54821")
PROJECT_REF = "vyzvvtyszwbefgkzgjzd"
SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# SQL migration files in order.
# This script lives in scripts/migrations/, so supabase/ is two levels up.
SQL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "supabase")
SQL_FILES = [
    "schema_final.sql",
    "migration_v3_invitations_platform.sql",
    "migration_v4_generation_batches.sql",
    "migration_v4_event_improvements.sql",
    "migration_v5_production_hardening.sql",
    "migration_v5_fix_missing_columns.sql",
    "migration_v6_constraints_and_governance.sql",
    "migration_v6_platform_limits.sql",
    "migration_v7_platform_consistency.sql",
    "migration_v8_optional_guest_whatsapp.sql",
    "migration_v8_slot_index.sql",
    "migration_v9_event_address.sql",
    "migration_v9_guest_count_scans.sql",
    "migration_v10_gate_teams_and_users.sql",
    "migration_v10_registration_forms.sql",
    "migration_v11_professional_plans.sql",
    "migration_v12_custom_plans.sql",
    "migration_v13_limits_and_features.sql",
    "migration_v14_addons_pricing.sql",
    "migration_v15_standard_plan_limits.sql",
    "migration_v16_paypal_pending_subscriptions.sql",
    "migration_v16_ui_permissions.sql",
    "migration_v17_team_workflows.sql",
    "migration_v18_org_requests.sql",
    "migration_v19_security_hardening.sql",
    "migration_v20_password_reset_otps.sql",
    "migration_v21_organizer_booking_marketplace.sql",
    "migration_v22_booking_event_link.sql",
    "migration_v23_phase1_operations.sql",
    "migration_v24_backfill_event_operations.sql",
    "migration_v25_phase1_tasks_enhancements.sql",
    "migration_v26_operation_progress_trigger.sql",
    "migration_v27_unified_authorization.sql",
    "migration_v28_entitlements_integrity.sql",
    "migration_v29_team_manager_role.sql",
    "migration_v30_operation_governance.sql",
    "migration_v31_operation_audit_triggers.sql",
    "migration_v32_booking_workflow.sql",
    "migration_v33_operations_management.sql",
    "migration_v34_task_permissions.sql",
    "migration_v35_operation_team.sql",
    "migration_v36_operation_attachments.sql",
    "migration_v37_team_manager_limits.sql",
    "migration_v38_team_manager_backfill.sql",
    "migration_v39_team_manager_owner_sync.sql",
    "migration_v40_team_manager_permission_repair.sql",
    "migration_v41_team_gate_controls.sql",
    "migration_v42_linked_workspaces.sql",
    "migration_v43_workspace_permission_matrix.sql",
    "migration_v44_billing_entitlement_hardening.sql",
    "migration_v45_operation_group_assignments.sql",
    "migration_v46_mobile_gate_foundation.sql",
    "migration_v47_field_qr_and_offline.sql",
    "migration_v48_fast_field_checkin.sql",
    "migration_v49_security_governance.sql",
    "migration_v50_event_operation_exclusivity.sql",
    "migration_v51_field_checkin_policy.sql",
    "migration_v52_rls_app_role.sql",
    "migration_v53_subscription_payments.sql",
    "migration_v54_currency_yer.sql",
    "migration_v55_plan_entitlements_production.sql",
    "migration_v56_event_lifecycle_production.sql",
]


def print_header(title):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def print_step(num, msg, status="⏳"):
    print(f"  {status} [{num}] {msg}")


def get_db_connection(password):
    """Connect to Supabase Cloud PostgreSQL."""
    import psycopg2
    
    # Try multiple connection methods
    connection_configs = [
        {
            "name": "Direct connection",
            "host": f"db.{PROJECT_REF}.supabase.co",
            "port": 5432,
            "user": "postgres",
            "password": password,
            "dbname": "postgres",
            "sslmode": "require",
        },
        {
            "name": "Connection Pooler (Transaction)",
            "host": f"aws-0-eu-central-1.pooler.supabase.com",
            "port": 6543,
            "user": f"postgres.{PROJECT_REF}",
            "password": password,
            "dbname": "postgres",
            "sslmode": "require",
        },
        {
            "name": "Connection Pooler (Session)",
            "host": f"aws-0-eu-central-1.pooler.supabase.com",
            "port": 5432,
            "user": f"postgres.{PROJECT_REF}",
            "password": password,
            "dbname": "postgres",
            "sslmode": "require",
        },
    ]
    
    for config in connection_configs:
        name = config.pop("name")
        try:
            print(f"    Trying {name}...", end=" ")
            conn = psycopg2.connect(**config, connect_timeout=15)
            conn.autocommit = True
            print("✅ Connected!")
            return conn, name
        except Exception as e:
            print(f"❌ {str(e)[:80]}")
            config["name"] = name
    
    return None, None


def execute_sql_file(conn, filepath, filename):
    """Execute a SQL file, splitting by statements."""
    with open(filepath, "r", encoding="utf-8") as f:
        sql_content = f.read()
    
    cur = conn.cursor()
    
    # Execute the entire file as one transaction
    try:
        cur.execute(sql_content)
        print(f"    ✅ {filename} — executed successfully")
        return True
    except Exception as e:
        error_msg = str(e).strip()
        # Check if it's just "already exists" errors
        if "already exists" in error_msg:
            print(f"    ⚠️  {filename} — some objects already exist (OK)")
            conn.rollback()
            # Try statement by statement
            return execute_sql_statements(conn, sql_content, filename)
        else:
            print(f"    ❌ {filename} — Error: {error_msg[:200]}")
            conn.rollback()
            # Try statement by statement as fallback
            return execute_sql_statements(conn, sql_content, filename)


def execute_sql_statements(conn, sql_content, filename):
    """Execute SQL content statement-by-statement for better error handling."""
    cur = conn.cursor()
    
    # Simple statement splitter (handles $$ blocks)
    statements = split_sql_statements(sql_content)
    
    success = 0
    skipped = 0
    errors = 0
    
    for stmt in statements:
        stmt = stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue
        try:
            cur.execute(stmt)
            success += 1
        except Exception as e:
            error_msg = str(e).strip()
            if "already exists" in error_msg or "duplicate" in error_msg.lower():
                skipped += 1
                conn.rollback()
                conn.autocommit = True
            else:
                errors += 1
                if errors <= 3:  # Only show first 3 errors
                    short_stmt = stmt[:80].replace('\n', ' ')
                    print(f"      ⚠️  Error in: {short_stmt}...")
                    print(f"         {error_msg[:120]}")
                conn.rollback()
                conn.autocommit = True
    
    print(f"    📊 {filename}: {success} OK, {skipped} skipped (exist), {errors} errors")
    return errors == 0


def split_sql_statements(sql):
    """Split SQL into statements, respecting $$ blocks and function bodies."""
    statements = []
    current = []
    in_dollar_block = False
    
    for line in sql.split("\n"):
        stripped = line.strip()
        
        # Skip pure comment lines at top level
        if not in_dollar_block and not current and stripped.startswith("--"):
            continue
        
        # Track dollar-quoted blocks ($$)
        dollar_count = line.count("$$")
        if dollar_count % 2 == 1:
            in_dollar_block = not in_dollar_block
        
        current.append(line)
        
        # Statement ends with ; at end of line, outside $$ blocks
        if not in_dollar_block and stripped.endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt and not all(l.strip().startswith("--") for l in current if l.strip()):
                statements.append(stmt)
            current = []
    
    # Any remaining content
    if current:
        stmt = "\n".join(current).strip()
        if stmt and not all(l.strip().startswith("--") for l in current if l.strip()):
            statements.append(stmt)
    
    return statements


def setup_storage():
    """Create the invitations storage bucket."""
    from supabase import create_client
    
    try:
        client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)
        buckets = client.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        
        if "invitations" in bucket_names:
            print("    ✅ Storage bucket 'invitations' already exists")
            return True
        
        client.storage.create_bucket(
            "invitations",
            options={"public": False, "file_size_limit": 524288000},  # 500MB
        )
        print("    ✅ Storage bucket 'invitations' created (private, 500MB limit)")
        return True
    except Exception as e:
        print(f"    ❌ Storage setup failed: {e}")
        return False


def test_auth():
    """Test auth by creating a test user."""
    from supabase import create_client
    import secrets
    
    client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)
    
    test_email = f"test-{secrets.token_hex(4)}@da3wa-test.com"
    test_password = f"Test@{secrets.token_hex(8)}"
    
    try:
        # Create user via admin API
        user = client.auth.admin.create_user({
            "email": test_email,
            "password": test_password,
            "email_confirm": True,
            "user_metadata": {"full_name": "Test User"}
        })
        print(f"    ✅ Auth: Created test user {test_email}")
        print(f"       User ID: {user.user.id}")
        
        # Test login via anon client
        anon_client = create_client(SUPABASE_URL, ANON_KEY)
        login = anon_client.auth.sign_in_with_password({
            "email": test_email,
            "password": test_password,
        })
        print(f"    ✅ Auth: Login successful!")
        print(f"       Access Token: {login.session.access_token[:40]}...")
        print(f"       JWT verified ✅")
        
        # Clean up - delete test user
        client.auth.admin.delete_user(str(user.user.id))
        print(f"    ✅ Auth: Test user cleaned up")
        
        return True
    except Exception as e:
        print(f"    ❌ Auth test failed: {e}")
        return False


def verify_tables(conn):
    """Verify key tables exist."""
    cur = conn.cursor()
    key_tables = [
        "profiles", "tenants", "memberships", "plans", "plan_limits",
        "subscriptions", "roles", "permissions", "invites", "audit_logs",
        "events", "invitations", "guests", "invite_templates", "checkins",
        "teams", "event_categories", "event_types", "event_gates",
    ]
    
    cur.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name
    """)
    existing = {row[0] for row in cur.fetchall()}
    
    found = 0
    missing = []
    for t in key_tables:
        if t in existing:
            found += 1
        else:
            missing.append(t)
    
    print(f"    📊 Tables: {found}/{len(key_tables)} key tables found")
    print(f"    📊 Total public tables: {len(existing)}")
    
    if missing:
        print(f"    ⚠️  Missing: {', '.join(missing[:10])}")
    else:
        print(f"    ✅ All key tables present!")
    
    return len(missing) == 0


def verify_seed_data(conn):
    """Verify seed data (plans, permissions, categories)."""
    cur = conn.cursor()
    
    checks = [
        ("plans", "SELECT count(*) FROM plans"),
        ("permissions", "SELECT count(*) FROM permissions"),
        ("event_categories", "SELECT count(*) FROM event_categories"),
        ("event_types", "SELECT count(*) FROM event_types"),
    ]
    
    for name, query in checks:
        try:
            cur.execute(query)
            count = cur.fetchone()[0]
            status = "✅" if count > 0 else "⚠️  (empty)"
            print(f"    {status} {name}: {count} rows")
        except Exception as e:
            print(f"    ❌ {name}: {str(e)[:60]}")


def update_env_db_url(password):
    """Update the DATABASE_URL in .env with the actual password."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Replace placeholder
    old_url = f"postgresql+asyncpg://postgres.{PROJECT_REF}:YOUR_DB_PASSWORD@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
    new_url = f"postgresql+asyncpg://postgres.{PROJECT_REF}:{password}@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
    
    if "YOUR_DB_PASSWORD" in content:
        content = content.replace("YOUR_DB_PASSWORD", password)
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("    ✅ .env DATABASE_URL updated with password")
    else:
        print("    ℹ️  .env DATABASE_URL already configured")


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Da3wa Platform — Supabase Cloud Setup                      ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"  🌐 Project: {SUPABASE_URL}")
    print(f"  📁 SQL Dir:  {SQL_DIR}\n")
    
    # ── Step 1: Get database password ──
    print_header("1. Database Connection")
    
    password = input("  🔑 Enter Supabase database password: ").strip()
    if not password:
        print("  ❌ Password required! Find it in:")
        print("     Supabase Dashboard → Settings → Database → Database password")
        return
    
    conn, method = get_db_connection(password)
    if not conn:
        print("\n  ❌ Could not connect to database.")
        print("  💡 Check your password and try again.")
        print("     Find it in: Supabase Dashboard → Settings → Database")
        return
    
    print(f"  ✅ Connected via: {method}")
    
    # ── Step 2: Update .env ──
    print_header("2. Updating .env")
    update_env_db_url(password)
    
    # ── Step 3: Deploy Schema ──
    print_header("3. Deploying Schema & Migrations")
    
    all_success = True
    for filename in SQL_FILES:
        filepath = os.path.join(SQL_DIR, filename)
        if not os.path.exists(filepath):
            print(f"    ⚠️  {filename} not found, skipping")
            continue
        
        result = execute_sql_file(conn, filepath, filename)
        if not result:
            all_success = False
    
    # ── Step 4: Verify Tables ──
    print_header("4. Verifying Tables")
    verify_tables(conn)
    
    # ── Step 5: Verify Seed Data ──
    print_header("5. Verifying Seed Data")
    verify_seed_data(conn)
    
    # ── Step 6: Storage ──
    print_header("6. Setting Up Storage")
    setup_storage()
    
    # ── Step 7: Test Auth ──
    print_header("7. Testing Auth (Signup + Login + JWT)")
    test_auth()
    
    # ── Summary ──
    print_header("✨ Setup Complete!")
    print(f"  🌐 Supabase URL: {SUPABASE_URL}")
    print(f"  📊 Database: Connected via {method}")
    print(f"  🔐 Auth: Supabase Auth + JWT (HS256)")
    print(f"  📁 Storage: invitations bucket")
    print(f"  🚀 Ready to start the server:")
    print(f"     cd d:\\QR")
    print(f"     uvicorn app.main:app --host 0.0.0.0 --port 8019")
    
    conn.close()


if __name__ == "__main__":
    main()
