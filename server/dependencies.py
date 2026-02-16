"""FastAPI dependency factories."""

import sys
from functools import lru_cache
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import Depends

from server.config import Settings
from server.runtime import Runtime, runtime_from_settings
from study.storage import CardStore

# Process-wide Runtime cache (keyed by settings identity for override support)
_runtime: Runtime | None = None
_runtime_settings_id: object | None = None


@lru_cache()
def get_settings() -> Settings:
    """Singleton Settings -- override via app.dependency_overrides in tests."""
    return Settings()


def get_runtime(settings: Settings = Depends(get_settings)) -> Runtime:
    """Process-wide Runtime cache for CardStore and GraphRegistry."""
    global _runtime, _runtime_settings_id
    # Recreate if settings were overridden (e.g. in tests)
    if _runtime is None or _runtime_settings_id is not settings:
        _runtime = runtime_from_settings(settings)
        _runtime_settings_id = settings
    return _runtime


def get_card_store(runtime: Runtime = Depends(get_runtime)) -> CardStore:
    """Cached CardStore from Runtime (process-wide)."""
    return runtime.get_store()


def get_graph(runtime: Runtime = Depends(get_runtime)):
    """Cached GraphRegistry from Runtime (process-wide), or None if absent."""
    return runtime.get_graph()
