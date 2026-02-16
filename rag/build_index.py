"""
Build FAISS + BM25 indexes from embedded chunks.

Input:  chunks_content_embedded.jsonl
Output: textbook_index/<book>/index/
   - faiss.index
   - chunk_ids.npy
   - meta.jsonl
   - bm25.pkl
"""

import json
import re
import pickle
import math
from pathlib import Path
from collections import Counter
from typing import Dict, List, Any

import numpy as np

try:
   import faiss
except ImportError:
   faiss = None

# Try rank_bm25, fall back to built-in SimpleBM25
try:
   from rank_bm25 import BM25Okapi
   _HAS_RANK_BM25 = True
except ImportError:
   _HAS_RANK_BM25 = False


# Code-relevant symbols to preserve as tokens
CODE_SYMBOLS = {"::","<<",">>","*","&","<",">","{","}","[","]","(",")","+","-","="}

_SYMBOL_RE = re.compile(r'(::|<<|>>|[*&<>{}\[\]()+\-=])')


def tokenize(text: str) -> List[str]:
   """
   Tokenize text for BM25.

   Lowercases words but preserves code symbols like ::, <<, >>, *, &.
   """
   symbols = _SYMBOL_RE.findall(text)
   words = re.findall(r'[a-zA-Z0-9_]+', text.lower())
   return words + symbols


class SimpleBM25:
   """
   Simple BM25 Okapi implementation for when rank-bm25 is not installed.

   Parameters: k1=1.5, b=0.75.
   """

   def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
      self.k1 = k1
      self.b = b
      self.corpus = corpus
      self.doc_count = len(corpus)
      self.avgdl = sum(len(doc) for doc in corpus) / max(self.doc_count, 1)

      self.df: Dict[str, int] = Counter()
      for doc in corpus:
         for term in set(doc):
            self.df[term] += 1

      self.tf: List[Dict[str, int]] = []
      self.doc_lens: List[int] = []
      for doc in corpus:
         self.tf.append(Counter(doc))
         self.doc_lens.append(len(doc))

   def get_scores(self, query: List[str]) -> np.ndarray:
      """Score all documents against the query. Returns array of scores."""
      scores = np.zeros(self.doc_count)

      for term in query:
         if term not in self.df:
            continue

         idf = math.log(
            (self.doc_count - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1.0
         )

         for i in range(self.doc_count):
            tf = self.tf[i].get(term, 0)
            dl = self.doc_lens[i]
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            scores[i] += idf * numerator / denominator

      return scores

   def get_top_n(self, query: List[str], n: int = 10) -> List[int]:
      """Return indices of top-n scoring documents."""
      scores = self.get_scores(query)
      top_indices = np.argsort(scores)[::-1][:n]
      return [int(i) for i in top_indices if scores[i] > 0]


def build_index(
   embedded_path: Path,
   index_dir: Path,
   verbose: bool = True,
) -> Dict[str, Any]:
   """
   Build FAISS vector index + BM25 index from embedded chunks.

   Args:
      embedded_path: Path to chunks_content_embedded.jsonl
      index_dir:     Output directory for index files
      verbose:       Print progress

   Returns:
      Stats dict with total_chunks, embedding_dim, index_dir
   """
   if faiss is None:
      raise ImportError(
         "faiss-cpu is required. Install with: pip install faiss-cpu"
      )

   index_dir.mkdir(parents=True, exist_ok=True)

   chunk_ids: List[str] = []
   embeddings: List[List[float]] = []
   meta_records: List[Dict] = []
   token_corpus: List[List[str]] = []

   with open(embedded_path, 'r', encoding='utf-8') as f:
      for line in f:
         line = line.strip()
         if not line:
            continue

         record = json.loads(line)
         embedding = record.get('embedding')
         if embedding is None:
            continue

         chunk_id = record['chunk_id']
         chunk_ids.append(chunk_id)
         embeddings.append(embedding)

         meta_records.append({
            'chunk_id': chunk_id,
            'book_name': record.get('book_name'),
            'chapter_number': record.get('chapter_number'),
            'chapter_title': record.get('chapter_title'),
            'section_number': record.get('section_number'),
            'section_title': record.get('section_title'),
            'page_start': record.get('page_start'),
            'page_end': record.get('page_end'),
            'word_count': record.get('word_count'),
            'text': record.get('text', ''),
         })

         token_corpus.append(tokenize(record.get('text', '')))

   if not chunk_ids:
      raise ValueError(f"No embedded chunks found in {embedded_path}")

   # Build FAISS index (cosine sim via inner product on unit vectors)
   dim = len(embeddings[0])
   emb_array = np.array(embeddings, dtype=np.float32)

   norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
   norms[norms == 0] = 1.0
   emb_array = emb_array / norms

   faiss_index = faiss.IndexFlatIP(dim)
   faiss_index.add(emb_array)

   # Build BM25 index
   if _HAS_RANK_BM25:
      bm25 = BM25Okapi(token_corpus)
   else:
      bm25 = SimpleBM25(token_corpus)

   # Save
   faiss.write_index(faiss_index, str(index_dir / "faiss.index"))
   np.save(str(index_dir / "chunk_ids.npy"), np.array(chunk_ids))

   with open(index_dir / "meta.jsonl", 'w', encoding='utf-8') as f:
      for m in meta_records:
         f.write(json.dumps(m, ensure_ascii=False) + '\n')

   with open(index_dir / "bm25.pkl", 'wb') as f:
      pickle.dump({
         'bm25': bm25,
         'token_corpus': token_corpus,
         'chunk_ids': chunk_ids,
      }, f)

   stats = {
      'total_chunks': len(chunk_ids),
      'embedding_dim': dim,
      'index_dir': str(index_dir),
   }

   if verbose:
      print(f"\nIndex Build Summary")
      print("-" * 50)
      print(f"  Chunks indexed:  {stats['total_chunks']}")
      print(f"  Embedding dim:   {stats['embedding_dim']}")
      print(f"  FAISS index:     {index_dir / 'faiss.index'}")
      print(f"  BM25 index:      {index_dir / 'bm25.pkl'}")
      print(f"  Metadata:        {index_dir / 'meta.jsonl'}")
      print("-" * 50)

   return stats
