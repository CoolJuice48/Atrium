#!/usr/bin/env python3
from __future__ import annotations

import re
import uuid
import json
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict, TYPE_CHECKING
from dataclasses import dataclass, asdict, is_dataclass, field
from pdf_to_jsonl import SectionRecord, PageRecord

if TYPE_CHECKING:
   from pdf_to_jsonl import DocumentRecord

from id_factory import IDFactory

""" -------------------------------------------------------------------------------------------------------- """
"""                                      REGEX AND HELPER FUNCTIONS                                          """
ANSWER_BLOCK_SPLIT = re.compile(r"(?=^\s*\d+\.\s+The correct answer is)", re.MULTILINE)
ANSWER_START = re.compile(r"^\s*(\d+)\.\s+The correct answer is\s*\(([A-Z])\)\.\s*(.*)", re.DOTALL)

QUESTION_BLOCK_SPLIT = re.compile(r"(?=^\s*\d+\.\s)", re.MULTILINE)
QUESTION_START = re.compile(r"^\s*(\d+)\.\s*(.*)", re.DOTALL)

CHAPTER_RE = re.compile(r"(Chapter\s+\d+)", re.IGNORECASE)

def chapter_key(title: str) -> str:
   m = CHAPTER_RE.search(title or "")
   return m.group(1).title() if m else "Chapter ?"

def canonical_problem_key(book_id: str, chapter: str, number: int) -> str:
   # stable across reruns
   return f"{book_id}|{chapter}|{number}"

def qa_id_from_problem_key(problem_key: str) -> str:
   # deterministic pair id
   return str(uuid.uuid5(uuid.NAMESPACE_URL, problem_key))

""" -------------------------------------------------------------------------------------------------------- """
@dataclass
class QuestionRecord:
   id: Optional[str]=None                              # Individual question ID (UUID)
   qa_id: str=None                                     # Unique Q&A pair ID (UUID)
   book_id: str=None                                   # Book ID this question belongs to
   chapter: str=None                                   # Chapter the question is under
   section_labels: Set[str]=field(default_factory=set) # Section label this question belongs to (e.g. "1.2")
   section_titles: Set[str]=field(default_factory=set) # Section title this question belongs to (e.g. "Section 1.2: Data Structures")
   pdf_page: int | None=None                           # PDF page number where the question is located, earliest page if multiple
   problem_key: str=None                               # Unique problem key this question belongs to (e.g. "Section 1.2#3")
   question_number: Optional[int]=None                 # Question number extracted from text (e.g. "1" for "Problem 1.2")
   question_text: str=None                             # Full text of the question
   question_embedding: Optional[List[float]]=None      # Optional text embedding for the question (e.g. from a language model)
   page_ids: Set[str]=field(default_factory=set)       # Set of page IDs this question appears in (for traceability)

""" -------------------------------------------------------------------------------------------------------- """
@dataclass
class AnswerRecord:
   id: Optional[str]=None                              # Individual answer ID (UUID)
   qa_id: Optional[str]=None                           # Unique Q&A pair ID (UUID)
   book_id: str=None                                   # Book ID this answer belongs to
   chapter: str=None                                   # Chapter the answer is under
   section_labels: Set[str]=field(default_factory=set) # Section label this answer belongs to (e.g. "1.2")
   section_titles: Set[str]=field(default_factory=set) # Section title this answer belongs to (e.g. "Section 1.2: Data Structures")
   pdf_page: int | None=None                           # PDF page number where the answer is located, earliest page if multiple
   problem_key: str=None                               # Unique problem key this answer belongs to (e.g. "Section 1.2#3")
   answer_number: Optional[int]=None                   # Answer number extracted from text (e.g. "1" for "Problem 1.2")
   answer_choice: Optional[str]=None                   # Multiple choice answer letter if applicable (e.g. "A", "B", "C", "D")
   answer_text: str=None                               # Full text of the answer
   answer_embedding: Optional[List[float]] = None      # Optional text embedding for the answer (e.g. from a language model)
   answer_confidence: Optional[List[float]] = None     # Optional confidence score for the answer (e.g. from a language model)
   page_ids: Set[str]=field(default_factory=set)       # Set of page IDs this answer appears in (for traceability)

