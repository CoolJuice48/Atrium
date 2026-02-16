"""
Embedding client interface and implementations.

Provides:
  - EmbeddingClient: Protocol for embedding text into vectors.
  - DummyHashEmbeddingClient: Deterministic hash-based embeddings for testing.
  - ExternalEmbeddingClient: Stub for real embedding providers.
"""
from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingClient(Protocol):
   """Protocol for embedding text into fixed-dimensional vectors."""

   def embed(self, text: str) -> list[float]:
      """Embed a single text string into a vector."""
      ...

   @property
   def dim(self) -> int:
      """Embedding dimensionality."""
      ...


class DummyHashEmbeddingClient:
   """
   Deterministic hash-based embedding for testing and development.

   WARNING: This produces meaningless vectors that do NOT capture semantic
   similarity. Use ONLY for testing pipeline mechanics (index building,
   retrieval plumbing, etc.).

   Vectors are normalized to unit length.
   """

   def __init__(self, dim: int = 64):
      self._dim = dim

   @property
   def dim(self) -> int:
      return self._dim

   def embed(self, text: str) -> list[float]:
      h = hashlib.sha256(text.encode('utf-8')).digest()

      raw: list[float] = []
      for i in range(self._dim):
         seed = hashlib.md5(h + i.to_bytes(4, 'little')).digest()
         val = int.from_bytes(seed[:4], 'little', signed=True) / (2**31)
         raw.append(val)

      # L2 normalize
      norm = math.sqrt(sum(x * x for x in raw))
      if norm > 0:
         raw = [x / norm for x in raw]

      return raw


class ExternalEmbeddingClient:
   """
   Stub for external embedding providers (OpenAI, Anthropic, local models).

   Set EMBEDDING_PROVIDER env var to your provider name and implement the
   embed() method for your chosen provider.

   Example providers: 'openai', 'sentence-transformers', 'local'.
   """

   def __init__(self, dim: int = 1536):
      self._dim = dim
      provider = os.environ.get('EMBEDDING_PROVIDER', '')
      if not provider:
         raise NotImplementedError(
            "ExternalEmbeddingClient requires EMBEDDING_PROVIDER env var.\n"
            "Set it to your provider name (e.g. 'openai') and implement\n"
            "the embed() method in rag/embedding_client.py."
         )
      self._provider = provider

   @property
   def dim(self) -> int:
      return self._dim

   def embed(self, text: str) -> list[float]:
      raise NotImplementedError(
         f"Embedding for provider '{self._provider}' not yet implemented.\n"
         f"Add your API call logic in ExternalEmbeddingClient.embed()."
      )
