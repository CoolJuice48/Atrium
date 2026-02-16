#!/usr/bin/env python3
"""
Section scanner for detecting subsections within chapters.

Detects section patterns like:
- "1.2 Pointers and References"
- "25.5 Shortest Path Algorithm"
- "14.3 Merge Sort"

Design principles:
- Configurable depth (1.2, 1.2.3, etc.)
- Links sections to parent chapters
- Validates section hierarchy
- Returns structured data
"""

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SectionBoundary:
   """Represents a section within a chapter."""
   section_number: str  # e.g., "1.2", "25.5"
   page_start: int
   page_end: Optional[int] = None
   section_title: Optional[str] = None
   chapter_number: Optional[int] = None
   depth: int = 1  # 1 for "1.2", 2 for "1.2.3", etc.

   def __repr__(self):
      title_str = f": {self.section_title}" if self.section_title else ""
      if self.page_end and self.page_end != self.page_start:
         return f"§{self.section_number}{title_str} @ pages {self.page_start}–{self.page_end}"
      return f"§{self.section_number}{title_str} @ page {self.page_start}"

   def to_dict(self) -> dict:
      """Convert to dictionary for JSON serialization."""
      return {
         'section_number': self.section_number,
         'page_start': self.page_start,
         'page_end': self.page_end,
         'section_title': self.section_title,
         'chapter_number': self.chapter_number,
         'depth': self.depth
      }

   @property
   def parent_chapter(self) -> int:
      """Extract parent chapter number from section number."""
      return int(self.section_number.split('.')[0])


def detect_section_at_page_start(
   text: str,
   *,
   max_depth: int = 2,
   min_title_length: int = 3,
) -> Optional[Tuple[str, str, int]]:
   """
   Detect if a page starts with a section header.
   
   Args:
      text: Page text to search
      max_depth: Maximum section depth (1 for "1.2", 2 for "1.2.3")
      min_title_length: Minimum characters for valid title
   
   Returns:
      (section_number, section_title, depth) or None
   """
   if not text:
      return None
   
   # Get first ~15 lines where sections usually appear
   lines = text.split('\n')[:15]
   
   for i, line in enumerate(lines):
      line = line.strip()
      
      # Build regex based on max_depth
      # For max_depth=1: matches "1.2"
      # For max_depth=2: matches "1.2" or "1.2.3"
      if max_depth == 1:
         pattern = r'^(\d+\.\d+)(?:\s+(.+))?$'
      elif max_depth == 2:
         pattern = r'^(\d+\.\d+(?:\.\d+)?)(?:\s+(.+))?$'
      else:
         # Generic pattern for any depth
         depth_pattern = r'\.\d+' * max_depth
         pattern = f'^(\\d+{depth_pattern}?)(?:\\s+(.+))?$'
      
      match = re.match(pattern, line)
      
      if match:
         section_num = match.group(1)
         title = match.group(2) if len(match.groups()) > 1 else None
         
         # Calculate depth (number of dots)
         depth = section_num.count('.')
         
         # If no title on same line, check next line
         if not title and i + 1 < len(lines):
               potential_title = lines[i + 1].strip()
               # Title should be substantial and not another section number
               if (len(potential_title) >= min_title_length and 
                  not re.match(r'^\d+\.', potential_title)):
                  title = potential_title
         
         # Validate title
         if title:
               # Skip if "title" is actually a chapter reference or page number
               if re.match(r'^(Chapter|Page|\d+)$', title, re.IGNORECASE):
                  continue
               
               # Clean up common artifacts
               title = title.strip('.')
         
         return (section_num, title, depth)
   
   return None


