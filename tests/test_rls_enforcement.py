"""PostgreSQL row-level security, exercised as the application role.

These tests switch the transactional session to ``qentry_app`` with
``SET LOCAL ROLE``, so the policies from migration v61 decide what is visible.
The seed rows are uncommitted and the transaction is rolled back, so nothing
leaks into other tests.

Requires a superuser or a member of qentry_app for the test connection (true for
the CI postgres service).  Production never runs these tests.
"""
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _insert_tenant(db: AsyncSession, name: str) -> str:
    tid = str(uuid4())
    await db.execute(text("""
        INSERT INTO tenants (id, name, slug, status, plan)
        VALUES (:id, :name, :slug, 'active', 'professional')
    """), {"id": tid, "name": name, "slug": f"rls-{tid[:8]}"})
    return tid


async def _insert_event(db: AsyncSession, tenant_id: str, title: str) -> str:
    eid = str(uuid4())
    await db.execute(text("""
        INSERT INTO events (id, tenant_id, title, start_date, status)
        VALUES (:id, :tid, :title, now(), 'draft')
    """), {"id": eid, "tid": tenant_id, "title": title})
    return eid


async def _insert_operation(db: AsyncSession, requester: str, provider: str, event_id: str) -> str:
    oid = str(uuid4())
    manager = str(uuid4())
    await db.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, :email, 'authenticated', 'authenticated', now(),
                '00000000-0000-0000-0000-000000000000')
        ON CONFLICT DO NOTHING
    """), {"id": manager, "email": f"pm-{manager[:8]}@test.com"})
    await db.execute(text(
        "INSERT INTO profiles (id, full_name) VALUES (:id, 'Project manager') ON CONFLICT DO NOTHING"
    ), {"id": manager})
    await db.execute(text("""
        INSERT INTO event_operations
          (id, event_id, requester_tenant_id, provider_tenant_id, project_manager_id,
           status, progress, priority, last_modified_at, created_at, updated_at)
        VALUES (:id, :event, :req, :prov, :pm, 'planning', 0, 'medium', now(), now(), now())
    """), {"id": oid, "event": event_id, "req": requester, "prov": provider, "pm": manager})
    return oid


async def _act_as(db: AsyncSession, tenant_id: str | None) -> None:
    """Become the application role with the given tenant context."""
    await db.execute(text("SET LOCAL ROLE qentry_app"))
    await db.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"),
                     {"t": tenant_id or ""})


@pytest_asyncio.fixture
async def two_orgs(db_session: AsyncSession):
    a = await _insert_tenant(db_session, "Org A")
    b = await _insert_tenant(db_session, "Org B")
    event_a = await _insert_event(db_session, a, "Event of A")
    event_b = await _insert_event(db_session, b, "Event of B")
    await db_session.flush()
    return {"a": a, "b": b, "event_a": event_a, "event_b": event_b}


@pytest.mark.asyncio
async def test_no_tenant_context_sees_no_rows(db_session, two_orgs):
    await _act_as(db_session, None)
    count = (await db_session.execute(text("SELECT count(*) FROM events"))).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_tenant_sees_only_its_own_rows(db_session, two_orgs):
    await _act_as(db_session, two_orgs["a"])
    ids = {str(r[0]) for r in (await db_session.execute(text("SELECT id FROM events"))).all()}
    assert str(two_orgs["event_a"]) in ids
    assert str(two_orgs["event_b"]) not in ids


@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenant_by_id(db_session, two_orgs):
    await _act_as(db_session, two_orgs["a"])
    count = (await db_session.execute(
        text("SELECT count(*) FROM events WHERE id = :id"), {"id": two_orgs["event_b"]}
    )).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_tenant_cannot_insert_rows_for_another_tenant(db_session, two_orgs):
    await _act_as(db_session, two_orgs["a"])
    with pytest.raises(Exception, match="row-level security"):
        await db_session.execute(text("""
            INSERT INTO events (id, tenant_id, title, start_date, status)
            VALUES (:id, :tid, 'forged', now(), 'draft')
        """), {"id": str(uuid4()), "tid": two_orgs["b"]})


@pytest.mark.asyncio
async def test_tenant_cannot_update_or_delete_another_tenant(db_session, two_orgs):
    await _act_as(db_session, two_orgs["a"])
    updated = (await db_session.execute(
        text("UPDATE events SET title = 'hacked' WHERE id = :id"), {"id": two_orgs["event_b"]}
    )).rowcount
    deleted = (await db_session.execute(
        text("DELETE FROM events WHERE id = :id"), {"id": two_orgs["event_b"]}
    )).rowcount
    assert updated == 0 and deleted == 0


@pytest.mark.asyncio
async def test_provider_sees_only_the_event_it_operates(db_session, two_orgs):
    """Operations scope access to one event.  The provider does not see the
    requester's other events, and cannot change the requester's data."""
    a, b = two_orgs["a"], two_orgs["b"]
    not_operated = await _insert_event(db_session, a, "Not operated")
    await _insert_operation(db_session, requester=a, provider=b, event_id=two_orgs["event_a"])
    await db_session.flush()

    await _act_as(db_session, b)
    visible = {str(r[0]) for r in (await db_session.execute(text("SELECT id FROM events"))).all()}
    assert str(two_orgs["event_a"]) in visible, "provider cannot read the event it operates"
    assert str(not_operated) not in visible, "provider reads a requester event it does not operate"

    edited = (await db_session.execute(
        text("UPDATE events SET title = 'provider edit' WHERE id = :id"), {"id": two_orgs["event_a"]}
    )).rowcount
    assert edited == 1, "provider cannot update rows of the event it operates"


@pytest.mark.asyncio
async def test_provider_cannot_write_into_requester_tenant_outside_operation(db_session, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    await _insert_operation(db_session, requester=a, provider=b, event_id=two_orgs["event_a"])
    await db_session.flush()

    await _act_as(db_session, b)
    with pytest.raises(Exception, match="row-level security"):
        await db_session.execute(text("""
            INSERT INTO events (id, tenant_id, title, start_date, status)
            VALUES (:id, :tid, 'injected', now(), 'draft')
        """), {"id": str(uuid4()), "tid": a})


@pytest.mark.asyncio
async def test_operation_rows_are_visible_to_both_parties_only(db_session, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    third = await _insert_tenant(db_session, "Uninvolved")
    op = await _insert_operation(db_session, requester=a, provider=b, event_id=two_orgs["event_a"])
    await db_session.flush()

    await _act_as(db_session, a)
    assert (await db_session.execute(
        text("SELECT count(*) FROM event_operations WHERE id = :id"), {"id": op})).scalar() == 1

    await _act_as(db_session, third)
    assert (await db_session.execute(
        text("SELECT count(*) FROM event_operations WHERE id = :id"), {"id": op})).scalar() == 0


@pytest.mark.asyncio
async def test_application_role_cannot_bypass_rls(db_session):
    row = (await db_session.execute(text("""
        SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'qentry_app'
    """))).first()
    assert row is not None and row.rolbypassrls is False and row.rolsuper is False


@pytest.mark.asyncio
async def test_every_tenant_table_has_forced_rls(db_session):
    unprotected = (await db_session.execute(text("""
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND EXISTS (SELECT 1 FROM information_schema.columns col
                      WHERE col.table_schema = 'public' AND col.table_name = c.relname
                        AND col.column_name = 'tenant_id')
          AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
    """))).scalars().all()
    assert unprotected == [], f"tenant tables without forced RLS: {unprotected}"


@pytest.mark.asyncio
async def test_legacy_public_policies_are_gone(db_session):
    legacy = (await db_session.execute(text("""
        SELECT tablename, policyname FROM pg_policies
        WHERE schemaname = 'public' AND 'public' = ANY(roles)
          AND policyname NOT LIKE 'tenant_%'
          AND tablename IN ('events', 'guests', 'memberships')
    """))).all()
    assert legacy == [], f"legacy policies still present: {legacy}"


async def _insert_guest_invited_to(db: AsyncSession, tenant: str, event: str, name: str) -> str:
    guest = str(uuid4())
    await db.execute(text("""
        INSERT INTO guests (id, tenant_id, full_name, phone)
        VALUES (:id, :tid, :name, :phone)
    """), {"id": guest, "tid": tenant, "name": name, "phone": f"05{uuid4().int % 10**8:08d}"})
    await db.execute(text("""
        INSERT INTO invitations (id, tenant_id, event_id, guest_id, status, guest_name, guest_phone)
        VALUES (:id, :tid, :eid, :gid, 'created', :name, :phone)
    """), {"id": str(uuid4()), "tid": tenant, "eid": event, "gid": guest, "name": name,
           "phone": f"05{uuid4().int % 10**8:08d}"})
    return guest


@pytest.mark.asyncio
async def test_provider_reads_guests_invited_to_operated_event_only(db_session, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    operated_guest = await _insert_guest_invited_to(db_session, a, two_orgs["event_a"], "Operated guest")
    other_event = await _insert_event(db_session, a, "Other")
    unrelated_guest = await _insert_guest_invited_to(db_session, a, other_event, "Unrelated guest")
    await _insert_operation(db_session, requester=a, provider=b, event_id=two_orgs["event_a"])
    await db_session.flush()

    await _act_as(db_session, b)
    visible = {str(r[0]) for r in (await db_session.execute(text("SELECT id FROM guests"))).all()}
    assert operated_guest in visible
    assert unrelated_guest not in visible

    edited = (await db_session.execute(
        text("UPDATE guests SET full_name = 'changed' WHERE id = :id"), {"id": operated_guest}
    )).rowcount
    assert edited == 0, "provider must not edit guest records owned by the requester"


# ── migration v62: notification fan-out and linked-workspace billing ──

async def _insert_booking(db: AsyncSession, requester: str, provider: str, requested_by: str) -> str:
    await db.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, :email, 'authenticated', 'authenticated', now(),
                '00000000-0000-0000-0000-000000000000')
        ON CONFLICT DO NOTHING
    """), {"id": requested_by, "email": f"requester-{requested_by[:8]}@test.com"})
    await db.execute(text(
        "INSERT INTO profiles (id, full_name) VALUES (:id, 'Requester') ON CONFLICT DO NOTHING"
    ), {"id": requested_by})
    bid = str(uuid4())
    await db.execute(text("""
        INSERT INTO organizer_booking_requests
          (id, requester_tenant_id, provider_tenant_id, requested_by, title, event_type,
           starts_at, ends_at, guest_count, contact_name, contact_phone, status)
        VALUES (:id, :req, :prov, :by, 'Test booking', 'wedding',
                now() + interval '1 day', now() + interval '1 day 4 hours', 100,
                'Contact', '0500000000', 'pending')
    """), {"id": bid, "req": requester, "prov": provider, "by": requested_by})
    return bid


