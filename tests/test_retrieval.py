#!/usr/bin/env python3
"""
Tests for rag/build_index.py and rag/retrieve.py

Uses DummyHashEmbeddingClient with a tiny corpus (6 chunks).

Run:  pytest tests/test_retrieval.py -v
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from rag.embedding_client import DummyHashEmbeddingClient
from rag.build_index import build_index, tokenize
from rag.retrieve import Retriever


# ============================================================================
# HELPERS
# ============================================================================

def _make_embedded_chunks(client):
   """Create a tiny corpus of 6 embedded chunks."""
   chunks = [
      {
         "chunk_id": "book|ch1|sec1.1|p1-2|i0|s0",
         "book_name": "test_book",
         "chapter_number": 1,
         "chapter_title": "Introduction",
         "section_number": "1.1",
         "section_title": "Overview",
         "page_start": 1,
         "page_end": 2,
         "word_count": 50,
         "text": "Binary search trees are fundamental data structures used in "
                 "computer science for efficient searching and sorting operations.",
      },
      {
         "chunk_id": "book|ch1|sec1.2|p3-4|i0|s0",
         "book_name": "test_book",
         "chapter_number": 1,
         "chapter_title": "Introduction",
         "section_number": "1.2",
         "section_title": "Motivation",
         "page_start": 3,
         "page_end": 4,
         "word_count": 40,
         "text": "Hash tables provide O(1) average case lookup using hash "
                 "functions to map keys to array indices.",
      },
      {
         "chunk_id": "book|ch2|sec2.1|p10-11|i0|s0",
         "book_name": "test_book",
         "chapter_number": 2,
         "chapter_title": "Trees",
         "section_number": "2.1",
         "section_title": "AVL Trees",
         "page_start": 10,
         "page_end": 11,
         "word_count": 60,
         "text": "AVL trees maintain balance through rotations. Each node stores "
                 "a balance factor. Left and right rotations restore the AVL "
                 "property after insertions and deletions.",
      },
      {
         "chunk_id": "book|ch2|sec2.1|p12-13|i0|s1",
         "book_name": "test_book",
         "chapter_number": 2,
         "chapter_title": "Trees",
         "section_number": "2.1",
         "section_title": "AVL Trees",
         "page_start": 12,
         "page_end": 13,
         "word_count": 45,
         "text": "The height of an AVL tree with n nodes is O(log n). This "
                 "guarantees efficient search, insert, and delete operations.",
      },
      {
         "chunk_id": "book|ch2|sec2.2|p14-15|i0|s0",
         "book_name": "test_book",
         "chapter_number": 2,
         "chapter_title": "Trees",
         "section_number": "2.2",
         "section_title": "Red-Black Trees",
         "page_start": 14,
         "page_end": 15,
         "word_count": 55,
         "text": "Red-black trees use a coloring scheme with five properties. "
                 "Every node is either red or black. The root is always black.",
      },
      {
         "chunk_id": "book|ch3|sec3.1|p20-21|i0|s0",
         "book_name": "test_book",
         "chapter_number": 3,
         "chapter_title": "C++ STL",
         "section_number": "3.1",
         "section_title": "Containers",
         "page_start": 20,
         "page_end": 21,
         "word_count": 50,
         "text": "The C++ STL provides std::map and std::set which use red-black "
                 "trees internally. Use std::cout << value to print. Iterators "
                 "use * and -> operators.",
      },
   ]

   for chunk in chunks:
      chunk['embedding'] = client.embed(chunk['text'])

   return chunks


def _write_jsonl(path, records):
   with open(path, 'w', encoding='utf-8') as f:
      for r in records:
         f.write(json.dumps(r, ensure_ascii=False) + '\n')


# ============================================================================
# TESTS: TOKENIZE
# ============================================================================

def test_tokenize_preserves_symbols():
   """Tokenizer preserves code symbols like ::, <<, >>."""
   tokens = tokenize("std::cout << value >> result")
   assert "::" in tokens
   assert "<<" in tokens
   assert ">>" in tokens
   assert "std" in tokens
   assert "cout" in tokens


def test_tokenize_lowercases():
   """Tokenizer lowercases word tokens."""
   tokens = tokenize("Binary Search Tree")
   assert "binary" in tokens
   assert "search" in tokens
   assert "tree" in tokens


# ============================================================================
# TESTS: INDEX BUILDING
# ============================================================================

def test_build_index_creates_files():
   """build_index creates all expected output files."""
   client = DummyHashEmbeddingClient(dim=64)
   chunks = _make_embedded_chunks(client)

   with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)

      embedded_path = tmpdir / "chunks.jsonl"
      _write_jsonl(embedded_path, chunks)

      index_dir = tmpdir / "index"
      stats = build_index(embedded_path, index_dir, verbose=False)

      assert (index_dir / "faiss.index").exists()
      assert (index_dir / "chunk_ids.npy").exists()
      assert (index_dir / "meta.jsonl").exists()
      assert (index_dir / "bm25.pkl").exists()

      assert stats['total_chunks'] == 6
      assert stats['embedding_dim'] == 64


# ============================================================================
# TESTS: RETRIEVAL
# ============================================================================

def test_retrieve_returns_results():
   """Retrieval returns non-empty results for a matching query."""
   client = DummyHashEmbeddingClient(dim=64)
   chunks = _make_embedded_chunks(client)

   with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)

      embedded_path = tmpdir / "chunks.jsonl"
      _write_jsonl(embedded_path, chunks)

      index_dir = tmpdir / "index"
      build_index(embedded_path, index_dir, verbose=False)

      retriever = Retriever(index_dir, embedding_client=client)
      results = retriever.retrieve("AVL tree rotations", final_k=5)

      assert len(results) > 0
      assert all('chunk_id' in r for r in results)
      assert all('score' in r for r in results)


def test_retrieve_respects_final_k():
   """Retrieval returns at most final_k results."""
   client = DummyHashEmbeddingClient(dim=64)
   chunks = _make_embedded_chunks(client)

   with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)

      embedded_path = tmpdir / "chunks.jsonl"
      _write_jsonl(embedded_path, chunks)

      index_dir = tmpdir / "index"
      build_index(embedded_path, index_dir, verbose=False)

      retriever = Retriever(index_dir, embedding_client=client)
      results = retriever.retrieve("binary search tree", final_k=3)

      assert len(results) <= 3


def test_diversity_cap_enforced():
   """At most max_per_section chunks from same (chapter, section)."""
   client = DummyHashEmbeddingClient(dim=64)

   # 5 chunks all from same section
   chunks = []
   for i in range(5):
      chunk = {
         "chunk_id": f"book|ch2|sec2.1|p10-11|i0|s{i}",
         "book_name": "test_book",
         "chapter_number": 2,
         "chapter_title": "Trees",
         "section_number": "2.1",
         "section_title": "AVL Trees",
         "page_start": 10,
         "page_end": 11,
         "word_count": 50,
         "text": f"AVL tree content variant {i} with rotations and balance "
                 f"factors and height analysis.",
      }
      chunk['embedding'] = client.embed(chunk['text'])
      chunks.append(chunk)

   with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)

      embedded_path = tmpdir / "chunks.jsonl"
      _write_jsonl(embedded_path, chunks)

      index_dir = tmpdir / "index"
      build_index(embedded_path, index_dir, verbose=False)

      retriever = Retriever(index_dir, embedding_client=client)
      results = retriever.retrieve("AVL tree", final_k=10, max_per_section=3)

      assert len(results) <= 3
