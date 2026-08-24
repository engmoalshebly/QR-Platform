"""Authorization regression tests for invitation lifecycle mutations."""
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_viewer_cannot_mutate_invitation_lifecycle_fields(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """A read-only viewer cannot change RSVP/status or group attendance counts."""
    from app.middleware import TenantResolutionMiddleware

    async def _transactional_tenant_context(_middleware, _request, call_next):
        return await call_next(_request)

    monkeypatch.setattr(TenantResolutionMiddleware, "dispatch", _transactional_tenant_context)

    viewer_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, 'viewer-invitation@example.com', 'authenticated', 'authenticated', now(),
                '00000000-0000-0000-0000-000000000000')
    """), {"id": str(viewer_id)})
    await db_session.execute(text("""
        INSERT INTO profiles (id, full_name) VALUES (:id, 'مشاهد الدعوات')
        ON CONFLICT (id) DO NOTHING
    """), {"id": str(viewer_id)})
    await db_session.execute(text("""
        INSERT INTO memberships (tenant_id, user_id, role, status)
        VALUES (:tenant_id, :user_id, 'member', 'active')
    """), {"tenant_id": str(org_world["requester_tenant"]), "user_id": str(viewer_id)})
    viewer_role = (await db_session.execute(text("""
        INSERT INTO roles (tenant_id, name, description, is_system_role)
        VALUES (:tenant_id, 'Invitation Read-only', 'عرض الدعوات فقط', FALSE)
        RETURNING id
    """), {"tenant_id": str(org_world["requester_tenant"])})).scalar_one()
    await db_session.execute(text("""
        INSERT INTO role_permissions (role_id, permission_key)
        VALUES (:role_id, 'invitations.view')
    """), {"role_id": str(viewer_role)})
    await db_session.execute(text("""
        INSERT INTO membership_roles (tenant_id, user_id, role_id)
        VALUES (:tenant_id, :user_id, :role_id)
    """), {
        "tenant_id": str(org_world["requester_tenant"]),
        "user_id": str(viewer_id),
        "role_id": str(viewer_role),
    })

    invitation_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO invitations (id, tenant_id, event_id, token, ticket_class, guest_count, status)
        VALUES (:id, :tenant_id, :event_id, :token, 'normal', 1, 'sent')
    """), {
        "id": str(invitation_id),
        "tenant_id": str(org_world["requester_tenant"]),
        "event_id": str(org_world["event_id"]),
        "token": f"viewer-mutation-{uuid4().hex}",
    })

    async with client_factory(viewer_id) as client:
        response = await client.patch(
            f"/api/v1/invitations/{invitation_id}",
            json={"guest_count": 99, "rsvp_status": "accepted"},
            headers=auth_headers(org_world["requester_tenant"]),
        )

    assert response.status_code == 403
    invitation = (await db_session.execute(text("""
        SELECT guest_count, rsvp_status FROM invitations WHERE id = :id
    """), {"id": str(invitation_id)})).mappings().one()
    assert invitation["guest_count"] == 1
    assert invitation["rsvp_status"] == "pending"
