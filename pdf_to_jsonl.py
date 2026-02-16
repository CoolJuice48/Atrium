"""
PDF to JSONL Converter with Complete Document Structure Extraction

COMPLETE PIPELINE:
  1. PDF Extraction → PageRecords (raw page text)
  2. Chapter Scanning → Chapter boundaries with special pages (practice/solutions)
  3. Section Scanning → Section boundaries (page ranges)
  4. Section Text Extraction → Complete sections with full text
  5. Optional Chunking → Split long sections for better embeddings

OUTPUT FILES:
  - {name}_PageRecords           : Raw page text (all pages)
  - {name}_DocumentRecord        : Document metadata
  - {name}_Chapters.jsonl        : Chapter boundaries + special pages
  - {name}_Sections.jsonl        : Section boundaries (page ranges)
  - {name}_SectionsWithText.jsonl: Complete sections with text (READY FOR EMBEDDINGS!)
  
The final SectionsWithText file contains everything needed for semantic search:
  - Section number & title
  - Chapter context
  - Page ranges
  - Full text content
  - Metadata for citations

Usage:
  python pdf_to_jsonl.py textbook.pdf
  
The result is embedding-ready sections that preserve document structure while
enabling semantic search with accurate citations.
"""

import uuid
import fitz
import json
import time
from pathlib import Path
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import List, Optional, TYPE_CHECKING, Union, Tuple, Set, Dict
from id_factory import IDFactory
from legacy.regex_parts import has_answer, has_question, has_chapter, has_section
from legacy.conversion_logger import ConversionLogger, log_new_pdf, log_completed_conversion
from legacy.chapter_scanner import scan_pagerecords_for_chapters, save_chapters_jsonl
from legacy.section_scanner import scan_pagerecords_for_sections, save_sections_jsonl
from legacy.section_text_extractor import build_sections_with_text, save_sections_with_text, chunk_long_sections, save_section_chunks

""" -------------------------------------------------------------------------------------------------------- """
if TYPE_CHECKING:
   from legacy.qa_handler import QuestionRecord, AnswerRecord

QAItem = Union['QuestionRecord', 'AnswerRecord']

""" -------------------------------------------------------------------------------------------------------- """
@dataclass
class DocumentRecord:
   id: Optional[str]=None                           # Individual book ID (UUID) generated from title/author/year
   section_ids: Set[str]=field(default_factory=set) # Set of section_ids in the book
   page_ids: Set[str]=field(default_factory=set)    # Set of page_ids in the book
   book_domain: Optional[str]=None                  # Domain or subject area of the book (e.g. "computer science", "physics", etc.)
   title: Optional[str]=None                        # Book title
   author: Optional[str]=None                       # Book author(s)
   publication_year: Optional[int]=None             # Publication year of the book
   references: Optional[List[str]]=None             # List of other documents' book_ids that are referenced
   source_pdf: Optional[str]=None                   # Original PDF file name for traceability
   output_jsonl_path: Optional[str]=None            # Path to output JSONL file containing page records
   source_link: Optional[str]=None                  # URL to original source if available
   related_readings: Optional[Set[str]]=None        # Deduplicated UUIDs of related documents
   page_start_num: Optional[int]=None               # Starting page number of the book (1-based)
   page_end_num: Optional[int]=None                 # Ending page number of the book (1-based)
   num_sections: int=0                              # Total number of sections extracted from the book
   num_pages: int=0                                 # Total number of pages in the book
   num_questions: int=0                             # Total number of questions extracted from the book
   num_answers: int=0                               # Total number of answers extracted from the book
   num_words: int=0                                 # Total number of words in the book (summed from all pages)
   

