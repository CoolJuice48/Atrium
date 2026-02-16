#!/usr/bin/env python3
"""
Complete PDF management CLI with conversion logging and regex-based Q&A extraction.
"""

import json
import sys
import os
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from legacy.conversion_logger import ConversionLogger, log_new_pdf, log_completed_conversion

# ============================================================================
# OPTION CLASS
# ============================================================================

@dataclass(frozen=True)
class Option:
   number: int
   label: str
   extra: str = ""

# ============================================================================
# DISPLAY HELPERS
# ============================================================================

def print_header(title: str):
   """Print a nice header."""
   print(f"\n{'='*70}")
   print(title)
   print(f"{'='*70}\n")

def print_options(options: List[Option]) -> None:
   """Print a list of options."""
   for opt in options:
      if opt.extra:
         print(f"{opt.number}.) {opt.label} {opt.extra}")
      else:
         print(f"{opt.number}.) {opt.label}")

def get_choice(prompt: str = "Choice >> ") -> str:
   """Get user input."""
   return input(prompt).strip()

def pause():
   """Wait for user to press Enter."""
   input("\nPress Enter to continue...")

# ============================================================================
# PDF MANAGEMENT
# ============================================================================

def list_pdfs(pdf_dir: Path) -> List[Path]:
   """Get all PDFs in directory."""
   return sorted(pdf_dir.glob("*.pdf"))

def get_pdf_status(pdf_path: Path, logger: ConversionLogger) -> str:
   """Get status emoji for a PDF."""
   if logger.is_converted(pdf_path.stem):
      return "✓"
   elif logger.get_entry(pdf_path.stem):
      return "↻"
   else:
      return "🗎"

# ============================================================================
# MENU: BROWSE ALL PDFS
# ============================================================================

def show_all_pdfs_menu(pdf_dir: Path, converted_dir: Path, logger: ConversionLogger):
   """Show menu of all PDFs with conversion status."""

   pdfs = list_pdfs(pdf_dir)

   if not pdfs:
      print("\n!  No PDFs found in pdfs/")
      pause()
      return

   # Build options
   pdf_options = []
   for i, pdf_path in enumerate(pdfs, start=1):
      status = get_pdf_status(pdf_path, logger)
      size_mb = pdf_path.stat().st_size / (1024 * 1024)
      extra = f"[{size_mb:.1f} MB] {status}"
      pdf_options.append(Option(i, pdf_path.stem, extra))

   # Display
   print_header("ALL PDFs")
   print("Status: 🗎 = New | ↻ = Logged | ✓ = Converted\n")
   print_options(pdf_options)
   print("\n0.) Go back")

   # Get selection
   choice_str = get_choice("\nSelect PDF >> ")

   if not choice_str or choice_str == "0":
      return

   try:
      choice = int(choice_str)
      if choice < 1 or choice > len(pdfs):
         print("✗ Invalid selection")
         pause()
         return
   except ValueError:
      print("✗ Please enter a number")
      pause()
      return

   # Show actions for selected PDF
   selected_pdf = pdfs[choice - 1]
   show_pdf_actions(selected_pdf, converted_dir, logger)

# ============================================================================
# MENU: VIEW CONVERTED PDFs
# ============================================================================

def show_converted_pdfs_menu(logger: ConversionLogger, converted_dir: Path):
   """Show menu of converted PDFs only."""

   converted = logger.get_all_converted()

   if not converted:
      print("\n!  No converted PDFs found")
      print("Convert some PDFs first!")
      pause()
      return

   # Build options
   pdf_options = []
   for i, entry in enumerate(converted, start=1):
      pages = entry.page_count or 0
      words = entry.word_count or 0
      questions = entry.question_count or 0
      
      extra = f"({pages} pages"
      if questions > 0:
         extra += f", {questions} questions)"
      else:
         extra += ")"
      
      pdf_options.append(Option(i, entry.document_title, extra))

   # Display
   print_header("CONVERTED PDFs")
   print_options(pdf_options)
   print("\n0.) Go back")

   # Get selection
   choice_str = get_choice("\nSelect PDF >> ")

   if not choice_str or choice_str == "0":
      return

   try:
      choice = int(choice_str)
      if choice < 1 or choice > len(converted):
         print("✗ Invalid selection")
         pause()
         return
   except ValueError:
      print("✗ Please enter a number")
      pause()
      return

   # Show actions
   selected_entry = converted[choice - 1]
   pdf_path = Path(selected_entry.document_file)
   show_pdf_actions(pdf_path, converted_dir, logger, entry=selected_entry)

