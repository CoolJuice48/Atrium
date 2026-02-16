#!/usr/bin/env python3
"""
Textbook Search - Completely Offline & Free

Uses TF-IDF vectorization (scikit-learn) - no API keys, no downloads, no network.
Works entirely offline with libraries you already have installed.

Installation:
   pip install scikit-learn  # Usually already installed

Usage:
   Integrated into run_pipeline.py — run that instead.
"""

import re
import json
import pickle
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Sentence boundary pattern — handles abbreviations, decimals, etc.
_SENTENCE_RE = re.compile(
   r'(?<=[.!?])\s+(?=[A-Z])'  # Split after punctuation followed by uppercase
)

# Pattern for heading-like / citation-like fragments:
#   e.g. "gradient descent (Section 8.6.1)." or "see Chapter 3."
_HEADING_LIKE_RE = re.compile(
   r'\((?:Section|Chapter|Fig(?:ure)?|Table|Eq(?:uation)?)\s+[\d.]+\)\s*[.!?]?\s*$',
   re.IGNORECASE,
)


# =========================================================================
# Stable PageRank (module-level, testable)
# =========================================================================

def pagerank_stable(
   transition: np.ndarray,
   damping: float = 0.85,
   max_iter: int = 50,
   tol: float = 1e-9,
) -> Tuple[np.ndarray, bool]:
   """
   Power-iteration PageRank with dangling-node handling.

   Args:
      transition: Row-stochastic (or to-be-normalised) NxN matrix.
                  Zero-sum rows are replaced with uniform distribution.
      damping: Teleportation factor (0.85 is standard).
      max_iter: Iteration cap.
      tol: L1-norm convergence threshold.

   Returns:
      (scores, fell_back) where scores is a stationary distribution vector
      (sums to 1) and fell_back is True if numerical failure forced a
      fallback to uniform scores.
   """
   n = transition.shape[0]
   if n == 0:
      return np.array([], dtype=np.float64), False

   T = np.array(transition, dtype=np.float64)

   # --- fix dangling nodes (zero rows → uniform) ---
   row_sums = T.sum(axis=1)
   dangling = row_sums == 0
   if dangling.any():
      T[dangling] = 1.0 / n

   # --- row-normalise ---
   row_sums = T.sum(axis=1, keepdims=True)
   row_sums[row_sums == 0] = 1.0      # safety
   T = T / row_sums

   scores = np.ones(n, dtype=np.float64) / n
   teleport = (1.0 - damping) / n

   fell_back = False
   with np.errstate(divide='ignore', over='ignore', invalid='ignore'):
      for _ in range(max_iter):
         prev = scores.copy()
         scores = teleport + damping * (T.T @ scores)

         # abort on numerical failure
         if not np.all(np.isfinite(scores)):
            scores = np.ones(n, dtype=np.float64) / n
            fell_back = True
            break

         if np.abs(scores - prev).sum() < tol:
            break

   # normalise to sum=1 (should already be ~1)
   s = scores.sum()
   if s > 0 and np.isfinite(s):
      scores /= s
   else:
      scores = np.ones(n, dtype=np.float64) / n
      fell_back = True

   return scores, fell_back


# =========================================================================
# Answer composer (module-level, testable)
# =========================================================================

# Code/math symbol tokens to track separately
_CODE_SYMBOL_RE = re.compile(r'(::|<<|>>|[*&<>{}()\[\]+\-=/])')

def _tokenize_simple(text: str):
   """Lowercase word tokens."""
   return set(re.findall(r'[a-z0-9_]+', text.lower()))

def _tokenize_symbols(text: str):
   """Code-relevant symbol tokens."""
   return set(_CODE_SYMBOL_RE.findall(text))


# Definition-bias question prefixes
_DEFINITION_PREFIXES = re.compile(
   r'^(?:what\s+is|what\s+are|define|explain|describe)\b', re.IGNORECASE
)

# Comparison keywords
_COMPARISON_RE = re.compile(
   r'\b(?:compare|comparing|comparison|difference|differences|differ|'
   r'vs\.?|versus|distinguish|contrast)\b', re.IGNORECASE
)

# Negation words for contradiction detection
_NEGATION_WORDS = {'not', 'no', 'never', 'neither', 'nor', 'cannot', "n't",
                   'without', 'none', 'nothing', 'nowhere', 'hardly', 'barely'}


def _is_definition_question(question: str) -> bool:
   """Check if the question asks for a definition/explanation."""
   return bool(_DEFINITION_PREFIXES.match(question.strip()))


def _is_comparison_question(question: str) -> bool:
   """Check if the question asks for a comparison."""
   return bool(_COMPARISON_RE.search(question))