""" -------------------------------------------------------------------------------------------------------- """
@dataclass
class SectionRecord:
   id: Optional[str]=None                           # Unique section ID (UUID) generated from book_id + section label/title
   page_ids: Set[str]=field(default_factory=set)    # Set of page IDs this section appears in
   book_id: str=''                                  # Book ID this section belongs to
   question_ids: Optional[Set[str]]=None            # Set of question_ids that belong to this section
   section_label: Optional[str]=None                # Section label extracted from text (e.g. "1.2")
   section_title: Optional[str]=None                # Section title extracted from text (e.g. "Section 1.2: Data Structures")
   section_begin: Optional[int]=None                # Starting page number of the section (1-based)
   section_end: Optional[int]=None                  # Ending page number of the section (1-based)
   text: str=''                                     # Full text of the section (concatenated from all pages it appears on)
   word_count: int=0                                # Total word count of the section text
   text_embedding: Optional[List[float]]=None       # Optional text embedding for the section (e.g. from a language model)

""" -------------------------------------------------------------------------------------------------------- """
@dataclass
class PageRecord:
   id: Optional[str]=None                           # Unique page ID (UUID) generated from book_id + page number for traceability
   section_ids: Set[str]=field(default_factory=set) # Set of section_ids that this page contains (for multi-section pages)
   book_id: str=None                                # Book ID this page belongs to
   pdf_page_number: int=None                        # Page number in the PDF (1-based)
   real_page_number: Optional[int] = None           # Optional real page number if available (e.g. from page text)
   text: str=None                                   # Full text of the page
   word_count: int=0                                # Total word count of the page text
   has_chapter: bool=False                          # Whether a chapter appears on a page
   has_section: bool=False                          # Whether a section appears on a page
   has_question: bool=False                         # Whether a question appears on a page
   has_answer: bool=False                           # Whether an answer appears on a page
   text_embedding: Optional[List[float]]=None       # Optional text embedding for the page (e.g. from a language model)

""" -------------------------------------------------------------------------------------------------------- """
"""
Convert dataclass objects to JSON-serializable format, handling sets and nested dataclasses.
Args:
   obj - The object to convert (can be a dataclass, dict, list, set, or primitive type)
Returns:
   A JSON-serializable version of the object (e.g. sets converted to sorted lists, dataclasses converted to dicts)
"""
def to_jsonable(obj):
   if is_dataclass(obj):
      obj = asdict(obj)
   if isinstance(obj, dict):
      return {k: to_jsonable(v) for k, v in obj.items()}
   if isinstance(obj, list):
      return [to_jsonable(v) for v in obj]
   if isinstance(obj, set):
      return sorted(obj)
   return obj

""" -------------------------------------------------------------------------------------------------------- """
"""
PDF to JSONL conversion using PyMuPDF page with improved gap detection.
Args:
   page - PyMuPDF page object
Returns:
   PageRecord object
"""
def words_to_text(
      pymu: str,
      book_id: str='',
) -> PageRecord:
   words = pymu.get_text("words") or []
   if not words:
      return PageRecord(
         id=IDFactory.page_id(book_id, pymu.number + 1),
         book_id=book_id,
         pdf_page_number=pymu.number + 1,
         text='',
         word_count=0
      )
   
   # Sort top to bottom, then left to right
   words.sort(key=lambda w: (w[5], w[6], w[1], w[0]))
   
   lines = []
   current_line = []
   prev = None
   
   for w in words:
      x0, y0, x1, y1, text, block_no, line_no, word_no = w
      
      if prev is None:
         current_line = [text]
         prev = w
         continue
      
      # New line if block or line number changes
      if (block_no, line_no) != (prev[5], prev[6]):
         lines.append(' '.join(current_line))
         current_line = [text]
         prev = w
         continue
      
      # Same line: use a FIXED gap threshold instead of proportion-based
      prev_x1 = prev[2]
      gap = x0 - prev_x1
      
      # Use a very low threshold - gaps between real words are ~2.2-3.0,
      # gaps between separate sections are negative (column jumps)
      # Use 2.0 to force separation at most gaps
      if gap >= 2.0:
         current_line.append(text)
      else:
         current_line[-1] = current_line[-1] + text
      
      prev = w
   
   if current_line:
      lines.append(' '.join(current_line))
   
   text = '\n'.join(lines)

   return PageRecord(
      id=IDFactory.page_id(book_id, pymu.number + 1),
      book_id=book_id,
      pdf_page_number=pymu.number + 1,
      text=text,
      word_count=len(words),
      has_chapter=has_chapter(text),
      has_section=has_section(text),
      has_question=has_question(text),
      has_answer=has_answer(text)
   )