async def _link_workspaces(db: AsyncSession, organizer: str, institution: str, owner_user: str) -> None:
    await db.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, :email, 'authenticated', 'authenticated', now(),
                '00000000-0000-0000-0000-000000000000')
        ON CONFLICT DO NOTHING
    """), {"id": owner_user, "email": f"owner-{owner_user[:8]}@test.com"})
    await db.execute(text(
        "INSERT INTO profiles (id, full_name) VALUES (:id, 'Owner') ON CONFLICT DO NOTHING"
    ), {"id": owner_user})
    await db.execute(text("""
        INSERT INTO workspace_links (organizer_tenant_id, institution_tenant_id, owner_user_id, billing_tenant_id, status)
        VALUES (:org, :inst, :owner, :inst, 'active')
    """), {"org": organizer, "inst": institution, "owner": owner_user})


@pytest.mark.asyncio
async def test_notification_fan_out_to_booking_counterparty_is_allowed(db_session, two_orgs):
    """Requester creates a booking, then notifies the provider's managers —
    exactly what app/routes/bookings.py does right after INSERT."""
    a, b = two_orgs["a"], two_orgs["b"]
    booking_id = await _insert_booking(db_session, requester=a, provider=b, requested_by=str(uuid4()))
    await db_session.flush()

    await _act_as(db_session, a)
    await db_session.execute(text("""
        INSERT INTO notifications (tenant_id, type, title, message)
        VALUES (:tid, 'booking.created', 'New booking', 'details')
    """), {"tid": b})  # provider is the counterparty, not the acting tenant


@pytest.mark.asyncio
async def test_notification_to_an_unrelated_tenant_is_still_blocked(db_session, two_orgs):
    a = two_orgs["a"]
    unrelated = await _insert_tenant(db_session, "Unrelated")
    await db_session.flush()

    await _act_as(db_session, a)
    with pytest.raises(Exception, match="row-level security"):
        await db_session.execute(text("""
            INSERT INTO notifications (tenant_id, type, title, message)
            VALUES (:tid, 'spam', 'x', 'y')
        """), {"tid": unrelated})


@pytest.mark.asyncio
async def test_linked_workspace_shares_usage_counters(db_session, two_orgs):
    """app/services/usage_service.py reads/writes usage_counters keyed by the
    billing tenant, which may be the organizer's linked institution."""
    organizer, institution = two_orgs["a"], two_orgs["b"]
    owner = str(uuid4())
    await _link_workspaces(db_session, organizer, institution, owner)
    # Seeded before switching role: qentry_app may not create a tenant.
    unrelated = await _insert_tenant(db_session, "Unrelated")
    await db_session.flush()

    await _act_as(db_session, organizer)
    await db_session.execute(text("""
        INSERT INTO usage_counters (tenant_id, period_start, period_end, key, value)
        VALUES (:tid, '1970-01-01', '2099-12-31', 'storage_bytes', 10)
        ON CONFLICT (tenant_id, period_start, key) DO UPDATE SET value = usage_counters.value + 10
    """), {"tid": institution})
    total = (await db_session.execute(text(
        "SELECT value FROM usage_counters WHERE tenant_id = :tid AND key = 'storage_bytes'"
    ), {"tid": institution})).scalar()
    assert total == 10

    await _act_as(db_session, unrelated)
    with pytest.raises(Exception, match="row-level security"):
        await db_session.execute(text("""
            INSERT INTO usage_counters (tenant_id, period_start, period_end, key, value)
            VALUES (:tid, '1970-01-01', '2099-12-31', 'storage_bytes', 999)
        """), {"tid": institution})