def _score_sentence(
   sentence: str,
   question_tokens: set,
   question_symbols: set,
   *,
   definition_mode: bool = False,
   section_title: str = '',
) -> float:
   """
   Score a single sentence for answer quality.

   Combines:
     - token overlap with question
     - symbol overlap bonus
     - penalty for heading-like / citation-like fragments
     - penalty for very short sentences
     - definition bias boost (when definition_mode=True)
   """
   words = sentence.split()
   n_words = len(words)

   # Very short → likely heading / label
   if n_words < 6:
      return -1.0

   sent_tokens = _tokenize_simple(sentence)
   sent_symbols = _tokenize_symbols(sentence)

   # Token overlap (Jaccard-ish, scaled)
   if question_tokens:
      overlap = len(sent_tokens & question_tokens) / max(len(question_tokens), 1)
   else:
      overlap = 0.0

   # Symbol overlap bonus
   if question_symbols:
      sym_overlap = len(sent_symbols & question_symbols) / max(len(question_symbols), 1)
   else:
      sym_overlap = 0.0

   score = overlap + 0.3 * sym_overlap

   # Penalise heading-like fragments:  "gradient descent (Section 8.6.1)."
   if _HEADING_LIKE_RE.search(sentence):
      score *= 0.2

   # Penalise sentences that are mostly punctuation (> 30% non-alnum chars)
   alnum = sum(c.isalnum() or c == ' ' for c in sentence)
   if len(sentence) > 0 and alnum / len(sentence) < 0.70:
      score *= 0.5

   # --- Definition bias (Part 2) ---
   if definition_mode:
      lower = sentence.lower()
      # Boost sentences containing definitional patterns
      if ' is ' in lower or ' are ' in lower:
         score += 0.15
      if 'defined as' in lower:
         score += 0.20
      # Boost if section title tokens overlap with query
      if section_title:
         title_tokens = _tokenize_simple(section_title)
         title_match = len(title_tokens & question_tokens)
         if title_match >= 2:
            score += 0.10

   return score


def _detect_contradiction(sentences: List[str], question_tokens: set) -> bool:
   """
   Heuristic contradiction detection: check if two sentences define the same
   key term with significantly different phrasing (one negated, one not).
   """
   if len(sentences) < 2:
      return False

   for i in range(len(sentences)):
      for j in range(i + 1, len(sentences)):
         tokens_i = _tokenize_simple(sentences[i])
         tokens_j = _tokenize_simple(sentences[j])

         # Check they share key terms with the question
         shared_q_i = tokens_i & question_tokens
         shared_q_j = tokens_j & question_tokens
         if len(shared_q_i) < 2 or len(shared_q_j) < 2:
            continue

         # Check if they share enough content terms (same topic)
         shared = tokens_i & tokens_j
         if len(shared) < 3:
            continue

         # Check if one has negation and the other doesn't
         neg_i = bool(tokens_i & _NEGATION_WORDS)
         neg_j = bool(tokens_j & _NEGATION_WORDS)
         if neg_i != neg_j:
            return True

   return False


def _compute_redundancy(sentences: List[str]) -> float:
   """
   Compute pairwise token overlap among selected sentences.
   High redundancy = strong agreement. Returns 0-1 score.
   """
   if len(sentences) < 2:
      return 0.0

   token_sets = [_tokenize_simple(s) for s in sentences]
   overlaps = []
   for i in range(len(token_sets)):
      for j in range(i + 1, len(token_sets)):
         union = token_sets[i] | token_sets[j]
         if not union:
            continue
         inter = token_sets[i] & token_sets[j]
         overlaps.append(len(inter) / len(union))

   return sum(overlaps) / len(overlaps) if overlaps else 0.0


def _format_citation(meta: Dict) -> str:
   """Build a citation string from chunk metadata."""
   cite_parts = []
   book = meta.get('book') or meta.get('book_name', '')
   if book:
      cite_parts.append(book)
   sec = meta.get('section') or meta.get('section_number', '')
   if sec:
      cite_parts.append(f'\u00a7{sec}')
   pages = meta.get('pages', '')
   if not pages:
      ps = meta.get('page_start', '')
      pe = meta.get('page_end', '')
      if ps:
         pages = f'{ps}-{pe}' if pe and pe != ps else str(ps)
   if pages:
      cite_parts.append(f'p.{pages}')
   return ', '.join(cite_parts)


