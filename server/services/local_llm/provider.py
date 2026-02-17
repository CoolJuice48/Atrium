"""Local LLM provider interface. Ollama primary; llama.cpp optional."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("atrium.local_llm")


@dataclass
class LocalLLMError(Exception):
    """Structured error from local LLM. Never expose raw tracebacks."""
    kind: str  # timeout | unavailable | invalid_json | invalid_schema | provider_error
    message: str
    details: Optional[Dict[str, Any]] = None


class LocalLLMProvider(ABC):
    """Abstract provider for local LLM generation."""

    name: str = "base"

    @abstractmethod
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: str,
        *,
        max_input_chars: int = 800,
        max_output_chars: int = 500,
        temperature: float = 0.2,
        timeout_s: int = 20,
    ) -> Dict[str, Any]:
        """Generate JSON output. Returns parsed dict or raises LocalLLMError."""
        ...

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        """Test if provider is available. Returns (ok, message)."""
        ...


class OllamaProvider(LocalLLMProvider):
    """Ollama HTTP API provider."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b-instruct",
        timeout_s: int = 20,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.name = "ollama"

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: str,
        *,
        max_input_chars: int = 800,
        max_output_chars: int = 500,
        temperature: float = 0.2,
        timeout_s: int = 20,
    ) -> Dict[str, Any]:
        full_prompt = f"{system_prompt}\n\n{schema_hint}\n\n{user_prompt}"
        if len(full_prompt) > max_input_chars:
            full_prompt = full_prompt[:max_input_chars] + "..."
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_output_chars,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
        except httpx.TimeoutException as e:
            raise LocalLLMError(kind="timeout", message="Model request timed out", details={"error": str(e)})
        except httpx.ConnectError as e:
            raise LocalLLMError(kind="unavailable", message="Cannot connect to Ollama", details={"error": str(e)})
        except Exception as e:
            logger.exception("Ollama request failed")
            raise LocalLLMError(kind="provider_error", message="Model request failed", details={"error": str(e)})
        if resp.status_code != 200:
            raise LocalLLMError(
                kind="provider_error",
                message=f"Ollama returned {resp.status_code}",
                details={"status": resp.status_code, "body": resp.text[:200]},
            )
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise LocalLLMError(kind="invalid_json", message="Invalid response from model", details={"error": str(e)})
        text = data.get("response", "")
        if not text:
            raise LocalLLMError(kind="invalid_json", message="Empty response from model")
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LocalLLMError(kind="invalid_json", message="Model output is not valid JSON", details={"error": str(e)})

    async def test_connection(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
            if resp.status_code == 200:
                return True, "Ollama available"
            return False, f"Ollama returned {resp.status_code}"
        except httpx.ConnectError:
            return False, "Ollama not detected. Install and run: ollama serve"
        except Exception as e:
            return False, str(e)


class FakeProvider(LocalLLMProvider):
    """Test double: returns canned responses."""

    def __init__(self, canned: Optional[Dict[str, Any]] = None, error: Optional[LocalLLMError] = None):
        self.canned = canned
        self.error = error
        self.name = "fake"

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: str,
        **kwargs,
    ) -> Dict[str, Any]:
        if self.error:
            raise self.error
        if self.canned is not None:
            return self.canned
        return {"error": "reject"}

    async def test_connection(self) -> tuple[bool, str]:
        if self.error and self.error.kind == "unavailable":
            return False, "Fake unavailable"
        return True, "Fake OK"


_provider: Optional[LocalLLMProvider] = None


def get_provider(settings) -> Optional[LocalLLMProvider]:
    """Get configured provider. Returns None if disabled."""
    if not getattr(settings, "local_llm_enabled", False):
        return None
    global _provider
    if _provider is None:
        provider_name = getattr(settings, "local_llm_provider", "ollama")
        if provider_name == "ollama":
            _provider = OllamaProvider(
                base_url=getattr(settings, "local_llm_base_url", "http://localhost:11434"),
                model=getattr(settings, "local_llm_model", "qwen2.5:7b-instruct"),
                timeout_s=getattr(settings, "local_llm_timeout_s", 20),
            )
        else:
            _provider = OllamaProvider(
                base_url=getattr(settings, "local_llm_base_url", "http://localhost:11434"),
                model=getattr(settings, "local_llm_model", "qwen2.5:7b-instruct"),
                timeout_s=getattr(settings, "local_llm_timeout_s", 20),
            )
    return _provider


def reset_provider() -> None:
    """Reset cached provider (for tests)."""
    global _provider
    _provider = None
