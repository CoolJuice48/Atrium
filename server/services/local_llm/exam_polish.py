"""Post-process exam questions with optional local LLM polish."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, List, Optional

from server.services.exam_generation import ExamQuestion

if TYPE_CHECKING:
    from server.services.local_llm.provider import LocalLLMProvider

logger = logging.getLogger("atrium.local_llm")


async def _polish_questions_async(
    questions: List[ExamQuestion],
    provider: "LocalLLMProvider",
    settings,
) -> List[ExamQuestion]:
    """Optionally polish definition and FIB questions. Falls back to original on any error."""
    from server.services.local_llm.polish import polish_definition_question, polish_fill_in_blank

    result = []
    for q in questions:
        if q.q_type == "definition" and q.source_text:
            try:
                polished = await polish_definition_question(
                    provider,
                    q.source_text,
                    _extract_term_from_stem(q.prompt),
                    q.answer,
                    settings=settings,
                )
                if polished:
                    term, question, answer = polished
                    result.append(ExamQuestion(
                        q_type=q.q_type,
                        prompt=question,
                        answer=answer,
                        citations=q.citations,
                        source_text=None,
                    ))
                else:
                    result.append(ExamQuestion(
                        q_type=q.q_type,
                        prompt=q.prompt,
                        answer=q.answer,
                        citations=q.citations,
                        source_text=None,
                    ))
            except Exception as e:
                logger.debug("Definition polish failed: %s", e)
                result.append(ExamQuestion(
                    q_type=q.q_type,
                    prompt=q.prompt,
                    answer=q.answer,
                    citations=q.citations,
                    source_text=None,
                ))
        elif q.q_type == "fib" and q.source_text:
            try:
                polished = await polish_fill_in_blank(
                    provider,
                    q.source_text,
                    q.answer,
                    settings=settings,
                )
                if polished:
                    prompt_with_blank, answer = polished
                    result.append(ExamQuestion(
                        q_type=q.q_type,
                        prompt=f"Fill in the blank: {prompt_with_blank}",
                        answer=answer,
                        citations=q.citations,
                        source_text=None,
                    ))
                else:
                    result.append(ExamQuestion(
                        q_type=q.q_type,
                        prompt=q.prompt,
                        answer=q.answer,
                        citations=q.citations,
                        source_text=None,
                    ))
            except Exception as e:
                logger.debug("FIB polish failed: %s", e)
                result.append(ExamQuestion(
                    q_type=q.q_type,
                    prompt=q.prompt,
                    answer=q.answer,
                    citations=q.citations,
                    source_text=None,
                ))
        else:
            result.append(ExamQuestion(
                q_type=q.q_type,
                prompt=q.prompt,
                answer=q.answer,
                citations=q.citations,
                source_text=None,
            ))
    return result


def _extract_term_from_stem(stem: str) -> str:
    """Extract term from 'What is X?'"""
    if stem.startswith("What is ") and stem.endswith("?"):
        return stem[8:-1].strip()
    return stem


def polish_exam_questions_sync(
    questions: List[ExamQuestion],
    provider: "LocalLLMProvider",
    settings,
) -> List[ExamQuestion]:
    """Run async polish from sync context. Uses asyncio.run()."""
    try:
        return asyncio.run(_polish_questions_async(questions, provider, settings))
    except Exception as e:
        logger.warning("Local LLM polish failed, using deterministic: %s", e)
        return questions
