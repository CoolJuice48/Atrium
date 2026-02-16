#!/usr/bin/env python3
"""
Content Corpus Builder

Reads SectionsWithText JSONL + PageClassifications JSONL and produces a
clean, normalized chunks_content.jsonl for downstream concept Q&A / RAG.

Filtering:
  - Pages classified as toc/index/front_matter/blankish (confidence >= threshold)
  - Text containing "Table of Contents" (case-insensitive)
  - Dot-leader-heavy sections (>= N matching lines)
  - Section titles with long dot padding

Cleaning:
  - Normalize line endings, trim whitespace
  - Strip embedded TOC lines and dot-leader lines from kept content

Subchunking:
  - Target 220-450 words per subchunk, hard max 650
  - Split on paragraph boundaries (double newline)
  - Preserve code blocks (indented / symbol-heavy lines)
  - Fall back to sentence boundaries for oversized paragraphs

Usage:
  python scripts/build_content_corpus.py \\
    --sections converted/book/book_SectionsWithText_Chunked.jsonl \\
    --page-classifications converted/book/book_PageClassifications.jsonl \\
    --out-root textbook_index

See --help for all options.
"""

import re
import json
import hashlib
import argparse
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class CorpusConfig:
   """Tunable parameters for the corpus builder."""
   include_noncontent: bool = False
   min_confidence: float = 0.7
   target_min_words: int = 220
   target_max_words: int = 450
   hard_max_words: int = 650
   max_dotleader_lines: int = 4   # filter threshold is > this value
   allow_page_types: Optional[set] = None  # whitelist specific noncontent types

# ============================================================================
# FILTER TYPES
# ============================================================================

NONCONTENT_PAGE_TYPES = {"toc", "index", "front_matter", "blankish"}

# ============================================================================
# REGEX PATTERNS
# ============================================================================

# Dot-leader line:  "Something . . . . . 42" or "Something.........42"
_DOT_LEADER_RE = re.compile(r'(?:\.\s*){3,}.*\b\d+\s*$')

# Dot-leader line WITHOUT trailing page number (PyMuPDF often splits the
# number onto its own line):  "Something . . . . . . . . . ."
_DOT_LEADER_BARE_RE = re.compile(r'(?:\.\s*){4,}\s*$')

# "Table of Contents" anywhere (case-insensitive)
_TOC_PHRASE_RE = re.compile(r'table\s+of\s+contents', re.IGNORECASE)

# Section title dot padding: "Introduction . . . . . . . . 1"
_TITLE_DOT_PADDING_RE = re.compile(r'(?:\.\s*){4,}')

# Sentence boundary (for splitting oversized paragraphs)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')

# Code-like line heuristic: starts with whitespace or has many symbols
_CODE_LINE_RE = re.compile(r'^(?:\s{4,}|\t)|[{}();=<>]{2,}')

# Section-number line with trailing page number (e.g., "1.2.3 Topic Name 42")
_SECTION_PAGE_LINE_RE = re.compile(r'^\d+(?:\.\d+)+\s+.*\b\d+\s*$')

# Bare section number on its own line (e.g. "1.2.1" or "10.3.4")
_BARE_SECTION_RE = re.compile(r'^\d+(?:\.\d+)+\s*$')


def looks_like_toc(text: str) -> bool:
   """
   Detect TOC-like content by structural signals, independent of page classification.

   Returns True if text has:
   - 5+ dot-leader lines (with or without trailing page number), OR
   - 5+ lines with section-number prefix and trailing page number, OR
   - 8+ bare section-number lines (like "1.2.1" alone on a line)
   """
   lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
   if not lines:
      return False

   # Classic dot-leaders: "Topic . . . . . 42"
   dot_leader_count = sum(
      1 for ln in lines
      if _DOT_LEADER_RE.search(ln) or _DOT_LEADER_BARE_RE.search(ln)
   )
   if dot_leader_count >= 5:
      return True

   # "1.2.3 Topic Name 42" style
   section_page_count = sum(1 for ln in lines if _SECTION_PAGE_LINE_RE.match(ln))
   if section_page_count >= 5:
      return True

   # Bare section numbers ("1.2.1" alone) — common when PyMuPDF splits TOC
   bare_section_count = sum(1 for ln in lines if _BARE_SECTION_RE.match(ln))
   if bare_section_count >= 8:
      return True

   return False