def scan_pagerecords_for_sections(
   pagerecords_file: Path,
   *,
   max_depth: int = 2,
   chapter_boundaries: List[dict] = None,
   verbose: bool = True,
) -> List[SectionBoundary]:
   """
   Scan PageRecords file and extract section boundaries with page ranges.

   Each unique section_number is recorded once (first occurrence only).
   After collection, page_end is computed from the next section's page_start.

   Args:
      pagerecords_file: Path to _PageRecords file
      max_depth: Maximum section depth to detect
      chapter_boundaries: Optional list of chapter boundaries for validation
      verbose: Print progress

   Returns:
      List of SectionBoundary objects, sorted by page_start
   """
   sections = []
   seen_sections = set()  # section_numbers already recorded
   last_page_num = 0

   if verbose:
      print(f"  Scanning for sections (max depth: {max_depth})...")

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

         # Track the last page in the file for final section's page_end
         last_page_num = max(last_page_num, page_num)

         # Detect section
         result = detect_section_at_page_start(text, max_depth=max_depth)

         if result:
               section_num, title, depth = result

               # Skip duplicates entirely — only keep first occurrence
               if section_num in seen_sections:
                  continue

               # Extract chapter number
               chapter_num = int(section_num.split('.')[0])

               # Create section boundary (page_end computed after collection)
               section = SectionBoundary(
                  section_number=section_num,
                  page_start=page_num,
                  section_title=title,
                  chapter_number=chapter_num,
                  depth=depth
               )

               sections.append(section)
               seen_sections.add(section_num)

               if verbose:
                  title_display = f": {title}" if title else ""
                  print(f"    ✓ Section {section_num}{title_display} @ page {page_num}")

   # Sort by page_start
   sections.sort(key=lambda s: s.page_start)

   # Compute page_end for each section
   for i, sec in enumerate(sections):
      if i + 1 < len(sections):
         sec.page_end = sections[i + 1].page_start - 1
      else:
         sec.page_end = last_page_num

   # Group by chapter and summarize
   if sections and verbose:
      by_chapter = {}
      for s in sections:
         by_chapter.setdefault(s.chapter_number, []).append(s)

      print(f"\n  Found {len(sections)} sections across {len(by_chapter)} chapters")

      # Show distribution
      for ch_num in sorted(by_chapter.keys())[:5]:  # Show first 5 chapters
         count = len(by_chapter[ch_num])
         print(f"    Chapter {ch_num}: {count} sections")

      if len(by_chapter) > 5:
         print(f"    ... and {len(by_chapter) - 5} more chapters")

   return sections


def build_page_to_sections(sections: List[SectionBoundary]) -> dict:
   """Map page_num -> list of {section_label, section_title}."""
   lookup = {}
   for s in sections:
      for page in range(s.page_start, (s.page_end or s.page_start) + 1):
         lookup.setdefault(page, []).append({
            'section_label': s.section_number,
            'section_title': s.section_title or s.section_number,
         })
   return lookup


def save_sections_jsonl(
   sections: List[SectionBoundary],
   output_file: Path,
   verbose: bool = True
):
   """Save section boundaries to JSONL file."""
   with open(output_file, 'w', encoding='utf-8') as f:
      for s in sections:
         f.write(json.dumps(s.to_dict(), ensure_ascii=False) + '\n')
   
   if verbose:
      print(f"\n  ✓ Saved {len(sections)} sections to {output_file.name}")


def load_chapter_boundaries(chapters_file: Path) -> List[dict]:
   """Load chapter boundaries from JSONL file."""
   chapters = []
   with open(chapters_file, 'r', encoding='utf-8') as f:
      for line in f:
         if line.strip():
               chapters.append(json.loads(line))
   return chapters


if __name__ == "__main__":
   import sys
   
   if len(sys.argv) < 2:
      print("Usage: python section_scanner.py <pagerecords_file> [chapters_file]")
      print("\nExamples:")
      print("  python section_scanner.py converted/eecs281/eecs281_textbook_PageRecords")
      print("  python section_scanner.py PageRecords Chapters.jsonl  # with chapter validation")
      sys.exit(1)
   
   pagerecords_file = Path(sys.argv[1])
   
   if not pagerecords_file.exists():
      print(f"Error: File not found: {pagerecords_file}")
      sys.exit(1)
   
   # Load chapters if provided
   chapters = None
   if len(sys.argv) > 2:
      chapters_file = Path(sys.argv[2])
      if chapters_file.exists():
         print(f"Loading chapter boundaries from {chapters_file.name}...")
         chapters = load_chapter_boundaries(chapters_file)
         print(f"  Loaded {len(chapters)} chapters\n")
   
   print(f"Scanning {pagerecords_file.name}...\n")
   
   # Scan for sections
   sections = scan_pagerecords_for_sections(
      pagerecords_file,
      max_depth=2,
      chapter_boundaries=chapters,
      verbose=True
   )
   
   # Summary
   print(f"\n{'='*70}")
   print(f"SUMMARY: Found {len(sections)} sections")
   print(f"{'='*70}")
   
   # Group by chapter for display
   by_chapter = {}
   for s in sections:
      by_chapter.setdefault(s.chapter_number, []).append(s)
   
   # Show first few chapters in detail
   for ch_num in sorted(by_chapter.keys())[:3]:
      print(f"\nChapter {ch_num}:")
      for s in by_chapter[ch_num][:10]:  # Show first 10 sections
         title_str = f": {s.section_title}" if s.section_title else ""
         if s.page_end and s.page_end != s.page_start:
            page_str = f"pages {s.page_start}–{s.page_end}"
         else:
            page_str = f"page {s.page_start}"
         print(f"  {s.section_number}{title_str} ({page_str})")

      if len(by_chapter[ch_num]) > 10:
         print(f"  ... and {len(by_chapter[ch_num]) - 10} more sections")
   
   # Save to JSONL
   if sections:
      output_file = pagerecords_file.parent / f"{pagerecords_file.stem.replace('_PageRecords', '')}_Sections.jsonl"
      save_sections_jsonl(sections, output_file, verbose=True)