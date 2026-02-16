import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from legacy.qa_schema import Question, Answer, QuestionOption

"""Represents a detected chapter heading."""
@dataclass
class ChapterRecord:
   chapter_number: int
   chapter_title: str
   page_number: Optional[int] = None
   start_position: int = 0  # Character position in text
   full_match: str = ""  # The actual matched text
   
   def __repr__(self):
      return f"Chapter {self.chapter_number}: {self.chapter_title}"

"""Represents a detected section/subsection heading."""
@dataclass
class SectionRecord:
   section_number: str  # e.g., "1.2.3"
   section_title: str
   level: int = 1  # 1=section, 2=subsection, 3=subsubsection
   page_number: Optional[int] = None
   start_position: int = 0
   full_match: str = ""
   
   def __repr__(self):
      return f"Section {self.section_number}: {self.section_title}"

# ============================================================================
# CHAPTER PATTERNS
# ============================================================================

CHAPTER_PATTERNS = [
   # "Chapter 1: Introduction"
   # "Chapter 1 - Introduction"
   # "CHAPTER 1: INTRODUCTION"
   r'^Chapter\s+(\d+)\s*[:\-–—]\s*(.+?)$',
   
   # "Chapter 1" (standalone)
   # "CHAPTER 1"
   r'^Chapter\s+(\d+)\s*$',
   
   # "CHAPTER ONE: Introduction"
   r'^Chapter\s+(One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve)\s*[:\-–—]\s*(.+?)$',
   
   # "Ch. 1: Introduction"
   # "Ch 1 - Introduction"
   r'^Ch\.?\s+(\d+)\s*[:\-–—]\s*(.+?)$',
]

WORD_TO_NUMBER = {
   'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
   'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
   'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15
}

ROMAN_TO_NUMBER = {
   'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
   'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
   'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15
}

# ============================================================================
# SECTION PATTERNS
# ============================================================================

SECTION_PATTERNS = [
   # "1.2 Pointers and References"
   # "1.2.3 Advanced Topics"
   r'^((?:\d+\.)+\d+)\s+(.+?)$',
   
   # "1.2. Pointers and References" (with trailing period)
   r'^((?:\d+\.)+\d+)\.\s+(.+?)$',
   
   # "Section 1.2: Pointers"
   # "Section 1.2 - Pointers"
   r'^Section\s+((?:\d+\.)+\d+)\s*[:\-–—]\s*(.+?)$',
   
   # "§1.2 Pointers"
   r'^§\s*((?:\d+\.)+\d+)\s+(.+?)$',
   
   # Lettered sections: "A. Introduction"
   r'^([A-Z])\.\s+([A-Z][^.]{5,})$',
]

# ============================================================================
# PRACTICE PROBLEM PATTERNS
# ============================================================================

QUESTION_HEADER_PATTERNS = [
   # "Chapter 1 Practice Exercises"
   # "Chapter 1 Practice Problems"
   r'Chapter\s+\d+\s+Practice\s+(Exercises|Problems|Questions)',
   
   # "Practice Exercises"
   # "Practice Problems"
   r'Practice\s+(Exercises|Problems|Questions)',
   
   # "Exercises"
   # "Problems"
   r'^(Exercises|Problems|Questions)\s*$',
   
   # "End of Chapter Exercises"
   r'End\s+of\s+Chapter\s+(Exercises|Problems|Questions)',
   
   # "Review Questions"
   r'Review\s+(Questions|Problems|Exercises)',
   
   # "Self-Test Questions"
   r'Self[- ]Test\s+(Questions|Problems|Exercises)',
   
   # "Homework Problems"
   r'Homework\s+(Problems|Questions|Exercises)',
]

