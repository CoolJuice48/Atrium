#!/usr/bin/env python3
"""
Page Classifier — classify PageRecords into page types.

Reads a PageRecords JSONL file and writes a sidecar
PageClassifications JSONL keyed by page_id.

Page types:
  toc          Table of Contents
  index        Back-of-book index
  practice     Exercises / problems / review questions
  front_matter Preface, copyright, acknowledgments
  blankish     Nearly empty page
  content      Normal body text
  unknown      Could not determine

Usage:
  python page_classifier.py --input converted/book/book_PageRecords \\
                            --output converted/book/book_PageClassifications.jsonl

Integrated into run_pipeline.py as an optional step (--classify-pages).
"""

import re
import json
import argparse
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# PAGE TYPES
# ============================================================================

PAGE_TYPES = ("toc", "index", "practice", "front_matter", "blankish", "content", "unknown")

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class ClassifierConfig:
   """Tunable thresholds for the page classifier."""

   # TOC
   min_dot_leader_lines_for_toc: int = 5
   min_section_number_lines_for_toc: int = 6
   toc_keyword_boost: float = 0.25

   # Index
   min_comma_page_refs_for_index: int = 5
   min_dot_leaders_for_index: int = 5

   # Practice
   min_question_starts_for_practice: int = 3
   min_mc_options_for_practice: int = 4

   # Front matter
   front_matter_max_pdf_page: int = 10

   # Blankish
   blankish_word_count: int = 40
   blankish_text_len: int = 200

   # Content vs unknown
   min_sentence_count_for_content: int = 3
   min_avg_line_len_for_content: int = 40

# ============================================================================
# CLASSIFICATION RESULT
# ============================================================================

@dataclass
class PageClassification:
   page_id: str
   pdf_page_number: int
   real_page_number: Optional[int] = None
   page_type: str = "unknown"
   confidence: float = 0.0
   signals: Dict[str, Any] = field(default_factory=dict)
   detected_section_numbers: List[str] = field(default_factory=list)
   detected_chapter_numbers: List[int] = field(default_factory=list)

# ============================================================================
# REGEX PATTERNS
# ============================================================================

# Dot-leader lines:  "Something . . . . . 42" or "Something.........42"
# Matches both consecutive dots and space-separated dots
_DOT_LEADER_RE = re.compile(r'(?:\.\s*){3,}.*\b\d+\s*$')

# Section numbering on its own line:  "1.2.3" (possibly alone or with trailing text)
_SECTION_NUMBER_LINE_RE = re.compile(r'^\s*\d+(\.\d+){1,3}\s*$')

# Trailing page number at end of line: "Something 42"
_TRAILING_PAGE_NUM_RE = re.compile(r'\S\s+\d{1,4}\s*$')

# Question start: "1. ", "2. ", etc.
_QUESTION_START_RE = re.compile(r'^\s*\d+\.\s')

# Multiple choice: "A)", "(A)", "A."
_MC_OPTION_RE = re.compile(r'^\s*(?:\(?[A-E]\)?[\.\)]\s)')

# Index comma-page-ref: "term 12, 45, 89" or "term 12–15"
_COMMA_PAGE_REF_RE = re.compile(r'\b\d{1,4}(?:\s*[,–—-]\s*\d{1,4})+')

# Sentence-ending punctuation — require at least 10 chars before the period
# to avoid counting dot-leaders as "sentences"
_SENTENCE_END_RE = re.compile(r'[a-zA-Z]{2}[.!?]\s')

# Chapter number in text (for detected_chapter_numbers)
_CHAPTER_NUM_RE = re.compile(r'Chapter\s+(\d+)', re.IGNORECASE)

# Section number anywhere (for detected_section_numbers)
_SECTION_NUM_RE = re.compile(r'\b(\d+(?:\.\d+){1,3})\b')

# ============================================================================
# KEYWORD LISTS
# ============================================================================

_TOC_KEYWORDS = [
   "table of contents",
   "contents",
]

