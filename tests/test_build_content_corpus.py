#!/usr/bin/env python3
"""
Tests for scripts/build_content_corpus.py

Run:  python -m pytest tests/test_build_content_corpus.py -v
      (from repo root)
"""

import sys
import json
import tempfile
from pathlib import Path

# Ensure imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.build_content_corpus import (
   check_filters,
   clean_text,
   clean_section_title,
   subchunk_text,
   build_corpus,
   make_chunk_id,
   get_page_types_in_range,
   looks_like_toc,
   CorpusConfig,
)


# ============================================================================
# HELPERS
# ============================================================================

def _write_jsonl(path: Path, records: list):
   with open(path, 'w', encoding='utf-8') as f:
      for r in records:
         f.write(json.dumps(r, ensure_ascii=False) + '\n')


def _read_jsonl(path: Path) -> list:
   records = []
   with open(path, 'r', encoding='utf-8') as f:
      for line in f:
         if line.strip():
            records.append(json.loads(line))
   return records


# ============================================================================
# SAMPLE DATA
# ============================================================================

TOC_SECTION = {
   "section_number": "0.0",
   "section_title": "Table of Contents",
   "chapter_number": 0,
   "chunk_index": 0,
   "total_chunks": 1,
   "text": (
      "Table of Contents\n"
      "1 Introduction . . . . . . . . . . . . . . . . . . . 1\n"
      "1.1 Background . . . . . . . . . . . . . . . . . . . 2\n"
      "1.2 Overview . . . . . . . . . . . . . . . . . . . . 5\n"
      "2 Data Structures . . . . . . . . . . . . . . . . . 10\n"
      "2.1 Arrays . . . . . . . . . . . . . . . . . . . . . 11\n"
      "2.2 Linked Lists . . . . . . . . . . . . . . . . . . 15\n"
   ),
   "word_count": 50,
   "page_start": 1,
   "page_end": 1,
   "book_name": "test_book",
   "chapter_title": "",
   "depth": 0,
}

CONTENT_SECTION = {
   "section_number": "3.2",
   "section_title": "Binary Search Trees . . . . . . . . . . . . . . 45",
   "chapter_number": 3,
   "chunk_index": 0,
   "total_chunks": 1,
   "text": (
      "A binary search tree is a rooted binary tree data structure whose "
      "internal nodes each store a key greater than all the keys in the "
      "node's left subtree and less than those in its right subtree. "
      "This property enables efficient lookup, insertion, and deletion. "
      "The time complexity of these operations depends on the height of "
      "the tree, which in the worst case can be O(n) for a skewed tree.\n\n"
      "To maintain balanced trees, we use self-balancing BSTs such as "
      "AVL trees and red-black trees. AVL trees maintain a strict balance "
      "factor where the heights of the left and right subtrees differ by "
      "at most one. Red-black trees use a coloring scheme with five "
      "properties to ensure the tree remains approximately balanced.\n\n"
      "Balanced BSTs guarantee O(log n) time for search, insert, and "
      "delete operations in the worst case. This makes them suitable for "
      "implementing ordered sets and maps in standard libraries.\n\n"
      "Traversal of binary search trees can be done in several orders: "
      "in-order traversal visits nodes in ascending key order, pre-order "
      "traversal visits the root before its subtrees, and post-order "
      "traversal visits the root after its subtrees. Each traversal "
      "runs in O(n) time since every node is visited exactly once.\n\n"
      "The successor of a node is the node with the smallest key greater "
      "than the current node's key. Finding the successor takes O(h) time "
      "where h is the height of the tree. Similarly, the predecessor can "
      "be found in O(h) time. These operations are essential for ordered "
      "iteration and range queries.\n\n"
      "Deletion from a BST has three cases: deleting a leaf node, deleting "
      "a node with one child, and deleting a node with two children. The "
      "third case requires finding the in-order successor or predecessor "
      "to replace the deleted node while maintaining the BST property."
   ),
   "word_count": 280,
   "page_start": 45,
   "page_end": 46,
   "book_name": "test_book",
   "chapter_title": "Trees and Graphs",
   "depth": 2,
}