@pytest.mark.asyncio
async def test_linked_workspace_shares_subscriptions_and_custom_plans(db_session, two_orgs):
    organizer, institution = two_orgs["a"], two_orgs["b"]
    owner = str(uuid4())
    await _link_workspaces(db_session, organizer, institution, owner)
    plan_id = (await db_session.execute(text("SELECT id FROM plans LIMIT 1"))).scalar()
    await db_session.flush()
    if plan_id is None:
        pytest.skip("no seeded plan rows in this database")

    await _act_as(db_session, organizer)
    await db_session.execute(text("""
        INSERT INTO subscriptions (tenant_id, plan_id, status, current_period_start, current_period_end)
        VALUES (:tid, :pid, 'active', now(), now() + interval '30 days')
    """), {"tid": institution, "pid": plan_id})
    found = (await db_session.execute(
        text("SELECT count(*) FROM subscriptions WHERE tenant_id = :tid"), {"tid": institution}
    )).scalar()
    assert found == 1


@pytest.mark.asyncio
async def test_linked_workspace_reads_members_and_invites_for_seat_counting(db_session, two_orgs):
    organizer, institution = two_orgs["a"], two_orgs["b"]
    owner = str(uuid4())
    await _link_workspaces(db_session, organizer, institution, owner)
    await db_session.execute(text("""
        INSERT INTO memberships (tenant_id, user_id, role, status) VALUES (:tid, :uid, 'owner', 'active')
    """), {"tid": institution, "uid": owner})
    await db_session.flush()

    await _act_as(db_session, organizer)
    seats = (await db_session.execute(text("""
        SELECT COUNT(DISTINCT user_id) FROM memberships
        WHERE tenant_id = ANY(ARRAY[:a, :b]::uuid[]) AND status = 'active'
    """), {"a": organizer, "b": institution})).scalar()
    assert seats >= 1, "the linked institution's owner membership must be readable"

    # Writing a membership into the partner tenant is still refused.
    with pytest.raises(Exception, match="row-level security"):
        await db_session.execute(text("""
            INSERT INTO memberships (tenant_id, user_id, role, status)
            VALUES (:tid, :uid, 'member', 'active')
        """), {"tid": institution, "uid": str(uuid4())})