QUESTION_NUMBER_PATTERNS = [
   r'^(\d+)[\.\)]\s+(Which|What|How|Why|Consider|Given|Suppose).+[?]?$',
   # "1. What is..."
   # "1) What is..."
   r'^(\d+)[\.\)]\s+(.+?)$',
   
   # "Question 1: What is..."
   # "Problem 1 - What is..."
   r'^(?:Question|Problem|Exercise)\s+(\d+)\s*[:\-–—]\s*(.+?)$',
   
   # "Q1. What is..."
   # "Q1) What is..."
   r'^[Qq](\d+)[\.\)]\s+(.+?)$',
   
   # Lettered: "a. What is..."
   # "a) What is..."
   r'^([a-z])[\.\)]\s+(.+?)$',
]

MULTIPLE_CHOICE_OPTION_PATTERNS = [
   # "A) Option text"
   # "A. Option text"
   r'^([A-E])[\.\)]\s+(.+?)$',
   
   # "(A) Option text"
   r'^\(([A-E])\)\s+(.+?)$',
   
   # "a) Option text" (lowercase)
   r'^([a-e])[\.\)]\s+(.+?)$',
]

SUB_QUESTION_PATTERNS = [
   # "I. Sub-question text"
   # "II. Sub-question text"
   r'^([IVX]+)\.\s+(.+?)$',
   
   # "(i) Sub-question"
   # "(ii) Sub-question"
   r'^\(([ivx]+)\)\s+(.+?)$',
   
   # "i. Sub-question"
   r'^([ivx]+)\.\s+(.+?)$',
]

# ============================================================================
# ANSWER/SOLUTION PATTERNS
# ============================================================================

ANSWER_HEADER_PATTERNS = [
   # "Chapter 1 Exercise Solutions"
   # "Chapter 1 Solutions"
   r'Chapter\s+\d+\s+(Exercise\s+)?Solutions',
   
   # "Solutions"
   # "Answers"
   r'^(Solutions|Answers)\s*$',
   
   # "Solution to Exercises"
   r'Solutions?\s+to\s+(Exercises|Problems|Questions)',
   
   # "Answer Key"
   r'Answer\s+Key',
   
   # "Selected Answers"
   r'Selected\s+(Answers|Solutions)',
]

ANSWER_PATTERNS = [
   # "1. The correct answer is (A)."
   # "1. Answer: A"
   r'^(\d+)\.\s+(?:The\s+correct\s+answer\s+is\s+)?\(?([A-E])\)?',
   
   # "Answer 1: (B)"
   r'^Answer\s+(\d+)\s*[:\-–—]\s*\(?([A-E])\)?',
   
   # Just the explanation starting with number
   r'^(\d+)\.\s+(.+?)$',
]

def find_chapters(text: str, page_number: Optional[int]=None) -> List[ChapterRecord]:
   chapters = []
   lines = text.split('\n')

   for line_idx, line in enumerate(lines):
      line = line.strip()
      if not line:
         continue

      for pattern in CHAPTER_PATTERNS:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
               groups = match.groups()
               
               # Parse chapter number
               chapter_num_str = groups[0]
               if chapter_num_str.isdigit():
                  chapter_num = int(chapter_num_str)
               elif chapter_num_str.lower() in WORD_TO_NUMBER:
                  chapter_num = WORD_TO_NUMBER[chapter_num_str.lower()]
               elif chapter_num_str in ROMAN_TO_NUMBER:
                  chapter_num = ROMAN_TO_NUMBER[chapter_num_str]
               else:
                  continue
               
               # Parse chapter title
               chapter_title = groups[1] if len(groups) > 1 else ""
               chapter_title = chapter_title.strip()
               
               chapters.append(ChapterRecord(
                  chapter_number=chapter_num,
                  chapter_title=chapter_title,
                  page_number=page_number,
                  start_position=line_idx,
                  full_match=line
               ))
               break
   
   return chapters

def find_sections(text: str, page_number: Optional[int] = None) -> List[SectionRecord]:
   """
   Find all section/subsection headings in text.
   
   Args:
      text: Text to search
      page_number: Optional page number for metadata
      
   Returns:
      List of SectionRecord objects
   """
   sections = []
   lines = text.split('\n')
   
   for line_idx, line in enumerate(lines):
      line = line.strip()
      if not line:
         continue
         
      for pattern in SECTION_PATTERNS:
         match = re.match(pattern, line)
         if match:
               groups = match.groups()
               section_num = groups[0]
               section_title = groups[1].strip()
               
               # Determine nesting level by counting dots
               level = section_num.count('.') + 1
               
               sections.append(SectionRecord(
                  section_number=section_num,
                  section_title=section_title,
                  level=level,
                  page_number=page_number,
                  start_position=line_idx,
                  full_match=line
               ))
               break
   
   return sections


