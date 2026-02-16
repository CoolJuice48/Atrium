import anthropic
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any

@dataclass
class QuestionOption:
   letter: str
   text: str

   def to_dict(self) -> Dict:
      return {"letter": self.letter, "text": self.text}
   
# Supports multiple question types
@dataclass
class Question:
   # Core
   question_id: str
   question_text: str
   question_type: str='multiple_choice'

   # MC
   options: List[QuestionOption]=field(default_factory=list)
   correct_answer: Optional[str]=None

   # Context
   sub_parts: List[str]=field(default_factory=list) # For I, II, III subparts
   code_snippet: Optional[str]=None

   # Metadata
   source_type: str='unknown'
   source_book: Optional[str]=None
   source_chapter: Optional[str]=None
   source_page: Optional[int]=None
   source_section: Optional[str]=None

   # Tagging for organization
   topics: List[str]=field(default_factory=list)
   difficulty: Optional[str]=None

   # Study tracking
   created_at: str=field(default_factory=lambda: datetime.now().isoformat())
   last_reviewed: Optional[str]=None
   times_attempted: int=0
   times_solved: int=0

   # Additional metadata
   notes: Optional[str]=None
   tags: List[str]=field(default_factory=list)
   custom_metadata: Dict[str, Any]=field(default_factory=dict)

   """ Dictionary conversion for JSON serialization """
   def to_dict(self) -> Dict:
      return {
         'question_id': self.question_id,
         'text': self.question_text,
         'q_type': self.question_type,
         'options': self.options,
         'correct_answer': self.correct_answer,
         'sub_parts': self.sub_parts,
         'code_snippet': self.code_snippet,
         'source_type': self.source_type,
         'source_book': self.source_book,
         'source_chapter': self.source_chapter,
         'source_page': self.source_page,
         'source_section': self.source_section,
         'topics': self.topics,
         'difficulty': self.difficulty,
         'created_at': self.created_at,
         'last_reviewed': self.last_reviewed,
         'times_attempted': self.times_attempted,
         'times_solved': self.times_solved,
         'notes': self.notes,
         'tags': self.tags,
         'custom_metadata': self.custom_metadata
      }
   
   """ Create Question from dictionary """
   @classmethod
   def from_dict(cls, data: Dict) -> 'Question':
      if 'options' in data and data['options']:
         data['options'] = [
            QuestionOption(**opt) if isinstance(opt, dict) else opt
            for opt in data['options']
         ]
      return cls(**data)
   
@dataclass
class Answer:
   # Link to question
   question_id: str

   # Answer content
   answer_text: str
   step_by_step: List[str]=field(default_factory=list)

   # Why others are incorrect
   incorrect_explanations: Dict[str, str]=field(default_factory=dict)

   # Supporting materials
   related_concepts: List[str]=field(default_factory=list)
   internal_references: List[str]=field(default_factory=list) # Textbook sections, etc.
   external_references: List[str]=field(default_factory=list) # Where this problem appears in the world

   # Metadata
   created_at: str=field(default_factory=lambda: datetime.now().isoformat())
   author: Optional[str]=None
   source: Optional[str]=None

   """ Dictionary conversion for JSON serialization """
   def to_dict(self) -> Dict:
      return {
         "question_id": self.question_id,
         "answer_text": self.answer_text,
         "step_by_step": self.step_by_step,
         "incorrect_explanations": self.incorrect_explanations,
         "related_concepts": self.related_concepts,
         "internal_references": self.internal_references,
         "external_references": self.external_references,
         "created_at": self.created_at,
         "author": self.author,
         "source": self.source
      }
   
   """ Create Answer from dictionary """
   def from_dict(cls, data: Dict) -> 'Answer':
      return cls(**data)
   
@dataclass
class QuestionBank:
   questions: List[Question]=field(default_factory=list)
   answers: List[Answer]=field(default_factory=list)
   name: str='untitled question bank'
   description: Optional[str]=None

   def add_question(self, question: Question) -> None:
      self.questions.append(question)

   def add_answer(self, answer: Answer) -> None:
      self.answers.append(answer)

   def add_question_answer_pair(self, question: Question, answer: Answer) -> None:
      self.questions.append(question)
      self.answers.append(answer)

   def get_question(self, question_id: str) -> Optional[Question]:
      for q in self.questions:
         if q.question_id == question_id:
            return q
      return None
   
   def get_answer(self, question_id: str) -> Optional[Answer]:
      for a in self.answers:
         if a.question_id == question_id:
            return a
      return None
   
   def filter_by_topic(self, topic: str) -> List[Question]:
      return [q for q in self.questions if topic in q.topics]
   
   def filter_by_source(self, source_book: str) -> List[Question]:
      return [q for q in self.questions if q.source_book == source_book]
   
   def save(self, filepath: str) -> None:
      data = {
         'name': self.name,
         'description': self.description,
         'questions': [asdict(q) for q in self.questions],
         'answers': [asdict(a) for a in self.answers]
      }
      with open(filepath, 'w') as f:
         json.dump(data, f, indent=2)
   
   @classmethod
   def load(cls, filepath: str) -> 'QuestionBank':
      with open(filepath, 'r') as f:
         data = json.load(f)

      bank = cls(
         name=data.get('name', 'untitled question bank'),
         description=data.get('description')
      )

      bank.questions = [Question.from_dict(q) for q in data.get('questions', [])]
      bank.answers = [Answer.from_dict(a) for a in data.get('answers', [])]

      return bank
   
   def __len__(self) -> int:
      return len(self.questions)
   
   def __repr__(self) -> str:
      return f"QuestionBank('{self.name}', {len(self.questions)} questions)"