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
    pdf_dir: Optional[Path] = None
    primary_min_hits: int = 5
    primary_min_top_score: float = 0.30
    study_db_path: Optional[Path] = None
    session_log_path: Optional[Path] = None
    graph_registry_path: Optional[Path] = None
    golden_sets_dir: Optional[Path] = None
    database_url: Optional[str] = None
    session_secret: Optional[str] = None
    syllabus_storage_path: Optional[Path] = None
    packs_dist_path: Optional[Path] = None
    uploads_root: Optional[Path] = None
    max_upload_size_mb: float = 80.0
    upload_rate_limit_per_user: int = 5  # max concurrent + recent uploads per user

    # Local LLM (Ollama / llama.cpp) - optional polish for practice exams
    local_llm_enabled: bool = False
    local_llm_provider: str = "ollama"
    local_llm_model: str = "qwen2.5:7b-instruct"
    local_llm_base_url: str = "http://localhost:11434"
    local_llm_timeout_s: int = 20
    local_llm_max_retries: int = 2
    local_llm_max_input_chars: int = 800
    local_llm_max_output_chars: int = 500
    local_llm_temperature: float = 0.2
    local_llm_top_p: float = 0.9
    local_llm_seed: int = 42
    local_llm_concurrency: int = 2
    local_llm_strict_json: bool = True

    def __post_init__(self):
        project_root = Path(__file__).resolve().parent.parent

        if self.index_root is None:
            env_root = os.environ.get("INDEX_ROOT")
            self.index_root = Path(env_root) if env_root else project_root / "textbook_index"
        self.index_root = Path(self.index_root)

        if self.pdf_dir is None:
            env_pdf = os.environ.get("PDF_DIR")
            self.pdf_dir = Path(env_pdf) if env_pdf else project_root / "pdfs"
        self.pdf_dir = Path(self.pdf_dir)

        env_hits = os.environ.get("PRIMARY_MIN_HITS")
        if env_hits is not None:
            try:
                self.primary_min_hits = int(env_hits)
            except ValueError:
                pass
        env_score = os.environ.get("PRIMARY_MIN_TOP_SCORE")
        if env_score is not None:
            try:
                self.primary_min_top_score = float(env_score)
            except ValueError:
                pass

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

        if self.database_url is None:
            self.database_url = os.environ.get("DATABASE_URL", "sqlite:///./atrium.db")
        if self.session_secret is None:
            self.session_secret = os.environ.get("SESSION_SECRET", "dev-secret-change-in-production")
        if self.syllabus_storage_path is None:
            self.syllabus_storage_path = project_root / "syllabus_storage"
        self.syllabus_storage_path = Path(self.syllabus_storage_path)
        if self.packs_dist_path is None:
            self.packs_dist_path = project_root / "atrium_packs" / "dist"
        self.packs_dist_path = Path(self.packs_dist_path)
        if self.uploads_root is None:
            self.uploads_root = project_root / "uploads"
        self.uploads_root = Path(self.uploads_root)

        # Local LLM env overrides
        if os.environ.get("LOCAL_LLM_ENABLED", "").lower() in ("1", "true", "yes"):
            self.local_llm_enabled = True
        if os.environ.get("LOCAL_LLM_PROVIDER"):
            self.local_llm_provider = os.environ["LOCAL_LLM_PROVIDER"]
        if os.environ.get("LOCAL_LLM_MODEL"):
            self.local_llm_model = os.environ["LOCAL_LLM_MODEL"]
        if os.environ.get("LOCAL_LLM_BASE_URL"):
            self.local_llm_base_url = os.environ["LOCAL_LLM_BASE_URL"]
        try:
            if v := os.environ.get("LOCAL_LLM_TIMEOUT_S"):
                self.local_llm_timeout_s = int(v)
        except ValueError:
            pass