def find_questions(text: str, source_book: str = "Unknown", page_number: Optional[int] = None) -> List[Question]:
   """
   Find all practice questions in text.
   
   Args:
      text: Text to search
      source_book: Source book name for metadata
      page_number: Optional page number for metadata
      
   Returns:
      List of Question objects
   """
   questions = []
   lines = text.split('\n')
   
   # Find where answer section starts (if any)
   answer_section_start = len(lines)
   for idx, line in enumerate(lines):
      if has_answer(line):
         answer_section_start = idx
         break
   
   i = 0
   while i < answer_section_start:  # Only look before answer section
      line = lines[i].strip()
      
      # Skip if this looks like an answer line
      if re.match(r'^\d+\.\s+(?:The\s+correct\s+answer|Answer)', line, re.IGNORECASE):
         i += 1
         continue
      
      # Try to match question number
      question_num = None
      question_text = None
      
      for pattern in QUESTION_NUMBER_PATTERNS:
         match = re.match(pattern, line)
         if match:
               groups = match.groups()
               question_num = groups[0]
               question_text = groups[1].strip()
               break
      
      if question_num and question_text:
         # Found a question - now look for options
         options = []
         sub_parts = []
         code_snippet = []
         j = i + 1
         
         # Collect the full question and options
         while j < answer_section_start:
               next_line = lines[j].strip()
               
               # Check if this is a multiple choice option
               is_option = False
               for opt_pattern in MULTIPLE_CHOICE_OPTION_PATTERNS:
                  opt_match = re.match(opt_pattern, next_line)
                  if opt_match:
                     letter = opt_match.group(1).upper()
                     text = opt_match.group(2).strip()
                     options.append(QuestionOption(letter, text))
                     is_option = True
                     break
               
               # Check if this is a sub-part (I, II, III)
               is_subpart = False
               for sub_pattern in SUB_QUESTION_PATTERNS:
                  sub_match = re.match(sub_pattern, next_line)
                  if sub_match:
                     sub_parts.append(next_line)
                     is_subpart = True
                     break
               
               # Check if we hit the next question
               is_next_question = False
               for q_pattern in QUESTION_NUMBER_PATTERNS:
                  if re.match(q_pattern, next_line):
                     # Make sure it's not an answer
                     if not re.match(r'^\d+\.\s+(?:The\s+correct\s+answer|Answer)', next_line, re.IGNORECASE):
                           is_next_question = True
                     break
               
               if is_next_question:
                  break
               
               # If not an option or subpart, might be continuation or code
               if not is_option and not is_subpart and next_line:
                  # If it looks like code (indented, has braces, etc.)
                  if (lines[j].startswith('    ') or 
                     lines[j].startswith('\t') or
                     '{' in next_line or '}' in next_line or
                     re.match(r'^\d+\s+\w+', next_line) or  # Code line numbers like "1  int main()"
                     next_line.startswith('//')):
                     code_snippet.append(lines[j])
                  elif not is_option:
                     # Continuation of question text
                     question_text += " " + next_line
               
               j += 1
         
         # Create Question object
         question_id = f"{source_book.lower().replace(' ', '_')}_p{page_number or 0}_q{question_num}"
         
         q = Question(
               question_id=question_id,
               question_text=question_text,
               question_type="multiple_choice" if options else "free_response",
               options=options,
               sub_parts=sub_parts,
               code_snippet="\n".join(code_snippet) if code_snippet else None,
               source_type="textbook",
               source_book=source_book,
               source_page=page_number,
         )
         
         questions.append(q)
         i = j  # Skip past this question
      else:
         i += 1
   
   return questions