DOT_LEADER_SECTION = {
   "section_number": "1.0",
   "section_title": "Contents",
   "chapter_number": 1,
   "chunk_index": 0,
   "total_chunks": 1,
   "text": (
      "Programming Foundations . . . . . . . . . . . . . . . . . . 1\n"
      "Introduction . . . . . . . . . . . . . . . . . . . . . . . 1\n"
      "Pointers and References . . . . . . . . . . . . . . . . . . 2\n"
      "Address Space . . . . . . . . . . . . . . . . . . . . . . . 5\n"
      "Compound Objects . . . . . . . . . . . . . . . . . . . . . 6\n"
      "Operator Overloading . . . . . . . . . . . . . . . . . . . 10\n"
   ),
   "word_count": 40,
   "page_start": 1,
   "page_end": 1,
   "book_name": "test_book",
   "chapter_title": "",
   "depth": 1,
}

NORMAL_SHORT_SECTION = {
   "section_number": "5.1",
   "section_title": "Sorting Basics",
   "chapter_number": 5,
   "chunk_index": 0,
   "total_chunks": 1,
   "text": "Sorting is the process of arranging elements in a specific order.",
   "word_count": 11,
   "page_start": 80,
   "page_end": 80,
   "book_name": "test_book",
   "chapter_title": "Sorting",
   "depth": 1,
}

# Page classifications for test data
PAGE_CLASSIFICATIONS = [
   {"page_id": "p1", "pdf_page_number": 1, "page_type": "toc", "confidence": 1.0,
    "detected_section_numbers": [], "detected_chapter_numbers": []},
   {"page_id": "p2", "pdf_page_number": 2, "page_type": "toc", "confidence": 0.75,
    "detected_section_numbers": [], "detected_chapter_numbers": []},
   {"page_id": "p45", "pdf_page_number": 45, "page_type": "content", "confidence": 0.85,
    "detected_section_numbers": [], "detected_chapter_numbers": []},
   {"page_id": "p46", "pdf_page_number": 46, "page_type": "content", "confidence": 0.85,
    "detected_section_numbers": [], "detected_chapter_numbers": []},
   {"page_id": "p80", "pdf_page_number": 80, "page_type": "content", "confidence": 0.90,
    "detected_section_numbers": [], "detected_chapter_numbers": []},
]


# ============================================================================
# TESTS: FILTERING
# ============================================================================

def test_toc_section_filtered():
   """TOC section with 'Table of Contents' in text must be filtered."""
   config = CorpusConfig()
   reason = check_filters(TOC_SECTION, {}, config)
   assert reason is not None, "TOC section should be filtered"
   assert "toc" in reason.lower(), f"Expected TOC filter reason, got: {reason}"


def test_dot_leader_section_filtered():
   """Section with many dot-leader lines must be filtered."""
   config = CorpusConfig()
   reason = check_filters(DOT_LEADER_SECTION, {}, config)
   assert reason is not None, "Dot-leader section should be filtered"
   assert "dot_leader" in reason.lower() or "looks_like_toc" in reason.lower(), \
      f"Expected dot_leader or looks_like_toc reason, got: {reason}"


def test_page_classification_filter():
   """Section on a TOC-classified page (confidence >= 0.8) must be filtered."""
   page_cls = {1: {"page_type": "toc", "confidence": 1.0}}
   config = CorpusConfig()
   reason = check_filters(TOC_SECTION, page_cls, config)
   assert reason is not None


def test_page_classification_low_confidence_not_filtered():
   """Section on a TOC-classified page with low confidence should NOT be filtered
   (unless text-based filters catch it)."""
   page_cls = {80: {"page_type": "toc", "confidence": 0.3}}
   config = CorpusConfig()
   reason = check_filters(NORMAL_SHORT_SECTION, page_cls, config)
   # Should not be filtered by page classification (low confidence)
   assert reason is None, f"Should not be filtered, got: {reason}"


