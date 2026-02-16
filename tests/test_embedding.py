#!/usr/bin/env python3
"""
Tests for rag/embedding_client.py

Run:  pytest tests/test_embedding.py -v
"""

import os
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.embedding_client import DummyHashEmbeddingClient, ExternalEmbeddingClient


def test_dummy_deterministic():
   """Same input always produces the same vector."""
   client = DummyHashEmbeddingClient(dim=64)
   v1 = client.embed("hello world")
   v2 = client.embed("hello world")
   assert v1 == v2


def test_dummy_different_inputs_differ():
   """Different inputs produce different vectors."""
   client = DummyHashEmbeddingClient(dim=64)
   v1 = client.embed("hello world")
   v2 = client.embed("goodbye world")
   assert v1 != v2


def test_dummy_correct_dim():
   """Vector has the requested dimensionality."""
   for dim in [32, 64, 128, 256]:
      client = DummyHashEmbeddingClient(dim=dim)
      v = client.embed("test text")
      assert len(v) == dim, f"Expected dim={dim}, got {len(v)}"


def test_dummy_unit_normalized():
   """Vector is unit-normalized (L2 norm = 1.0)."""
   client = DummyHashEmbeddingClient(dim=64)
   v = client.embed("some text to embed for normalization check")
   norm = math.sqrt(sum(x * x for x in v))
   assert abs(norm - 1.0) < 1e-6, f"Expected norm ~1.0, got {norm}"


def test_dummy_dim_property():
   """dim property returns correct value."""
   client = DummyHashEmbeddingClient(dim=128)
   assert client.dim == 128


def test_external_raises_without_env():
   """ExternalEmbeddingClient raises NotImplementedError without EMBEDDING_PROVIDER."""
   old = os.environ.pop('EMBEDDING_PROVIDER', None)
   try:
      try:
         ExternalEmbeddingClient()
         assert False, "Should have raised NotImplementedError"
      except NotImplementedError:
         pass
   finally:
      if old is not None:
         os.environ['EMBEDDING_PROVIDER'] = old
