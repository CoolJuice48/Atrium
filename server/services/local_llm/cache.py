"""LRU cache for local LLM outputs. Prevents duplicate calls."""

import hashlib
import logging
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger("atrium.local_llm")

_CACHE: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_CACHE_MAX = 500
_LOCK = Lock()


def _cache_key(model: str, prompt_type: str, normalized_input: str) -> str:
    h = hashlib.sha256(f"{model}|{prompt_type}|{normalized_input}".encode()).hexdigest()
    return h[:32]


def get(model: str, prompt_type: str, normalized_input: str) -> Optional[Dict[str, Any]]:
    """Get cached result. Returns None if miss."""
    key = _cache_key(model, prompt_type, normalized_input)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    return None


def set_(model: str, prompt_type: str, normalized_input: str, value: Dict[str, Any]) -> None:
    """Store result. Evicts oldest if at capacity."""
    key = _cache_key(model, prompt_type, normalized_input)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
        _CACHE[key] = value
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def clear() -> None:
    """Clear cache (for tests)."""
    with _LOCK:
        _CACHE.clear()