def test_content_section_not_filtered():
   """Normal content section should not be filtered."""
   page_cls = {
      45: {"page_type": "content", "confidence": 0.85},
      46: {"page_type": "content", "confidence": 0.85},
   }
   config = CorpusConfig()
   reason = check_filters(CONTENT_SECTION, page_cls, config)
   assert reason is None, f"Content should not be filtered, got: {reason}"


def test_include_noncontent_overrides():
   """With include_noncontent=True, page classification filtering is skipped."""
   page_cls = {1: {"page_type": "toc", "confidence": 1.0}}
   config = CorpusConfig(include_noncontent=True)
   # Page classification filter is skipped, but text-based filter still catches TOC
   reason = check_filters(NORMAL_SHORT_SECTION, page_cls, config)
   # NORMAL_SHORT_SECTION is on page 80, not page 1, so no issue here
   assert reason is None


# ============================================================================
# TESTS: TEXT CLEANING
# ============================================================================

def test_clean_text_removes_toc_lines():
   """clean_text should remove 'Table of Contents' lines."""
   text = "Chapter 1\nTable of Contents\nSome real content here."
   cleaned = clean_text(text)
   assert "Table of Contents" not in cleaned
   assert "Some real content here" in cleaned


def test_clean_section_title():
   """clean_section_title should strip dot padding."""
   title = "Introduction . . . . . . . . . . . . . . . . . . . . 1"
   cleaned = clean_section_title(title)
   assert cleaned == "Introduction"


def test_clean_section_title_no_dots():
   """clean_section_title should leave clean titles unchanged."""
   title = "Binary Search Trees"
   cleaned = clean_section_title(title)
   assert cleaned == "Binary Search Trees"


# ============================================================================
# TESTS: SUBCHUNKING
# ============================================================================

def test_content_splits_into_subchunks():
   """A large content record should produce multiple subchunks."""
   config = CorpusConfig(target_min_words=50, target_max_words=100, hard_max_words=150)
   subchunks = subchunk_text(CONTENT_SECTION['text'], config)
   assert len(subchunks) > 1, f"Expected multiple subchunks, got {len(subchunks)}"

   # Each subchunk should be within bounds (with some tolerance for the last one)
   for i, sc in enumerate(subchunks):
      wc = len(sc.split())
      # Last chunk can be smaller
      if i < len(subchunks) - 1:
         assert wc <= config.hard_max_words, \
            f"Subchunk {i} has {wc} words, exceeds hard max {config.hard_max_words}"


def test_small_section_single_chunk():
   """A small section should produce exactly one subchunk."""
   config = CorpusConfig()
   subchunks = subchunk_text(NORMAL_SHORT_SECTION['text'], config)
   assert len(subchunks) == 1


def test_empty_text_returns_empty():
   """Empty text should return empty list or single empty."""
   config = CorpusConfig()
   subchunks = subchunk_text("", config)
   assert len(subchunks) == 0 or (len(subchunks) == 1 and not subchunks[0].strip())


# ============================================================================
# TESTS: CHUNK ID
# ============================================================================

def test_chunk_id_deterministic():
   """Same inputs should always produce the same chunk ID."""
   id1 = make_chunk_id("book", 3, "3.2", 45, 46, 0, 0)
   id2 = make_chunk_id("book", 3, "3.2", 45, 46, 0, 0)
   assert id1 == id2


def test_chunk_id_varies_with_subchunk():
   """Different subchunk indices produce different IDs."""
   id0 = make_chunk_id("book", 3, "3.2", 45, 46, 0, 0)
   id1 = make_chunk_id("book", 3, "3.2", 45, 46, 0, 1)
   assert id0 != id1


def test_chunk_id_handles_none():
   """Missing chapter/section should use placeholders, not crash."""
   chunk_id = make_chunk_id("book", None, None, None, None, None, 0)
   assert "chX" in chunk_id
   assert "secX" in chunk_id