""" -------------------------------------------------------------------------------------------------------- """
"""
Identify section boundaries based on page text and simple heuristics.
Args:
   page - PageRecord object
   curr_idx - Current page index in the overall document (0-based)
Returns:
   Set of section keys
"""
def group_sections_per_page(page: PageRecord) -> Set[str]:
   import re
   text = page.text or ''
   text_lower = text.lower()
   section_ids: Set[str] = set()

   # --- Practice / exercise detection ---
   practice_keywords = [
      "practice exercises",
      "practice problems",
      "practice questions",
      "review questions",
      "review problems",
      "review exercises",
      "self-test questions",
      "self-test problems",
      "self test questions",
      "homework problems",
      "homework questions",
      "homework exercises",
      "end of chapter exercises",
      "end of chapter problems",
      "chapter exercises",
      "suggested exercises",
      "suggested problems",
      "worked examples",
      "study questions",
      "discussion questions",
      "comprehension questions",
      "conceptual questions",
      "thought questions",
   ]
   for kw in practice_keywords:
      if kw in text_lower:
         section_ids.add(IDFactory.section_id(page.book_id, "practice exercises"))
         break

   # Standalone headings: "Exercises", "Problems", "Questions" on their own line
   if IDFactory.section_id(page.book_id, "practice exercises") not in section_ids:
      if re.search(r'(?m)^(Exercises?|Problems?|Questions?)\s*$', text, re.IGNORECASE):
         section_ids.add(IDFactory.section_id(page.book_id, "practice exercises"))

   # --- Solution / answer detection ---
   solution_keywords = [
      "exercise solutions",
      "answer key",
      "answer keys",
      "solutions to exercises",
      "solutions to problems",
      "solution to exercises",
      "solution to problems",
      "selected answers",
      "selected solutions",
      "answers to exercises",
      "answers to problems",
      "answers to questions",
      "hints and solutions",
      "solutions to selected",
      "answers to selected",
      "solutions to odd-numbered",
      "answers to odd-numbered",
      "solutions manual",
   ]
   for kw in solution_keywords:
      if kw in text_lower:
         section_ids.add(IDFactory.section_id(page.book_id, "exercise solutions"))
         break

   # Standalone headings: "Solutions", "Answers" on their own line
   if IDFactory.section_id(page.book_id, "exercise solutions") not in section_ids:
      if re.search(r'(?m)^(Solutions?|Answers?)\s*$', text, re.IGNORECASE):
         section_ids.add(IDFactory.section_id(page.book_id, "exercise solutions"))

   return section_ids

