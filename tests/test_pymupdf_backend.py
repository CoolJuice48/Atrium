#!/usr/bin/env python3
"""
Tests for pymupdf_backend.py and pdf_backends.py

Creates tiny PDFs on the fly using PyMuPDF so no external fixtures are needed.

Run:  pytest tests/test_pymupdf_backend.py -v
"""

import sys
import json
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from id_factory import IDFactory
from extractors.pymupdf_backend import extract_pages, extract_toc, extract_page_labels
from extractors.pdf_backends import extract_pagerecords


# ============================================================================
# HELPERS
# ============================================================================

def _make_test_pdf(pages_text, *, toc=None):
    """
    Create a temporary PDF with the given page texts.

    Args:
        pages_text: list of strings, one per page.
        toc: optional list of [level, title, page] for PDF outline.

    Returns:
        Path to the temporary PDF file.
    """
    doc = fitz.open()

    for text in pages_text:
        page = doc.new_page(width=612, height=792)  # US Letter
        # Insert text at top-left
        page.insert_text((72, 72), text, fontsize=12)

    if toc:
        doc.set_toc(toc)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc.save(tmp.name)
    doc.close()
    tmp.close()

    return Path(tmp.name)


BOOK_ID = IDFactory.book_id("test-book-pymupdf")


# ============================================================================
# pymupdf_backend.py — extract_pages (text mode)
# ============================================================================

def test_extract_pages_text_mode_basic():
    """Two pages extracted in text mode produce correct records."""
    pdf_path = _make_test_pdf([
        "Hello world from page one.",
        "Second page has different content.",
    ])

    records = list(extract_pages(pdf_path, BOOK_ID, mode="text"))

    assert len(records) == 2

    # Page numbers are 1-based
    assert records[0]["pdf_page_number"] == 1
    assert records[1]["pdf_page_number"] == 2

    # Text is present
    assert "Hello world" in records[0]["text"]
    assert "Second page" in records[1]["text"]

    # Word counts are positive
    assert records[0]["word_count"] > 0
    assert records[1]["word_count"] > 0

    # IDs are deterministic
    expected_id_1 = IDFactory.page_id(BOOK_ID, 1)
    expected_id_2 = IDFactory.page_id(BOOK_ID, 2)
    assert records[0]["id"] == expected_id_1
    assert records[1]["id"] == expected_id_2

    pdf_path.unlink()


def test_extract_pages_text_mode_schema():
    """Every record has exactly the expected PageRecord keys."""
    pdf_path = _make_test_pdf(["Schema test page."])

    records = list(extract_pages(pdf_path, BOOK_ID, mode="text"))
    assert len(records) == 1

    expected_keys = {
        "id", "section_ids", "book_id", "pdf_page_number",
        "real_page_number", "text", "word_count",
        "has_chapter", "has_section", "has_question", "has_answer",
        "text_embedding",
    }
    assert set(records[0].keys()) == expected_keys

    # Defaults
    assert records[0]["section_ids"] == []
    assert records[0]["real_page_number"] is None
    assert records[0]["text_embedding"] is None

    pdf_path.unlink()


def test_extract_pages_empty_page():
    """An empty page still emits a record with empty text."""
    pdf_path = _make_test_pdf([""])

    records = list(extract_pages(pdf_path, BOOK_ID, mode="text"))
    assert len(records) == 1
    assert records[0]["word_count"] == 0
    assert records[0]["pdf_page_number"] == 1

    pdf_path.unlink()


def test_extract_pages_book_id_propagated():
    """book_id is set correctly on every record."""
    pdf_path = _make_test_pdf(["Page A.", "Page B.", "Page C."])

    records = list(extract_pages(pdf_path, BOOK_ID, mode="text"))
    for r in records:
        assert r["book_id"] == BOOK_ID

    pdf_path.unlink()


# ============================================================================
# pymupdf_backend.py — extract_pages (blocks mode)
# ============================================================================

def test_extract_pages_blocks_mode():
    """Blocks mode extracts text and produces valid records."""
    pdf_path = _make_test_pdf([
        "Block mode test content here.",
        "Another page in blocks mode.",
    ])

    records = list(extract_pages(pdf_path, BOOK_ID, mode="blocks"))

    assert len(records) == 2
    assert "Block mode" in records[0]["text"]
    assert "Another page" in records[1]["text"]
    assert records[0]["word_count"] > 0

    pdf_path.unlink()


def test_invalid_mode_raises():
    """Requesting an unknown mode raises ValueError."""
    pdf_path = _make_test_pdf(["test"])

    try:
        list(extract_pages(pdf_path, BOOK_ID, mode="invalid"))
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "invalid" in str(e)
    finally:
        pdf_path.unlink()


# ============================================================================
# pymupdf_backend.py — TOC extraction
# ============================================================================

