"""Orchestrates local LLM polish with cache, validation, fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from server.services.local_llm.cache import get as cache_get, set_ as cache_set
from server.services.local_llm.provider import LocalLLMError, LocalLLMProvider
from server.services.local_llm.prompts import polish_definition_question as def_prompts, polish_fill_in_blank as fib_prompts
from server.services.local_llm.validate import validate_definition_polish, validate_fill_blank_polish

logger = logging.getLogger("atrium.local_llm")

_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore(concurrency: int = 2) -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(concurrency)
    return _semaphore


def _normalize_input(*parts: str) -> str:
    return "|".join(p[:200] for p in parts if p)


async def polish_definition_question(
    provider: LocalLLMProvider,
    sentence: str,
    term_candidate: str,
    definition_candidate: str,
    *,
    settings: Any = None,
    def_stats: Any = None,
) -> Optional[Tuple[str, str, str]]:
    """
    Polish definition (term, question, answer). Returns (term, question, answer) or None to use deterministic.
    """
    max_input = getattr(settings, "local_llm_max_input_chars", 800) if settings else 800
    max_output = getattr(settings, "local_llm_max_output_chars", 500) if settings else 500
    timeout = getattr(settings, "local_llm_timeout_s", 20) if settings else 20
    temp = getattr(settings, "local_llm_temperature", 0.2) if settings else 0.2
    concurrency = getattr(settings, "local_llm_concurrency", 2) if settings else 2
    model = getattr(settings, "local_llm_model", "qwen2.5:7b-instruct") if settings else "default"

    sentence = sentence[:max_input]
    definition_candidate = " ".join(definition_candidate.split()[:35])

    cache_key_input = _normalize_input(sentence, term_candidate, definition_candidate)
    cached = cache_get(model, "definition", cache_key_input)
    if cached is not None:
        ok, _ = validate_definition_polish(cached)
        if ok:
            return (cached["term"], cached["question"], cached["answer"])
        return None

    system, user, schema = def_prompts(sentence, term_candidate, definition_candidate)
    if def_stats:
        def_stats.local_llm_attempted += 1
    sem = _get_semaphore(concurrency)
    async with sem:
        try:
            out = await provider.generate_json(
                system, user, schema,
                max_input_chars=max_input,
                max_output_chars=max_output,
                temperature=temp,
                timeout_s=timeout,
            )
        except LocalLLMError as e:
            if def_stats:
                def_stats.local_llm_fallback_used += 1
                if e.kind == "timeout":
                    def_stats.local_llm_timeout += 1
                elif e.kind == "invalid_json":
                    def_stats.local_llm_invalid_json += 1
                elif e.kind == "invalid_schema":
                    def_stats.local_llm_invalid_schema += 1
            logger.debug("Local LLM definition polish failed: %s", e.kind)
            return None

    ok, reason = validate_definition_polish(out)
    if not ok:
        if def_stats:
            def_stats.local_llm_fallback_used += 1
            def_stats.local_llm_invalid_schema += 1
        logger.debug("Definition polish validation failed: %s", reason)
        return None
    if def_stats:
        def_stats.local_llm_success += 1
    cache_set(model, "definition", cache_key_input, out)
    return (out["term"], out["question"], out["answer"])


async def polish_fill_in_blank(
    provider: LocalLLMProvider,
    sentence: str,
    blank_phrase_candidate: str,
    *,
    settings: Any = None,
    fib_stats: Any = None,
) -> Optional[Tuple[str, str]]:
    """
    Polish FIB (prompt, answer). Returns (prompt_with_blank, answer) or None to use deterministic.
    """
    max_input = getattr(settings, "local_llm_max_input_chars", 800) if settings else 800
    max_output = getattr(settings, "local_llm_max_output_chars", 500) if settings else 500
    timeout = getattr(settings, "local_llm_timeout_s", 20) if settings else 20
    temp = getattr(settings, "local_llm_temperature", 0.2) if settings else 0.2
    concurrency = getattr(settings, "local_llm_concurrency", 2) if settings else 2
    model = getattr(settings, "local_llm_model", "qwen2.5:7b-instruct") if settings else "default"

    sentence = sentence[:max_input]

    cache_key_input = _normalize_input(sentence, blank_phrase_candidate)
    cached = cache_get(model, "fib", cache_key_input)
    if cached is not None:
        ok, _ = validate_fill_blank_polish(cached)
        if ok:
            return (cached["prompt"], cached["answer"])
        return None

    system, user, schema = fib_prompts(sentence, blank_phrase_candidate)
    if fib_stats:
        fib_stats.local_llm_attempted += 1
    sem = _get_semaphore(concurrency)
    async with sem:
        try:
            out = await provider.generate_json(
                system, user, schema,
                max_input_chars=max_input,
                max_output_chars=max_output,
                temperature=temp,
                timeout_s=timeout,
            )
        except LocalLLMError as e:
            if fib_stats:
                fib_stats.local_llm_fallback_used += 1
                if e.kind == "timeout":
                    fib_stats.local_llm_timeout += 1
                elif e.kind == "invalid_json":
                    fib_stats.local_llm_invalid_json += 1
                elif e.kind == "invalid_schema":
                    fib_stats.local_llm_invalid_schema += 1
            logger.debug("Local LLM FIB polish failed: %s", e.kind)
            return None

    ok, reason = validate_fill_blank_polish(out)
    if not ok:
        if fib_stats:
            fib_stats.local_llm_fallback_used += 1
            fib_stats.local_llm_invalid_schema += 1
        logger.debug("FIB polish validation failed: %s", reason)
        return None
    if fib_stats:
        fib_stats.local_llm_success += 1
    cache_set(model, "fib", cache_key_input, out)
    return (out["prompt"], out["answer"])
