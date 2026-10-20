"""Persisted contacts and quota counters against an isolated PostgreSQL database."""
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import text
from app.routes import batches
from app.services import feature_service

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('contact_key', ['رقم الجوال', 'guest.phone'])
async def test_designed_rsvp_persists_contact_without_printed_field(db_session, org_world, client_factory, monkeypatch, contact_key):
    tenant = org_world['requester_tenant']
    template = uuid4()
    await db_session.execute(text("""INSERT INTO invite_templates
        (id, tenant_id, event_id, name, template_type, ticket_class)
        VALUES (:id, :tenant, :event, 'P0 test', 'designed', 'normal')"""),
        {'id': str(template), 'tenant': str(tenant), 'event': str(org_world['event_id'])})
    monkeypatch.setattr(batches, '_dispatch_pipeline', lambda *args: None)
    monkeypatch.setattr(feature_service, 'require_feature', AsyncMock())
    monkeypatch.setattr(feature_service, 'enforce_monthly_limit', AsyncMock())
    monkeypatch.setattr(feature_service, 'enforce_static_limit', AsyncMock())
    async with client_factory(org_world['requester_user']) as client:
        response = await client.post('/api/v1/batches/generate-designed-fast',
            headers={'X-Tenant-ID': str(tenant)}, json={
                'event_id': str(org_world['event_id']), 'template_id': str(template),
                'output_formats': [], 'invitations': [{'guest_name': 'ضيف اختبار', 'guest_count': 3,
                    'metadata': {'require_rsvp': True, 'custom_fields': {contact_key: '+967700000000'}}}],
            })
    assert response.status_code == 201, response.text
    result = await db_session.execute(text('SELECT guest_phone, guest_count, rsvp_status, metadata FROM invitations WHERE event_id=:id'), {'id': str(org_world['event_id'])})
    row = result.mappings().one()
    assert row['guest_phone'] == '967700000000'
    assert row['guest_count'] == 3
    assert row['rsvp_status'] == 'pending'
    assert row['metadata']['custom_fields'][contact_key] == '+967700000000'


@pytest.mark.asyncio
async def test_event_quota_counters_count_people_and_ignore_revoked(db_session, org_world, client_factory):
    for people, status in [(3, 'accepted'), (7, 'revoked')]:
        await db_session.execute(text("""INSERT INTO invitations
            (tenant_id, event_id, token, ticket_class, guest_count, status)
            VALUES (:tenant, :event, :token, 'normal', :people, :status)"""),
            {'tenant': str(org_world['requester_tenant']), 'event': str(org_world['event_id']),
             'token': str(uuid4()), 'people': people, 'status': status})
    async with client_factory(org_world['requester_user']) as client:
        response = await client.get(f"/api/v1/events/{org_world['event_id']}/stats",
            headers={'X-Tenant-ID': str(org_world['requester_tenant'])})
    assert response.status_code == 200, response.text
    assert response.json()['normal_quota_used'] == 3
