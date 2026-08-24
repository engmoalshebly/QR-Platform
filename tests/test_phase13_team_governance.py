"""Phase 13 regression tests for team-manager governance contracts."""
from pathlib import Path

import pytest

from app.routes.operations import _real_content_type


@pytest.mark.unit
@pytest.mark.parametrize("payload,content_type", [
    (b"%PDF-1.7\n", "application/pdf"),
    (b"\xff\xd8\xff\xe0", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFFxxxxWEBP", "image/webp"),
])
def test_attachment_real_content_type(payload, content_type):
    assert _real_content_type(payload) == content_type


@pytest.mark.unit
def test_attachment_type_spoof_is_rejected_by_detector():
    assert _real_content_type(b"not-a-pdf") is None
    assert _real_content_type(b"PK\x03\x04not-a-docx") is None


@pytest.mark.unit
def test_phase_migrations_are_registered():
    manifest = Path("scripts/migrations/ci_migrate.py").read_text(encoding="utf-8")
    for version in ("migration_v32_booking_workflow.sql", "migration_v34_task_permissions.sql",
                    "migration_v35_operation_team.sql", "migration_v36_operation_attachments.sql",
                    "migration_v37_team_manager_limits.sql", "migration_v40_team_manager_permission_repair.sql"):
        assert version in manifest


@pytest.mark.unit
def test_team_manager_ui_contract_contains_granular_permissions():
    keys = Path("frontend/src/shared/permissions/keys.ts").read_text(encoding="utf-8")
    for permission in (
        "operations.tasks.view", "operations.tasks.create", "operations.tasks.update_any",
        "operations.attachments.view", "operations.attachments.upload",
        "operations.attachments.download", "reports.export",
    ):
        assert permission in keys
