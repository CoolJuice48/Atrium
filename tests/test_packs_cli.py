"""Tests for Atrium Packs CLI: validate, build."""

import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import after path setup
import scripts.packs_cli as cli


def _tmp_pack(tmp: Path, pack_id: str, books: list, allowed: list = None) -> Path:
    """Create a pack directory with pack.json."""
    pack_dir = tmp / "atrium_packs" / "test_path" / "packs" / pack_id
    pack_dir.mkdir(parents=True)
    pack = {
        "pack_id": pack_id,
        "version": "1.0.0",
        "title": "Test Pack",
        "path_id": "test_path",
        "module": {"id": pack_id, "title": "Test", "order": 1, "prereqs": []},
        "books": books,
    }
    if allowed is not None:
        pack["allowed_licenses"] = allowed
    (pack_dir / "pack.json").write_text(json.dumps(pack, indent=2))
    return pack_dir


def test_validate_fails_on_disallowed_license():
    """validate fails when license type not in allowed list."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pack_dir = _tmp_pack(root, "bad-license", [
            {
                "source_file": "x.pdf",
                "source_url": "https://example.com/x.pdf",
                "license": {"type": "CC BY-NC 4.0", "url": "https://creativecommons.org/licenses/by-nc/4.0/", "proof_url": "https://example.com"},
                "attribution": "Test",
            },
        ])
        (pack_dir / "sources").mkdir()
        (pack_dir / "sources" / "x.pdf").write_bytes(b"%PDF")
        (pack_dir / "LICENSES").mkdir()

        orig = cli.PACKS_ROOT
        cli.PACKS_ROOT = root / "atrium_packs"
        try:
            exit_code = cli.validate_all()
            assert exit_code == 1
        finally:
            cli.PACKS_ROOT = orig


def test_validate_fails_when_source_file_missing():
    """validate fails when source_file does not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pack_dir = _tmp_pack(root, "missing-pdf", [
            {
                "source_file": "nonexistent.pdf",
                "source_url": "https://example.com/x.pdf",
                "license": {"type": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/", "proof_url": "https://example.com"},
                "attribution": "Test",
            },
        ])
        (pack_dir / "sources").mkdir()
        (pack_dir / "LICENSES").mkdir()

        orig = cli.PACKS_ROOT
        cli.PACKS_ROOT = root / "atrium_packs"
        try:
            exit_code = cli.validate_all()
            assert exit_code == 1
        finally:
            cli.PACKS_ROOT = orig


def test_build_produces_catalog_and_zip():
    """build produces catalog.json and zip with expected files."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pack_dir = _tmp_pack(root, "good-pack", [
            {
                "source_file": "intro.pdf",
                "title": "Intro",
                "source_url": "https://example.com/intro.pdf",
                "license": {"type": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/", "proof_url": "https://example.com"},
                "attribution": "Intro by Author, CC BY 4.0",
            },
        ])
        (pack_dir / "sources").mkdir()
        (pack_dir / "sources" / "intro.pdf").write_bytes(b"%PDF-1.4")
        (pack_dir / "LICENSES").mkdir()

        orig_root = cli.REPO_ROOT
        orig_packs = cli.PACKS_ROOT
        orig_dist = cli.DIST_ROOT
        cli.REPO_ROOT = root
        cli.PACKS_ROOT = root / "atrium_packs"
        cli.DIST_ROOT = root / "atrium_packs" / "dist"
        try:
            exit_code = cli.build_all()
            assert exit_code == 0

            dist = root / "atrium_packs" / "dist"
            assert (dist / "catalog.json").exists()
            catalog = json.loads((dist / "catalog.json").read_text())
            assert len(catalog) >= 1
            entry = next(e for e in catalog if e["pack_id"] == "good-pack")
            assert entry["book_count"] == 1
            assert "download_url" in entry
            assert "sha256" in entry

            zip_path = dist / "packs" / "good-pack-1.0.0.zip"
            assert zip_path.exists()
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                assert "pack.json" in names
                assert "LICENSES/attribution.json" in names
                assert "LICENSES/THIRD_PARTY_NOTICES.txt" in names
                assert "sources/intro.pdf" in names
        finally:
            cli.REPO_ROOT = orig_root
            cli.PACKS_ROOT = orig_packs
            cli.DIST_ROOT = orig_dist


def test_attribution_json_matches_pack_inputs():
    """attribution.json generation matches pack.json inputs."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        book_entry = {
            "source_file": "book.pdf",
            "title": "My Book",
            "author": "Jane Doe",
            "source_url": "https://example.com/book.pdf",
            "license": {"type": "CC BY-SA 4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/", "proof_url": "https://example.com"},
            "attribution": "My Book by Jane Doe, CC BY-SA 4.0",
        }
        pack_dir = _tmp_pack(root, "attr-pack", [book_entry])
        (pack_dir / "sources").mkdir()
        (pack_dir / "sources" / "book.pdf").write_bytes(b"%PDF")
        (pack_dir / "LICENSES").mkdir()

        orig_root = cli.REPO_ROOT
        orig_packs = cli.PACKS_ROOT
        orig_dist = cli.DIST_ROOT
        cli.REPO_ROOT = root
        cli.PACKS_ROOT = root / "atrium_packs"
        cli.DIST_ROOT = root / "atrium_packs" / "dist"
        try:
            cli.build_all()
            att_path = pack_dir / "LICENSES" / "attribution.json"
            assert att_path.exists()
            att = json.loads(att_path.read_text())
            assert att["pack_id"] == "attr-pack"
            assert len(att["books"]) == 1
            b = att["books"][0]
            assert b["source_file"] == "book.pdf"
            assert b["title"] == "My Book"
            assert b["author"] == "Jane Doe"
            assert b["attribution"] == "My Book by Jane Doe, CC BY-SA 4.0"
            assert b["license"]["type"] == "CC BY-SA 4.0"
        finally:
            cli.REPO_ROOT = orig_root
            cli.PACKS_ROOT = orig_packs
            cli.DIST_ROOT = orig_dist
