"""An accepted snapshot must not silently cross rendering library versions."""
import pytest
from app.services import generation_snapshot_service as snapshots


def test_renderer_identity_includes_installed_pillow_version(monkeypatch):
    original = snapshots.renderer_fingerprint()
    version = snapshots.metadata.version
    monkeypatch.setattr(snapshots.metadata, 'version', lambda name: version(name) + '-changed' if name == 'pillow' else version(name))
    assert snapshots.renderer_fingerprint() != original


def test_renderer_identity_includes_native_font_libraries(monkeypatch):
    original = snapshots.renderer_fingerprint()
    version = snapshots.features.version
    monkeypatch.setattr(snapshots.features, 'version', lambda name: str(version(name)) + '-changed' if name == 'freetype2' else version(name))
    assert snapshots.renderer_fingerprint() != original


def test_missing_renderer_dependency_fails_closed(monkeypatch):
    def missing(name):
        raise snapshots.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(snapshots.metadata, 'version', missing)
    with pytest.raises(snapshots.metadata.PackageNotFoundError):
        snapshots.renderer_fingerprint()