_INDEX_KEYWORDS = [
   "index",
   "subject index",
   "author index",
]

_PRACTICE_KEYWORDS = [
   "practice exercises",
   "practice problems",
   "practice questions",
   "review questions",
   "review problems",
   "review exercises",
   "self-test questions",
   "self-test problems",
   "homework problems",
   "homework questions",
   "homework exercises",
   "end of chapter exercises",
   "chapter exercises",
   "suggested exercises",
   "study questions",
   "discussion questions",
   "comprehension questions",
   "conceptual questions",
   "worked examples",
   "exercises",
   "problems",
]

_FRONT_MATTER_KEYWORDS = [
   "preface",
   "acknowledgments",
   "acknowledgements",
   "copyright",
   "isbn",
   "all rights reserved",
   "published by",
   "foreword",
   "about the author",
   "about the authors",
   "dedication",
]

# ============================================================================
# SIGNAL EXTRACTION
# ============================================================================

def _compute_signals(text: str, word_count: int, pdf_page_number: int) -> Dict[str, Any]:
   """
   Compute all heuristic signals from page text.

   Returns a flat dict of signal names to counts / booleans / floats.
   """
   text_lower = text.lower()
   lines = text.split('\n')
   non_empty_lines = [ln for ln in lines if ln.strip()]

   signals: Dict[str, Any] = {}

   # ── TOC signals ───────────────────────────────────────────────────
   signals['toc_keyword_hit'] = any(kw in text_lower for kw in _TOC_KEYWORDS)
   signals['dot_leader_count'] = sum(1 for ln in lines if _DOT_LEADER_RE.search(ln))
   signals['section_number_line_count'] = sum(1 for ln in lines if _SECTION_NUMBER_LINE_RE.match(ln))
   signals['trailing_page_num_line_count'] = sum(1 for ln in lines if _TRAILING_PAGE_NUM_RE.search(ln))

   # ── Index signals ─────────────────────────────────────────────────
   # "Index" near top of page (first 5 non-empty lines)
   top_text = '\n'.join(non_empty_lines[:5]).lower()
   signals['index_keyword_hit'] = any(kw in top_text for kw in _INDEX_KEYWORDS)
   signals['comma_page_refs_count'] = len(_COMMA_PAGE_REF_RE.findall(text))

   # ── Practice signals ──────────────────────────────────────────────
   # Check line-by-line so we match headings / short lines containing
   # the keyword, not passing mentions buried in long body paragraphs.
   practice_kw_hit = False
   for ln in lines:
      ln_stripped = ln.strip().lower()
      if not ln_stripped:
         continue
      for kw in _PRACTICE_KEYWORDS:
         if kw in ln_stripped and len(ln_stripped) < 80:
            practice_kw_hit = True
            break
      if practice_kw_hit:
         break
   signals['practice_keyword_hit'] = practice_kw_hit
   signals['question_start_count'] = sum(1 for ln in lines if _QUESTION_START_RE.match(ln))
   signals['mc_option_count'] = sum(1 for ln in lines if _MC_OPTION_RE.match(ln))

   # ── Front matter signals ──────────────────────────────────────────
   signals['front_matter_keyword_hit'] = any(kw in text_lower for kw in _FRONT_MATTER_KEYWORDS)
   signals['pdf_page_number'] = pdf_page_number

   # ── Blankish signals ──────────────────────────────────────────────
   signals['word_count'] = word_count
   signals['stripped_text_len'] = len(text.strip())

   # ── Content signals ───────────────────────────────────────────────
   signals['sentence_count_estimate'] = len(_SENTENCE_END_RE.findall(text))
   avg_line_len = (
      sum(len(ln) for ln in non_empty_lines) / len(non_empty_lines)
      if non_empty_lines else 0
   )
   signals['avg_line_len'] = round(avg_line_len, 1)

   # Punctuation density: fraction of chars that are sentence-ending
   total_chars = len(text) or 1
   punct_chars = sum(1 for c in text if c in '.!?;:')
   signals['punctuation_density'] = round(punct_chars / total_chars, 4)

   return signals