""" -------------------------------------------------------------------------------------------------------- """
"""
Converts the PDF to JSONL format, one page per line. PageRecords and DocumentRecord stored as two
separate JSONL files in a new directory
Returns:
   Tuple of (DocumentRecord ID, output path)
"""
def convert_pdf(
    pdf_path: Path,
    output_dir_name: str = None,
    output_dir: Path = None,
    auto_chunk: bool = None,
    backend: str = "pymupdf",
    pymupdf_mode: str = "text",
    emit_pdf_toc: bool = False,
    emit_page_labels: bool = False,
) -> Tuple[str, Path]:
   """
   Convert PDF to JSONL. When output_dir is provided, use it directly (no converted/).
   Otherwise use root/converted/{output_dir_name or base_name}.
   """
   root = Path(__file__).parent
   base_name = pdf_path.stem

   if output_dir is not None:
      output_dir = Path(output_dir).resolve()
      output_dir.mkdir(parents=True, exist_ok=True)
      log_file = output_dir / ".conversion_log.jsonl"
   else:
      if output_dir_name is not None:
         out_dir = output_dir_name
      else:
         out_dir = input("Enter desired output folder name, or press enter for default: ").strip()
      if out_dir:
         output_dir = root / 'converted' / Path(out_dir)
      else:
         output_dir = root / 'converted' / base_name
      output_dir.mkdir(parents=True, exist_ok=True)
      log_file = root / "converted" / "conversion_logs.jsonl"

   logger = ConversionLogger(log_file)

   # Initialize book record
   pdf_name = pdf_path.stem
   book = DocumentRecord(title=pdf_name)
   book_key = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(pdf_path)))
   book.id = IDFactory.book_id(book_key)
   book.source_pdf = str(pdf_path)

   # Check if already logged
   if not logger.get_entry(pdf_name):
      log_new_pdf(logger, pdf_path, book.id)

   print(f"{'=' * 70}\n")
   print(f"Converting PDF to JSONL...\n")

   page_count = 0

   t0 = time.perf_counter()
   last_print_time = t0
   DRAW_EVERY_SEC = 0.25  # Print progress every 0.25 seconds
   BAR_WIDTH = 15

   def draw_progress(done: int, total: int, elapsed: float):
      rate = done / elapsed if elapsed > 0 else 0.0
      remaining = (total - done) / rate if rate > 0 else float("inf")

      frac = done / total if total else 0.0
      filled = int(frac * BAR_WIDTH)
      bar = "█" * filled + "░" * (BAR_WIDTH - filled)

      eta_str = "∞" if remaining == float("inf") else f"{remaining:6.1f}s"
      line = (
         f"\r[{bar}] {done:4d}/{total}  "
         f"elapsed {elapsed:6.1f}s  "
         f"eta {eta_str}  "
         f"{rate:5.2f} pages/s"
      )
      print(line, end="", flush=True)

   # Read PDF
   page_out_file = output_dir / f"{base_name}_PageRecords"
   TOC_SCAN_PAGES = 60
   toc_pages: List[PageRecord] = []

   use_pymupdf = backend == "pymupdf"

   if use_pymupdf:
      # --- PyMuPDF backend: iterate via pdf_backends dispatcher ---
      from extractors.pdf_backends import extract_pagerecords

      # We need total page count for the progress bar
      with fitz.open(pdf_path) as tmp_doc:
         total_pages = len(tmp_doc)

      with open(page_out_file, 'w', encoding='utf-8') as outf:
         for d in extract_pagerecords(
            pdf_path, book.id,
            backend="pymupdf", pymupdf_mode=pymupdf_mode
         ):
            page_count += 1
            pdf_page_number = d["pdf_page_number"]

            # Rebuild a lightweight PageRecord for TOC scanning
            if pdf_page_number <= TOC_SCAN_PAGES:
               toc_pages.append(PageRecord(
                  id=d["id"], book_id=d["book_id"],
                  pdf_page_number=pdf_page_number,
                  text=d["text"], word_count=d["word_count"],
                  has_chapter=d["has_chapter"], has_section=d["has_section"],
                  has_question=d["has_question"], has_answer=d["has_answer"],
               ))

            book.page_ids.add(d["id"])
            book.num_words += d["word_count"]
            book.num_pages = page_count
            for sid in d.get("section_ids", []):
               book.section_ids.add(sid)
            book.num_sections = len(book.section_ids)

            outf.write(json.dumps(d, ensure_ascii=False) + '\n')

            now = time.perf_counter()
            if now - last_print_time >= DRAW_EVERY_SEC:
               draw_progress(page_count, total_pages, now - t0)
               last_print_time = now

      # Emit optional sidecar metadata files
      if emit_pdf_toc:
         from extractors.pymupdf_backend import extract_toc, save_toc
         toc_data = extract_toc(pdf_path)
         if toc_data:
            toc_out = output_dir / f"{base_name}_TOCFromPDF.json"
            save_toc(toc_data, toc_out)
            print(f"\n  TOC metadata: {toc_out.name} ({len(toc_data)} entries)")

      if emit_page_labels:
         from extractors.pymupdf_backend import extract_page_labels, save_page_labels
         labels = extract_page_labels(pdf_path)
         if labels:
            labels_out = output_dir / f"{base_name}_PageLabels.json"
            save_page_labels(labels, labels_out)
            print(f"  Page labels: {labels_out.name} ({len(labels)} pages)")

   else:
      # --- Current backend: original words_to_text() logic ---
      with fitz.open(pdf_path) as pdf:
         with open(page_out_file, 'w', encoding='utf-8') as outf:
            for page_idx in range(len(pdf)):

               # 1) Build PageRecord object
               page = words_to_text(pdf[page_idx], book_id=book.id)
               if page_idx < TOC_SCAN_PAGES:
                  toc_pages.append(page)

               # 2) Add page.id to book.page_ids
               book.page_ids.add(page.id)

               # 3) Add section_ids to page record based on heuristics
               sections = group_sections_per_page(page)
               page.section_ids = {s for s in sections if s is not None}

               # 4) Dump PageRecord to DocumentRecord JSONL file
               d = to_jsonable(page)
               outf.write(json.dumps(d, ensure_ascii=False) + '\n')

               # 5) Update num_pages and num_words in book record as we go
               page_count += 1
               book.num_words += page.word_count
               book.num_pages = page_count

               # 6) Update remaining book metadata
               book.section_ids.update(page.section_ids)
               book.page_ids.add(page.id)
               book.num_sections = len(book.section_ids)
               book.num_questions = 0
               book.num_answers = 0
               book.references = []
               book.related_readings = []

               now = time.perf_counter()
               if now - last_print_time >= DRAW_EVERY_SEC:
                  draw_progress(page_count, len(pdf), now - t0)
                  last_print_time = now

               book.num_pages = page_count

   # --- Simple chapter detection by scanning PageRecords ---
   print(f"\n{'='*70}")
   print("DETECTING CHAPTERS")
   print(f"{'='*70}")
   
   try:
      boundaries = scan_pagerecords_for_chapters(
         page_out_file,
         min_chapter=1,
         max_chapter=50,
         min_page_gap=5,
         verbose=True
      )
      
      if boundaries:
         chapters_out = output_dir / f"{base_name}_Chapters.jsonl"
         save_chapters_jsonl(boundaries, chapters_out, verbose=True)
         print(f"\n✓ Chapter detection complete: {len(boundaries)} chapters found")
      else:
         print(f"\n⚠ No chapters detected")

   except Exception as e:
      print(f"\n⚠ Chapter detection failed: {e}")
      import traceback
      traceback.print_exc()

   # --- Section detection by scanning PageRecords ---
   print(f"\n{'='*70}")
   print("DETECTING SECTIONS")
   print(f"{'='*70}")

   try:
      sections = scan_pagerecords_for_sections(
         page_out_file,
         max_depth=2,
         verbose=True
      )

      if sections:
         sections_out = output_dir / f"{base_name}_Sections.jsonl"
         save_sections_jsonl(sections, sections_out, verbose=True)
         print(f"\n✓ Section detection complete: {len(sections)} sections found")
      else:
         print(f"\n⚠ No sections detected")

   except Exception as e:
      print(f"\n⚠ Section detection failed: {e}")
      import traceback
      traceback.print_exc()
      sections = []  # Empty list if detection failed

   # --- Extract section text (only if sections were detected) ---
   if sections:
      print(f"\n{'='*70}")
      print("EXTRACTING SECTION TEXT")
      print(f"{'='*70}")
      
      try:
         # Build complete sections with text
         complete_sections = build_sections_with_text(
            sections_out,
            page_out_file,
            book_name=base_name,
            chapters_file=chapters_out if 'chapters_out' in locals() else None,
            verbose=True
         )
         
         # Ask user if they want chunking (unless auto_chunk is set)
         print("\n" + "="*70)
         if auto_chunk is None:
            use_chunking = input("Chunk long sections for better embeddings? (y/n, default=y): ").strip().lower()
            use_chunking = use_chunking != 'n'  # Default to yes
         else:
            use_chunking = auto_chunk
            print(f"Auto-chunking: {'enabled' if use_chunking else 'disabled'}")
         
         if use_chunking:
            print("\n" + "="*70)
            print("CHUNKING LONG SECTIONS")
            print("="*70)
            
            chunks = chunk_long_sections(
               complete_sections,
               max_words=1000,
               overlap_words=100,
               verbose=True
            )
            
            sections_text_out = output_dir / f"{base_name}_SectionsWithText_Chunked.jsonl"
            save_section_chunks(chunks, sections_text_out, verbose=True)
            
            print(f"\n✓ Section text extraction complete: {len(chunks)} chunks created")
         else:
            sections_text_out = output_dir / f"{base_name}_SectionsWithText.jsonl"
            save_sections_with_text(complete_sections, sections_text_out, verbose=True)
            
            print(f"\n✓ Section text extraction complete: {len(complete_sections)} sections with text")
      
      except Exception as e:
         print(f"\n⚠ Section text extraction failed: {e}")
         import traceback
         traceback.print_exc()

   book.output_jsonl_path = str(output_dir)
   
   # Write DocumentRecord to same directory
   book_out_file = output_dir / f"{base_name}_DocumentRecord"
   with open(book_out_file, 'w', encoding='utf-8') as outf:
      outf.write(json.dumps(to_jsonable(book), indent=2, ensure_ascii=False, sort_keys=True))

   # Print closing message
   print(f"\n\n{'=' * 70}")
   print(f"CONVERSION COMPLETE")
   print(f"{'=' * 70}")
   print(f"\nOutput directory: {output_dir}")
   print(f"\nFiles created:")
   print(f"  📄 Pages: {page_out_file.name}")
   print(f"     └─ {page_count} pages, {book.num_words:,} words")
   
   if 'chapters_out' in locals() and chapters_out.exists():
      num_chapters = len(boundaries) if 'boundaries' in locals() else 0
      print(f"  📚 Chapters: {chapters_out.name}")
      print(f"     └─ {num_chapters} chapters detected")
   
   if 'sections_out' in locals() and sections_out.exists():
      num_sections = len(sections) if sections else 0
      print(f"  📑 Sections: {sections_out.name}")
      print(f"     └─ {num_sections} section boundaries")
   
   if 'sections_text_out' in locals() and sections_text_out.exists():
      file_size = sections_text_out.stat().st_size / (1024*1024)
      print(f"  ✨ Sections with Text: {sections_text_out.name}")
      print(f"     └─ {file_size:.2f} MB - READY FOR EMBEDDINGS!")
   
   print(f"  📋 Document Record: {book_out_file.name}")
   
   print(f"\nStatistics:")
   print(f"  Total words: {book.num_words:,}")
   print(f"  Avg words/page: {book.num_words / page_count:.0f}")
   
   if 'sections_text_out' in locals():
      print(f"\n🎉 Pipeline complete! Section text is ready for embedding.")

   log_completed_conversion(
      logger,
      base_name,
      str(output_dir),
      page_count=book.num_pages,
      word_count=book.num_words
   )
    
   return (book.id, output_dir)

