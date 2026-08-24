from pathlib import Path


def test_migration_manifest_is_complete_and_ordered():
    root = Path(__file__).parents[1]
    names = [
        "schema_final.sql",
        "migration_v3_invitations_platform.sql",
        "migration_v4_generation_batches.sql",
        "migration_v17_team_workflows.sql",
        "migration_v18_org_requests.sql",
        "migration_v19_security_hardening.sql",
        "migration_v23_phase1_operations.sql",
        "migration_v24_backfill_event_operations.sql",
        "migration_v25_phase1_tasks_enhancements.sql",
        "migration_v26_operation_progress_trigger.sql",
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
        "migration_v57_registration_form_expiry.sql",
        "migration_v58_public_event_slug_repair.sql",
        "migration_v59_registration_identity_uniqueness.sql",
    ]
    previous = -1
    for name in names:
        assert (root / "supabase" / name).exists(), name
        if "migration_v" in name:
            version = int(name.split("migration_v", 1)[1].split("_", 1)[0])
            assert version >= previous
            previous = version


def test_ci_auth_stub_supports_the_profile_creation_trigger():
    """The CI auth.users shape must support schema_final.handle_new_user."""
    source = (Path(__file__).parents[1] / "scripts" / "migrations" / "ci_migrate.py").read_text(encoding="utf-8")
    assert "raw_user_meta_data jsonb" in source
    assert '"migration_v49_security_governance.sql"' in source
    assert '"migration_v50_event_operation_exclusivity.sql"' in source
    assert '"migration_v51_field_checkin_policy.sql"' in source
    assert '"migration_v55_plan_entitlements_production.sql"' in source
    assert '"migration_v56_event_lifecycle_production.sql"' in source
    assert '"migration_v57_registration_form_expiry.sql"' in source
    assert '"migration_v58_public_event_slug_repair.sql"' in source
    assert '"migration_v59_registration_identity_uniqueness.sql"' in source


def test_event_operation_exclusivity_has_a_database_guard():
    source = (
        Path(__file__).parents[1]
        / "supabase"
        / "migration_v50_event_operation_exclusivity.sql"
    ).read_text(encoding="utf-8")
    assert "prevent_parallel_active_event_operations" in source
    assert "trg_prevent_parallel_active_event_operations" in source
    assert "pg_advisory_xact_lock" in source
    assert "status NOT IN ('completed', 'closed', 'cancelled')" in source