# ============================================================================
# CLASSIFIER
# ============================================================================

def classify_page(
   text: str,
   *,
   word_count: Optional[int] = None,
   pdf_page_number: int = 0,
   config: Optional[ClassifierConfig] = None,
) -> Tuple[str, float, Dict[str, Any]]:
   """
   Classify a single page into a page type.

   Args:
      text: Full text of the page
      word_count: Word count (computed from text if None)
      pdf_page_number: 1-based PDF page number
      config: Optional ClassifierConfig with thresholds

   Returns:
      (page_type, confidence, signals)
   """
   if config is None:
      config = ClassifierConfig()

   text = text or ''
   if word_count is None:
      word_count = len(text.split())

   signals = _compute_signals(text, word_count, pdf_page_number)

   # ── 1. Blankish (check first — nearly empty pages can't be anything else) ─
   if (
      word_count < config.blankish_word_count
      or signals['stripped_text_len'] < config.blankish_text_len
   ):
      return ("blankish", 0.95, signals)

   # ── 2. TOC ────────────────────────────────────────────────────────
   toc_score = 0.0

   if signals['toc_keyword_hit']:
      toc_score += 0.50

   if signals['dot_leader_count'] >= config.min_dot_leader_lines_for_toc:
      toc_score += 0.40

   if signals['section_number_line_count'] >= config.min_section_number_lines_for_toc:
      toc_score += 0.20

   if signals['trailing_page_num_line_count'] >= config.min_dot_leader_lines_for_toc:
      toc_score += 0.15

   if toc_score >= 0.50:
      confidence = min(toc_score, 1.0)
      return ("toc", round(confidence, 3), signals)

   # ── 3. Index ──────────────────────────────────────────────────────
   index_score = 0.0

   if signals['index_keyword_hit']:
      index_score += 0.40

   if signals['comma_page_refs_count'] >= config.min_comma_page_refs_for_index:
      index_score += 0.40

   if signals['dot_leader_count'] >= config.min_dot_leaders_for_index:
      index_score += 0.20

   # Index pages tend to have low sentence punctuation
   if signals['punctuation_density'] < 0.01 and signals['word_count'] > 100:
      index_score += 0.10

   if index_score >= 0.50:
      confidence = min(index_score, 1.0)
      return ("index", round(confidence, 3), signals)

   # ── 4. Front matter (check before practice — early pages mentioning
   #       "exercises" in prose should not be classified as practice) ──
   if (
      signals['front_matter_keyword_hit']
      and pdf_page_number <= config.front_matter_max_pdf_page
   ):
      return ("front_matter", 0.80, signals)

   # ── 5. Practice ───────────────────────────────────────────────────
   practice_score = 0.0

   if signals['practice_keyword_hit']:
      practice_score += 0.45

   if signals['question_start_count'] >= config.min_question_starts_for_practice:
      practice_score += 0.35

   if signals['mc_option_count'] >= config.min_mc_options_for_practice:
      practice_score += 0.25

   if practice_score >= 0.45:
      confidence = min(practice_score, 1.0)
      return ("practice", round(confidence, 3), signals)

   # ── 6. Content vs Unknown ────────────────────────────────────────
   if (
      signals['sentence_count_estimate'] >= config.min_sentence_count_for_content
      and signals['avg_line_len'] >= config.min_avg_line_len_for_content
   ):
      return ("content", 0.85, signals)

   # Looser: if we have enough words and some sentences, still content
   if word_count > 100 and signals['sentence_count_estimate'] >= 2:
      return ("content", 0.60, signals)

   return ("unknown", 0.30, signals)

# ============================================================================
# DETECTED NUMBERS (optional enrichment)
# ============================================================================