def compose_answer(
   question: str,
   top_chunks: List[Dict],
   *,
   max_sentences: int = 4,
   max_bullets: int = 4,
   max_chunks: int = 3,
   max_per_chunk: int = 2,
) -> Dict:
   """
   Build a coherent short answer + key points with citations from top chunks.

   Heuristic-only — no LLM, no network calls.

   Args:
      question:      The user's question.
      top_chunks:    List of dicts, each with 'text' and 'metadata'.
      max_sentences: Max sentences in the composed answer paragraph.
      max_bullets:   Max bullet key-points.
      max_chunks:    Only consider the first N chunks.
      max_per_chunk: Diversity cap — no more than this many sentences from one chunk.

   Returns:
      dict with keys: answer, key_points, citations, confidence
   """
   # Check for comparison mode
   if _is_comparison_question(question):
      result = _compose_comparison(question, top_chunks, max_chunks=max_chunks)
      if result is not None:
         return result

   q_tokens = _tokenize_simple(question)
   q_symbols = _tokenize_symbols(question)
   def_mode = _is_definition_question(question)

   # Collect candidate sentences across top chunks
   candidates = []  # (score, sentence, chunk_index, meta)
   for ci, chunk in enumerate(top_chunks[:max_chunks]):
      text = chunk.get('text', '')
      meta = chunk.get('metadata', chunk)  # allow either shape
      sec_title = meta.get('section_title', '')
      for sent in _SENTENCE_RE.split(text):
         for line in sent.split('\n'):
            line = line.strip()
            if len(line) < 20:
               continue
            sc = _score_sentence(
               line, q_tokens, q_symbols,
               definition_mode=def_mode,
               section_title=sec_title,
            )
            candidates.append((sc, line, ci, meta))

   empty_result = {
      'answer': '', 'key_points': [], 'citations': [],
      'confidence': {
         'level': 'low',
         'evidence_coverage_score': 0.0,
         'source_diversity_score': 0,
         'redundancy_score': 0.0,
         'contradiction_flag': False,
      },
   }
   if not candidates:
      return empty_result

   # Sort by score descending
   candidates.sort(key=lambda x: x[0], reverse=True)

   # Select with diversity cap
   selected = []
   chunk_counts = {}
   for sc, sent, ci, meta in candidates:
      if len(selected) >= max_sentences:
         break
      if chunk_counts.get(ci, 0) >= max_per_chunk:
         continue
      if sc <= 0:
         continue
      selected.append((sc, sent, ci, meta))
      chunk_counts[ci] = chunk_counts.get(ci, 0) + 1

   if not selected:
      sc, sent, ci, meta = candidates[0]
      if sc > -1.0:
         selected = [(sc, sent, ci, meta)]

   if not selected:
      return empty_result

   # --- Evidence metrics ---
   sel_sentences = [s[1] for s in selected]
   sel_scores = [s[0] for s in selected]
   sel_metas = [s[3] for s in selected]

   evidence_coverage = sum(sel_scores) / len(sel_scores) if sel_scores else 0.0
   source_books = set()
   for m in sel_metas:
      book = m.get('book') or m.get('book_name', '')
      if book:
         source_books.add(book)
   source_diversity = len(source_books)
   redundancy = _compute_redundancy(sel_sentences)
   contradiction = _detect_contradiction(sel_sentences, q_tokens)

   # Confidence level
   if evidence_coverage >= 0.3 and source_diversity >= 2 and not contradiction:
      level = 'high'
   elif evidence_coverage >= 0.15 and not contradiction:
      level = 'medium'
   else:
      level = 'low'

   # Build answer paragraph (join selected sentences in chunk-order)
   selected_by_order = sorted(selected, key=lambda x: (x[2], candidates.index(x)))
   answer_text = '  '.join(s[1].rstrip('.') + '.' for s in selected_by_order)

   # Build key points + citations
   key_points = []
   citations = []
   for _, sent, _, meta in selected_by_order[:max_bullets]:
      key_points.append(sent.strip())
      citations.append(_format_citation(meta))

   return {
      'answer': answer_text,
      'key_points': key_points,
      'citations': citations,
      'confidence': {
         'level': level,
         'evidence_coverage_score': round(evidence_coverage, 3),
         'source_diversity_score': source_diversity,
         'redundancy_score': round(redundancy, 3),
         'contradiction_flag': contradiction,
      },
   }