# ============================================================================
# TESTS: PROVENANCE
# ============================================================================

def test_page_types_in_range():
   """get_page_types_in_range returns correct types for page range."""
   page_cls = {
      45: {"page_type": "content", "confidence": 0.85},
      46: {"page_type": "content", "confidence": 0.85},
   }
   types = get_page_types_in_range(45, 46, page_cls)
   assert types == ["content", "content"]


def test_page_types_in_range_missing_pages():
   """Missing page classifications should return 'unknown'."""
   page_cls = {45: {"page_type": "content", "confidence": 0.85}}
   types = get_page_types_in_range(45, 47, page_cls)
   assert types == ["content", "unknown", "unknown"]


# ============================================================================
# TESTS: END-TO-END
# ============================================================================

def test_end_to_end_build():
   """Full pipeline: write fake inputs, run build_corpus, verify outputs."""
   with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)

      # Write sections
      sections_path = tmpdir / "sections.jsonl"
      _write_jsonl(sections_path, [TOC_SECTION, CONTENT_SECTION, DOT_LEADER_SECTION, NORMAL_SHORT_SECTION])

      # Write page classifications
      cls_path = tmpdir / "classifications.jsonl"
      _write_jsonl(cls_path, PAGE_CLASSIFICATIONS)

      # Run corpus build
      out_root = tmpdir / "output"
      stats = build_corpus(
         sections_path=sections_path,
         page_cls_path=cls_path,
         out_root=out_root,
         book_name_override="test_book",
         verbose=False,
      )

      # Verify stats
      assert stats['total_input'] == 4
      assert stats['filtered'] >= 2, "TOC + dot-leader should be filtered"
      assert stats['total_output'] >= 1, "Content section should produce output"

      # Verify output file exists
      chunks_file = out_root / "test_book" / "chunks_content.jsonl"
      assert chunks_file.exists()

      # Verify log file exists
      logs_file = out_root / "test_book" / "corpus_build_logs.jsonl"
      assert logs_file.exists()

      # Read and check output chunks
      chunks = _read_jsonl(chunks_file)
      assert len(chunks) >= 1

      # Verify schema of first chunk
      first = chunks[0]
      assert 'chunk_id' in first
      assert 'book_name' in first
      assert first['source_type'] == 'textbook_content'
      assert 'text' in first
      assert 'word_count' in first
      assert 'flags' in first
      assert 'provenance' in first
      assert 'page_types_in_range' in first['provenance']

      # Verify section title was cleaned
      for c in chunks:
         if c['section_number'] == '3.2':
            assert '. . .' not in c['section_title'], \
               f"Section title should be cleaned: {c['section_title']}"

      # Verify log entries
      logs = _read_jsonl(logs_file)
      assert len(logs) >= 2, "At least TOC + dot-leader should be logged"

      log_reasons = [l['reason'] for l in logs]
      assert any('toc' in r.lower() for r in log_reasons), \
         f"Expected TOC filter in logs, got: {log_reasons}"


def test_provenance_includes_page_types():
   """Output chunks should have correct page_types_in_range in provenance."""
   with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)

      sections_path = tmpdir / "sections.jsonl"
      _write_jsonl(sections_path, [CONTENT_SECTION])

      cls_path = tmpdir / "classifications.jsonl"
      _write_jsonl(cls_path, PAGE_CLASSIFICATIONS)

      out_root = tmpdir / "output"
      build_corpus(
         sections_path=sections_path,
         page_cls_path=cls_path,
         out_root=out_root,
         book_name_override="test_book",
         verbose=False,
      )

      chunks = _read_jsonl(out_root / "test_book" / "chunks_content.jsonl")
      assert len(chunks) >= 1

      # Page 45-46 should both be "content"
      for c in chunks:
         ptypes = c['provenance']['page_types_in_range']
         assert ptypes == ["content", "content"], f"Expected content pages, got: {ptypes}"


# ============================================================================
# TESTS: looks_like_toc
# ============================================================================

