#!/usr/bin/env python3
"""
Section Text Extractor - The final piece of the pipeline.

Takes section boundaries and PageRecords, produces complete sections with text.

Pipeline:
1. section_scanner.py → section boundaries (page ranges)
2. THIS FILE → extract text for each section
3. Output → embedding-ready sections with full content

Design principles:
- Use scanner output as input
- Handle multi-page sections
- Optional chunking for very long sections
- Clean, structured output ready for embeddings
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class Section:
   """Complete section with text content - ready for embedding."""
   section_number: str
   section_title: str
   chapter_number: int
   page_start: int
   page_end: int
   text: str
   word_count: int
   depth: int = 1
   
   # Metadata for retrieval
   book_name: Optional[str] = None
   chapter_title: Optional[str] = None
   
   def to_dict(self) -> dict:
      """Convert to dictionary for JSON serialization."""
      return asdict(self)
   
   def __repr__(self):
      pages = f"{self.page_start}-{self.page_end}" if self.page_end != self.page_start else str(self.page_start)
      return f"§{self.section_number}: {self.section_title} (pages {pages}, {self.word_count} words)"


@dataclass 
class SectionChunk:
   """Chunk of a section (for very long sections)."""
   section_number: str
   section_title: str
   chapter_number: int
   chunk_index: int  # 0, 1, 2, ... for multi-chunk sections
   total_chunks: int  # total number of chunks for this section
   text: str
   word_count: int
   page_start: int
   page_end: int
   
   # Metadata
   book_name: Optional[str] = None
   chapter_title: Optional[str] = None
   depth: int = 1
   
   def to_dict(self) -> dict:
      return asdict(self)
   
   def __repr__(self):
      return f"§{self.section_number}: {self.section_title} [chunk {self.chunk_index+1}/{self.total_chunks}] ({self.word_count} words)"


def load_page_text_map(pagerecords_file: Path) -> Dict[int, str]:
   """
   Load PageRecords and create page_number -> text mapping.
   
   Returns:
      Dictionary mapping page numbers to their text content
   """
   page_map = {}
   
   with open(pagerecords_file, 'r', encoding='utf-8') as f:
      for line in f:
         if not line.strip():
               continue
         
         try:
               page_data = json.loads(line)
               page_num = page_data.get('pdf_page_number')
               text = page_data.get('text', '')
               
               if page_num:
                  page_map[page_num] = text
         except json.JSONDecodeError:
               continue
   
   return page_map


def extract_section_text(
   section_boundary: dict,
   page_map: Dict[int, str]
) -> str:
   """
   Extract text for a section across its page range.
   
   Args:
      section_boundary: Section boundary from scanner (with page_start, page_end)
      page_map: Mapping of page numbers to text
   
   Returns:
      Concatenated text for the entire section
   """
   page_start = section_boundary['page_start']
   page_end = section_boundary.get('page_end', page_start)
   
   # Collect text from all pages in range
   texts = []
   for page_num in range(page_start, page_end + 1):
      if page_num in page_map:
         texts.append(page_map[page_num])
   
   # Join with double newline to preserve page boundaries
   return '\n\n'.join(texts)


def build_sections_with_text(
   sections_file: Path,
   pagerecords_file: Path,
   *,
   book_name: str = None,
   chapters_file: Path = None,
   verbose: bool = True
) -> List[Section]:
   """
   Build complete Section objects with text content.
   
   Args:
      sections_file: Path to _Sections.jsonl from scanner
      pagerecords_file: Path to _PageRecords file
      book_name: Optional book name for metadata
      chapters_file: Optional chapters file for chapter titles
      verbose: Print progress
   
   Returns:
      List of complete Section objects with text
   """
   if verbose:
      print("Building sections with text content...")
   
   # Load section boundaries
   if verbose:
      print(f"  Loading section boundaries from {sections_file.name}...")
   
   section_boundaries = []
   with open(sections_file, 'r', encoding='utf-8') as f:
      for line in f:
         if line.strip():
               section_boundaries.append(json.loads(line))
   
   if verbose:
      print(f"  Loaded {len(section_boundaries)} section boundaries")
   
   # Load chapter titles if provided
   chapter_titles = {}
   if chapters_file and chapters_file.exists():
      if verbose:
         print(f"  Loading chapter titles from {chapters_file.name}...")
      
      with open(chapters_file, 'r', encoding='utf-8') as f:
         for line in f:
               if line.strip():
                  ch_data = json.loads(line)
                  chapter_titles[ch_data['chapter_number']] = ch_data.get('chapter_title')
   
   # Load page text map
   if verbose:
      print(f"  Loading page text from {pagerecords_file.name}...")
   
   page_map = load_page_text_map(pagerecords_file)
   
   if verbose:
      print(f"  Loaded {len(page_map)} pages")
      print(f"\n  Extracting section text...")
   
   # Build complete sections
   sections = []
   
   for i, boundary in enumerate(section_boundaries, 1):
      # Extract text
      text = extract_section_text(boundary, page_map)
      word_count = len(text.split())
      
      # Create Section object
      section = Section(
         section_number=boundary['section_number'],
         section_title=boundary.get('section_title', boundary['section_number']),
         chapter_number=boundary['chapter_number'],
         page_start=boundary['page_start'],
         page_end=boundary.get('page_end', boundary['page_start']),
         text=text,
         word_count=word_count,
         depth=boundary.get('depth', 1),
         book_name=book_name,
         chapter_title=chapter_titles.get(boundary['chapter_number'])
      )
      
      sections.append(section)
      
      if verbose and i % 10 == 0:
         print(f"    Processed {i}/{len(section_boundaries)} sections...")
   
   if verbose:
      total_words = sum(s.word_count for s in sections)
      avg_words = total_words / len(sections) if sections else 0
      print(f"\n  ✓ Built {len(sections)} complete sections")
      print(f"    Total words: {total_words:,}")
      print(f"    Average words/section: {avg_words:.0f}")
   
   return sections


def chunk_long_sections(
   sections: List[Section],
   *,
   max_words: int = 1000,
   overlap_words: int = 100,
   verbose: bool = True
) -> List[SectionChunk]:
   """
   Split very long sections into chunks for better embedding.
   
   Args:
      sections: List of Section objects
      max_words: Maximum words per chunk
      overlap_words: Number of words to overlap between chunks
      verbose: Print progress
   
   Returns:
      List of SectionChunk objects (some sections may be split)
   """
   chunks = []
   
   for section in sections:
      # If section is short enough, create single chunk
      if section.word_count <= max_words:
         chunk = SectionChunk(
               section_number=section.section_number,
               section_title=section.section_title,
               chapter_number=section.chapter_number,
               chunk_index=0,
               total_chunks=1,
               text=section.text,
               word_count=section.word_count,
               page_start=section.page_start,
               page_end=section.page_end,
               book_name=section.book_name,
               chapter_title=section.chapter_title,
               depth=section.depth
         )
         chunks.append(chunk)
      else:
         # Split into overlapping chunks
         words = section.text.split()
         num_chunks = (len(words) + max_words - 1) // max_words  # ceiling division
         
         for i in range(num_chunks):
               start_idx = i * (max_words - overlap_words)
               end_idx = start_idx + max_words
               
               chunk_words = words[start_idx:end_idx]
               chunk_text = ' '.join(chunk_words)
               
               chunk = SectionChunk(
                  section_number=section.section_number,
                  section_title=section.section_title,
                  chapter_number=section.chapter_number,
                  chunk_index=i,
                  total_chunks=num_chunks,
                  text=chunk_text,
                  word_count=len(chunk_words),
                  page_start=section.page_start,
                  page_end=section.page_end,
                  book_name=section.book_name,
                  chapter_title=section.chapter_title,
                  depth=section.depth
               )
               chunks.append(chunk)
         
         if verbose:
               print(f"    Split {section.section_number} into {num_chunks} chunks ({section.word_count} words)")
   
   return chunks


def save_sections_with_text(
   sections: List[Section],
   output_file: Path,
   verbose: bool = True
):
   """Save complete sections with text to JSONL file."""
   with open(output_file, 'w', encoding='utf-8') as f:
      for section in sections:
         f.write(json.dumps(section.to_dict(), ensure_ascii=False) + '\n')
   
   if verbose:
      total_words = sum(s.word_count for s in sections)
      file_size_mb = output_file.stat().st_size / (1024 * 1024)
      print(f"\n✓ Saved {len(sections)} sections to {output_file.name}")
      print(f"  Total words: {total_words:,}")
      print(f"  File size: {file_size_mb:.2f} MB")


def save_section_chunks(
   chunks: List[SectionChunk],
   output_file: Path,
   verbose: bool = True
):
   """Save section chunks to JSONL file."""
   with open(output_file, 'w', encoding='utf-8') as f:
      for chunk in chunks:
         f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + '\n')
   
   if verbose:
      total_words = sum(c.word_count for c in chunks)
      file_size_mb = output_file.stat().st_size / (1024 * 1024)
      print(f"\n✓ Saved {len(chunks)} section chunks to {output_file.name}")
      print(f"  Total words: {total_words:,}")
      print(f"  File size: {file_size_mb:.2f} MB")


if __name__ == "__main__":
   import sys
   
   if len(sys.argv) < 3:
      print("Usage: python section_text_extractor.py <sections_file> <pagerecords_file> [--chunk]")
      print("\nExamples:")
      print("  # Basic - create sections with text")
      print("  python section_text_extractor.py eecs281_Sections.jsonl eecs281_PageRecords")
      print()
      print("  # With chunking for long sections")
      print("  python section_text_extractor.py eecs281_Sections.jsonl eecs281_PageRecords --chunk")
      sys.exit(1)
   
   sections_file = Path(sys.argv[1])
   pagerecords_file = Path(sys.argv[2])
   use_chunking = '--chunk' in sys.argv
   
   if not sections_file.exists():
      print(f"Error: Sections file not found: {sections_file}")
      sys.exit(1)
   
   if not pagerecords_file.exists():
      print(f"Error: PageRecords file not found: {pagerecords_file}")
      sys.exit(1)
   
   # Detect book name from filename
   book_name = pagerecords_file.stem.replace('_PageRecords', '')
   
   # Look for chapters file
   chapters_file = pagerecords_file.parent / f"{book_name}_Chapters.jsonl"
   
   print(f"Processing {book_name}...")
   print("=" * 70)
   
   # Build sections with text
   sections = build_sections_with_text(
      sections_file,
      pagerecords_file,
      book_name=book_name,
      chapters_file=chapters_file if chapters_file.exists() else None,
      verbose=True
   )
   
   # Output file
   output_base = pagerecords_file.parent / f"{book_name}_SectionsWithText"
   
   if use_chunking:
      print("\n" + "=" * 70)
      print("CHUNKING LONG SECTIONS")
      print("=" * 70)
      
      chunks = chunk_long_sections(
         sections,
         max_words=1000,
         overlap_words=100,
         verbose=True
      )
      
      output_file = Path(str(output_base) + "_Chunked.jsonl")
      save_section_chunks(chunks, output_file, verbose=True)
   else:
      output_file = Path(str(output_base) + ".jsonl")
      save_sections_with_text(sections, output_file, verbose=True)
   
   # Summary
   print("\n" + "=" * 70)
   print("SUMMARY")
   print("=" * 70)
   
   if use_chunking:
      print(f"Original sections: {len(sections)}")
      print(f"Output chunks: {len(chunks)}")
      multi_chunk = sum(1 for c in chunks if c.total_chunks > 1)
      print(f"Sections split into chunks: {multi_chunk}")
   else:
      print(f"Sections: {len(sections)}")
      long_sections = sum(1 for s in sections if s.word_count > 1000)
      print(f"Long sections (>1000 words): {long_sections}")
      if long_sections > 0:
         print(f"\nTip: Use --chunk flag to split long sections for better embeddings")
   
   print(f"\nOutput: {output_file}")
   print("\n✓ Ready for embedding!")