def find_answers(text: str, questions: List[Question] = None) -> List[Answer]:
   """
   Find all answer explanations in text.
   
   Args:
      text: Text to search
      questions: Optional list of questions to match answers to
      
   Returns:
      List of Answer objects
   """
   answers = []
   lines = text.split('\n')
   
   i = 0
   while i < len(lines):
      line = lines[i].strip()
      
      # Try to match answer number and letter
      answer_num = None
      correct_letter = None
      explanation = ""
      
      for pattern in ANSWER_PATTERNS:
         match = re.match(pattern, line)
         if match:
               groups = match.groups()
               answer_num = groups[0]
               if len(groups) > 1:
                  # Has a letter
                  correct_letter = groups[1] if groups[1].isalpha() else None
                  if len(groups) > 2:
                     explanation = groups[2]
               else:
                  # Just explanation
                  explanation = groups[1] if len(groups) > 1 else ""
               break
      
      if answer_num:
         # Found an answer - collect full explanation
         j = i + 1
         while j < len(lines) and not re.match(ANSWER_PATTERNS[0], lines[j].strip()):
               explanation += " " + lines[j].strip()
               j += 1
         
         # Try to match to a question
         question_id = None
         if questions:
               for q in questions:
                  if answer_num in q.question_id:
                     question_id = q.question_id
                     break
         
         if not question_id:
               question_id = f"unknown_q{answer_num}"
         
         # Parse out incorrect explanations if present
         incorrect_explanations = {}
         # Look for patterns like "Statement I is false because..."
         
         answer = Answer(
               question_id=question_id,
               answer_text=explanation.strip(),
               incorrect_explanations=incorrect_explanations,
         )
         
         answers.append(answer)
         i = j
      else:
         i += 1
   
   return answers


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def has_chapter(text: str) -> bool:
   """Check if text contains an answer/solution section header."""
   for pattern in CHAPTER_PATTERNS:
      if re.search(pattern, text, re.IGNORECASE):
         return True
   return False

def has_section(text: str) -> bool:
   """Check if text contains an answer/solution section header."""
   for pattern in SECTION_PATTERNS:
      if re.search(pattern, text, re.IGNORECASE):
         return True
   return False


def has_question(text: str) -> bool:
   """Check if text contains a question/exercise section header."""
   for pattern in QUESTION_HEADER_PATTERNS:
      if re.search(pattern, text, re.IGNORECASE):
         return True
   return False


def has_answer(text: str) -> bool:
   """Check if text contains an answer/solution section header."""
   for pattern in ANSWER_HEADER_PATTERNS:
      if re.search(pattern, text, re.IGNORECASE):
         return True
   return False


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
   # Test chapter detection
   test_text = """
Chapter 1: Introduction to Programming
This is some content.

Chapter 2 - Data Structures
More content here.

1. Arrays and Lists
Content about arrays.

1.2 Dynamic Arrays
More detailed content.

Practice Exercises

1. Which of the following is true?
A) Option A
B) Option B
C) Option C

2. What is the time complexity?
A) O(1)
B) O(n)
C) O(log n)

Solutions

1. The correct answer is (A). Because...
2. The correct answer is (C). Because...
"""
   
   print("=" * 60)
   print("TESTING CHAPTER DETECTION")
   print("=" * 60)
   chapters = find_chapters(test_text)
   for ch in chapters:
      print(ch)
   
   print("\n" + "=" * 60)
   print("TESTING SECTION DETECTION")
   print("=" * 60)
   sections = find_sections(test_text)
   for sec in sections:
      print(sec)
   
   print("\n" + "=" * 60)
   print("TESTING QUESTION DETECTION")
   print("=" * 60)
   questions = find_questions(test_text, "Test Book", 1)
   for q in questions:
      print(f"Q{q.question_id}: {q.question_text[:50]}...")
      print(f"  Options: {len(q.options)}")
   
   print("\n" + "=" * 60)
   print("TESTING ANSWER DETECTION")
   print("=" * 60)
   answers = find_answers(test_text, questions)
   for a in answers:
      print(f"A for {a.question_id}: {a.answer_text[:50]}...")
