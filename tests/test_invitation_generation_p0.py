"""Production admission, completion and export regressions; no real storage or sends."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.routes import fast_invitations as routes, batches
from app.services import fast_generation_service as fast, batch_pipeline as pipeline
from app.services import feature_service, permission_service, pdf_service


@pytest.mark.parametrize('count', [-1, 0, 2.5, 'bad', True, 101, 'NaN'])
def test_invalid_people_count_is_rejected(count):
    with pytest.raises(ValueError, match='عدد الأشخاص'):
        fast._normalize_invitation_row({'guest_name': 'ضيف اختبار', 'guest_count': count}, 0)


def test_contacts_promoted_without_printed_contact_fields():
    row = fast._normalize_invitation_row({'guest_name': 'ضيف اختبار', 'guest_count': '٣',
        'metadata': {'require_rsvp': True, 'custom_fields': {'guest.phone': '+967700000000', 'الجهة': 'اختبار'}}}, 0)
    assert row['guest_phone'] == '967700000000'
    assert row['guest_count'] == 3
    assert row['metadata']['custom_fields']['الجهة'] == 'اختبار'
    assert row['metadata']['require_rsvp'] is True


@pytest.mark.parametrize('payload', [
    {'guest_name': ''}, {'guest_name': 'Test', 'ticket_class': 'unknown'},
    {'guest_name': 'Test', 'guest_phone': '0501234567'},
    {'guest_name': 'Test', 'guest_email': 'not-email'},
    {'guest_name': 'Test', 'metadata': {'require_rsvp': True}},
])
def test_admission_rejects_invalid_guests(payload):
    with pytest.raises(ValidationError):
        routes.FastInvitationRequest(event_id=uuid4(), invitations=[payload])


def test_designed_admission_uses_same_contact_and_count_rules():
    request = batches.BatchGenerateDesignedFast(event_id=uuid4(), template_id=uuid4(),
        invitations=[{'guest_name': 'Test', 'metadata': {'require_rsvp': True,
                     'custom_fields': {'البريد الإلكتروني': 'test@example.com'}}}])
    assert request.invitations[0]['guest_email'] == 'test@example.com'
    with pytest.raises(ValidationError):
        batches.BatchGenerateDesignedFast(event_id=uuid4(), template_id=uuid4(),
            invitations=[{'guest_name': 'Test', 'guest_count': 2.5}])


@pytest.mark.asyncio
async def test_partial_barcodes_never_report_success(monkeypatch):
    ids = [str(uuid4()), str(uuid4())]
    monkeypatch.setattr(fast, '_create_invitations_batch', AsyncMock(return_value=[{'id': i} for i in ids]))
    monkeypatch.setattr(fast, '_generate_barcodes_parallel', AsyncMock(return_value=[{'invitation_id': ids[0]}]))
    uploads = AsyncMock()
    monkeypatch.setattr(fast, '_upload_files_parallel', uploads)
    result = await fast.generate_invitations_fast(SimpleNamespace(), str(uuid4()), str(uuid4()),
        [{'guest_name': 'Test'}, {'guest_name': 'Test 2'}])
    assert result.success is False
    uploads.assert_not_awaited()


@pytest.mark.asyncio
async def test_export_gate_checks_permission_and_feature(monkeypatch):
    permission = AsyncMock()
    feature = AsyncMock()
    monkeypatch.setattr(routes, 'require_permission', permission)
    monkeypatch.setattr(feature_service, 'require_feature', feature)
    await routes.require_generation_export(None, uuid4(), uuid4(), False)
    permission.assert_not_awaited()
    await routes.require_generation_export(None, uuid4(), uuid4(), True)
    assert permission.await_args.args[-1] == 'invitations.export'
    assert feature.await_args.args[-1] == 'pdf_export'


@pytest.mark.asyncio
async def test_download_refresh_requires_owned_persisted_reference(monkeypatch):
    tenant, event = uuid4(), uuid4()
    result = MagicMock()
    result.first.return_value = (event,)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    signer = MagicMock(return_value='https://storage.example/fresh')
    monkeypatch.setattr(routes.storage_service, 'get_signed_url', signer)
    reference = f'https://storage.example/storage/v1/object/sign/invitations/{tenant}/{event}/barcodes/test.pdf?token=expired'
    assert await routes._fresh_owned_download(db, tenant, reference) == 'https://storage.example/fresh'
    signer.assert_called_once_with(f'{tenant}/{event}/barcodes/test.pdf', expires_in=300)
    result.first.return_value = None
    with pytest.raises(HTTPException) as error:
        await routes._fresh_owned_download(db, tenant, reference)
    assert error.value.status_code == 404
    assert signer.call_count == 1


@pytest.mark.asyncio
async def test_pipeline_failed_assets_and_rows_are_not_ready(monkeypatch):
    batch_id, tenant, event = uuid4(), uuid4(), uuid4()
    item = {'id': str(uuid4()), 'invitation_id': str(uuid4()), 'render_status': 'pending'}
    batch = {'status': 'queued', 'tenant_id': tenant, 'event_id': event, 'created_by': uuid4(),
             'mode': 'quick', 'layout_json': {}, 'output_formats': ['pdf', 'zip']}
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(pipeline, '_load_batch', AsyncMock(return_value=batch))
    monkeypatch.setattr(pipeline, '_load_batch_items', AsyncMock(side_effect=[[item], [{**item, 'render_status': 'failed', 'error_message': 'render failed'}]]))
    monkeypatch.setattr(pipeline, '_load_invitation', AsyncMock(return_value={'id': item['invitation_id'], 'token': 'local-only'}))
    monkeypatch.setattr(permission_service, 'require_permission', AsyncMock())
    monkeypatch.setattr(feature_service, 'require_feature', AsyncMock())
    monkeypatch.setattr(pipeline.storage_service, 'ensure_bucket_exists', AsyncMock())
    monkeypatch.setattr(pipeline.barcode_service, 'generate_barcode_for_invitation', MagicMock(side_effect=RuntimeError('simulated barcode failure')))
    monkeypatch.setattr(pipeline.pdf_service, 'generate_barcode_grid_pdf', MagicMock(side_effect=RuntimeError('simulated PDF failure')))
    monkeypatch.setattr(pipeline.storage_service, 'upload_batch_zip', MagicMock(return_value='local-zip'))
    monkeypatch.setattr(pipeline.storage_service, 'get_signed_url', MagicMock(return_value='local-signed'))
    result = await pipeline.run_batch_pipeline(db, batch_id)
    assert result['status'] == 'failed'
    assert result['count_done'] == 0
    assert result['count_failed'] == 1
    final = next(call.args[1] for call in db.execute.await_args_list if 'error_summary = CAST' in str(call.args[0]))
    assert final['final_status'] == 'failed'
    assert 'PDF output missing' in final['errs']


@pytest.mark.parametrize("name", ["محمد الشيبلي", "Guest Name", "محمد Ahmed", "VIP محمد"])
def test_arabic_pdf_embeds_font_and_shapes_guest_name(name):
    import fitz
    from PIL import Image
    import io
    image = io.BytesIO()
    Image.new('RGB', (100, 100), 'white').save(image, format='PNG')
    payload = pdf_service.generate_barcode_grid_pdf([{'png_bytes': image.getvalue(), 'guest_name': name, 'code': 'test'}],
        {'rows': 1, 'cols': 1, 'show_guest_name': True})
    document = fitz.open(stream=payload, filetype='pdf')
    assert any('Amiri' in font[3] for font in document[0].get_fonts())
    assert '\u25a0' not in document[0].get_text()
    assert pdf_service._guest_label('محمد الشيبلي', 300) != 'محمد الشيبلي'


@pytest.mark.asyncio
async def test_missing_requested_aggregate_is_failure(monkeypatch):
    invitation = {'id': str(uuid4())}
    monkeypatch.setattr(fast, '_create_invitations_batch', AsyncMock(return_value=[invitation]))
    monkeypatch.setattr(fast, '_generate_barcodes_parallel', AsyncMock(return_value=[{'invitation_id': invitation['id'], 'png_bytes': b'local-png'}]))
    monkeypatch.setattr(fast, '_generate_pdf_unified', AsyncMock(return_value=(b'local-pdf', 9)))
    monkeypatch.setattr(fast, '_generate_zip_fast', AsyncMock(return_value=(b'local-zip', 9)))
    monkeypatch.setattr(fast, '_upload_files_parallel', AsyncMock(return_value=('local-pdf', None)))
    update = AsyncMock()
    monkeypatch.setattr(fast, '_update_invitations_with_urls', update)
    result = await fast.generate_invitations_fast(SimpleNamespace(), str(uuid4()), str(uuid4()), [{'guest_name': 'Test'}])
    assert not result.success
    update.assert_not_awaited()


def test_invalid_grid_is_rejected_before_rendering():
    with pytest.raises(ValidationError):
        routes.FastInvitationRequest(event_id=uuid4(), invitations=[{'guest_name': 'Test'}],
                                     layout_config={'cols': 20, 'gap_x_mm': 50})


@pytest.mark.asyncio
async def test_readers_without_export_permission_cannot_receive_file_references(monkeypatch):
    monkeypatch.setattr(permission_service, 'has_permission', AsyncMock(return_value=False))
    feature = AsyncMock()
    monkeypatch.setattr(feature_service, 'check_feature_flag', feature)
    assert await routes._can_download_exports(None, uuid4(), uuid4()) is False
    feature.assert_not_awaited()
    monkeypatch.setattr(permission_service, 'has_permission', AsyncMock(return_value=True))
    feature.return_value = False
    assert await routes._can_download_exports(None, uuid4(), uuid4()) is False


@pytest.mark.asyncio
async def test_download_never_signs_foreign_path_even_if_database_reference_is_corrupt(monkeypatch):
    tenant, event = uuid4(), uuid4()
    response = MagicMock()
    response.first.return_value = (event,)
    signer = MagicMock()
    monkeypatch.setattr(routes.storage_service, 'get_signed_url', signer)
    db = SimpleNamespace(execute=AsyncMock(return_value=response))
    reference = f'https://storage.example/storage/v1/object/sign/invitations/{uuid4()}/{event}/result.pdf'
    with pytest.raises(HTTPException):
        await routes._fresh_owned_download(db, tenant, reference)
    signer.assert_not_called()


@pytest.mark.asyncio
async def test_redaction_removes_signed_files_without_hiding_guest_data(monkeypatch):
    monkeypatch.setattr(routes, '_can_download_exports', AsyncMock(return_value=False))
    original = {'guest_name': 'Test', 'pdf_url': 'signed-pdf', 'zip_url': 'signed-zip'}
    rows = await routes.redact_generation_files(None, uuid4(), uuid4(), [original])
    assert rows == [{'guest_name': 'Test', 'pdf_url': None, 'zip_url': None}]
    assert original['pdf_url'] == 'signed-pdf'