# ============================================================================
# MENU: PDF ACTIONS
# ============================================================================

def show_pdf_actions(pdf_path: Path, converted_dir: Path, logger: ConversionLogger, entry=None):
   """Show available actions for a selected PDF."""

   pdf_name = pdf_path.stem

   # Get entry if not provided
   if entry is None:
      entry = logger.get_entry(pdf_name)

   is_converted = entry and entry.converted

   while True:
      print_header(f"PDF: {pdf_name}")
      
      # Show status
      if entry:
         print(f"Status: {'✓ Converted' if entry.converted else '↻ Logged, not converted'}")
         if entry.converted and entry.output_path:
               print(f"Output: {entry.output_path}")
               print(f"Pages: {entry.page_count or 0}")
               print(f"Words: {entry.word_count or 0:,}")
               if entry.question_count:
                  print(f"Questions: {entry.question_count}")
      else:
         print(f"Status: 🗎 New (not in log)")
      
      print()
      
      # Build action options
      actions = []
      
      if not is_converted:
         actions.append(Option(1, "Convert to JSONL"))
      else:
         actions.append(Option(1, "Re-convert (overwrite)"))
      
      if is_converted:
         actions.append(Option(2, "Extract Q&A (regex)"))
         actions.append(Option(3, "View conversion details"))
      
      actions.append(Option(0, "Go back"))
      
      print("Available actions:\n")
      print_options(actions)
      
      # Get action
      action_str = get_choice("\nAction >> ")
      
      if not action_str or action_str == "0":
         return
      
      try:
         action = int(action_str)
      except ValueError:
         print("✗ Please enter a number")
         pause()
         continue
      
      # Execute action
      if action == 1:
         # Convert PDF
         execute_conversion(pdf_path, logger)
         # Refresh entry
         entry = logger.get_entry(pdf_name)
         is_converted = entry and entry.converted
         
      elif action == 2 and is_converted:
         # Extract Q&A
         execute_qa_extraction(pdf_name, entry, logger)
         # Refresh entry
         entry = logger.get_entry(pdf_name)
         
      elif action == 3 and is_converted:
         # Show details
         show_conversion_details(entry)

# ============================================================================
# ACTION EXECUTORS
# ============================================================================

def execute_conversion(pdf_path: Path, logger: ConversionLogger):
   """Execute PDF to JSONL conversion."""

   pdf_name = pdf_path.stem

   print(f"\n{'='*70}")
   print(f"CONVERTING: {pdf_name}")
   print(f"{'='*70}\n")

   # Check if already logged
   entry = logger.get_entry(pdf_name)
   if not entry:
      from id_factory import IDFactory
      import uuid
      
      book_key = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(pdf_path)))
      doc_id = IDFactory.book_id(book_key)
      log_new_pdf(logger, pdf_path, doc_id)
      print(f"📝 Logged {pdf_name} in conversion tracker")

   # Run conversion
   try:
      from pdf_to_jsonl import convert_pdf
      
      doc_id, output_path = convert_pdf(pdf_path)
      
      print(f"\n✓ Conversion complete!")
      print(f"Output: {output_path}")
      
   except Exception as e:
      print(f"\n✗ Conversion failed: {e}")

   pause()