def test_looks_like_toc_dot_leaders():
   """Text with 5+ dot-leader lines is detected as TOC."""
   toc_text = (
      "1 Introduction . . . . . . . . . . . . . . . . . . . 1\n"
      "1.1 Background . . . . . . . . . . . . . . . . . . . 2\n"
      "1.2 Overview . . . . . . . . . . . . . . . . . . . . 5\n"
      "2 Data Structures . . . . . . . . . . . . . . . . . 10\n"
      "2.1 Arrays . . . . . . . . . . . . . . . . . . . . . 11\n"
      "2.2 Linked Lists . . . . . . . . . . . . . . . . . . 15\n"
   )
   assert looks_like_toc(toc_text) is True


def test_looks_like_toc_section_page_numbers():
   """Text with section-number + trailing page number lines is detected as TOC."""
   toc_text = (
      "1.1 Introduction 1\n"
      "1.2 Background 3\n"
      "1.3 Overview 5\n"
      "1.4 Definitions 8\n"
      "1.5 Notation 10\n"
      "2.1 Algorithms 15\n"
      "2.2 Data Structures 20\n"
   )
   assert looks_like_toc(toc_text) is True


def test_looks_like_toc_normal_content():
   """Normal content text is not detected as TOC."""
   assert looks_like_toc(CONTENT_SECTION['text']) is False


# ============================================================================
# TESTS: TOC page classification filtering (the bug)
# ============================================================================

def test_toc_page_classification_filters_chunk():
   """A chunk on a TOC-classified page (confidence >= 0.8) must be filtered."""
   with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)

      # Section on page 2 with TOC-like content
      section = {
         "section_number": "1.9",
         "section_title": "Templates",
         "chapter_number": 1,
         "chunk_index": 0,
         "total_chunks": 1,
         "text": (
            "ii\n"
            "1.9 Templates .... 22\n"
            "1.9.1 Templates .... 22\n"
            "1.10 Iterators .... 25\n"
         ),
         "word_count": 20,
         "page_start": 2,
         "page_end": 2,
         "book_name": "test_book",
         "chapter_title": "Chapter 1",
         "depth": 1,
      }

      sections_path = tmpdir / "sections.jsonl"
      _write_jsonl(sections_path, [section])

      # Page 2 classified as TOC with high confidence
      cls_path = tmpdir / "classifications.jsonl"
      _write_jsonl(cls_path, [
         {"page_id": "p2", "pdf_page_number": 2, "page_type": "toc",
          "confidence": 1.0, "detected_section_numbers": [],
          "detected_chapter_numbers": []},
      ])

      out_root = tmpdir / "output"
      stats = build_corpus(
         sections_path=sections_path,
         page_cls_path=cls_path,
         out_root=out_root,
         book_name_override="test_book",
         verbose=False,
      )

      # Should be filtered
      assert stats['filtered'] >= 1
      assert stats.get('total_output', 0) == 0

      # Should be in logs
      logs_file = out_root / "test_book" / "corpus_build_logs.jsonl"
      assert logs_file.exists()
      logs = _read_jsonl(logs_file)
      assert len(logs) >= 1
      assert any('toc' in l['reason'].lower() for l in logs)

      # Should NOT be in chunks
      chunks_file = out_root / "test_book" / "chunks_content.jsonl"
      assert chunks_file.exists()
      chunks = _read_jsonl(chunks_file)
      assert len(chunks) == 0


def test_allow_page_types_whitelist():
   """allow_page_types lets specific noncontent types through."""
   page_cls = {1: {"page_type": "toc", "confidence": 1.0}}
   config = CorpusConfig(allow_page_types={"toc"})
   # Page classification should NOT filter when toc is whitelisted
   # (but text-based filters may still catch it)
   reason = check_filters(NORMAL_SHORT_SECTION, page_cls, config)
   # NORMAL_SHORT_SECTION is on page 80, not page 1 — no filtering expected
   assert reason is None
