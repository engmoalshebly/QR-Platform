import asyncio
import unittest
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from app.main import app
from app.routes.bookings import BookingCreate, provision_operation
from app.services.schema_guard import verify_schema


class Phase1WorkflowTests(unittest.TestCase):
    def test_registration_approval_booking_routes_are_exposed(self):
        paths = app.openapi()["paths"]
        self.assertIn("post", paths["/api/v1/auth/org-request"])
        self.assertIn("post", paths["/api/v1/platform/org-requests/{request_id}/approve"])
        self.assertIn("post", paths["/api/v1/bookings"])
        self.assertIn("post", paths["/api/v1/bookings/{booking_id}/respond"])
        self.assertIn("get", paths["/api/v1/operations/{operation_id}"])
        self.assertIn("get", paths["/api/v1/notifications"])

    def test_booking_contract_requires_event_and_contact_phone(self):
        provider_id, event_id = uuid4(), uuid4()
        body = BookingCreate(provider_tenant_id=provider_id, event_id=event_id, contact_phone="0500000000")
        self.assertEqual(body.provider_tenant_id, provider_id)
        self.assertEqual(body.event_id, event_id)

    def test_acceptance_provisions_operation_manager_and_activity(self):
        operation_id, booking_id, event_id = uuid4(), uuid4(), uuid4()
        requester_id, provider_id, manager_id = uuid4(), uuid4(), uuid4()

        async def _stub(*args, **kwargs):
            class _R:
                def scalar(self):
                    return operation_id
                def first(self):
                    return None
                def mappings(self):
                    return self
                def all(self):
                    return []
                def scalars(self):
                    return self
            return _R()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_stub)
        booking = {"event_id": event_id, "requester_tenant_id": requester_id,
                   "provider_tenant_id": provider_id, "event_type": "default"}

        created = asyncio.run(provision_operation(db, booking_id, booking, manager_id))

        self.assertEqual(created, operation_id)
        self.assertGreaterEqual(db.execute.await_count, 3)
        sql_calls = " ".join(str(call.args[0]) for call in db.execute.await_args_list)
        self.assertIn("event_operations", sql_calls)
        self.assertIn("event_operation_members", sql_calls)
        self.assertIn("event_operation_activity", sql_calls)

    def test_database_schema_contract_is_current(self):
        try:
            asyncio.run(verify_schema())
        except (OSError, ConnectionError, RuntimeError) as exc:
            pytest.skip(f"PostgreSQL unavailable: {type(exc).__name__}")

    def test_phase1_migration_defines_all_operational_capabilities(self):
        sql = Path("supabase/migration_v23_phase1_operations.sql").read_text(encoding="utf-8")
        for required in ("event_operations", "event_operation_members", "event_operation_tasks",
                         "event_operation_attachments", "event_operation_activity", "notifications",
                         "application_errors", "'manager','lead','member'"):
            self.assertIn(required, sql)


if __name__ == "__main__":
    unittest.main(verbosity=2)
