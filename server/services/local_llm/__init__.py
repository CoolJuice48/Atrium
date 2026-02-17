"""Optional local LLM polish for practice exams. Uses Ollama/llama.cpp. No paid APIs."""

from server.services.local_llm.provider import (
    LocalLLMError,
    LocalLLMProvider,
    get_provider,
)
from server.services.local_llm.polish import (
    polish_definition_question,
    polish_fill_in_blank,
)

__all__ = [
    "LocalLLMError",
    "LocalLLMProvider",
    "get_provider",
    "polish_definition_question",
    "polish_fill_in_blank",
]
