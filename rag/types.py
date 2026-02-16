from typing import List, Optional
from dataclasses import dataclass

@dataclass
class Chunk:
   chunk_id: str
   text: str
   source_id: str
   chapter: Optional[int]
   section: Optional[str]
   section_title: Optional[str]
   page_start: Optional[int]
   page_end: Optional[int]
   type: str  # "section" | "question" | "answer"
   embedding: Optional[np.ndarray]