""" -------------------------------------------------------------------------------------------------------- """
"""
Convert a dataclass object to a JSONL record (one line of JSON)
Args:
   obj: A dataclass object (e.g. QuestionRecord, AnswerRecord, SectionRecord, PageRecord)
Returns:
   A JSON string representing the object, suitable for writing to a JSONL file
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
Page to section lookup
Args:
   struct_nodes: List of SectionRecords with pdf_start and pdf_end page numbers
Returns:
   A list indexed by page number (1-based) containing section info for that
   page, or None if no section info
"""
def lookup_section(sec_recs: List[SectionRecord]) -> list:
   # Prefer shorter sections first then longer
   sections = list(sec_recs)  # Make a copy to avoid modifying original
   max_page = max(s.page_end for s in sections)
   sections_sorted = sorted(sections, key=lambda s: (s.page_end - s.page_start, s.page_start))

   lookup = [None] * (max_page + 1)  # 1-based indexing

   for s in sections_sorted:
      for p in range(s.page_start, s.page_end + 1):
         if p <= max_page and lookup[p] is None:
            lookup[p] = {
               "section_label": s.section_label,
               "section_title": s.section_title
            }

   return lookup

""" -------------------------------------------------------------------------------------------------------- """
r"""
Extract questions from text using regex patterns
Args:
   text: The text to search for questions
   question_patterns: A list of regex patterns to identify questions (e.g. r"Problem\s*\d+(\.\d+)*:?\s*(.*)")
Returns:
   A list of QuestionRecord objects connected to their corresponding AnswerRecord
"""
def extract_questions(pages: List[PageRecord], lookup, book_id: str) -> List[Dict]:
   # 1) Gather all practice text in reading order
   chunks = []
   for page in pages:
      sec = lookup[page.pdf_page_number] if page.pdf_page_number < len(lookup) else None
      if not sec:
         continue
      if "Practice Exercises" not in (sec.get("section_title") or ""):
         continue
      chunks.append((page, page.text or ""))

   # 2) Concatenate with page markers for later attribution
   questions = []
   carry = None

   for page, text in chunks:
      parts = QUESTION_BLOCK_SPLIT.split(text)
      parts = [p.strip() for p in parts if p.strip()]

      # Check for multi-page questions
      if parts and not re.match(r"^\s*\d+\.\s", parts[0]):
         if carry:
               carry["raw"] += "\n" + parts[0]
               carry["page_ids"].add(page.id)
               parts = parts[1:]

      for part in parts:
         m = QUESTION_START.match(part)
         if not m:
            continue
         qnum = int(m.group(1))
         body = part.strip()

         carry = {
            "qnum": qnum,
            "raw": body,
            "page_ids": {page.id},
            "pdf_pages": {page.pdf_page_number},
            "section_title": lookup[page.pdf_page_number]["section_title"],
            "section_label": lookup[page.pdf_page_number]["section_label"],
         }
         questions.append(carry)
   
   return questions

""" -------------------------------------------------------------------------------------------------------- """
r"""
Extract answers from text using regex patterns, connected to their corresponding questions
Args:
   text: The text to search for answers
   answer_patterns: A list of regex patterns to identify answers (e.g. r"The correct answer is \(([A-Z])\)")
Returns:
   A list of AnswerRecord objects connected to their corresponding QuestionRecord
"""
def extract_answers(pages, lookup, book_id: str) -> List[Dict]:
   # 1) Gather all practice text in reading order
   chunks = []
   for page in pages:
      sec = lookup[page.pdf_page_number] if page.pdf_page_number < len(lookup) else None
      if not sec:
         continue
      title = sec.get("section_title") or ""
      if "Solutions" not in title:
         continue
      chunks.append((page, page.text or ""))

   # 2) Concatenate with page markers for later attribution
   answers = []
   carry = None

   for page, text in chunks:
      parts = ANSWER_BLOCK_SPLIT.split(text)
      parts = [p.strip() for p in parts if p.strip()]

      if parts and not re.match(r"^\s*\d+\.\s+The correct answer is", parts[0]):
         if carry:
               carry["raw"] += "\n" + parts[0]
               carry["page_ids"].add(page.id)
               parts = parts[1:]
         
      for part in parts:
         m = ANSWER_START.match(part)
         if not m:
            continue

         anum = int(m.group(1))
         choice = m.group(2)
         rest = (m.group(3) or "").strip()
         body = part.strip()

         carry = {
               "anum": anum,
               "choice": choice,
               "raw": body,
               "answer_text": rest if rest else body,
               "page_ids": {page.id},
               "pdf_pages": {page.pdf_page_number},
               "section_title": lookup[page.pdf_page_number]["section_title"],
               "section_label": lookup[page.pdf_page_number].get("section_label"),
         }
         answers.append(carry)

   return answers