# ============================================================================
# PAGE CLASSIFICATION LOADER
# ============================================================================

def load_page_classifications(path: Path) -> Dict[int, Dict]:
   """
   Load page classifications into a dict keyed by pdf_page_number.

   Returns:
      {pdf_page_number: {"page_type": ..., "confidence": ..., ...}}
   """
   classifications = {}

   with open(path, 'r', encoding='utf-8') as f:
      for line in f:
         line = line.strip()
         if not line:
            continue
         record = json.loads(line)
         page_num = record.get('pdf_page_number')
         if page_num is not None:
            classifications[page_num] = record

   return classifications

# ============================================================================
# CHUNK ID GENERATION
# ============================================================================

def make_chunk_id(
   book_name: str,
   chapter_number: Optional[int],
   section_number: Optional[str],
   page_start: Optional[int],
   page_end: Optional[int],
   chunk_index: Optional[int],
   subchunk_index: int,
) -> str:
   """
   Build a stable, deterministic chunk ID string.

   Format: "{book}|ch{N}|sec{N}|p{start}-{end}|i{chunk}|s{sub}"
   """
   ch = f"ch{chapter_number}" if chapter_number is not None else "chX"
   sec = f"sec{section_number}" if section_number else "secX"
   ps = page_start if page_start is not None else 0
   pe = page_end if page_end is not None else 0
   ci = chunk_index if chunk_index is not None else 0

   raw = f"{book_name}|{ch}|{sec}|p{ps}-{pe}|i{ci}|s{subchunk_index}"
   return raw

# ============================================================================
# TEXT CLEANING
# ============================================================================

def clean_text(text: str) -> str:
   """
   Normalize and clean section text for corpus use.

   - Normalize line endings
   - Remove embedded TOC lines ("Table of Contents")
   - Remove pure dot-leader lines
   - Trim excessive whitespace but keep paragraph structure
   """
   # Normalize line endings
   text = text.replace('\r\n', '\n').replace('\r', '\n')

   # Process line by line
   cleaned_lines = []
   for line in text.split('\n'):
      # Remove "Table of Contents" lines
      if _TOC_PHRASE_RE.search(line):
         continue

      # Remove dot-leader lines (with or without trailing page number)
      stripped = line.strip()
      if stripped and (_DOT_LEADER_RE.search(stripped) or _DOT_LEADER_BARE_RE.search(stripped)):
         # Check if dots dominate the line (ratio of dot/space chars vs total)
         dot_space_chars = len(re.findall(r'[.\s]', stripped))
         total = len(stripped)
         if total > 0 and dot_space_chars / total > 0.5:
            continue

      cleaned_lines.append(line)

   text = '\n'.join(cleaned_lines)

   # Collapse 3+ consecutive blank lines to 2
   text = re.sub(r'\n{3,}', '\n\n', text)

   # Trim leading/trailing whitespace
   text = text.strip()

   return text


def clean_section_title(title: str) -> str:
   """Remove dot-leader padding from section titles."""
   if not title:
      return title
   # Strip everything after the dot-leader pattern (". . . . 42")
   cleaned = _TITLE_DOT_PADDING_RE.split(title)[0].strip()
   # Also strip trailing dots and whitespace
   cleaned = cleaned.rstrip('. ')
   return cleaned if cleaned else title

# ============================================================================
# FILTERING
# ============================================================================

