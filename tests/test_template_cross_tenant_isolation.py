"""template_elements and template_assets have RLS disabled by design
(migration_v63) because isolation for these tables must be app-enforced via a
join to invite_templates.tenant_id. Every mutating/listing route under
/templates/{template_id}/elements and /templates/{template_id}/assets must
verify that ownership itself, not just that the caller holds the permission
in their OWN tenant."""
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture
async def owned_template(db_session, org_world):
    template_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO invite_templates (id, tenant_id, name, template_type, ticket_class)
        VALUES (:id, :tid, 'قالب المؤسسة', 'designed', 'normal')
    """), {"id": str(template_id), "tid": str(org_world["requester_tenant"])})
    element_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO template_elements (id, template_id, element_type, x, y, width, height)
        VALUES (:id, :tid, 'custom_text', 0.1, 0.1, 0.2, 0.05)
    """), {"id": str(element_id), "tid": str(template_id)})
    asset_id = uuid4()
    await db_session.execute(text("""
        INSERT INTO template_assets (id, template_id, asset_type, file_url, file_name)
        VALUES (:id, :tid, 'overlay', 'https://example.test/secret-asset.png', 'secret.png')
    """), {"id": str(asset_id), "tid": str(template_id)})
    await db_session.commit()
    return {"template_id": template_id, "element_id": element_id, "asset_id": asset_id}


@pytest.mark.asyncio
async def test_other_tenant_cannot_add_element_to_foreign_template(
    db_session, org_world, client_factory, owned_template,
):
    async with client_factory(org_world["provider_user"]) as client:
        resp = await client.post(
            f"/api/v1/templates/{owned_template['template_id']}/elements",
            json={"element_type": "custom_text", "x": 0.5, "y": 0.5, "width": 0.2, "height": 0.05},
            headers={"X-Tenant-ID": str(org_world["provider_tenant"])},
        )
    assert resp.status_code == 404, resp.text
    count = (await db_session.execute(text("""
        SELECT COUNT(*) FROM template_elements WHERE template_id = :tid
    """), {"tid": str(owned_template["template_id"])})).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_other_tenant_cannot_update_or_delete_foreign_element(
    db_session, org_world, client_factory, owned_template,
):
    async with client_factory(org_world["provider_user"]) as client:
        upd = await client.patch(
            f"/api/v1/templates/{owned_template['template_id']}/elements/{owned_template['element_id']}",
            json={"x": 0.9},
            headers={"X-Tenant-ID": str(org_world["provider_tenant"])},
        )
        dele = await client.delete(
            f"/api/v1/templates/{owned_template['template_id']}/elements/{owned_template['element_id']}",
            headers={"X-Tenant-ID": str(org_world["provider_tenant"])},
        )
    assert upd.status_code == 404, upd.text
    assert dele.status_code == 404, dele.text
    row = (await db_session.execute(text("""
        SELECT x FROM template_elements WHERE id = :id
    """), {"id": str(owned_template["element_id"])})).mappings().one()
    assert float(row["x"]) == 0.1


@pytest.mark.asyncio
async def test_other_tenant_cannot_replace_all_elements_of_foreign_template(
    db_session, org_world, client_factory, owned_template,
):
    async with client_factory(org_world["provider_user"]) as client:
        resp = await client.put(
            f"/api/v1/templates/{owned_template['template_id']}/elements",
            json=[{"element_type": "custom_text", "x": 0.5, "y": 0.5, "width": 0.2, "height": 0.05}],
            headers={"X-Tenant-ID": str(org_world["provider_tenant"])},
        )
    assert resp.status_code == 404, resp.text
    count = (await db_session.execute(text("""
        SELECT COUNT(*) FROM template_elements WHERE template_id = :tid
    """), {"tid": str(owned_template["template_id"])})).scalar()
    assert count == 1, "a foreign tenant must not be able to wipe another tenant's elements"


@pytest.mark.asyncio
async def test_other_tenant_cannot_list_or_delete_foreign_assets(
    db_session, org_world, client_factory, owned_template,
):
    async with client_factory(org_world["provider_user"]) as client:
        listed = await client.get(
            f"/api/v1/templates/{owned_template['template_id']}/assets",
            headers={"X-Tenant-ID": str(org_world["provider_tenant"])},
        )
        deleted = await client.delete(
            f"/api/v1/templates/{owned_template['template_id']}/assets/{owned_template['asset_id']}",
            headers={"X-Tenant-ID": str(org_world["provider_tenant"])},
        )
    assert listed.status_code == 404, listed.text
    assert deleted.status_code == 404, deleted.text
    row = (await db_session.execute(text("""
        SELECT id FROM template_assets WHERE id = :id
    """), {"id": str(owned_template["asset_id"])})).first()
    assert row is not None, "a foreign tenant must not be able to delete another tenant's asset"
