from __future__ import annotations

import json
from typing import TYPE_CHECKING
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ---- You will likely need to adjust these imports to match your repo ----
# CardStore (JSONL store)
from study.storage import CardStore  # type: ignore

# Graph registry
from graph.models import GraphRegistry  # type: ignore


@dataclass
class RuntimePaths:
   index_root: Path
   store_path: Path
   session_log_path: Path
   graph_path: Path
   last_answer_path: Path


class Runtime:
   """
   Process-wide runtime cache for expensive objects.

   - Search engine/index: expensive to load => cached
   - Card store: cached
   - Graph registry: loaded lazily; writes are atomic
   """

   def __init__(self, paths: RuntimePaths):
      self.paths = paths

      self._engine_lock = threading.Lock()
      self._store_lock = threading.Lock()
      self._graph_lock = threading.Lock()

      self._engine: Optional[Any] = None
      self._store: Optional[CardStore] = None
      self._graph: Optional[GraphRegistry] = None

   # ----------------------------
   # Engine
   # ----------------------------
   def get_engine(self) -> Any:
      """
      Returns the cached search engine, building it if needed.
      """
      if self._engine is not None:
         return self._engine
      with self._engine_lock:
         if self._engine is None:
               self._engine = build_engine(self.paths.index_root)
      return self._engine

   def reset_engine(self) -> None:
      """
      Useful for tests or if you rebuild the index at runtime.
      """
      with self._engine_lock:
         self._engine = None

   # ----------------------------
   # Store
   # ----------------------------
   def get_store(self) -> CardStore:
      if self._store is not None:
         return self._store
      with self._store_lock:
         if self._store is None:
               self._store = CardStore(str(self.paths.store_path))
      return self._store

   # ----------------------------
   # Graph
   # ----------------------------
   def get_graph(self) -> Optional[GraphRegistry]:
      """
      Loads graph registry if it exists; returns None if absent.
      Cached process-wide.
      """
      if self._graph is not None:
         return self._graph
      with self._graph_lock:
         if self._graph is None:
               if self.paths.graph_path.exists():
                  greg = GraphRegistry()
                  greg.load(self.paths.graph_path)
                  self._graph = greg
               else:
                  self._graph = None
      return self._graph

   def save_graph_atomic(self, graph: GraphRegistry) -> None:
      """
      Atomically saves graph to disk (temp write + rename), and updates cache.
      """
      with self._graph_lock:
         path = self.paths.graph_path
         path.parent.mkdir(parents=True, exist_ok=True)

         tmp = path.with_suffix(path.suffix + ".tmp")
         # GraphRegistry.save() might already write deterministically; if it writes directly,
         # we still want atomicity. So we serialize ourselves if possible.
         data = graph.to_dict() if hasattr(graph, "to_dict") else None

         if data is not None:
               with tmp.open("w", encoding="utf-8") as f:
                  json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
               tmp.replace(path)
         else:
               # Fallback: call the graph's save method, but still atomic (tmp + rename).
               graph.save(tmp)
               tmp.replace(path)

         self._graph = graph

   def invalidate_graph(self) -> None:
      with self._graph_lock:
         self._graph = None


# -------------------------------------------------------------------
# Engine builder wrapper
# -------------------------------------------------------------------
def build_engine(index_root: Path) -> Any:
   """
   Thin wrapper around your existing offline search/index loader.

   This SHOULD NOT duplicate logic.
   It should import and call the same code your CLI uses to load the index.

   Replace the import/call below with your project's actual entry point.
   """

   # --- Option 1: If your legacy module exposes a loader function ---
   # from legacy.textbook_search_offline import TextbookSearchOffline
   # return TextbookSearchOffline(index_root=str(index_root))

   # --- Option 2: If you have a function like `load_offline_search(index_root)` ---
   # from legacy.textbook_search_offline import load_offline_search
   # return load_offline_search(str(index_root))

   # --- Placeholder: raise with an actionable error until wired ---
   raise RuntimeError(
      "build_engine() is not wired yet. "
      "Edit server/runtime.py to call your actual offline index/search loader "
      "(e.g., TextbookSearchOffline(index_root=...))."
   )


# -------------------------------------------------------------------
# Runtime factory (for FastAPI dependency injection)
# -------------------------------------------------------------------
if TYPE_CHECKING:
    from server.config import Settings


def runtime_from_settings(settings: "Settings") -> Runtime:
    """Build Runtime from Settings. Used by get_runtime dependency."""
    paths = RuntimePaths(
        index_root=Path(settings.index_root),
        store_path=Path(settings.study_db_path),
        session_log_path=Path(settings.session_log_path),
        graph_path=Path(settings.graph_registry_path),
        last_answer_path=Path(settings.index_root) / "_last_answer.json",
    )
    return Runtime(paths)