def check_filters(
   record: Dict,
   page_classifications: Dict[int, Dict],
   config: CorpusConfig,
) -> Optional[str]:
   """
   Check if a SectionsWithText record should be filtered out.

   Returns:
      None if the record should be KEPT.
      A reason string if the record should be FILTERED.
   """
   text = record.get('text', '')
   page_start = record.get('page_start', 0)
   page_end = record.get('page_end', 0)

   # Compute effective excluded page types
   excluded_types = NONCONTENT_PAGE_TYPES - (config.allow_page_types or set())

   # --- 1. Page classification filter ---
   if not config.include_noncontent and page_classifications:
      for pg in range(page_start, page_end + 1):
         cls = page_classifications.get(pg)
         if cls and cls.get('page_type') in excluded_types:
            if cls.get('confidence', 0) >= config.min_confidence:
               return f"page_{cls['page_type']}_confidence_{cls['confidence']}"

   # --- 2. "Table of Contents" in text ---
   if _TOC_PHRASE_RE.search(text):
      return "contains_toc_phrase"

   # --- 3. Structural TOC detection ---
   if looks_like_toc(text):
      return "looks_like_toc"

   # --- 4. Dot-leader heavy (configurable threshold) ---
   lines = text.split('\n')
   dot_leader_count = sum(1 for ln in lines if _DOT_LEADER_RE.search(ln))
   if dot_leader_count > config.max_dotleader_lines:
      return f"dot_leader_heavy_{dot_leader_count}_lines"

   # --- 5. Section title is dot-padded TOC entry ---
   section_title = record.get('section_title', '')
   if section_title and _TITLE_DOT_PADDING_RE.search(section_title):
      # Only filter if there's no real content beyond the TOC header
      word_count = record.get('word_count', 0) or len(text.split())
      if word_count < 50:
         return "dot_padded_title_no_content"

   return None


def get_page_types_in_range(
   page_start: int,
   page_end: int,
   page_classifications: Dict[int, Dict],
   min_confidence: float = 0.7,
) -> List[str]:
   """Get the list of page types for pdf pages in [page_start..page_end].

   Noncontent types (toc, index, front_matter, blankish) are only reported
   when their confidence meets ``min_confidence``; otherwise the page is
   recorded as "content" to avoid polluting provenance with uncertain labels.
   """
   types = []
   for pg in range(page_start, page_end + 1):
      cls = page_classifications.get(pg)
      if cls:
         ptype = cls['page_type']
         conf = cls.get('confidence', 0)
         if ptype in NONCONTENT_PAGE_TYPES and conf < min_confidence:
            types.append("content")
         else:
            types.append(ptype)
      else:
         types.append("unknown")
   return types

# ============================================================================
# SUBCHUNKING
# ============================================================================

def _is_code_line(line: str) -> bool:
   """Heuristic: does this line look like code?"""
   return bool(_CODE_LINE_RE.match(line))


def _split_into_paragraphs(text: str) -> List[str]:
   """
   Split text into paragraph blocks on double-newline boundaries.
   Keeps code blocks (consecutive code-like lines) together.
   """
   raw_paragraphs = re.split(r'\n\s*\n', text)
   return [p.strip() for p in raw_paragraphs if p.strip()]


def _split_paragraph_by_sentences(paragraph: str) -> List[str]:
   """Split a single paragraph into sentence-level pieces."""
   pieces = _SENTENCE_SPLIT_RE.split(paragraph)
   return [p.strip() for p in pieces if p.strip()]


def _word_count(text: str) -> int:
   return len(text.split())


