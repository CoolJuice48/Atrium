import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from bisect import bisect_right

@dataclass
class ChapterBoundary:
   chapter_number: int
   page_number: int
   chapter_title: Optional[str]=None

   def __repr__(self):
      if self.chapter_title:
         return f"Chapter {self.chapter_number} ('{self.chapter_title}') @ page {self.page_number}"
      return f"Chapter {self.chapter_number} @ page {self.page_number}"
   
@dataclass
class ChapterRegistry:
   boundaries: List[ChapterBoundary]=field(default_factory=list)
   def register_chapter(
         self,
         chapter_num: int,
         page_num: int,
         title: Optional[str]=None
   ) -> None:
      boundary = ChapterBoundary(chapter_num, page_num, title)
      self.boundaries.append(boundary)

   def finalize(self, page_num: int) -> str:
      self.boundaries.sort(key=lambda x: x.page_number)

   def get_chapter_id(self, page_num: int) -> str:
      if not self.boundaries:
         return 'ch00'
      
      page_numbers = [b.page_number for b in self.boundaries]
      idx = bisect_right(page_numbers, page_num) - 1

      if idx < 0:
         return 'ch00'
      
      chapter_num = self.boundaries[idx].chapter_number
      return f'ch{chapter_num:02d}'
   
   def get_chapter_info(self, page_num: int) -> Optional[ChapterBoundary]:
      if not self.boundaries:
         return None
      
      page_numbers = [b.page_number for b in self.boundaries]
      idx = bisect_right(page_numbers, page_num) - 1

      if idx < 0:
         return None
      
      return self.boundaries[idx]
   
   def summary(self) -> str:
      if not self.boundaries:
         return "No chapters detected"
      
      lines = [f"Detected {len(self.boundaries)} chapters"]

      for boundary in self.boundaries:
         lines.append(f"  - {boundary}")
      
      return '\n'.join(lines)
   
CHAPTER_PATTERNS = [
   # "Chapter 1", "Chapter 2:", "Chapter 1 -"
   r'Chapter\s+(\d+)',

   # "CHAPTER 1", "CHAPTER ONE"
   r'CHAPTER\s+(\d+)',

   # "1. Introduction" (at start of line/page)
   r'^(\d+)\.\s+[A-Z][a-z]+',

   # "1. Introduction" (followed by capitalized word)
   r'^(\d+)\s+[A-Z][A-Z\s]+$'
]

TOC_PATTERNS = [
   # "Chapter 1: Introduction...........15"
   # "Chapter 2 Data Structures.........45"
   r'Chapter\s+(\d+)[:\-\s]*([^.]*?)\.+\s*(\d+)',
   
   # "1. Introduction...........15"
   # "1 Introduction............15"
   r'^(\d+)[.\s]+([A-Z][^.]*?)\.+\s*(\d+)',
   
   # "CHAPTER 1: INTRODUCTION...15"
   r'CHAPTER\s+(\d+)[:\-\s]*([^.]*?)\.+\s*(\d+)',
   
   # "1 Introduction 15" (no dots)
   r'^(\d+)\s+([A-Z][^0-9]*?)\s+(\d+)$',
]

def parse_toc_line(line: str) -> Optional[Tuple[int, str, int]]:
   line = line.strip()

   for pattern in TOC_PATTERNS:
      match = re.search(pattern, line, re.IGNORECASE | re.MULTILINE)
      if match:
         try:
            chapter_num = int(match.group(1))
            title = match.group(2).strip() if len(match.groups()) >= 2 else None
            page_num = match.group(3)

            # Clean title
            if title:
               title = re.sub(r'\s+', ' ', title) # Normalize whitespace
               title = title.strip('. -:')

            return (chapter_num, title, page_num)
         except (ValueError, IndexError):
            continue
   
   return None

def extract_toc_from_pdf():
   return

"""
(Chapter number, chapter title)
"""
def detect_chapter(text: str, page_num: int) -> Optional[Tuple[int, str]]:
   text = text.strip()

   for pattern in CHAPTER_PATTERNS:
      match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
      if match:
         chapter_num = int(match.group(1))

         # Extract title
         title_match = re.search(
            r'Chapter\s+\d+[\s\-:]*(.+?)(?:\n|$)',
            text,
            re.IGNORECASE
         )
         title = title_match.group(1).strip() if title_match else None

         return (chapter_num, title)
   
   return None

def create_chapter_detector() -> ChapterRegistry:
   return ChapterRegistry()

# Example usage and testing
if __name__ == "__main__":
   # Simulate PDF processing
   registry = ChapterRegistry()
   
   # Simulate detecting chapters while processing PDF
   sample_pages = [
      (45, "Chapter 1: Introduction to Algorithms"),
      (89, "Chapter 2\nData Structures"),
      (156, "CHAPTER 3 - Sorting and Searching"),
      (234, "Chapter 4: Graph Algorithms"),
      (312, "Chapter 5\nDynamic Programming"),
   ]
   
   print("=== DETECTING CHAPTERS ===\n")
   for page_num, text in sample_pages:
      result = detect_chapter(text, page_num)
      if result:
         chapter_num, title = result
         registry.register_chapter(chapter_num, page_num, title)
         print(f"Page {page_num}: Found {title or f'Chapter {chapter_num}'}")
   
   # Finalize after processing all pages
   registry.finalize()
   
   print("\n" + "=" * 50)
   print(registry.summary())
   print("=" * 50)
   
   # Test lookups
   print("\n=== TESTING LOOKUPS ===\n")
   test_pages = [20, 50, 100, 180, 250, 320, 999]
   
   for page in test_pages:
      chapter_id = registry.get_chapter_id(page)
      info = registry.get_chapter_info(page)
      
      if info:
         print(f"Page {page:3d} → {chapter_id} ({info.chapter_title or 'No title'})")
      else:
         print(f"Page {page:3d} → {chapter_id} (before first chapter)")
   
   # Show how to use in problem_key generation
   print("\n=== PROBLEM KEY GENERATION ===\n")
   questions = [(45, 1), (92, 4), (165, 7), (240, 3)]
   
   for page, q_num in questions:
      chapter_id = registry.get_chapter_id(page)
      problem_key = f"{chapter_id}_q{q_num}"
      print(f"Question {q_num} on page {page} → problem_key: '{problem_key}'")