def test_extract_toc_with_outline():
    """TOC extraction returns entries when the PDF has an outline."""
    toc = [
        [1, "Chapter 1: Intro", 1],
        [2, "1.1 Background", 1],
        [1, "Chapter 2: Methods", 2],
    ]
    pdf_path = _make_test_pdf(["Page one.", "Page two."], toc=toc)

    result = extract_toc(pdf_path)

    assert len(result) == 3
    assert result[0] == {"level": 1, "title": "Chapter 1: Intro", "page": 1}
    assert result[1]["level"] == 2
    assert result[2]["page"] == 2

    pdf_path.unlink()


def test_extract_toc_no_outline():
    """TOC extraction returns empty list when PDF has no outline."""
    pdf_path = _make_test_pdf(["No outline here."])

    result = extract_toc(pdf_path)
    assert result == []

    pdf_path.unlink()


# ============================================================================
# pymupdf_backend.py — page labels extraction
# ============================================================================

def test_extract_page_labels():
    """Page labels extraction returns one entry per page."""
    pdf_path = _make_test_pdf(["P1.", "P2.", "P3."])

    labels = extract_page_labels(pdf_path)

    assert len(labels) == 3
    assert labels[0]["pdf_page_number"] == 1
    assert labels[1]["pdf_page_number"] == 2
    assert labels[2]["pdf_page_number"] == 3

    pdf_path.unlink()


# ============================================================================
# pdf_backends.py — extract_pagerecords dispatcher
# ============================================================================

def test_backend_dispatcher_pymupdf():
    """Dispatcher routes to pymupdf backend correctly."""
    pdf_path = _make_test_pdf(["Dispatcher test page one.", "Page two here."])

    records = list(extract_pagerecords(
        pdf_path, BOOK_ID, backend="pymupdf", pymupdf_mode="text"
    ))

    assert len(records) == 2
    assert "Dispatcher test" in records[0]["text"]
    assert records[0]["pdf_page_number"] == 1
    assert records[1]["pdf_page_number"] == 2

    pdf_path.unlink()


def test_backend_dispatcher_legacy():
    """Dispatcher routes to legacy (words) backend correctly."""
    pdf_path = _make_test_pdf(["Current backend test."])

    records = list(extract_pagerecords(
        pdf_path, BOOK_ID, backend="legacy"
    ))

    assert len(records) == 1
    assert records[0]["pdf_page_number"] == 1
    assert records[0]["word_count"] > 0

    pdf_path.unlink()


def test_backend_dispatcher_invalid():
    """Unknown backend raises ValueError."""
    pdf_path = _make_test_pdf(["test"])

    try:
        list(extract_pagerecords(pdf_path, BOOK_ID, backend="nonexistent"))
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "nonexistent" in str(e)
    finally:
        pdf_path.unlink()


def test_backend_pymupdf_blocks_mode():
    """Dispatcher passes pymupdf_mode='blocks' through correctly."""
    pdf_path = _make_test_pdf(["Blocks via dispatcher."])

    records = list(extract_pagerecords(
        pdf_path, BOOK_ID, backend="pymupdf", pymupdf_mode="blocks"
    ))

    assert len(records) == 1
    assert records[0]["word_count"] > 0

    pdf_path.unlink()


def test_section_ids_populated_by_dispatcher():
    """
    The dispatcher runs group_sections_per_page() so section_ids
    are populated when practice/exercise keywords appear.
    """
    pdf_path = _make_test_pdf(["Practice Exercises\n\n1. What is O(n)?"])

    records = list(extract_pagerecords(
        pdf_path, BOOK_ID, backend="pymupdf", pymupdf_mode="text"
    ))

    assert len(records) == 1
    # section_ids should contain the practice exercises section ID
    assert len(records[0]["section_ids"]) > 0

    pdf_path.unlink()


# ============================================================================
# Deterministic IDs across backends
# ============================================================================

def test_ids_match_across_backends():
    """
    Both backends produce the same page IDs for the same book_id
    and page number, since they both use IDFactory.page_id().
    """
    pdf_path = _make_test_pdf(["ID consistency test.", "Page two."])

    current_records = list(extract_pagerecords(
        pdf_path, BOOK_ID, backend="legacy"
    ))
    pymupdf_records = list(extract_pagerecords(
        pdf_path, BOOK_ID, backend="pymupdf", pymupdf_mode="text"
    ))

    assert len(current_records) == len(pymupdf_records) == 2

    for c, p in zip(current_records, pymupdf_records):
        assert c["id"] == p["id"], (
            f"ID mismatch on page {c['pdf_page_number']}: "
            f"current={c['id']} vs pymupdf={p['id']}"
        )
        assert c["pdf_page_number"] == p["pdf_page_number"]

    pdf_path.unlink()