def _compose_comparison(
   question: str,
   top_chunks: List[Dict],
   *,
   max_chunks: int = 3,
) -> Optional[Dict]:
   """
   Structured comparison when the question asks to compare two concepts.

   Splits the question on comparison keywords, retrieves sentences for each
   concept, and builds a structured comparison dict.

   Returns None if splitting fails (falls back to normal answer).
   """
   # Split on comparison keywords
   parts = _COMPARISON_RE.split(question)
   parts = [p.strip() for p in parts if p.strip()]

   if len(parts) < 2:
      return None

   concept_a = parts[0]
   concept_b = parts[-1]

   # Strip leading question words from concept_a
   concept_a = re.sub(r'^(?:what|how|why|when|where)\s+(?:is|are|do|does)\s+(?:the\s+)?',
                      '', concept_a, flags=re.IGNORECASE).strip()
   # Strip trailing question marks
   concept_b = concept_b.rstrip('?').strip()

   if not concept_a or not concept_b:
      return None

   q_symbols = _tokenize_symbols(question)
   q_tokens_full = _tokenize_simple(question)

   # Score sentences for each concept
   tokens_a = _tokenize_simple(concept_a)
   tokens_b = _tokenize_simple(concept_b)

   sents_a = []  # (score, sentence, meta)
   sents_b = []
   all_sentences = []

   for ci, chunk in enumerate(top_chunks[:max_chunks]):
      text = chunk.get('text', '')
      meta = chunk.get('metadata', chunk)
      for sent in _SENTENCE_RE.split(text):
         for line in sent.split('\n'):
            line = line.strip()
            if len(line) < 20:
               continue
            sent_tokens = _tokenize_simple(line)
            overlap_a = len(sent_tokens & tokens_a)
            overlap_b = len(sent_tokens & tokens_b)

            if overlap_a > overlap_b and overlap_a >= 2:
               sc = _score_sentence(line, tokens_a, q_symbols)
               sents_a.append((sc, line, meta))
            elif overlap_b > overlap_a and overlap_b >= 2:
               sc = _score_sentence(line, tokens_b, q_symbols)
               sents_b.append((sc, line, meta))

            all_sentences.append(line)

   if not sents_a and not sents_b:
      return None

   sents_a.sort(key=lambda x: x[0], reverse=True)
   sents_b.sort(key=lambda x: x[0], reverse=True)

   top_a = sents_a[:2]
   top_b = sents_b[:2]

   # Build differences
   differences = []
   for (_, sa, _), (_, sb, _) in zip(top_a, top_b):
      differences.append(f"{concept_a}: {sa}  vs  {concept_b}: {sb}")

   # Evidence metrics for comparison
   all_sel = [s[1] for s in top_a + top_b]
   coverage_scores = [s[0] for s in top_a + top_b]
   evidence_coverage = sum(coverage_scores) / max(len(coverage_scores), 1)
   books = set()
   for s in top_a + top_b:
      book = s[2].get('book') or s[2].get('book_name', '')
      if book:
         books.add(book)
   contradiction = _detect_contradiction(all_sel, q_tokens_full)

   if evidence_coverage >= 0.3 and len(books) >= 2 and not contradiction:
      level = 'high'
   elif evidence_coverage >= 0.15 and not contradiction:
      level = 'medium'
   else:
      level = 'low'

   answer_parts = []
   if top_a:
      answer_parts.append(top_a[0][1].rstrip('.') + '.')
   if top_b:
      answer_parts.append(top_b[0][1].rstrip('.') + '.')
   answer_text = '  '.join(answer_parts)

   return {
      'answer': answer_text,
      'key_points': [s[1] for s in top_a[:2]] + [s[1] for s in top_b[:2]],
      'citations': [_format_citation(s[2]) for s in top_a[:2]] +
                   [_format_citation(s[2]) for s in top_b[:2]],
      'confidence': {
         'level': level,
         'evidence_coverage_score': round(evidence_coverage, 3),
         'source_diversity_score': len(books),
         'redundancy_score': round(_compute_redundancy(all_sel), 3),
         'contradiction_flag': contradiction,
      },
      'comparison': {
         'concept_a': {
            'name': concept_a,
            'summary': top_a[0][1] if top_a else '',
            'citations': [_format_citation(s[2]) for s in top_a[:2]],
         },
         'concept_b': {
            'name': concept_b,
            'summary': top_b[0][1] if top_b else '',
            'citations': [_format_citation(s[2]) for s in top_b[:2]],
         },
         'differences': differences,
      },
   }