""" -------------------------------------------------------------------------------------------------------- """
"""
Match questions and answers based on unique problem keys
Args:
   questions: List of QuestionRecord objects
   answers: List of AnswerRecord objects
Returns:
   None (the function modifies the input lists in place to connect questions and answers based on their problem keys)
"""
def match_questions_and_answers(q_blocks, a_blocks, book_id: str) -> Tuple[List[QuestionRecord], Optional[List[AnswerRecord]]]:
   # Map answers by canonical key
   a_map = {}
   for a in a_blocks:
      chap = chapter_key(a["section_title"])
      key = canonical_problem_key(book_id, chap, a["anum"])
      a_map[key] = a

   questions_out = []
   answers_out = []

   for q in q_blocks:
      chap = chapter_key(q["section_title"])
      key = canonical_problem_key(book_id, chap, q["qnum"])
      qa_id = qa_id_from_problem_key(key)

      # Build QuestionRecord
      qrec = QuestionRecord(
         id=str(uuid.uuid4()),
         qa_id=qa_id,
         book_id=book_id,
         problem_key=key,
         question_number=q["qnum"],
         question_text=q["raw"],
         page_ids=set(q["page_ids"]),
         section_titles={q["section_title"]},
         section_labels={q["section_label"]} if q["section_label"] else set(),
      )
      questions_out.append(qrec)

      # Build AnswerRecord
      a = a_map.get(key)
      if a:
         arec = AnswerRecord(
            id=str(uuid.uuid4()),
            qa_id=qa_id,
            book_id=book_id,
            problem_key=key,
            answer_number=a["anum"],
            answer_choice=a["choice"],
            answer_text=a["raw"],
            page_ids=set(a["page_ids"]),
            section_titles={q["section_title"]},
            section_labels={q["section_label"]} if a["section_label"] else set(),
         )
         answers_out.append(arec)

   q_keys = {q.problem_key for q in questions_out}
   a_keys = {a.problem_key for a in answers_out}

   print("Questions:", len(q_keys))
   print("Answers:", len(a_keys))
   print("Matched:", len(q_keys & a_keys))
   print("Unmatched questions:", len(q_keys - a_keys))
   print("Unmatched answers:", len(a_keys - q_keys))

   return questions_out, answers_out

""" -------------------------------------------------------------------------------------------------------- """
"""
Build a section lookup from PageRecords by identifying sections from their content and section_ids
Args:
   pages: List of PageRecord objects
Returns:
   A lookup list indexed by page number, containing section info
"""
def build_lookup_from_pages(pages: List[PageRecord]) -> list:
   """
   Build a lookup table from pages by finding 'Practice Exercises' and 'Solutions' sections.
   Returns a list indexed by page number (1-based) with section info.
   """
   # Find which pages contain which sections
   page_sections = {}
   
   for page in pages:
      page_num = page.pdf_page_number
      text_lower = page.text.lower()
      
      # Identify section type from page text
      if "practice exercises" in text_lower:
         page_sections[page_num] = {
            "section_label": "practice",
            "section_title": "Practice Exercises"
         }
      elif "exercise solutions" in text_lower or "solutions" in text_lower:
         page_sections[page_num] = {
            "section_label": "solutions", 
            "section_title": "Exercise Solutions"
         }
   
   # Build lookup array
   if page_sections:
      max_page = max(page_sections.keys())
      lookup = [None] * (max_page + 1)
      for page_num, section_info in page_sections.items():
         lookup[page_num] = section_info
      return lookup
   
   return []

