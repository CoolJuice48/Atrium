"""Data models and registry for the concept-question graph."""

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def make_question_id(question_text: str) -> str:
    """Deterministic question ID from normalized question text."""
    normalized = question_text.strip().lower()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


def make_concept_id(term: str) -> str:
    """Deterministic concept ID from normalized term."""
    normalized = term.strip().lower()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


@dataclass
class QNode:
    """A question node in the concept graph."""
    question_id: str
    question_text: str
    citations: List[str] = field(default_factory=list)      # chunk_ids
    books: List[str] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)
    terminality_score: float = 0.0
    confidence_snapshot: Dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'QNode':
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ConceptNode:
    """A concept node in the concept graph."""
    concept_id: str
    name: str
    occurrences: int = 1
    books: List[str] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)
    mastery_score: float = 0.0
    linked_qnodes: List[str] = field(default_factory=list)  # question_ids

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ConceptNode':
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


class GraphRegistry:
    """
    In-memory concept-question graph backed by a JSON file.

    Stores QNodes, ConceptNodes, and co-occurrence edges.
    """

    def __init__(self):
        self._qnodes: Dict[str, QNode] = {}
        self._concepts: Dict[str, ConceptNode] = {}
        self._cooccurrences: Dict[str, Dict[str, int]] = {}  # concept_id -> {concept_id: count}

    # -- Persistence --

    def load(self, path: Path) -> None:
        """Load the registry from a JSON file."""
        if not path.exists():
            return
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for qd in data.get('qnodes', []):
            qn = QNode.from_dict(qd)
            self._qnodes[qn.question_id] = qn
        for cd in data.get('concepts', []):
            cn = ConceptNode.from_dict(cd)
            self._concepts[cn.concept_id] = cn
        self._cooccurrences = data.get('cooccurrences', {})

    def save(self, path: Path) -> None:
        """Save the registry to a JSON file with deterministic ordering."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'qnodes': [self._qnodes[k].to_dict()
                        for k in sorted(self._qnodes)],
            'concepts': [self._concepts[k].to_dict()
                         for k in sorted(self._concepts)],
            'cooccurrences': {k: dict(sorted(v.items()))
                              for k, v in sorted(self._cooccurrences.items())},
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # -- QNode operations --

    def add_qnode(self, qnode: QNode) -> None:
        """Add or update a QNode."""
        self._qnodes[qnode.question_id] = qnode

    def get_qnode(self, question_id: str) -> Optional[QNode]:
        return self._qnodes.get(question_id)

    def all_qnodes(self) -> List[QNode]:
        return list(self._qnodes.values())

    # -- Concept operations --

    def add_concept(self, concept: ConceptNode) -> None:
        """Add or update a ConceptNode. Merges occurrences if exists."""
        existing = self._concepts.get(concept.concept_id)
        if existing:
            existing.occurrences += concept.occurrences
            for b in concept.books:
                if b not in existing.books:
                    existing.books.append(b)
            for s in concept.sections:
                if s not in existing.sections:
                    existing.sections.append(s)
            for qid in concept.linked_qnodes:
                if qid not in existing.linked_qnodes:
                    existing.linked_qnodes.append(qid)
        else:
            self._concepts[concept.concept_id] = concept

    def get_concept(self, concept_id: str) -> Optional[ConceptNode]:
        return self._concepts.get(concept_id)

    def get_concept_by_name(self, name: str) -> Optional[ConceptNode]:
        """Lookup concept by normalized name."""
        cid = make_concept_id(name)
        return self._concepts.get(cid)

    def all_concepts(self) -> List[ConceptNode]:
        return list(self._concepts.values())

    # -- Linking --

    def link_qnode_concepts(self, qnode_id: str, concept_ids: List[str]) -> None:
        """Link a QNode to a list of concepts (bidirectional)."""
        for cid in concept_ids:
            concept = self._concepts.get(cid)
            if concept and qnode_id not in concept.linked_qnodes:
                concept.linked_qnodes.append(qnode_id)

    def link_concept_cooccurrence(self, concept_a: str, concept_b: str) -> None:
        """Record that two concepts co-occurred."""
        if concept_a == concept_b:
            return
        self._cooccurrences.setdefault(concept_a, {})
        self._cooccurrences[concept_a][concept_b] = (
            self._cooccurrences[concept_a].get(concept_b, 0) + 1
        )
        self._cooccurrences.setdefault(concept_b, {})
        self._cooccurrences[concept_b][concept_a] = (
            self._cooccurrences[concept_b].get(concept_a, 0) + 1
        )

    def get_cooccurrences(self, concept_id: str) -> Dict[str, int]:
        """Return co-occurrence counts for a concept."""
        return dict(self._cooccurrences.get(concept_id, {}))

    def count_qnodes(self) -> int:
        return len(self._qnodes)

    def count_concepts(self) -> int:
        return len(self._concepts)