def subchunk_text(text: str, config: CorpusConfig) -> List[str]:
   """
   Split cleaned text into subchunks targeting config word-count ranges.

   Strategy:
   1. Split on paragraph boundaries (double newline).
   2. Merge small paragraphs together up to target_max_words.
   3. Split oversized paragraphs by sentence boundaries.
   4. If a single sentence exceeds hard_max_words, split by single newlines.

   Returns:
      List of subchunk text strings.
   """
   paragraphs = _split_into_paragraphs(text)

   if not paragraphs:
      return [text] if text.strip() else []

   # Flatten oversized paragraphs into sentence-level pieces
   pieces = []
   for para in paragraphs:
      wc = _word_count(para)
      if wc <= config.hard_max_words:
         pieces.append(para)
      else:
         # Try sentence split first
         sentences = _split_paragraph_by_sentences(para)
         if len(sentences) > 1:
            pieces.extend(sentences)
         else:
            # Fall back to single-newline split
            sub_lines = para.split('\n')
            if len(sub_lines) > 1:
               pieces.extend(ln for ln in sub_lines if ln.strip())
            else:
               # Truly one giant run-on: force word-level split
               words = para.split()
               chunk_size = config.target_max_words
               for start in range(0, len(words), chunk_size):
                  pieces.append(' '.join(words[start:start + chunk_size]))

   # Merge pieces into subchunks respecting target range
   subchunks = []
   current_parts = []
   current_wc = 0

   for piece in pieces:
      piece_wc = _word_count(piece)

      # If adding this piece stays within hard max, accumulate
      if current_wc + piece_wc <= config.hard_max_words:
         current_parts.append(piece)
         current_wc += piece_wc

         # If we've reached the target range, flush
         if current_wc >= config.target_min_words:
            subchunks.append('\n\n'.join(current_parts))
            current_parts = []
            current_wc = 0
      else:
         # Flush current, then start new with this piece
         if current_parts:
            subchunks.append('\n\n'.join(current_parts))
         current_parts = [piece]
         current_wc = piece_wc

   # Flush remaining
   if current_parts:
      remaining = '\n\n'.join(current_parts)
      # If the last subchunk is very small, merge with previous
      if subchunks and _word_count(remaining) < config.target_min_words // 2:
         subchunks[-1] = subchunks[-1] + '\n\n' + remaining
      else:
         subchunks.append(remaining)

   # Safety: if nothing was produced, return the original text
   if not subchunks:
      return [text]

   return subchunks

# ============================================================================
# CORPUS BUILDER
# ============================================================================