def execute_qa_extraction(pdf_name: str, entry, logger: ConversionLogger):
   """Execute Q&A extraction from converted PDF using regex patterns."""

   print(f"\n{'='*70}")
   print(f"EXTRACTING Q&A: {pdf_name}")
   print(f"{'='*70}\n")

   # Build paths
   output_base = Path(entry.output_path)
   pages_file = output_base / f"{pdf_name}_PageRecords"
   doc_file = output_base / f"{pdf_name}_DocumentRecord"

   # Check if files exist
   if not pages_file.exists():
      print(f"✗ Pages file not found: {pages_file}")
      print("Try re-converting the PDF first.")
      pause()
      return

   if not doc_file.exists():
      print(f"✗ Document file not found: {doc_file}")
      print("Try re-converting the PDF first.")
      pause()
      return

   # Get book_id from document record
   try:
      with open(doc_file, 'r', encoding='utf-8') as f:
         doc_data = json.load(f)
         book_id = doc_data.get('id')
         
      if not book_id:
         print(f"✗ Could not find book_id in document record")
         pause()
         return
         
   except Exception as e:
      print(f"✗ Error reading document record: {e}")
      pause()
      return

   # Run extraction
   try:
      from legacy.qa_handler import extract_qas
      
      print(f"🗎 Reading PageRecords from {pages_file.name}")
      print(f"🔍 Searching for Practice Exercises and Solutions...\n")
      
      questions_path, answers_path = extract_qas(pages_file, book_id)
      
      print(f"\n✓ Extraction complete!")
      print(f"   Questions: {questions_path}")
      print(f"   Answers: {answers_path}")
      
      # Count questions for log update
      try:
         question_count = 0
         if questions_path.exists():
            with open(questions_path, 'r', encoding='utf-8') as f:
               question_count = sum(1 for line in f if line.strip())
         
         # Update log
         logger.update_entry(pdf_name, question_count=question_count)
         print(f"\n📊 Total questions: {question_count}")
         
      except Exception as e:
         print(f"\n!  Could not count questions: {e}")
      
   except Exception as e:
      print(f"\n✗ Extraction failed: {e}")
      import traceback
      traceback.print_exc()

   pause()

def show_conversion_details(entry):
   """Show detailed information about a converted PDF."""

   print_header(f"CONVERSION DETAILS: {entry.document_title}")

   print(f"Document ID: {entry.document_id}")
   print(f"Source PDF: {entry.document_file}")
   print(f"Output Path: {entry.output_path}")
   print(f"Pages: {entry.page_count or 0}")
   print(f"Words: {entry.word_count or 0:,}")
   print(f"Questions: {entry.question_count or 'Not extracted yet'}")

   # Check if output files exist
   if entry.output_path:
      output_base = Path(entry.output_path)
      pages_file = output_base / f"{entry.document_title}_PageRecords"
      doc_file = output_base / f"{entry.document_title}_DocumentRecord"
      
      print(f"\nFiles:")
      print(f"  Pages: {'✓' if pages_file.exists() else '✗'} {pages_file}")
      print(f"  Document: {'✓' if doc_file.exists() else '✗'} {doc_file}")
      
      # Check for Q&A files
      questions_file = output_base / f"{entry.document_title}_Questions.jsonl"
      answers_file = output_base / f"{entry.document_title}_Answers.jsonl"
      if questions_file.exists():
         print(f"  Questions: ✓ {questions_file}")
      if answers_file.exists():
         print(f"  Answers: ✓ {answers_file}")

   pause()

# ============================================================================
# MAIN MENU
# ============================================================================

def run_program(input_dir: Path, output_dir: Path) -> None:
   """Main entry point."""

   # Initialize logger
   log_file = output_dir / "conversion_logs.jsonl"
   logger = ConversionLogger(log_file)

   # Main menu loop
   while True:
      print_header("ATRIUM PDF PROCESSOR")
      
      # Count stats
      all_pdfs = list_pdfs(input_dir)
      converted_count = len(logger.get_all_converted())
      
      print(f"PDFs available: {len(all_pdfs)}")
      print(f"PDFs converted: {converted_count}\n")
      
      # Main options
      main_options = [
         Option(1, "Browse all PDFs"),
         Option(2, "View converted PDFs"),
         Option(3, "Quit")
      ]
      
      print_options(main_options)
      
      choice_str = get_choice("\nChoice >> ")
      
      if not choice_str:
         continue
      
      try:
         choice = int(choice_str)
      except ValueError:
         print("✗ Please enter a number")
         pause()
         continue
      
      if choice == 1:
         show_all_pdfs_menu(input_dir, output_dir, logger)
      elif choice == 2:
         show_converted_pdfs_menu(logger, output_dir)
      elif choice == 3:
         print("\nGoodbye!")
         break
      else:
         print("✗ Invalid choice")
         pause()

if __name__ == "__main__":
   run_program()