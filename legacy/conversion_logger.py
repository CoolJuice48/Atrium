"""
Conversion logging system for tracking PDF processing status.
Maintains a JSONL log of all PDFs and their conversion status.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class ConversionLogEntry:
   """Single log entry for a PDF document."""
   document_title: str      # PDF stem (filename without extension)
   document_id: str         # UUID of the document
   document_file: str       # Full path to original PDF
   converted: bool          # True if conversion completed
   output_path: Optional[str] = None  # Path to converted output directory
   page_count: Optional[int] = None
   word_count: Optional[int] = None
   question_count: Optional[int] = None
   
   def to_dict(self) -> Dict:
      return asdict(self)
   
   @classmethod
   def from_dict(cls, data: Dict) -> 'ConversionLogEntry':
      return cls(**data)


class ConversionLogger:
   """Manages the conversion log file."""
   
   def __init__(self, log_path: Path):
      self.log_path = Path(log_path)
      self.log_path.parent.mkdir(parents=True, exist_ok=True)
      
      # Create log file if it doesn't exist
      if not self.log_path.exists():
         self.log_path.touch()
   
   def _read_all_entries(self) -> List[ConversionLogEntry]:
      """Read all log entries from file."""
      entries = []
      
      if not self.log_path.exists():
         return entries
      
      with open(self.log_path, 'r', encoding='utf-8') as f:
         for line in f:
               if line.strip():  # Skip empty lines
                  try:
                     data = json.loads(line)
                     entries.append(ConversionLogEntry.from_dict(data))
                  except json.JSONDecodeError:
                     continue
      
      return entries
   
   def _write_all_entries(self, entries: List[ConversionLogEntry]):
      """Write all entries back to file (overwrites)."""
      with open(self.log_path, 'w', encoding='utf-8') as f:
         for entry in entries:
               f.write(json.dumps(entry.to_dict()) + '\n')
   
   def get_entry(self, pdf_name: str) -> Optional[ConversionLogEntry]:
      """
      Get log entry for a PDF by its name (stem).
      
      Args:
         pdf_name: PDF filename stem (without .pdf extension)
         
      Returns:
         ConversionLogEntry if found, None otherwise
      """
      entries = self._read_all_entries()
      
      for entry in entries:
         if entry.document_title == pdf_name:
               return entry
      
      return None
   
   def add_entry(self, entry: ConversionLogEntry) -> None:
      """
      Add a new log entry. If entry already exists, does nothing.
      
      Args:
         entry: ConversionLogEntry to add
      """
      existing = self.get_entry(entry.document_title)
      
      if existing:
         # Entry already exists, don't add duplicate
         return
      
      # Append new entry
      with open(self.log_path, 'a', encoding='utf-8') as f:
         f.write(json.dumps(entry.to_dict()) + '\n')
   
   def update_entry(self, pdf_name: str, **updates) -> bool:
      """
      Update an existing log entry.
      
      Args:
         pdf_name: PDF filename stem
         **updates: Fields to update (e.g., converted=True, page_count=100)
         
      Returns:
         True if entry was found and updated, False otherwise
      """
      entries = self._read_all_entries()
      found = False
      
      for i, entry in enumerate(entries):
         if entry.document_title == pdf_name:
               # Update fields
               for key, value in updates.items():
                  if hasattr(entry, key):
                     setattr(entry, key, value)
               found = True
               break
      
      if found:
         self._write_all_entries(entries)
      
      return found
   
   def mark_as_converted(self, pdf_name: str, output_path: str, 
                        page_count: int = 0, word_count: int = 0) -> bool:
      """
      Mark a PDF as converted.
      
      Args:
         pdf_name: PDF filename stem
         output_path: Path to conversion output directory
         page_count: Number of pages converted
         word_count: Total word count
         
      Returns:
         True if successfully updated
      """
      return self.update_entry(
         pdf_name,
         converted=True,
         output_path=output_path,
         page_count=page_count,
         word_count=word_count
      )
   
   def is_converted(self, pdf_name: str) -> bool:
      """
      Check if a PDF has been converted.
      
      Args:
         pdf_name: PDF filename stem
         
      Returns:
         True if PDF is logged as converted, False otherwise
      """
      entry = self.get_entry(pdf_name)
      return entry.converted if entry else False
   
   def get_all_converted(self) -> List[ConversionLogEntry]:
      """Get all PDFs that have been converted."""
      entries = self._read_all_entries()
      return [e for e in entries if e.converted]
   
   def get_all_unconverted(self) -> List[ConversionLogEntry]:
      """Get all PDFs that have not been converted."""
      entries = self._read_all_entries()
      return [e for e in entries if not e.converted]
   
   def list_all(self) -> List[ConversionLogEntry]:
      """Get all log entries."""
      return self._read_all_entries()
   
   def delete_entry(self, pdf_name: str) -> bool:
      """
      Remove a log entry.
      
      Args:
         pdf_name: PDF filename stem
         
      Returns:
         True if entry was found and deleted
      """
      entries = self._read_all_entries()
      original_len = len(entries)
      
      entries = [e for e in entries if e.document_title != pdf_name]
      
      if len(entries) < original_len:
         self._write_all_entries(entries)
         return True
      
      return False


# ============================================================================
# INTEGRATION HELPERS
# ============================================================================

def log_new_pdf(logger: ConversionLogger, pdf_path: Path, document_id: str):
   """
   Log a newly discovered PDF that hasn't been converted yet.
   
   Args:
      logger: ConversionLogger instance
      pdf_path: Path to the PDF file
      document_id: UUID for the document
   """
   entry = ConversionLogEntry(
      document_title=pdf_path.stem,
      document_id=document_id,
      document_file=str(pdf_path),
      converted=False
   )
   
   logger.add_entry(entry)
   print(f"🗎 Logged new PDF: {pdf_path.stem}")


def log_completed_conversion(logger: ConversionLogger, pdf_name: str, 
                           output_path: str, page_count: int, word_count: int):
   """
   Mark a PDF conversion as complete.
   
   Args:
      logger: ConversionLogger instance
      pdf_name: PDF filename stem
      output_path: Path to output directory
      page_count: Number of pages
      word_count: Total words
   """
   success = logger.mark_as_converted(
      pdf_name,
      output_path,
      page_count,
      word_count
   )
   
   if success:
      print(f"  Marked {pdf_name} as converted")
   else:
      print(f"✗  Could not find log entry for {pdf_name}")

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
   from pathlib import Path
   
   # Initialize logger
   log_file = Path("converted/conversion_logs.jsonl")
   logger = ConversionLogger(log_file)
   
   # Simulate logging a new PDF
   pdf_path = Path("pdfs/eecs_281_textbook.pdf")
   log_new_pdf(logger, pdf_path, "doc-12345-abcd")
   
   # Check if converted
   print(f"\nIs converted? {logger.is_converted('eecs_281_textbook')}")
   
   # Simulate conversion completion
   log_completed_conversion(
      logger,
      "eecs_281_textbook",
      "converted/eecs_281",
      1083,
      350000
   )
   
   # Check again
   print(f"Is converted now? {logger.is_converted('eecs_281_textbook')}")
   
   # Get entry details
   entry = logger.get_entry('eecs_281_textbook')
   if entry:
      print(f"\nEntry details:")
      print(f"  Title: {entry.document_title}")
      print(f"  Converted: {entry.converted}")
      print(f"  Pages: {entry.page_count}")
      print(f"  Words: {entry.word_count}")
   
   # List all converted PDFs
   converted = logger.get_all_converted()
   print(f"\nConverted PDFs: {len(converted)}")
   for c in converted:
      print(f"  - {c.document_title} ({c.page_count} pages)")