def _extract_detected_numbers(text: str) -> Tuple[List[str], List[int]]:
   """Pull section numbers (1.2.3) and chapter numbers from text."""
   section_numbers = sorted(set(_SECTION_NUM_RE.findall(text)))
   chapter_numbers = sorted(set(int(m) for m in _CHAPTER_NUM_RE.findall(text)))
   return section_numbers, chapter_numbers

# ============================================================================
# FILE-LEVEL PROCESSING
# ============================================================================

def classify_pagerecords(
   input_path: Path,
   output_path: Path,
   config: Optional[ClassifierConfig] = None,
   verbose: bool = True,
) -> Dict[str, int]:
   """
   Classify every page in a PageRecords JSONL and write a sidecar file.

   Args:
      input_path: Path to *_PageRecords JSONL
      output_path: Path to write *_PageClassifications.jsonl
      config: Optional ClassifierConfig
      verbose: Print summary when done

   Returns:
      Dict of page_type -> count
   """
   if config is None:
      config = ClassifierConfig()

   counts: Counter = Counter()
   confidence_sums: Counter = Counter()

   with open(input_path, 'r', encoding='utf-8') as fin, \
        open(output_path, 'w', encoding='utf-8') as fout:

      for line in fin:
         line = line.strip()
         if not line:
            continue

         record = json.loads(line)
         text = record.get('text', '') or ''
         wc = record.get('word_count', None)
         pdf_page = record.get('pdf_page_number', 0)

         page_type, confidence, signals = classify_page(
            text,
            word_count=wc,
            pdf_page_number=pdf_page,
            config=config,
         )

         section_nums, chapter_nums = _extract_detected_numbers(text)

         classification = PageClassification(
            page_id=record.get('id', ''),
            pdf_page_number=pdf_page,
            real_page_number=record.get('real_page_number'),
            page_type=page_type,
            confidence=confidence,
            signals=signals,
            detected_section_numbers=section_nums,
            detected_chapter_numbers=chapter_nums,
         )

         fout.write(json.dumps(asdict(classification), ensure_ascii=False) + '\n')

         counts[page_type] += 1
         confidence_sums[page_type] += confidence

   if verbose:
      _print_summary(counts, confidence_sums)

   return dict(counts)

# ============================================================================
# SUMMARY
# ============================================================================

def _print_summary(counts: Counter, confidence_sums: Counter) -> None:
   total = sum(counts.values())
   print(f"\nPage Classification Summary ({total} pages):")
   print("-" * 50)
   print(f"  {'Type':<14s} {'Count':>6s} {'Avg Conf':>10s}")
   print(f"  {'----':<14s} {'-----':>6s} {'--------':>10s}")

   for ptype in PAGE_TYPES:
      c = counts.get(ptype, 0)
      if c == 0:
         continue
      avg = confidence_sums[ptype] / c
      print(f"  {ptype:<14s} {c:>6d} {avg:>10.3f}")

   print("-" * 50)

# ============================================================================
# CLI
# ============================================================================

def main():
   parser = argparse.ArgumentParser(
      description="Classify PageRecords into page types (toc, index, practice, etc.)"
   )
   parser.add_argument(
      '--input', '-i',
      required=True,
      help="Path to *_PageRecords JSONL file",
   )
   parser.add_argument(
      '--output', '-o',
      default=None,
      help="Output path (default: same dir, *_PageClassifications.jsonl)",
   )

   args = parser.parse_args()

   input_path = Path(args.input)
   if not input_path.exists():
      print(f"✗ Input file not found: {input_path}")
      return

   if args.output:
      output_path = Path(args.output)
   else:
      # Derive output name from input
      stem = input_path.stem
      if stem.endswith('_PageRecords'):
         stem = stem[:-len('_PageRecords')]
      output_path = input_path.parent / f"{stem}_PageClassifications.jsonl"

   print(f"Input:  {input_path}")
   print(f"Output: {output_path}")

   classify_pagerecords(input_path, output_path)

   print(f"\n✓ Classifications written to {output_path}")


if __name__ == "__main__":
   main()
