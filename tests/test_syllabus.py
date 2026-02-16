"""Tests for zero-knowledge syllabus upload."""

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from server.app import app
from server.config import Settings
from server.db.session import init_db, reset_engine
from server.dependencies import get_settings


def test_syllabus_upload_stores_ciphertext_no_plaintext():
    """Syllabus upload stores ciphertext and no plaintext fields exist."""
    reset_engine()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        storage_path = Path(tmp) / "syllabus_storage"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        settings = Settings()
        settings.syllabus_storage_path = storage_path
        init_db(settings)
        app.dependency_overrides[get_settings] = lambda: settings

        try:
            client = TestClient(app)
            r = client.post("/auth/register", json={"email": "u@x.com", "password": "password123"})
            assert r.status_code == 200
            cookies = r.cookies

            ciphertext = b"encrypted-blob-content"
            wrapped_udk = base64.b64encode(b"wrapped-key-bytes").decode()
            kdf_params = json.dumps({"salt": "abc"})

            r = client.post(
                "/syllabus/upload",
                files={"file": ("syllabus.enc", ciphertext, "application/octet-stream")},
                data={
                    "filename": "syllabus.pdf",
                    "mime": "application/pdf",
                    "size_bytes": str(len(ciphertext)),
                    "wrapped_udk": wrapped_udk,
                    "kdf_params": kdf_params,
                },
                cookies=cookies,
            )
            assert r.status_code == 200
            syllabus_id = r.json()["syllabus_id"]

            # Verify DB row has no plaintext
            from server.db.session import get_session_factory
            from server.db.models import Syllabus
            factory = get_session_factory(settings)
            db = factory()
            row = db.query(Syllabus).filter(Syllabus.id == syllabus_id).first()
            assert row is not None
            assert row.ciphertext_object_key
            assert row.wrapped_udk is not None
            assert row.filename == "syllabus.pdf"
            # No plaintext field
            assert not hasattr(row, "plaintext") or getattr(row, "plaintext", None) is None
            db.close()

            # Verify ciphertext on disk
            obj_path = storage_path / row.ciphertext_object_key
            assert obj_path.exists()
            assert obj_path.read_bytes() == ciphertext
        finally:
            app.dependency_overrides.clear()