@pytest.mark.asyncio
async def test_audit_log_can_record_a_linked_billing_action(db_session, two_orgs):
    organizer, institution = two_orgs["a"], two_orgs["b"]
    owner = str(uuid4())
    await _link_workspaces(db_session, organizer, institution, owner)
    await db_session.flush()

    await _act_as(db_session, organizer)
    await db_session.execute(text("""
        INSERT INTO audit_logs (tenant_id, actor_user_id, action, resource_type, resource_id)
        VALUES (:tid, :actor, 'subscription.create', 'subscription', :rid)
    """), {"tid": institution, "actor": owner, "rid": str(uuid4())})


@pytest.mark.asyncio
async def test_tenant_can_read_and_update_its_own_row(db_session, two_orgs):
    """app/routes/tenants.py: GET and PATCH /api/v1/tenants/current must work for
    every tenant, not only ones with a booking, operation or billing link."""
    a = two_orgs["a"]
    await _act_as(db_session, a)
    name = (await db_session.execute(text("SELECT name FROM tenants WHERE id = :id"), {"id": a})).scalar()
    assert name == "Org A"

    updated = (await db_session.execute(
        text("UPDATE tenants SET name = 'Org A renamed' WHERE id = :id"), {"id": a}
    )).rowcount
    assert updated == 1


