"""Acceptance coverage for the organizer application approval lifecycle."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.auth import CurrentUser, get_current_user
from app.database import get_db
from app.main import app


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_platform_approval_provisions_linked_organizer_workspaces(db_session, monkeypatch):
    """Approval must produce one authenticated owner and the two linked workspaces."""
    from app.routes import platform as platform_routes

    staff_id, applicant_id, request_id = uuid4(), uuid4(), uuid4()
    staff_email = f"staff-{staff_id}@example.com"
    applicant_email = f"organizer-{applicant_id}@example.com"
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES
          (:staff_id, :staff_email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000'),
          (:applicant_id, :applicant_email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
    """), {
        "staff_id": str(staff_id), "staff_email": staff_email,
        "applicant_id": str(applicant_id), "applicant_email": applicant_email,
    })
    await db_session.execute(text("UPDATE profiles SET is_staff = true WHERE id = :id"), {"id": str(staff_id)})
    await db_session.execute(text("""
        INSERT INTO organization_requests
          (id, full_name, email, phone, org_name, org_type, requested_plan_code, created_user_id)
        VALUES (:id, 'صاحب فريق الاختبار', :email, '0500000000', 'فريق اختبار الاعتماد',
                'تنظيم فعاليات', 'starter', :user_id)
    """), {"id": str(request_id), "email": applicant_email, "user_id": str(applicant_id)})

    auth_updates = []

    class FakeAuthAdmin:
        def update_user_by_id(self, user_id, payload):
            auth_updates.append((str(user_id), payload))
            return {"id": str(user_id)}

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        platform_routes,
        "get_supabase_admin",
        lambda: SimpleNamespace(auth=SimpleNamespace(admin=FakeAuthAdmin())),
    )
    monkeypatch.setattr(platform_routes, "send_org_request_approved", _noop)
    app.dependency_overrides[get_db] = lambda: db_session

    async def _staff_user():
        return CurrentUser(id=staff_id, email=staff_email, role="authenticated", aal="aal2")

    app.dependency_overrides[get_current_user] = _staff_user
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        response = await client.post(f"/api/v1/platform/org-requests/{request_id}/approve", json={"note": "مقبول"})
        assert response.status_code == 200, response.text
        organizer_id = response.json()["created_tenant_id"]
    finally:
        await client.aclose()
        app.dependency_overrides.clear()

    assert auth_updates == [(str(applicant_id), {"email_confirm": True})]
    organizer = (await db_session.execute(text("""
        SELECT workspace_type FROM tenants WHERE id = :id
    """), {"id": organizer_id})).mappings().one()
    assert organizer["workspace_type"] == "organizer"

    link = (await db_session.execute(text("""
        SELECT institution_tenant_id, owner_user_id, billing_tenant_id
        FROM workspace_links WHERE organizer_tenant_id = :id AND status = 'active'
    """), {"id": organizer_id})).mappings().one()
    assert str(link["owner_user_id"]) == str(applicant_id)
    assert str(link["billing_tenant_id"]) == organizer_id

    memberships = (await db_session.execute(text("""
        SELECT tenant_id FROM memberships
        WHERE user_id = :user_id AND role = 'owner' AND status = 'active'
    """), {"user_id": str(applicant_id)})).scalars().all()
    assert {str(value) for value in memberships} == {organizer_id, str(link["institution_tenant_id"])}

    team_manager = await db_session.scalar(text("""
        SELECT 1
        FROM membership_roles mr
        JOIN roles r ON r.id = mr.role_id
        WHERE mr.tenant_id = :tenant_id AND mr.user_id = :user_id AND r.name = 'team_manager'
    """), {"tenant_id": organizer_id, "user_id": str(applicant_id)})
    assert team_manager == 1

    request_row = (await db_session.execute(text("""
        SELECT status, created_tenant_id, institution_tenant_id, password_encrypted
        FROM organization_requests WHERE id = :id
    """), {"id": str(request_id)})).mappings().one()
    assert request_row["status"] == "approved"
    assert str(request_row["created_tenant_id"]) == organizer_id
    assert str(request_row["institution_tenant_id"]) == str(link["institution_tenant_id"])
    assert request_row["password_encrypted"] is None
