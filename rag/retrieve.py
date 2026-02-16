"""
Hybrid retrieval: FAISS vector search + BM25 keyword search.

Loads index built by rag/build_index.py and provides a Retriever class.

Scoring:
   score = 0.65 * cosine + 0.25 * token_overlap + 0.10 * symbol_overlap

Diversity: max 3 chunks per (chapter_number, section_number).
"""

import json
import pickle
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Any

import numpy as np

try:
   import faiss
except ImportError:
   faiss = None

from rag.build_index import tokenize, CODE_SYMBOLS


class Retriever:
   """
   Hybrid retriever combining dense (FAISS) and sparse (BM25) search.

   Requires an index directory produced by build_index().
   """

   def __init__(self, index_dir: Path, embedding_client=None):
      """
      Load index from directory.

      Args:
         index_dir:        Path to index/ directory
         embedding_client: EmbeddingClient for encoding queries
      """
      if faiss is None:
         raise ImportError("faiss-cpu is required. Install with: pip install faiss-cpu")

      self.index_dir = Path(index_dir)
      self.client = embedding_client

      # Load FAISS index
      self.faiss_index = faiss.read_index(str(self.index_dir / "faiss.index"))

      # Load chunk IDs
      self.chunk_ids: List[str] = list(
         np.load(str(self.index_dir / "chunk_ids.npy"), allow_pickle=True)
      )

      # Load metadata
      self.meta: Dict[str, Dict] = {}
      with open(self.index_dir / "meta.jsonl", 'r', encoding='utf-8') as f:
         for line in f:
            line = line.strip()
            if not line:
               continue
            record = json.loads(line)
            self.meta[record['chunk_id']] = record

      # Load BM25
      with open(self.index_dir / "bm25.pkl", 'rb') as f:
         bm25_data = pickle.load(f)
         self.bm25 = bm25_data['bm25']
         self.bm25_chunk_ids: List[str] = bm25_data['chunk_ids']

   def retrieve(
      self,
      query: str,
      vector_top_k: int = 50,
      bm25_top_k: int = 50,
      final_k: int = 10,
      max_per_section: int = 3,
   ) -> List[Dict[str, Any]]:
      """
      Hybrid retrieval: vector + BM25, with diversity and reranking.

      Args:
         query:            User query string
         vector_top_k:     Candidates from vector search
         bm25_top_k:       Candidates from BM25 search
         final_k:          Number of results to return
         max_per_section:  Max chunks per (chapter, section) pair

      Returns:
         List of result dicts with chunk_id, score, metadata, text
      """
      query_tokens = tokenize(query)
      query_token_set = set(query_tokens)
      query_symbols = query_token_set & CODE_SYMBOLS

      # --- Vector search ---
      vector_scores: Dict[str, float] = {}
      if self.client is not None:
         query_vec = np.array([self.client.embed(query)], dtype=np.float32)
         norm = np.linalg.norm(query_vec)
         if norm > 0:
            query_vec = query_vec / norm

         k = min(vector_top_k, len(self.chunk_ids))
         scores, indices = self.faiss_index.search(query_vec, k)

         for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
               continue
            vector_scores[self.chunk_ids[idx]] = float(score)

      # --- BM25 search ---
      bm25_scores_raw = self.bm25.get_scores(query_tokens)
      bm25_top_indices = np.argsort(bm25_scores_raw)[::-1][:bm25_top_k]

      bm25_max = float(max(bm25_scores_raw)) if len(bm25_scores_raw) > 0 else 1.0
      if bm25_max == 0:
         bm25_max = 1.0

      bm25_scores: Dict[str, float] = {}
      for idx in bm25_top_indices:
         idx = int(idx)
         if bm25_scores_raw[idx] <= 0:
            continue
         bm25_scores[self.bm25_chunk_ids[idx]] = float(bm25_scores_raw[idx]) / bm25_max

      # --- Union candidates ---
      all_candidates = set(vector_scores.keys()) | set(bm25_scores.keys())

      # --- Score each candidate ---
      scored: List[Dict[str, Any]] = []
      for cid in all_candidates:
         cosine = vector_scores.get(cid, 0.0)

         meta = self.meta.get(cid, {})
         chunk_tokens = set(tokenize(meta.get('text', '')))

         # Token overlap
         overlap = len(query_token_set & chunk_tokens)
         token_overlap = overlap / max(len(query_token_set), 1)

         # Symbol overlap
         chunk_symbols = chunk_tokens & CODE_SYMBOLS
         if query_symbols:
            sym_overlap = len(query_symbols & chunk_symbols) / len(query_symbols)
         else:
            sym_overlap = 0.0

         score = 0.65 * cosine + 0.25 * token_overlap + 0.10 * sym_overlap

         scored.append({
            'chunk_id': cid,
            'score': score,
            'cosine': cosine,
            'token_overlap': token_overlap,
            'symbol_overlap': sym_overlap,
            **meta,
         })

      scored.sort(key=lambda x: x['score'], reverse=True)

      # --- Diversity filter ---
      section_counts: Dict[tuple, int] = defaultdict(int)
      results: List[Dict[str, Any]] = []

      for item in scored:
         key = (item.get('chapter_number'), item.get('section_number'))
         if section_counts[key] >= max_per_section:
            continue
         section_counts[key] += 1
         results.append(item)

         if len(results) >= final_k:
            break

      return results