@pytest.mark.asyncio
async def test_tenant_cannot_read_or_update_an_unrelated_tenant_row(db_session, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    await _act_as(db_session, a)
    invisible = (await db_session.execute(text("SELECT name FROM tenants WHERE id = :id"), {"id": b})).scalar()
    assert invisible is None

    updated = (await db_session.execute(
        text("UPDATE tenants SET name = 'hacked' WHERE id = :id"), {"id": b}
    )).rowcount
    assert updated == 0


# ── migration v63: tables that must never carry a tenant_id-based RLS policy ──

NON_TENANT_READABLE_TABLES = (
    "plans", "profiles", "permissions", "role_permissions", "plan_limits", "plan_addons",
    "plan_features", "checkins", "event_gates", "team_memberships",
    "template_assets", "template_elements", "event_assets", "invitation_deliveries",
    "subscription_events",
)


@pytest.mark.asyncio
async def test_global_and_child_tables_are_readable_by_application_role(db_session):
    """These tables carry no tenant_id; isolation for them is enforced by the
    application (ADR-0001), not by RLS.  A stale legacy policy that blocks the
    application role entirely is worse than no RLS: it breaks ordinary reads
    (a profile lookup, a plan resolution, a check-in list) for every tenant."""
    await db_session.execute(text("SET LOCAL ROLE qentry_app"))
    for table in NON_TENANT_READABLE_TABLES:
        await db_session.execute(text(f"SELECT count(*) FROM {table}"))  # must not raise


@pytest.mark.asyncio
async def test_no_table_outside_the_reviewed_set_still_carries_rls(db_session):
    """Guardrail for the next migration: every table with RLS enabled must be one
    we deliberately scoped (tenant-owned or the two-party tables), or `tenants`
    itself.  Anything else means a future migration re-enabled RLS on a table
    that has no policy maintained for qentry_app, which fails closed and silent."""
    reviewed = {
        "tenants",  # id-scoped: tenant_read / tenant_update only (no insert/delete)
        "event_operations", "organizer_booking_requests",  # party_* policies
        "batch_items",  # v79: derived parent tenant, forced RLS, own/operated access and composite FKs
    }
    # These reviewed migrations use one FOR ALL policy instead of four
    # per-command policies. Check the exact role and predicates; do not exempt
    # arbitrary new single-policy tables from this inventory.
    owned_all = {
        'generation_operations','generation_imports','generation_import_rows','generation_snapshot_assets',
        'generation_uploads','generation_upload_rows','generation_storage_objects',
        'generation_operation_assets','generation_outbox','generation_artifacts','generation_artifact_items',
        'whatsapp_connections','whatsapp_deliveries','whatsapp_delivery_requests',
        'whatsapp_message_images','whatsapp_message_templates','whatsapp_webhook_receipts',
    }
    for table in owned_all:
        policy = (await db_session.execute(text("SELECT cmd,roles,qual,with_check FROM pg_policies WHERE schemaname='public' AND tablename=:table"),{'table':table})).one()
        assert policy.cmd=='ALL' and policy.roles==['qentry_app'], table
        for predicate in (policy.qual,policy.with_check):
            assert predicate.replace(' ','').replace('public.','')=='(tenant_id=current_tenant_id())', table
    reviewed.update(owned_all)
    rows = (await db_session.execute(text("""
        SELECT c.relname, count(p.policyname) AS n
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_policies p ON p.schemaname = 'public' AND p.tablename = c.relname
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity
        GROUP BY c.relname
    """))).all()
    unexplained = []
    for relname, n in rows:
        if relname in reviewed or relname in NON_TENANT_READABLE_TABLES:
            continue
        has_tenant_id = (await db_session.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :t AND column_name = 'tenant_id'
        """), {"t": relname})).first()
        # A tenant_id table with the standard 4 tenant_* policies is fine; anything
        # else (0 policies, or a table with no tenant_id at all) needs a human look.
        if not has_tenant_id or n != 4:
            unexplained.append((relname, n))
    assert unexplained == [], f"tables with unreviewed RLS state: {unexplained}"


# ── migration v65: pending_subscriptions follows billing_tenant_id, resolved
# one layer above subscription_engine.py (app/routes/subscriptions.py), via a
# linked organizer/institution workspace.  SQL mirrors the real statements in
# app/services/subscription_engine.py exactly.

@pytest.mark.asyncio
async def test_pending_subscription_lifecycle_crosses_the_billing_link(db_session, two_orgs):
    organizer, institution = two_orgs["a"], two_orgs["b"]
    owner = str(uuid4())
    await _link_workspaces(db_session, organizer, institution, owner)
    plan_id = (await db_session.execute(text("SELECT id FROM plans LIMIT 1"))).scalar()
    await db_session.flush()
    if plan_id is None:
        pytest.skip("no seeded plan rows in this database")

    await _act_as(db_session, organizer)

    # initiate_subscription(): INSERT keyed by the billing tenant.
    pending_id = (await db_session.execute(text("""
        INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id)
        VALUES (:tid, :pid, 'link', :agreement)
        RETURNING id
    """), {"tid": institution, "pid": plan_id, "agreement": "pay_" + str(uuid4())[:8]})).scalar()
    assert pending_id is not None

    # _load_pending(): SELECT ... WHERE tenant_id = :tid FOR UPDATE, on confirm.
    loaded = (await db_session.execute(text("""
        SELECT id FROM pending_subscriptions
        WHERE tenant_id = :tid AND provider = 'link'
        ORDER BY created_at DESC LIMIT 1 FOR UPDATE
    """), {"tid": institution})).first()
    assert loaded is not None and str(loaded[0]) == str(pending_id), (
        "the organizer session must find the pending payment it just opened "
        "for its linked institution"
    )

    # confirm_subscription(): DELETE ... WHERE id = :id, no tenant filter at all.
    deleted = (await db_session.execute(
        text("DELETE FROM pending_subscriptions WHERE id = :id"), {"id": str(pending_id)}
    )).rowcount
    assert deleted == 1, "cleanup after a confirmed payment must actually remove the row"


@pytest.mark.asyncio
async def test_pending_subscription_is_invisible_to_an_unrelated_tenant(db_session, two_orgs):
    organizer, institution = two_orgs["a"], two_orgs["b"]
    owner = str(uuid4())
    await _link_workspaces(db_session, organizer, institution, owner)
    unrelated = await _insert_tenant(db_session, "Unrelated for pending sub")
    plan_id = (await db_session.execute(text("SELECT id FROM plans LIMIT 1"))).scalar()
    await db_session.flush()
    if plan_id is None:
        pytest.skip("no seeded plan rows in this database")

    await _act_as(db_session, organizer)
    pending_id = (await db_session.execute(text("""
        INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id)
        VALUES (:tid, :pid, 'link', :agreement)
        RETURNING id
    """), {"tid": institution, "pid": plan_id, "agreement": "pay_" + str(uuid4())[:8]})).scalar()

    await _act_as(db_session, unrelated)
    invisible = (await db_session.execute(text("""
        SELECT id FROM pending_subscriptions WHERE tenant_id = :tid AND provider = 'link'
    """), {"tid": institution})).first()
    assert invisible is None

    deleted = (await db_session.execute(
        text("DELETE FROM pending_subscriptions WHERE id = :id"), {"id": str(pending_id)}
    )).rowcount
    assert deleted == 0, "an unrelated tenant must not be able to delete another billing unit's pending payment"
