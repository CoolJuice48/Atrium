#!/usr/bin/env python3
"""
Enhanced chapter scanner with special page type detection.

Detects:
- Chapter boundaries (Chapter 1, Chapter 2, etc.)
- Special page types (Practice Exercises, Exercise Solutions)
- Configurable patterns for different textbook formats
"""

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple, Set
from dataclasses import dataclass, field


@dataclass
class SpecialPageType:
   """Represents a special page type within a chapter."""
   page_type: str  # 'practice', 'solutions', 'summary', etc.
   page_number: int
   chapter_number: Optional[int] = None
   title: Optional[str] = None
   
   def __repr__(self):
      return f"{self.page_type.title()} @ page {self.page_number}"


@dataclass
class ChapterBoundary:
   """Enhanced chapter boundary with special pages."""
   chapter_number: int
   page_number: int
   chapter_title: Optional[str] = None
   special_pages: List[SpecialPageType] = field(default_factory=list)
   
   def add_special_page(self, page_type: str, page_num: int, title: str = None):
      """Add a special page to this chapter."""
      special = SpecialPageType(
         page_type=page_type,
         page_number=page_num,
         chapter_number=self.chapter_number,
         title=title
      )
      self.special_pages.append(special)
   
   def __repr__(self):
      special_info = f" ({len(self.special_pages)} special pages)" if self.special_pages else ""
      if self.chapter_title:
         return f"Chapter {self.chapter_number}: '{self.chapter_title}' @ page {self.page_number}{special_info}"
      return f"Chapter {self.chapter_number} @ page {self.page_number}{special_info}"
   
   def to_dict(self) -> dict:
      """Convert to dictionary for JSON serialization."""
      return {
         'chapter_number': self.chapter_number,
         'page_number': self.page_number,
         'chapter_title': self.chapter_title,
         'special_pages': [
               {
                  'type': sp.page_type,
                  'page': sp.page_number,
                  'title': sp.title
               }
               for sp in self.special_pages
         ]
      }


# Configurable patterns for different page types
SPECIAL_PAGE_PATTERNS = {
   'practice': [
      r'Chapter\s+\d+\s+Practice\s+Exercises?',
      r'Practice\s+Problems?',
      r'Chapter\s+Exercises?',
      r'Exercises?\s*$',
      r'Problems?\s*$',
   ],
   'solutions': [
      r'Chapter\s+\d+\s+Exercise\s+Solutions?',
      r'Solutions?\s+to\s+Exercises?',
      r'Answer\s+Key',
   ],
   'summary': [
      r'Chapter\s+\d+\s+Summary',
      r'Chapter\s+Review',
   ],
   'review': [
      r'Chapter\s+\d+\s+Review',
      r'Review\s+Questions?',
   ]
}


def detect_chapter_at_page_start(text: str) -> Optional[Tuple[int, str]]:
   """
   Detect if a page starts with a chapter header.
   
   Returns:
      (chapter_number, chapter_title) or None
   """
   if not text:
      return None
   
   lines = text.split('\n')[:15]
   
   for i, line in enumerate(lines):
      line = line.strip()
      match = re.match(r'^Chapter\s+(\d+)(?:[.:]\s+.+)?$', line, re.IGNORECASE)
      
      if match:
         chapter_num = int(match.group(1))
         
         # Try to get title from next line
         title = None
         if i + 1 < len(lines):
               potential_title = lines[i + 1].strip()
               # Title should be non-empty and not a section number
               if potential_title and not re.match(r'^\d+\.\d+', potential_title):
                  title = potential_title
         
         return (chapter_num, title)
   
   return None


def detect_special_page_type(
   text: str,
   patterns: dict = SPECIAL_PAGE_PATTERNS
) -> Optional[Tuple[str, str]]:
   """
   Detect if page contains special section (practice, solutions, etc.).
   
   Args:
      text: Page text to search
      patterns: Dictionary of {page_type: [regex_patterns]}
   
   Returns:
      (page_type, matched_text) or None
   """
   if not text:
      return None
   
   # Check first ~20 lines where headers usually appear
   header = '\n'.join(text.split('\n')[:20])
   
   for page_type, pattern_list in patterns.items():
      for pattern in pattern_list:
         match = re.search(pattern, header, re.IGNORECASE | re.MULTILINE)
         if match:
               return (page_type, match.group(0))
   
   return None


