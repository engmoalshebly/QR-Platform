"""Regression tests for truthful event-invitation delivery outcomes."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration


async def _noop(*_args, **_kwargs):
    """Replace entitlement/permission/audit dependencies in route tests."""


async def _disable_tenant_middleware(_request, call_next):
    return await call_next(_request)


async def _create_email_invitation(
    db_session,
    org_world,
    *,
    email="guest@example.test",
    expires_at=None,
):
    invitation_id = uuid4()
    token = f"delivery-{uuid4().hex}"
    await db_session.execute(text("""
        INSERT INTO invitations
            (id, tenant_id, event_id, token, ticket_class, guest_count,
             guest_name, guest_email, expires_at, status)
        VALUES
            (:id, :tenant_id, :event_id, :token, 'normal', 1,
             'ضيف الاختبار', :email, :expires_at, 'created')
    """), {
        "id": str(invitation_id),
        "tenant_id": str(org_world["requester_tenant"]),
        "event_id": str(org_world["event_id"]),
        "token": token,
        "email": email,
        "expires_at": expires_at,
    })
    return invitation_id, token


def _patch_route_dependencies(monkeypatch):
    """Keep the test focused on delivery state rather than plan fixtures."""
    from app.main import app
    from app.middleware import TenantResolutionMiddleware
    from app.routes import digital_invitations
    from app.services import feature_service

    # Starlette binds ``dispatch`` into ``dispatch_func`` when the middleware
    # stack is first built. Patch both forms so this remains deterministic
    # regardless of test collection/order.
    monkeypatch.setattr(
        TenantResolutionMiddleware,
        "dispatch",
        lambda _self, request, call_next: _disable_tenant_middleware(request, call_next),
    )
    middleware = app.middleware_stack
    while middleware is not None:
        if isinstance(middleware, TenantResolutionMiddleware):
            monkeypatch.setattr(middleware, "dispatch_func", _disable_tenant_middleware)
            break
        middleware = getattr(middleware, "app", None)
    monkeypatch.setattr(digital_invitations, "require_permission", _noop)
    monkeypatch.setattr(digital_invitations, "log_audit", _noop)
    monkeypatch.setattr(feature_service, "require_feature", _noop)
    monkeypatch.setattr(feature_service, "enforce_monthly_limit", _noop)
    return digital_invitations


@pytest.mark.asyncio
async def test_email_invitation_is_marked_sent_only_after_smtp_accepts(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """A successful relay handoff creates the sole allowed ``sent`` outcome."""
    route = _patch_route_dependencies(monkeypatch)
    invitation_id, token = await _create_email_invitation(db_session, org_world)
    sent_calls = []

    def _smtp_accepts(*args):
        sent_calls.append(args)
        return True

    monkeypatch.setattr(route, "is_email_delivery_configured", lambda: True)
    monkeypatch.setattr(route, "send_event_invitation_email", _smtp_accepts)

    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post(
            "/api/v1/invitations/send",
            json={"invitation_ids": [str(invitation_id)], "channel": "email"},
            headers=auth_headers(org_world["requester_tenant"]),
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": 1, "failed": 0, "skipped": 0}
    assert len(sent_calls) == 1
    assert sent_calls[0][0] == "guest@example.test"
    assert sent_calls[0][1].endswith(f"/i/{token}")

    invitation_status = (await db_session.execute(text("""
        SELECT status FROM invitations WHERE id = :id
    """), {"id": str(invitation_id)})).scalar_one()
    delivery = (await db_session.execute(text("""
        SELECT status, recipient, provider, sent_at, error_message
        FROM invitation_deliveries
        WHERE invitation_id = :id
    """), {"id": str(invitation_id)})).mappings().one()
    assert invitation_status == "sent"
    assert delivery["status"] == "sent"
    assert delivery["recipient"] == "guest@example.test"
    assert delivery["provider"] == "smtp"
    assert delivery["sent_at"] is not None
    assert delivery["error_message"] is None


@pytest.mark.asyncio
async def test_email_failure_never_claims_the_invitation_was_sent(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """A relay failure leaves the invitation created and records ``failed``."""
    route = _patch_route_dependencies(monkeypatch)
    invitation_id, _ = await _create_email_invitation(db_session, org_world)

    monkeypatch.setattr(route, "is_email_delivery_configured", lambda: True)
    monkeypatch.setattr(route, "send_event_invitation_email", lambda *_args: False)

    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post(
            "/api/v1/invitations/send",
            json={"invitation_ids": [str(invitation_id)], "channel": "email"},
            headers=auth_headers(org_world["requester_tenant"]),
        )

    assert response.status_code == 503, response.text
    assert response.json() == {"sent": 0, "failed": 1, "skipped": 0}
    invitation_status = (await db_session.execute(text("""
        SELECT status FROM invitations WHERE id = :id
    """), {"id": str(invitation_id)})).scalar_one()
    delivery = (await db_session.execute(text("""
        SELECT status, sent_at, error_message
        FROM invitation_deliveries
        WHERE invitation_id = :id
    """), {"id": str(invitation_id)})).mappings().one()
    assert invitation_status == "created"
    assert delivery["status"] == "failed"
    assert delivery["sent_at"] is None
    assert delivery["error_message"]


@pytest.mark.asyncio
async def test_unconfigured_smtp_is_reported_as_a_failed_delivery(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """Missing SMTP settings return 503 and leave an auditable failed attempt."""
    route = _patch_route_dependencies(monkeypatch)
    invitation_id, _ = await _create_email_invitation(db_session, org_world)

    monkeypatch.setattr(route, "is_email_delivery_configured", lambda: False)
    monkeypatch.setattr(
        route,
        "send_event_invitation_email",
        lambda *_args: pytest.fail("SMTP sender must not run when unconfigured"),
    )

    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post(
            "/api/v1/invitations/send",
            json={"invitation_ids": [str(invitation_id)], "channel": "email"},
            headers=auth_headers(org_world["requester_tenant"]),
        )

    assert response.status_code == 503, response.text
    assert response.json()["sent"] == 0
    assert response.json()["failed"] == 1
    status = (await db_session.execute(text("""
        SELECT status FROM invitations WHERE id = :id
    """), {"id": str(invitation_id)})).scalar_one()
    delivery = (await db_session.execute(text("""
        SELECT status, sent_at, error_message
        FROM invitation_deliveries WHERE invitation_id = :id
    """), {"id": str(invitation_id)})).mappings().one()
    assert status == "created"
    assert delivery["status"] == "failed"
    assert delivery["sent_at"] is None
    assert "غير مهيأة" in delivery["error_message"]


@pytest.mark.asyncio
async def test_unimplemented_sms_is_rejected_and_not_marked_sent(
    db_session, org_world, client_factory, auth_headers, monkeypatch,
):
    """SMS stays fail-closed until a provider is integrated."""
    _patch_route_dependencies(monkeypatch)
    invitation_id, _ = await _create_email_invitation(db_session, org_world)

    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post(
            "/api/v1/invitations/send",
            json={"invitation_ids": [str(invitation_id)], "channel": "sms"},
            headers=auth_headers(org_world["requester_tenant"]),
        )

    assert response.status_code == 501, response.text
    assert response.json()["sent"] == 0
    assert response.json()["failed"] == 1
    invitation_status = (await db_session.execute(text("""
        SELECT status FROM invitations WHERE id = :id
    """), {"id": str(invitation_id)})).scalar_one()
    delivery = (await db_session.execute(text("""
        SELECT channel, status, sent_at
        FROM invitation_deliveries
        WHERE invitation_id = :id
    """), {"id": str(invitation_id)})).mappings().one()
    assert invitation_status == "created"
    assert delivery["channel"] == "sms"
    assert delivery["status"] == "failed"
    assert delivery["sent_at"] is None


@pytest.mark.asyncio
async def test_expired_invitation_is_rejected_by_public_view_and_rsvp(
    db_session, org_world, client_factory, monkeypatch,
):
    """Timestamp expiry is enforced even before a background expiry job runs."""
    _patch_route_dependencies(monkeypatch)
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    view_id, view_token = await _create_email_invitation(
        db_session, org_world, expires_at=expired_at,
    )
    rsvp_id, rsvp_token = await _create_email_invitation(
        db_session, org_world, expires_at=expired_at,
    )

    async with client_factory(org_world["requester_user"]) as client:
        view_response = await client.get(f"/api/v1/invitations/view/{view_token}")
        rsvp_response = await client.post(
            f"/api/v1/invitations/rsvp/{rsvp_token}",
            json={"status": "accepted"},
        )

    assert view_response.status_code == 410
    assert rsvp_response.status_code == 410
    statuses = (await db_session.execute(text("""
        SELECT id, status FROM invitations WHERE id IN (:view_id, :rsvp_id)
    """), {"view_id": str(view_id), "rsvp_id": str(rsvp_id)})).mappings().all()
    assert {row["status"] for row in statuses} == {"expired"}


@pytest.mark.asyncio
async def test_rsvp_rejects_unknown_status_before_touching_an_invitation(
    org_world, client_factory, monkeypatch,
):
    """Public callers can only submit the documented RSVP states."""
    _patch_route_dependencies(monkeypatch)
    async with client_factory(org_world["requester_user"]) as client:
        response = await client.post(
            f"/api/v1/invitations/rsvp/{uuid4().hex}",
            json={"status": "arbitrary-state"},
        )
    assert response.status_code == 422