""" -------------------------------------------------------------------------------------------------------- """
"""
Hierarchical parsing of document pages to extract questions and answers
Args:
   document: A DocumentRecord object from convert_pdf()
Returns:
   A tuple of (QuestionRecord Path, AnswerRecord Path) extracted from the document
"""
def extract_qas(output_path: Path, book_id: str) -> Tuple[Path, Path]:
   # 1) Load PageRecords from JSONL file
   pages = []
   
   with open(output_path, 'r', encoding='utf-8') as f:
      for line in f:
         if line.strip():
            record = json.loads(line)
            # Reconstruct PageRecord from JSON
            page = PageRecord(
               id=record.get('id'),
               book_id=record.get('book_id'),
               pdf_page_number=record.get('pdf_page_number'),
               real_page_number=record.get('real_page_number'),
               text=record.get('text', ''),
               word_count=record.get('word_count', 0),
               section_ids=set(record.get('section_ids', []))
            )
            pages.append(page)
   
   # 2) Build section lookup from pages
   lookup = build_lookup_from_pages(pages)
   
   # 3) Extract questions and answers
   questions = extract_questions(pages, lookup, book_id)
   answers = extract_answers(pages, lookup, book_id)
   
   # 4) Match questions with answers
   questions_out, answers_out = match_questions_and_answers(questions, answers, book_id)

   # 5) Save to output directory
   questions_path, answers_path = save_qa_extraction(questions_out, answers_out, output_path)
   
   return questions_path, answers_path 

""" -------------------------------------------------------------------------------------------------------- """
"""
Save extracted questions and answers to JSONL files in /questions and /answers folders
Args:
   questions: List of QuestionRecord objects
   answers: List of AnswerRecord objects
   input_jsonl_path: Path to the input JSONL file (used to determine output filename)
Returns:
   A tuple of (questions_output_path, answers_output_path)
"""
def save_qa_extraction(questions: List[QuestionRecord], answers: List[AnswerRecord], output_path: Path) -> Tuple[Path, Path]:
   from pathlib import Path
   from pdf_to_jsonl import to_jsonable

   # Get base filename without extension
   base_name = output_path.stem  # e.g., "eecs_test3" from "eecs_test3.jsonl"
   if base_name.endswith('_PageRecords'):
      base_name = base_name[:-len('_PageRecords')]

   output_dir = output_path.parent
   # Create output paths
   questions_output = output_dir / f"{base_name}_Questions.jsonl"
   answers_output = output_dir / f"{base_name}_Answers.jsonl"
   
   print(f"Saving to:")
   print(f"  Questions: {questions_output}")
   print(f"  Answers: {answers_output}\n")

   # Save questions
   with open(questions_output, 'w', encoding='utf-8') as f:
      for q in questions:
         record = to_jsonable(q)
         f.write(json.dumps(record, ensure_ascii=False) + '\n')
   
   # Save answers
   with open(answers_output, 'w', encoding='utf-8') as f:
      for a in answers:
         record = to_jsonable(a)
         f.write(json.dumps(record, ensure_ascii=False) + '\n')
   
   return questions_output, answers_output

def load_pages(path: Path):
   pages = []
   with open(path, "r", encoding="utf-8") as f:
      for line in f:
         data = json.loads(line)
         pages.append(PageRecord(**data))
   return pages

if __name__ == "__main__":
   root = Path(__file__).parent

   input_path = root / 'jsonls' / 'eecs_test4.jsonl'
   q_out_path = root / 'questions' / 'questions_test4.jsonl'
   a_out_path = root / 'answers' / 'answers_test4.jsonl'

   print("Loading pages...")
   pages = load_pages(input_path)

   book_id = pages[0].book_id

   print("Parsing document...")
   questions, answers = parse_document_pages(input_path, "47bbcc23-9276-5662-9e40-96e8a4841ec7")

   print(f"Extracted {len(questions)} questions")
   print(f"Extracted {len(answers)} answers")
   

   # Write questions
   with open(q_out_path, "w", encoding="utf-8") as f:
      json.dump(to_jsonable(questions), f, indent=2)

   # Write answers
   with open(a_out_path, "w", encoding="utf-8") as f:
      json.dump(to_jsonable(answers), f, indent=2)

   print("\nDone.\n")