def build_corpus(
   sections_path: Path,
   page_cls_path: Optional[Path],
   out_root: Path,
   book_name_override: Optional[str] = None,
   config: Optional[CorpusConfig] = None,
   verbose: bool = True,
) -> Dict[str, int]:
   """
   Build the content corpus from SectionsWithText + PageClassifications.

   Args:
      sections_path: Path to *_SectionsWithText*.jsonl
      page_cls_path: Path to *_PageClassifications.jsonl (optional)
      out_root: Root output directory (e.g. textbook_index/)
      book_name_override: Override book name (otherwise read from records)
      config: CorpusConfig with thresholds
      verbose: Print summary

   Returns:
      Dict with stats: total_input, filtered_*, total_output, avg_words
   """
   if config is None:
      config = CorpusConfig()

   # Load page classifications if provided
   page_cls: Dict[int, Dict] = {}
   if page_cls_path and page_cls_path.exists():
      page_cls = load_page_classifications(page_cls_path)
      if verbose:
         print(f"  Loaded {len(page_cls)} page classifications")

   # Determine book name from first record if not overridden
   book_name = book_name_override
   if not book_name:
      with open(sections_path, 'r', encoding='utf-8') as f:
         first_line = f.readline().strip()
         if first_line:
            first_rec = json.loads(first_line)
            book_name = first_rec.get('book_name', 'unknown_book')
         else:
            book_name = 'unknown_book'

   # Setup output paths
   book_out_dir = out_root / book_name
   book_out_dir.mkdir(parents=True, exist_ok=True)

   chunks_path = book_out_dir / "chunks_content.jsonl"
   logs_path = book_out_dir / "corpus_build_logs.jsonl"

   # Stats
   stats: Counter = Counter()
   filter_reasons: Counter = Counter()
   total_output_words = 0

   with open(sections_path, 'r', encoding='utf-8') as fin, \
        open(chunks_path, 'w', encoding='utf-8') as fout, \
        open(logs_path, 'w', encoding='utf-8') as flog:

      for line in fin:
         line = line.strip()
         if not line:
            continue

         record = json.loads(line)
         stats['total_input'] += 1

         text = record.get('text', '')
         section_number = record.get('section_number')
         chapter_number = record.get('chapter_number')
         chunk_index = record.get('chunk_index')
         page_start = record.get('page_start', 0)
         page_end = record.get('page_end', 0)
         rec_book_name = record.get('book_name', book_name)

         # ── Check filters ────────────────────────────────────────────
         filter_reason = check_filters(record, page_cls, config)

         if filter_reason:
            stats['filtered'] += 1
            filter_reasons[filter_reason] += 1

            # Write log record
            candidate_id = make_chunk_id(
               rec_book_name, chapter_number, section_number,
               page_start, page_end, chunk_index, 0,
            )

            log_entry = {
               "chunk_id_candidate": candidate_id,
               "reason": filter_reason,
               "section_number": section_number,
               "chapter_number": chapter_number,
               "page_start": page_start,
               "page_end": page_end,
               "word_count": record.get('word_count', 0),
            }
            flog.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            continue

         # ── Clean text ───────────────────────────────────────────────
         cleaned = clean_text(text)

         if not cleaned.strip():
            stats['filtered'] += 1
            filter_reasons['empty_after_cleaning'] += 1
            continue

         # ── Clean section title ──────────────────────────────────────
         section_title_raw = record.get('section_title', '')
         section_title_clean = clean_section_title(section_title_raw)

         # ── Build provenance ─────────────────────────────────────────
         page_types = get_page_types_in_range(
            page_start, page_end, page_cls,
            min_confidence=config.min_confidence,
         )

         provenance = {
            "sectionswithtext_record": {
               "chapter_number": chapter_number,
               "section_number": section_number,
               "chunk_index": chunk_index,
               "page_start": page_start,
               "page_end": page_end,
            },
            "page_types_in_range": page_types,
         }

         # ── Text flags ───────────────────────────────────────────────
         contains_toc_phrase = bool(_TOC_PHRASE_RE.search(text))
         lines = text.split('\n')
         dot_leader_count = sum(1 for ln in lines if _DOT_LEADER_RE.search(ln))
         looks_like_dot_leader_toc = dot_leader_count > config.max_dotleader_lines

         # ── Subchunk ─────────────────────────────────────────────────
         subchunks = subchunk_text(cleaned, config)
         subchunk_total = len(subchunks)

         for sub_idx, sub_text in enumerate(subchunks):
            wc = _word_count(sub_text)

            chunk_id = make_chunk_id(
               rec_book_name, chapter_number, section_number,
               page_start, page_end, chunk_index, sub_idx,
            )

            output_record = {
               "chunk_id": chunk_id,
               "book_name": rec_book_name,
               "source_type": "textbook_content",
               "chapter_number": chapter_number,
               "chapter_title": record.get('chapter_title'),
               "section_number": section_number,
               "section_title": section_title_clean,
               "page_start": page_start,
               "page_end": page_end,
               "parent_section_chunk_index": chunk_index,
               "parent_section_total_chunks": record.get('total_chunks'),
               "subchunk_index": sub_idx,
               "subchunk_total": subchunk_total,
               "text": sub_text,
               "word_count": wc,
               "flags": {
                  "filtered_reason": None,
                  "contains_toc_phrase": contains_toc_phrase,
                  "looks_like_dot_leader_toc": looks_like_dot_leader_toc,
               },
               "provenance": provenance,
            }

            fout.write(json.dumps(output_record, ensure_ascii=False) + '\n')
            stats['total_output'] += 1
            total_output_words += wc

   # ── Summary ────────────────────────────────────────────────────────
   avg_words = (
      total_output_words / stats['total_output']
      if stats['total_output'] > 0 else 0
   )
   stats['avg_words_per_chunk'] = round(avg_words, 1)

   if verbose:
      _print_summary(stats, filter_reasons, chunks_path)

   return dict(stats)