def scan_pagerecords_for_chapters(
   pagerecords_file: Path,
   *,
   min_chapter: int = 1,
   max_chapter: int = 50,
   min_page_gap: int = 5,
   detect_special_pages: bool = True,
   special_patterns: dict = None,
   verbose: bool = True,
) -> List[ChapterBoundary]:
   """
   Scan PageRecords file and extract chapter boundaries with special pages.
   
   Args:
      pagerecords_file: Path to _PageRecords file
      min_chapter: Minimum expected chapter number
      max_chapter: Maximum expected chapter number
      min_page_gap: Minimum pages between chapters
      detect_special_pages: Whether to detect special page types
      special_patterns: Custom patterns dict (uses SPECIAL_PAGE_PATTERNS if None)
      verbose: Print progress
   
   Returns:
      List of ChapterBoundary objects with special pages
   """
   boundaries = []
   seen_chapters = set()
   last_page = 0
   current_chapter = None
   
   if special_patterns is None:
      special_patterns = SPECIAL_PAGE_PATTERNS
   
   if verbose:
      print(f"  Scanning for chapters and special pages...")
   
   with open(pagerecords_file, 'r', encoding='utf-8') as f:
      for line_num, line in enumerate(f, 1):
         if not line.strip():
               continue
         
         try:
               page_data = json.loads(line)
         except json.JSONDecodeError:
               if verbose:
                  print(f"    Warning: Skipping malformed JSON at line {line_num}")
               continue
         
         page_num = page_data.get('pdf_page_number')
         text = page_data.get('text', '')
         
         if not page_num or not text:
               continue
         
         # Detect chapter boundary
         chapter_result = detect_chapter_at_page_start(text)
         
         if chapter_result:
               chapter_num, title = chapter_result
               
               # Validation
               if not (min_chapter <= chapter_num <= max_chapter):
                  continue
               
               if chapter_num in seen_chapters:
                  continue
               
               if last_page > 0 and (page_num - last_page) < min_page_gap:
                  if verbose:
                     print(f"    Skipping Chapter {chapter_num} @ page {page_num} (too close)")
                  continue
               
               # Valid chapter found
               boundary = ChapterBoundary(chapter_num, page_num, title)
               boundaries.append(boundary)
               seen_chapters.add(chapter_num)
               last_page = page_num
               current_chapter = boundary
               
               if verbose:
                  title_display = f": {title}" if title else ""
                  print(f"    ✓ Chapter {chapter_num}{title_display} @ page {page_num}")
         
         # Detect special pages (only if we're in a chapter)
         elif detect_special_pages and current_chapter:
               special_result = detect_special_page_type(text, special_patterns)
               
               if special_result:
                  page_type, matched_text = special_result
                  current_chapter.add_special_page(page_type, page_num, matched_text)
                  
                  if verbose:
                     print(f"      → {page_type.title()} page @ {page_num}")
   
   # Sort by page number
   boundaries.sort(key=lambda b: b.page_number)
   
   # Validation
   if boundaries and verbose:
      chapter_nums = [b.chapter_number for b in boundaries]
      expected = list(range(min(chapter_nums), max(chapter_nums) + 1))
      missing = set(expected) - set(chapter_nums)
      
      if missing:
         print(f"    ⚠ Missing chapters: {sorted(missing)}")
      
      # Summary of special pages
      total_special = sum(len(b.special_pages) for b in boundaries)
      if total_special > 0:
         print(f"\n  Found {total_special} special pages:")
         special_counts = {}
         for b in boundaries:
               for sp in b.special_pages:
                  special_counts[sp.page_type] = special_counts.get(sp.page_type, 0) + 1
         
         for page_type, count in sorted(special_counts.items()):
               print(f"    - {page_type.title()}: {count}")
   
   return boundaries


def save_chapters_jsonl(
   boundaries: List[ChapterBoundary],
   output_file: Path,
   verbose: bool = True
):
   """Save enhanced chapter boundaries to JSONL file."""
   with open(output_file, 'w', encoding='utf-8') as f:
      for b in boundaries:
         f.write(json.dumps(b.to_dict(), ensure_ascii=False) + '\n')
   
   if verbose:
      print(f"\n  ✓ Saved {len(boundaries)} chapters to {output_file.name}")


if __name__ == "__main__":
   import sys
   
   if len(sys.argv) < 2:
      print("Usage: python chapter_scanner_enhanced.py <pagerecords_file>")
      print("\nExample:")
      print("  python chapter_scanner_enhanced.py converted/eecs281/eecs281_textbook_PageRecords")
      sys.exit(1)
   
   pagerecords_file = Path(sys.argv[1])
   
   if not pagerecords_file.exists():
      print(f"Error: File not found: {pagerecords_file}")
      sys.exit(1)
   
   print(f"Scanning {pagerecords_file.name}...\n")
   
   # Scan for chapters with special pages
   boundaries = scan_pagerecords_for_chapters(
      pagerecords_file,
      detect_special_pages=True,
      verbose=True
   )
   
   # Summary
   print(f"\n{'='*70}")
   print(f"SUMMARY: Found {len(boundaries)} chapters")
   print(f"{'='*70}")
   
   for b in boundaries:
      title_str = f": {b.chapter_title}" if b.chapter_title else ""
      print(f"\nChapter {b.chapter_number:2d}{title_str} (page {b.page_number})")
      
      if b.special_pages:
         for sp in b.special_pages:
               print(f"  → {sp.page_type.title()}: page {sp.page_number}")
   
   # Save to JSONL
   if boundaries:
      output_file = pagerecords_file.parent / f"{pagerecords_file.stem.replace('_PageRecords', '')}_Chapters.jsonl"
      save_chapters_jsonl(boundaries, output_file, verbose=True)