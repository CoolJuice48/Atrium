"""Zero-knowledge syllabus storage: server stores only ciphertext."""

import uuid
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.orm import Session as DBSession

from server.db.models import Syllabus


def store_syllabus(
    db: DBSession,
    user_id: str,
    filename: str,
    mime: str,
    size_bytes: int,
    ciphertext: bytes,
    wrapped_udk: bytes,
    kdf_params: Dict[str, Any] | None,
    storage_path: Path,
) -> str:
    """Store ciphertext on disk, record in DB. Returns syllabus_id."""
    syllabus_id = str(uuid.uuid4())
    storage_path.mkdir(parents=True, exist_ok=True)
    object_key = f"{user_id}/{syllabus_id}"
    file_path = storage_path / object_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(ciphertext)

    row = Syllabus(
        id=syllabus_id,
        user_id=user_id,
        filename=filename,
        mime=mime,
        size_bytes=size_bytes,
        ciphertext_object_key=object_key,
        wrapped_udk=wrapped_udk,
        kdf_params=kdf_params,
    )
    db.add(row)
    db.flush()
    return syllabus_id


def get_syllabus_meta(db: DBSession, syllabus_id: str, user_id: str) -> Syllabus | None:
    """Return syllabus row if it exists and belongs to user. Never returns plaintext."""
    return db.query(Syllabus).filter(
        Syllabus.id == syllabus_id,
        Syllabus.user_id == user_id,
    ).first()