class TextbookSearchOffline:
   """Completely offline semantic search using TF-IDF."""
   
   def __init__(self, db_path: str = "./textbook_index"):
      """
      Initialize the search system.
      
      Args:
         db_path: Where to store the index (persists between runs)
      """
      self.db_path = Path(db_path)
      self.db_path.mkdir(exist_ok=True)
      
      # TF-IDF vectorizer
      self.vectorizer = TfidfVectorizer(
         max_features=10000,  # Use top 10k most important words
         stop_words='english',
         ngram_range=(1, 2),  # Use single words and pairs
         min_df=2,  # Ignore words that appear in fewer than 2 docs
         max_df=0.8  # Ignore words that appear in >80% of docs
      )
      
      # Storage
      self.documents = []
      self.metadatas = []
      self.vectors = None
      
      # Try to load existing index
      self._load_index()
      
      print(f"✓ Initialized offline search at {db_path}")
      print(f"  Current index size: {len(self.documents)} chunks")
   
   def load_textbook(self, sections_file: Path, book_name: str = None):
      """
      Load a textbook's sections into the index.
      
      Args:
         sections_file: Path to SectionsWithText_Chunked.jsonl
         book_name: Optional override for book name
      """
      if not sections_file.exists():
         print(f"✗ File not found: {sections_file}")
         return
      
      # Auto-detect book name if not provided
      if book_name is None:
         book_name = sections_file.stem.replace('_SectionsWithText_Chunked', '')
         book_name = book_name.replace('_SectionsWithText', '')
      
      print(f"\nLoading {book_name}...")
      
      new_docs = []
      new_metas = []
      
      with open(sections_file, 'r', encoding='utf-8') as f:
         for i, line in enumerate(f):
               if not line.strip():
                  continue
               
               section = json.loads(line)
               
               # Store document text
               new_docs.append(section['text'])
               
               # Store metadata
               new_metas.append({
                  'book': section.get('book_name', book_name),
                  'chapter': str(section.get('chapter_number', 'unknown')),
                  'section': section.get('section_number', ''),
                  'section_title': section.get('section_title', ''),
                  'pages': f"{section['page_start']}-{section['page_end']}",
                  'chunk_index': section.get('chunk_index', 0),
                  'total_chunks': section.get('total_chunks', 1),
                  'word_count': section.get('word_count', 0)
               })
               
               if (i + 1) % 50 == 0:
                  print(f"  Loaded {i + 1} chunks...")
      
      # Add to existing data
      self.documents.extend(new_docs)
      self.metadatas.extend(new_metas)
      
      # Re-vectorize all documents (includes new ones)
      print(f"  Vectorizing {len(self.documents)} total chunks...")
      self.vectors = self.vectorizer.fit_transform(self.documents)
      
      # Save index
      self._save_index()
      
      print(f"✓ Loaded {len(new_docs)} chunks from {book_name}")
      print(f"  Total in index: {len(self.documents)} chunks")
   
   def search(
      self,
      query: str,
      n_results: int = 5,
      book_filter: Optional[str] = None,
      chapter_filter: Optional[str] = None
   ) -> List[Dict]:
      """
      Search the textbooks.
      
      Args:
         query: Natural language question
         n_results: How many results to return
         book_filter: Optional - only search specific book
         chapter_filter: Optional - only search specific chapter
      
      Returns:
         List of search results with text and metadata
      """
      if len(self.documents) == 0:
         return []
      
      # Vectorize query
      query_vector = self.vectorizer.transform([query])
      
      # Calculate similarity
      similarities = cosine_similarity(query_vector, self.vectors)[0]
      
      # Apply filters
      valid_indices = []
      for i, meta in enumerate(self.metadatas):
         if book_filter and meta['book'] != book_filter:
               continue
         if chapter_filter and meta['chapter'] != str(chapter_filter):
               continue
         valid_indices.append(i)
      
      # Get top results from valid indices
      if valid_indices:
         valid_sims = [(i, similarities[i]) for i in valid_indices]
      else:
         valid_sims = [(i, similarities[i]) for i in range(len(similarities))]
      
      # Sort by similarity
      valid_sims.sort(key=lambda x: x[1], reverse=True)
      top_indices = [i for i, _ in valid_sims[:n_results]]
      
      # Format results
      results = []
      for idx in top_indices:
         results.append({
               'text': self.documents[idx],
               'metadata': self.metadatas[idx],
               'similarity': float(similarities[idx])
         })
      
      return results
   
   def ask(
      self,
      question: str,
      n_results: int = 3,
      book_filter: Optional[str] = None,
      show_full_text: bool = False
   ):
      """
      Ask a question and display results with citations.
      
      Args:
         question: Natural language question
         n_results: Number of relevant sections to retrieve
         book_filter: Optional - only search specific book
         show_full_text: Show full text or just preview
      """
      print(f"\n{'='*70}")
      print(f"Question: {question}")
      print(f"{'='*70}\n")
      
      results = self.search(question, n_results=n_results, book_filter=book_filter)
      
      if not results:
         print("No results found.")
         return
      
      for i, result in enumerate(results, 1):
         meta = result['metadata']
         text = result['text']
         similarity = result['similarity']
         
         # Citation
         citation = f"[{meta['book']}"
         if meta.get('section'):
               citation += f", §{meta['section']}"
         if meta.get('section_title'):
               title = meta['section_title'][:50]
               citation += f": {title}"
         citation += f", p.{meta['pages']}]"
         
         # Chunk info if multi-part section
         if meta.get('total_chunks', 1) > 1:
               citation += f" [chunk {meta['chunk_index']+1}/{meta['total_chunks']}]"
         
         # Similarity score
         citation += f" (similarity: {similarity:.3f})"
         
         print(f"{i}. {citation}")
         print("-" * 70)
         
         if show_full_text:
               print(text)
         else:
               # Show preview (first 300 chars)
               preview = text[:300] + "..." if len(text) > 300 else text
               print(preview)
         
         print()
   
   def answer(
      self,
      question: str,
      n_sentences: int = 5,
      n_chunks: int = 5,
      book_filter: Optional[str] = None,
      qa_dir: Optional[Path] = None,
      show_snippets: bool = False,
   ):
      """
      Answer a question using extractive sentence ranking and QuestionBank matching.

      1. Tries to match against existing QuestionBank Q&A pairs (if available)
      2. Falls back to sentence-level extraction from indexed text

      Args:
         question: Natural language question
         n_sentences: Number of top sentences to show
         n_chunks: Number of chunks to pull sentences from
         book_filter: Optional - only search specific book
         qa_dir: Directory containing converted books (to find QuestionBanks)
         show_snippets: If True, also show raw top-N sentence snippets
      """
      print(f"\n{'='*70}")
      print(f"Q: {question}")
      print(f"{'='*70}")

      self._pagerank_fell_back = False

      # --- Phase 1: QuestionBank matching ---
      qa_match = None
      if qa_dir is not None:
         qa_match = self._match_questionbank(question, qa_dir, book_filter)

      if qa_match:
         sim, q_text, a_text, source = qa_match
         print(f"\n>> QuestionBank Match (similarity: {sim:.3f})")
         print(f"   Source: {source}")
         print(f"   Matched Q: {q_text[:200]}")
         print(f"\n   Answer: {a_text}")
         print()

      # --- Phase 2: Sentence-level extraction ---
      results = self.search(question, n_results=n_chunks, book_filter=book_filter)

      if not results:
         if not qa_match:
            print("\nNo results found.")
         return

      # Split all retrieved chunks into individual sentences with metadata
      scored_sentences = self._rank_sentences(question, results)

      # --- Phase 2b: Composed answer ---
      composed = compose_answer(question, results)

      # --- Integration hook: save last answer for study mode ---
      try:
         last_answer_path = self.db_path / '_last_answer.json'
         last_answer_data = {
            'question': question,
            'answer_dict': composed,
            'retrieved_chunks': [
               {
                  'text': r.get('text', ''),
                  'metadata': r.get('metadata', r),
               }
               for r in results[:3]
            ],
         }
         with open(last_answer_path, 'w', encoding='utf-8') as _f:
            json.dump(last_answer_data, _f, ensure_ascii=False, indent=2)
      except OSError:
         pass  # Non-fatal: study hook is optional

      # --- Integration hook: update concept graph registry ---
      try:
         from graph.models import GraphRegistry, QNode, make_question_id
         from graph.concepts import extract_concepts, make_concept_nodes
         from graph.terminality import compute_terminality

         graph_path = self.db_path / 'graph_registry.json'
         greg = GraphRegistry()
         greg.load(graph_path)

         conf = composed.get('confidence', {})
         qid = make_question_id(question)

         # Gather books and sections from results
         g_books = []
         g_sections = []
         g_chunk_ids = []
         for r in results[:3]:
            meta = r.get('metadata', r)
            bk = meta.get('book') or meta.get('book_name', '')
            if bk and bk not in g_books:
               g_books.append(bk)
            sec = meta.get('section') or meta.get('section_number', '')
            if sec and sec not in g_sections:
               g_sections.append(str(sec))
            cid = meta.get('chunk_id', '')
            if cid:
               g_chunk_ids.append(cid)

         qnode = QNode(
            question_id=qid,
            question_text=question,
            citations=g_chunk_ids,
            books=g_books,
            sections=g_sections,
            terminality_score=compute_terminality(conf),
            confidence_snapshot=conf,
         )
         greg.add_qnode(qnode)

         terms = extract_concepts(question, composed,
                                   [{'text': r.get('text', ''),
                                     'metadata': r.get('metadata', r)}
                                    for r in results[:3]])
         cnodes = make_concept_nodes(terms, g_books, g_sections, qid)
         concept_ids = []
         for cn in cnodes:
            greg.add_concept(cn)
            concept_ids.append(cn.concept_id)
         greg.link_qnode_concepts(qid, concept_ids)

         # Record co-occurrences between all concept pairs
         for i, ca in enumerate(concept_ids):
            for cb in concept_ids[i + 1:]:
               greg.link_concept_cooccurrence(ca, cb)

         greg.save(graph_path)
      except Exception:
         pass  # Non-fatal: graph hook is optional

      if composed['answer']:
         print(f"\n>> Short Answer:\n")
         print(f"  {composed['answer']}")

         if composed['key_points']:
            print(f"\n>> Key Points:\n")
            for bp, cite in zip(composed['key_points'], composed['citations']):
               print(f"  - {bp}")
               print(f"    [{cite}]")

      # --- Evidence stats ---
      conf = composed.get('confidence', {})
      level = conf.get('level', 'low').upper()
      cov = conf.get('evidence_coverage_score', 0.0)
      div = conf.get('source_diversity_score', 0)
      red = conf.get('redundancy_score', 0.0)
      contra = conf.get('contradiction_flag', False)

      print(f"\n  Confidence: {level}")
      book_word = 'book' if div == 1 else 'books'
      n_chunks_used = len(composed.get('key_points', []))
      print(f"  Evidence: {n_chunks_used} chunks across {div} {book_word}"
            f"  (coverage={cov:.2f}, redundancy={red:.2f})")
      if contra:
         print("  Warning: contradiction detected among sources")

      # Diagnostics
      if self._pagerank_fell_back:
         print("\n  [diag] PageRank fell back to uniform scores (numerical instability)")

      # --- Optional raw snippets (toggled by 'snippets' command) ---
      if show_snippets and scored_sentences:
         top = scored_sentences[:n_sentences]
         top.sort(key=lambda x: x[3])  # Sort by source_order

         print(f"\n>> Raw Snippets ({len(top)} best sentences):\n")
         print("-" * 70)

         for score, sentence, meta, _ in top:
            cite_parts = [meta['book']]
            if meta.get('section'):
               cite_parts.append(f"\u00a7{meta['section']}")
            cite_parts.append(f"p.{meta['pages']}")
            cite = ", ".join(cite_parts)

            print(f"  {sentence.strip()}")
            print(f"  [{cite}] (score: {score:.3f})\n")

      print("-" * 70)

   # ------------------------------------------------------------------
   # Internal helpers for answer()
   # ------------------------------------------------------------------

   def _split_sentences(self, text: str) -> List[str]:
      """Split text into sentences, filtering out very short fragments."""
      raw = _SENTENCE_RE.split(text)
      # Also split on newlines that look like sentence boundaries
      sentences = []
      for chunk in raw:
         for line in chunk.split('\n'):
            line = line.strip()
            if len(line) > 30:  # Skip tiny fragments
               sentences.append(line)
      return sentences

   def _textrank(self, sim_matrix: np.ndarray, damping: float = 0.85, max_iter: int = 50) -> np.ndarray:
      """
      Run PageRank on a sentence similarity matrix to get importance scores.

      Delegates to the module-level ``pagerank_stable`` for numerical safety.

      Returns:
         Array of importance scores normalised to [0, 1].
      """
      n = sim_matrix.shape[0]
      if n == 0:
         return np.array([])

      scores, fell_back = pagerank_stable(sim_matrix, damping=damping, max_iter=max_iter)

      # Log fallback (once per call, not spammy)
      if fell_back:
         self._pagerank_fell_back = True

      # Normalise to [0, 1] for blending with query-relevance scores
      mx = scores.max()
      if mx > 0 and np.isfinite(mx):
         scores = scores / mx

      return scores

   def _rank_sentences(
      self, query: str, results: List[Dict]
   ) -> List[Tuple[float, str, Dict, int]]:
      """
      Break search results into sentences and rank using TextRank + query relevance.

      TextRank finds the most *informative* sentences (graph centrality).
      Query relevance finds the most *on-topic* sentences.
      The combined score picks sentences that are both.

      Returns list of (combined_score, sentence_text, metadata, source_order)
      sorted by combined score descending.
      """
      sentences = []
      metas = []
      source_orders = []  # Track original position for readability reordering

      order = 0
      for result in results:
         for sent in self._split_sentences(result['text']):
            sentences.append(sent)
            metas.append(result['metadata'])
            source_orders.append(order)
            order += 1

      if not sentences:
         return []

      # Build TF-IDF vectors for all sentences
      sent_vectorizer = TfidfVectorizer(
         stop_words='english',
         ngram_range=(1, 2),
         max_features=5000
      )

      try:
         sent_vectors = sent_vectorizer.fit_transform(sentences)
      except ValueError:
         return []

      # --- Query relevance scores ---
      query_vec = sent_vectorizer.transform([query])
      query_sims = cosine_similarity(query_vec, sent_vectors)[0]

      # --- TextRank importance scores ---
      # Build sentence-to-sentence similarity graph
      sent_sim_matrix = cosine_similarity(sent_vectors, sent_vectors)
      # Zero out self-similarity (no self-loops)
      np.fill_diagonal(sent_sim_matrix, 0)
      textrank_scores = self._textrank(sent_sim_matrix)

      # --- Combined score: weighted blend ---
      # 0.6 query relevance + 0.4 TextRank importance
      combined = 0.6 * query_sims + 0.4 * textrank_scores

      scored = [
         (float(combined[i]), sentences[i], metas[i], source_orders[i])
         for i in range(len(sentences))
      ]
      scored.sort(key=lambda x: x[0], reverse=True)

      # Deduplicate near-identical sentences
      seen = set()
      unique = []
      for score, sent, meta, src_order in scored:
         key = sent.strip().lower()[:80]
         if key not in seen:
            seen.add(key)
            unique.append((score, sent, meta, src_order))

      return unique

   def _match_questionbank(
      self,
      query: str,
      qa_dir: Path,
      book_filter: Optional[str] = None,
      threshold: float = 0.3
   ) -> Optional[Tuple[float, str, str, str]]:
      """
      Try to match the query against QuestionBank Q&A pairs.

      Returns (similarity, question_text, answer_text, source_book) or None.
      """
      # Collect all QuestionBank files
      bank_files = sorted(qa_dir.glob("**/*_QuestionBank.json"))

      if not bank_files:
         return None

      all_questions = []   # (question_text, answer_text, source)
      q_texts = []

      for bf in bank_files:
         source = bf.parent.name
         if book_filter and source != book_filter:
            continue

         try:
            with open(bf, 'r', encoding='utf-8') as f:
               data = json.load(f)
         except (json.JSONDecodeError, OSError):
            continue

         # Build a map of question_id -> answer_text
         answer_map = {}
         for a in data.get('answers', []):
            qid = a.get('question_id', '')
            a_text = a.get('answer_text', '')
            if qid and a_text:
               answer_map[qid] = a_text

         for q in data.get('questions', []):
            q_text = q.get('text', '') or q.get('question_text', '')
            qid = q.get('question_id', '')
            a_text = answer_map.get(qid, '')

            if q_text and a_text:
               all_questions.append((q_text, a_text, source))
               q_texts.append(q_text)

      if not q_texts:
         return None

      # Vectorize questions + query together
      qa_vectorizer = TfidfVectorizer(
         stop_words='english',
         ngram_range=(1, 2),
         max_features=5000
      )

      try:
         q_vectors = qa_vectorizer.fit_transform(q_texts)
      except ValueError:
         return None

      query_vec = qa_vectorizer.transform([query])
      sims = cosine_similarity(query_vec, q_vectors)[0]

      best_idx = int(np.argmax(sims))
      best_sim = float(sims[best_idx])

      if best_sim < threshold:
         return None

      q_text, a_text, source = all_questions[best_idx]
      return (best_sim, q_text, a_text, source)

   def list_books(self):
      """List all books in the index."""
      books = set(m['book'] for m in self.metadatas)
      
      print(f"\nBooks in index ({len(books)}):")
      for book in sorted(books):
         # Count chunks per book
         book_chunks = sum(1 for m in self.metadatas if m['book'] == book)
         print(f"  - {book}: {book_chunks} chunks")
   
   def stats(self):
      """Show index statistics."""
      books = set(m['book'] for m in self.metadatas)
      total_words = sum(m.get('word_count', 0) for m in self.metadatas)

      print(f"\nIndex Statistics:")
      print(f"  Books: {len(books)}")
      print(f"  Total chunks: {len(self.documents)}")
      print(f"  Total words: {total_words:,}")
      avg_words = 0
      if self.metadatas:
         avg_words = total_words // len(self.metadatas)
         print(f"  Avg words/chunk: {avg_words}")
      print(f"  Vocabulary size: {len(self.vectorizer.vocabulary_) if hasattr(self.vectorizer, 'vocabulary_') else 0}")

      # Chunk-size diagnostic
      if avg_words > 600:
         print(f"\n  WARNING: Chunks are large (avg {avg_words} words);"
               f" answer extraction quality may suffer."
               f" Consider rebuilding corpus with smaller target chunk sizes.")
   
   def _save_index(self):
      """Save index to disk."""
      # Save documents and metadata
      data = {
         'documents': self.documents,
         'metadatas': self.metadatas
      }
      with open(self.db_path / 'data.json', 'w', encoding='utf-8') as f:
         json.dump(data, f)
      
      # Save vectorizer and vectors
      with open(self.db_path / 'vectorizer.pkl', 'wb') as f:
         pickle.dump(self.vectorizer, f)
      
      if self.vectors is not None:
         with open(self.db_path / 'vectors.pkl', 'wb') as f:
               pickle.dump(self.vectors, f)
      
      print(f"  💾 Saved index to {self.db_path}")
   
   def _load_index(self):
      """Load index from disk if it exists."""
      data_file = self.db_path / 'data.json'
      vectorizer_file = self.db_path / 'vectorizer.pkl'
      vectors_file = self.db_path / 'vectors.pkl'
      
      if not data_file.exists():
         return
      
      print(f"  Loading existing index from {self.db_path}...")
      
      # Load documents and metadata
      with open(data_file, 'r', encoding='utf-8') as f:
         data = json.load(f)
         self.documents = data['documents']
         self.metadatas = data['metadatas']
      
      # Load vectorizer
      if vectorizer_file.exists():
         with open(vectorizer_file, 'rb') as f:
               self.vectorizer = pickle.load(f)
      
      # Load vectors
      if vectors_file.exists():
         with open(vectors_file, 'rb') as f:
               self.vectors = pickle.load(f)


if __name__ == "__main__":
   print("Use run_pipeline.py to process PDFs and search textbooks.")
   print("  python run_pipeline.py")