def _print_summary(stats: Counter, filter_reasons: Counter, chunks_path: Path) -> None:
   total_in = stats.get('total_input', 0)
   total_filtered = stats.get('filtered', 0)
   total_out = stats.get('total_output', 0)
   avg_words = stats.get('avg_words_per_chunk', 0)

   print(f"\nContent Corpus Build Summary")
   print("-" * 50)
   print(f"  Input records:       {total_in:>6d}")
   print(f"  Filtered:            {total_filtered:>6d}")
   print(f"  Output chunks:       {total_out:>6d}")
   print(f"  Avg words/chunk:     {avg_words:>6.1f}")

   if filter_reasons:
      print(f"\n  Filter reasons:")
      for reason, count in filter_reasons.most_common():
         print(f"    {reason:<45s} {count:>5d}")

   print(f"\n  Output: {chunks_path}")
   print("-" * 50)

# ============================================================================
# CLI
# ============================================================================

def main():
   parser = argparse.ArgumentParser(
      description="Build a clean content corpus from SectionsWithText + PageClassifications."
   )
   parser.add_argument(
      '--sections', '-s', required=True,
      help="Path to *_SectionsWithText*.jsonl",
   )
   parser.add_argument(
      '--page-classifications', '-p', default=None,
      help="Path to *_PageClassifications.jsonl (optional but recommended)",
   )
   parser.add_argument(
      '--out-root', '-o', default='textbook_index',
      help="Root output directory (default: textbook_index/)",
   )
   parser.add_argument(
      '--book-name', default=None,
      help="Override book name (otherwise read from records)",
   )
   parser.add_argument(
      '--include-noncontent', action='store_true', default=False,
      help="Include pages classified as toc/index/front_matter/blankish",
   )
   parser.add_argument(
      '--min-confidence', type=float, default=0.8,
      help="Min confidence for page classification filtering (default: 0.8)",
   )
   parser.add_argument(
      '--target-min-words', type=int, default=220,
      help="Target minimum words per subchunk (default: 220)",
   )
   parser.add_argument(
      '--target-max-words', type=int, default=450,
      help="Target maximum words per subchunk (default: 450)",
   )
   parser.add_argument(
      '--hard-max-words', type=int, default=650,
      help="Hard maximum words per subchunk (default: 650)",
   )
   parser.add_argument(
      '--max-dotleader-lines', type=int, default=4,
      help="Max dot-leader lines before filtering (default: 4, filters at >= 5)",
   )
   parser.add_argument(
      '--allow-page-types', default=None,
      help="Comma-separated page types to allow in content-only mode (e.g. 'toc,index')",
   )

   args = parser.parse_args()

   sections_path = Path(args.sections)
   if not sections_path.exists():
      print(f"✗ Sections file not found: {sections_path}")
      return

   page_cls_path = Path(args.page_classifications) if args.page_classifications else None
   if page_cls_path and not page_cls_path.exists():
      print(f"⚠ Page classifications not found: {page_cls_path}")
      print("  Continuing without page-level filtering.\n")
      page_cls_path = None

   out_root = Path(args.out_root)

   allow_page_types = set(args.allow_page_types.split(',')) if args.allow_page_types else None

   config = CorpusConfig(
      include_noncontent=args.include_noncontent,
      min_confidence=args.min_confidence,
      target_min_words=args.target_min_words,
      target_max_words=args.target_max_words,
      hard_max_words=args.hard_max_words,
      max_dotleader_lines=args.max_dotleader_lines,
      allow_page_types=allow_page_types,
   )

   print(f"Building content corpus...")
   print(f"  Sections: {sections_path}")
   if page_cls_path:
      print(f"  Classifications: {page_cls_path}")
   print(f"  Output root: {out_root}")
   print(f"  Target words: {config.target_min_words}-{config.target_max_words} (hard max {config.hard_max_words})")

   build_corpus(
      sections_path=sections_path,
      page_cls_path=page_cls_path,
      out_root=out_root,
      book_name_override=args.book_name,
      config=config,
   )

   print("\n✓ Done")


if __name__ == "__main__":
   main()
