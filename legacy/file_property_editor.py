#!/usr/bin/env python3
"""
File Property Editor for JSONL files

Allows editing fields in Questions.jsonl and Answers.jsonl:
- Manual edit: Type in new value
- Auto-fill: Run functions like find_chapters(), fill_author()
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# ============================================================================
# AUTO-FILL FUNCTIONS
# ============================================================================

def autofill_chapters(records: List[Dict], pages_file: Path) -> List[Dict]:
   """Use chapter_detector to fill chapter field from PageRecords."""
   
   from chapter_scanner import scan_pagerecords_for_chapters
   from bisect import bisect_right

   print(f"\n Scanning PageRecords for chapters...")

   boundaries = scan_pagerecords_for_chapters(pages_file, verbose=True)

   # Build lookup for page -> chapter using bisect
   boundary_pages = [b.page_number for b in boundaries]

   def get_chapter_for_page(page_num):
      if not boundaries:
         return None
      idx = bisect_right(boundary_pages, page_num) - 1
      if idx < 0:
         return None
      return boundaries[idx]

   # Update records
   updated = 0
   for record in records:
      page_num = record.get('pdf_page')
      if page_num:
         chapter_info = get_chapter_for_page(page_num)
         if chapter_info:
               record['chapter'] = str(chapter_info.chapter_number)
               if chapter_info.chapter_title:
                  record['chapter_title'] = chapter_info.chapter_title
               updated += 1
   
   print(f"✓ Updated {updated} records with chapter info")
   
   return records


def autofill_manual(records: List[Dict], field: str) -> List[Dict]:
   """Manually enter a value to fill in all records."""
   
   current_value = records[0].get(field, 'null') if records else 'null'
   print(f"\n✎ Current value: {current_value}")
   
   new_value = input(f"Enter new value for '{field}' >> ").strip()
   
   if not new_value:
      print("✗ No value entered, cancelled")
      return records
   
   # Confirm
   print(f"\n⚠  This will update ALL {len(records)} records")
   confirm = input(f"Set {field} = '{new_value}' for all records? (y/n) >> ").strip().lower()
   
   if confirm != 'y':
      print("Cancelled")
      return records
   
   # Update
   for record in records:
      record[field] = new_value
   
   print(f"✓ Updated {len(records)} records")
   
   return records


def autofill_clear(records: List[Dict], field: str) -> List[Dict]:
   """Clear (set to null) a field in all records."""
   
   print(f"\n⚠  This will clear '{field}' in ALL {len(records)} records")
   confirm = input(f"Are you sure? (y/n) >> ").strip().lower()
   
   if confirm != 'y':
      print("Cancelled")
      return records
   
   # Update
   for record in records:
      record[field] = None
   
   print(f"✓ Cleared '{field}' in {len(records)} records")
   
   return records


# ============================================================================
# PROPERTY EDITOR INTERFACE
# ============================================================================

@dataclass
class FieldInfo:
   name: str
   current_value: Any
   count_null: int
   count_filled: int
   sample_values: List[Any]

def analyze_field(records: List[Dict], field: str) -> FieldInfo:
   """Analyze a field across all records."""
   
   values = []
   null_count = 0
   
   for record in records:
      value = record.get(field)
      if value is None or value == 'null':
         null_count += 1
      else:
         values.append(value)
   
   # Get unique sample values (up to 5)
   unique_values = list(set(values))[:5]
   
   return FieldInfo(
      name=field,
      current_value=values[0] if values else None,
      count_null=null_count,
      count_filled=len(values),
      sample_values=unique_values
   )


def show_file_properties(file_path: Path, output_dir: Path):
   """Show and edit properties of a JSONL file."""
   
   # Load records
   records = []
   with open(file_path, 'r', encoding='utf-8') as f:
      for line in f:
         if line.strip():
               records.append(json.loads(line))
   
   if not records:
      print(f"\n⚠  File is empty!")
      input("Press Enter to continue...")
      return
   
   print(f"\n{'='*70}")
   print(f"FILE PROPERTIES: {file_path.name}")
   print(f"{'='*70}\n")
   
   print(f"Total records: {len(records)}\n")
   
   # Get all fields from first record
   all_fields = list(records[0].keys())
   
   # Analyze each field
   print("Field Analysis:\n")
   print(f"{'Field':<25} {'Filled':<10} {'Null':<10} Sample Values")
   print(f"{'-'*70}")
   
   field_infos = {}
   for field in all_fields:
      info = analyze_field(records, field)
      field_infos[field] = info
      
      # Format sample values
      if info.sample_values:
         samples = str(info.sample_values[:2])[:40]
      else:
         samples = "null"
      
      print(f"{field:<25} {info.count_filled:<10} {info.count_null:<10} {samples}")
   
   print()
   
   # Select field to edit
   while True:
      print(f"\nSelect field to edit (or press Enter to go back):")
      
      # Show numbered list
      for i, field in enumerate(all_fields, 1):
         info = field_infos[field]
         status = "✓" if info.count_null == 0 else f"⚠  {info.count_null} null"
         print(f"{i:2d}.) {field:<25} {status}")
      
      choice = input("\nField >> ").strip()
      
      if not choice:
         return
      
      try:
         idx = int(choice) - 1
         if idx < 0 or idx >= len(all_fields):
               print("✗ Invalid selection")
               continue
         
         selected_field = all_fields[idx]
         
      except ValueError:
         print("✗ Please enter a number")
         continue
      
      # Show edit options for this field
      if edit_field(records, selected_field, file_path, output_dir):
         # Field was modified, save and return
         return


def edit_field(records: List[Dict], field: str, file_path: Path, output_dir: Path) -> bool:
   """Edit a specific field. Returns True if file was modified."""
   
   info = analyze_field(records, field)
   
   print(f"\n{'='*70}")
   print(f"EDIT FIELD: {field}")
   print(f"{'='*70}\n")
   
   print(f"Filled: {info.count_filled}")
   print(f"Null: {info.count_null}")
   print(f"Sample values: {info.sample_values[:3]}\n")
   
   # Build auto-fill options
   autofill_options = []
   
   if field in ['chapter', 'chapter_title']:
      autofill_options.append(("Auto-fill from PageRecords", autofill_chapters_wrapper))
   
   autofill_options.append(("Manual entry", autofill_manual))
   autofill_options.append(("Clear field (set to null)", autofill_clear))
   
   # Show options
   print("Edit options:\n")
   for i, (label, _) in enumerate(autofill_options, 1):
      print(f"{i}.) {label}")
   print(f"0.) Cancel")
   
   choice = input("\nOption >> ").strip()
   
   if not choice or choice == "0":
      return False
   
   try:
      idx = int(choice) - 1
      if idx < 0 or idx >= len(autofill_options):
         print("✗ Invalid selection")
         input("Press Enter to continue...")
         return False
      
      label, func = autofill_options[idx]
      
   except ValueError:
      print("✗ Please enter a number")
      input("Press Enter to continue...")
      return False
   
   # Execute the selected function
   try:
      if func == autofill_chapters_wrapper:
         # Need to find PageRecords file
         base_name = file_path.stem
         if '_Questions' in base_name:
               base_name = base_name.replace('_Questions', '')
         elif '_Answers' in base_name:
               base_name = base_name.replace('_Answers', '')
         
         pages_file = output_dir / f"{base_name}_PageRecords"
         
         if not pages_file.exists():
               print(f"\n✗ PageRecords file not found: {pages_file}")
               input("Press Enter to continue...")
               return False
         
         records = func(records, pages_file)
      else:
         records = func(records, field)
      
      # Save modified records
      print(f"\n✎ Saving changes to {file_path.name}...")
      
      with open(file_path, 'w', encoding='utf-8') as f:
         for record in records:
               f.write(json.dumps(record, ensure_ascii=False) + '\n')
      
      print(f"✓ File saved!")
      input("\nPress Enter to continue...")
      
      return True
      
   except Exception as e:
      print(f"\n✗ Error: {e}")
      import traceback
      traceback.print_exc()
      input("\nPress Enter to continue...")
      return False


def autofill_chapters_wrapper(records: List[Dict], pages_file: Path) -> List[Dict]:
   """Wrapper for autofill_chapters that passes pages_file."""
   return autofill_chapters(records, pages_file)


# ============================================================================
# INTEGRATION WITH QUERY.PY
# ============================================================================

def add_edit_properties_to_file_actions():
   """
   Instructions for adding to query.py's show_file_actions function:
   
   In the actions list, add:
   
      # After "Export to formatted text"
      if file_path.suffix == '.jsonl':
         actions.append(Option(5, "Edit file properties"))
   
   Then in the action handler:
   
      elif action == 5 and file_path.suffix == '.jsonl':
         # Edit properties
         from file_property_editor import show_file_properties
         show_file_properties(file_path, output_base)
         return  # Refresh folder view
   """
   pass


if __name__ == "__main__":
   # Example usage
   print("File Property Editor")
   print("=" * 70)
   print("\nThis module provides property editing for JSONL files.")
   print("Import into query.py to use.")