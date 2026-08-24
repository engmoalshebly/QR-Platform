import asyncio

import pytest

from app.services.tenant_query import TenantQuery


def test_tenant_query_rejects_unsafe_fragments():
    query = TenantQuery(object(), "00000000-0000-0000-0000-000000000001")
    with pytest.raises(ValueError):
        asyncio.run(query.select("events; DROP TABLE users"))
    with pytest.raises(ValueError):
        asyncio.run(query.select("events", order_by="id; DROP TABLE users"))
    with pytest.raises(ValueError):
        asyncio.run(query.select("events", where="id = :id; DROP TABLE users"))


def test_tenant_query_rejects_cross_tenant_insert():
    query = TenantQuery(object(), "tenant-a")
    with pytest.raises(ValueError):
        asyncio.run(query.insert("events", ["title", "tenant_id"], {
            "title": "x", "tenant_id": "tenant-b"
        }))
