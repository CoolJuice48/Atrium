"""Configuration for the Atrium API server."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Settings:
    """
    All filesystem paths the server needs.

    Defaults resolve relative to the project root.
    Every field is overridable at construction for testing.
    """
    index_root: Optional[Path] = None
    study_db_path: Optional[Path] = None
    session_log_path: Optional[Path] = None
    graph_registry_path: Optional[Path] = None
    golden_sets_dir: Optional[Path] = None

    def __post_init__(self):
        project_root = Path(__file__).resolve().parent.parent

        if self.index_root is None:
            env_root = os.environ.get("INDEX_ROOT")
            self.index_root = Path(env_root) if env_root else project_root / "textbook_index"
        self.index_root = Path(self.index_root)

        if self.study_db_path is None:
            self.study_db_path = self.index_root / 'study_cards.jsonl'
        self.study_db_path = Path(self.study_db_path)

        if self.session_log_path is None:
            self.session_log_path = self.index_root / 'session_log.jsonl'
        self.session_log_path = Path(self.session_log_path)

        if self.graph_registry_path is None:
            self.graph_registry_path = self.index_root / 'graph_registry.json'
        self.graph_registry_path = Path(self.graph_registry_path)

        if self.golden_sets_dir is None:
            self.golden_sets_dir = project_root / 'eval' / 'golden_sets'
        self.golden_sets_dir = Path(self.golden_sets_dir)
