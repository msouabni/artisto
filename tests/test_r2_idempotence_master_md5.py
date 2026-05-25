"""Tests pour l'idempotence R2 via custom metadata ``master-md5``."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _md5(body: bytes) -> str:
    return hashlib.md5(body).hexdigest()


class FakeR2Client:
    """Simule un bucket R2 en mémoire pour les tests d'idempotence."""

    def __init__(self):
        self.objects: dict[str, dict] = {}

    def head(self, key: str) -> dict | None:
        obj = self.objects.get(key)
        if obj is None:
            return None
        return {
            "ETag": f'"{obj["etag"]}"',
            "Metadata": dict(obj.get("metadata", {})),
        }

    def put(self, key: str, body: bytes, content_type: str,
            metadata: dict[str, str] | None = None) -> str:
        etag = _md5(body)
        self.objects[key] = {
            "body": body,
            "etag": etag,
            "content_type": content_type,
            "metadata": metadata or {},
        }
        return etag

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def r2():
    return FakeR2Client()


@pytest.fixture
def master_bytes():
    return b"PNG master content deterministic"


@pytest.fixture
def variants(master_bytes):
    return {
        "master": master_bytes,
        "web": b"webp bytes run1",
        "thumb": b"thumb bytes run1",
        "pdf": b"pdf bytes run1",
    }


@pytest.fixture
def variants_run2(master_bytes):
    """Mêmes master bytes, variants différents (non-déterministes)."""
    return {
        "master": master_bytes,
        "web": b"webp bytes run2 different",
        "thumb": b"thumb bytes run2 different",
        "pdf": b"pdf bytes run2 different",
    }


def test_first_upload_writes_master_md5_metadata(r2, variants, master_bytes):
    from alwanbooks_pipeline import _upload_variants_real

    master_md5 = _md5(master_bytes)
    uploaded, skipped = _upload_variants_real(r2, "test-slug", variants, master_md5)

    assert len(uploaded) == 4
    assert len(skipped) == 0

    for key in uploaded.values():
        obj = r2.objects[key]
        assert obj["metadata"]["master-md5"] == master_md5


def test_second_upload_same_master_skips_all_variants(
    r2, variants, variants_run2, master_bytes
):
    from alwanbooks_pipeline import _upload_variants_real

    master_md5 = _md5(master_bytes)
    _upload_variants_real(r2, "test-slug", variants, master_md5)

    uploaded, skipped = _upload_variants_real(r2, "test-slug", variants_run2, master_md5)

    assert len(uploaded) == 0
    assert len(skipped) == 4


def test_master_changed_triggers_full_reupload(r2, variants, master_bytes):
    from alwanbooks_pipeline import _upload_variants_real

    master_md5 = _md5(master_bytes)
    _upload_variants_real(r2, "test-slug", variants, master_md5)

    new_master = b"PNG master content CHANGED"
    new_md5 = _md5(new_master)
    new_variants = {
        "master": new_master,
        "web": b"new webp",
        "thumb": b"new thumb",
        "pdf": b"new pdf",
    }
    uploaded, skipped = _upload_variants_real(r2, "test-slug", new_variants, new_md5)

    assert len(uploaded) == 4
    assert len(skipped) == 0

    for key in uploaded.values():
        assert r2.objects[key]["metadata"]["master-md5"] == new_md5


def test_legacy_object_without_metadata_falls_back_to_etag(r2):
    from alwanbooks_pipeline import _upload_variants_real

    body = b"some variant content"
    r2.objects["coloriages/png/test-slug.png"] = {
        "body": body,
        "etag": _md5(body),
        "content_type": "image/png",
        "metadata": {},
    }

    variants = {
        "master": body,
        "web": b"webp",
        "thumb": b"thumb",
        "pdf": b"pdf",
    }
    master_md5 = _md5(body)
    uploaded, skipped = _upload_variants_real(r2, "test-slug", variants, master_md5)

    assert "master" in skipped
    assert len(uploaded) == 3


def test_legacy_object_after_first_reupload_gets_master_md5(r2):
    from alwanbooks_pipeline import _upload_variants_real

    master_body = b"stable master png"
    r2.objects["coloriages/png/test-slug.png"] = {
        "body": master_body,
        "etag": _md5(master_body),
        "content_type": "image/png",
        "metadata": {},
    }
    r2.objects["coloriages/webp/test-slug.webp"] = {
        "body": b"old webp",
        "etag": _md5(b"old webp"),
        "content_type": "image/webp",
        "metadata": {},
    }

    variants = {
        "master": master_body,
        "web": b"new webp different bytes",
        "thumb": b"new thumb",
        "pdf": b"new pdf",
    }
    master_md5 = _md5(master_body)
    uploaded1, skipped1 = _upload_variants_real(r2, "test-slug", variants, master_md5)

    assert "master" in skipped1
    assert "web" in uploaded1

    assert r2.objects["coloriages/webp/test-slug.webp"]["metadata"]["master-md5"] == master_md5

    variants_run2 = {
        "master": master_body,
        "web": b"yet another webp bytes",
        "thumb": b"yet another thumb",
        "pdf": b"yet another pdf",
    }
    uploaded2, skipped2 = _upload_variants_real(r2, "test-slug", variants_run2, master_md5)

    assert "web" in skipped2


def test_rollback_on_partial_failure_preserves_skipped(r2, master_bytes):
    from alwanbooks_pipeline import _upload_variants_real

    master_md5 = _md5(master_bytes)
    r2.objects["coloriages/png/test-slug.png"] = {
        "body": master_bytes,
        "etag": _md5(master_bytes),
        "content_type": "image/png",
        "metadata": {"master-md5": master_md5},
    }

    call_count = 0
    original_put = r2.put

    def failing_put(key, body, content_type, metadata=None):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise RuntimeError("simulated R2 failure")
        return original_put(key, body, content_type, metadata=metadata)

    r2.put = failing_put

    variants = {
        "master": master_bytes,
        "web": b"webp",
        "thumb": b"thumb will fail",
        "pdf": b"pdf",
    }

    with pytest.raises(RuntimeError, match="simulated"):
        _upload_variants_real(r2, "test-slug", variants, master_md5)

    assert "coloriages/png/test-slug.png" in r2.objects
    assert "coloriages/webp/test-slug.webp" not in r2.objects