if __name__ == "__main__":
   import argparse

   parser = argparse.ArgumentParser(
      description="Convert a PDF to JSONL PageRecords with chapter/section detection."
   )
   parser.add_argument("--pdf", type=Path, required=True, help="Path to the PDF file")
   parser.add_argument("--out", type=str, default=None,
                        help="Output folder name (under converted/). Default: PDF stem")
   parser.add_argument("--backend", choices=["pymupdf", "legacy"], default="pymupdf",
                        help="Extraction backend (default: pymupdf)")
   parser.add_argument("--pymupdf-mode", choices=["text", "blocks"], default="text",
                        help="PyMuPDF extraction mode (default: text)")
   parser.add_argument("--emit-pdf-toc", action="store_true",
                        help="Write <book>_TOCFromPDF.json sidecar (pymupdf backend only)")
   parser.add_argument("--emit-page-labels", action="store_true",
                        help="Write <book>_PageLabels.json sidecar (pymupdf backend only)")
   parser.add_argument("--auto-chunk", action="store_true", default=None,
                        help="Enable section chunking without prompting")
   parser.add_argument("--no-chunk", action="store_true",
                        help="Disable section chunking without prompting")

   args = parser.parse_args()

   chunk_flag = None
   if args.auto_chunk:
      chunk_flag = True
   elif args.no_chunk:
      chunk_flag = False

   convert_pdf(
      pdf_path=args.pdf,
      output_dir_name=args.out,
      auto_chunk=chunk_flag,
      backend=args.backend,
      pymupdf_mode=args.pymupdf_mode,
      emit_pdf_toc=args.emit_pdf_toc,
      emit_page_labels=args.emit_page_labels,
   )