"""Prompts for local LLM polish. Small inputs only."""

from typing import Tuple


def polish_definition_question(
    sentence: str,
    term_candidate: str,
    definition_candidate: str,
) -> Tuple[str, str, str]:
    """
    Return (system_prompt, user_prompt, schema_hint) for definition polish.
    Inputs must be pre-truncated (sentence <= 800 chars, definition <= 35 words).
    """
    system = """You are a structuring tool for educational questions. Do not add facts. Do not paraphrase with new information.
Only rewrite for clarity. Keep content faithful to the source.
Output JSON only, no markdown, no code blocks.
If you cannot comply, output {"error":"reject"}."""

    schema = """Output schema (JSON only):
{
  "term": "string (2-6 tokens, no leading determiners like a/an/the/any/this/that, no discourse markers like then/thus/however)",
  "question": "string (must start with 'What is ' and end with '?', <= 12 words)",
  "answer": "string (5-30 words, single line, no long verbatim quotes)",
  "notes": "string (optional, for debug only)"
}"""

    user = f"""Source sentence: {sentence}

Extracted term candidate: {term_candidate}
Extracted definition: {definition_candidate}

Produce a clean definition question. The term must be a proper noun phrase (2-6 words), no determiners or discourse markers at the start. The question must be "What is [term]?" and the answer must be a short faithful definition (5-30 words). Output JSON only."""

    return system, user, schema


def polish_fill_in_blank(
    sentence: str,
    blank_phrase_candidate: str,
) -> Tuple[str, str, str]:
    """
    Return (system_prompt, user_prompt, schema_hint) for FIB polish.
    """
    system = """You are a structuring tool for fill-in-the-blank questions. Do not add facts. Do not change meaning.
Only rewrite the sentence with exactly one blank (use ____) where the phrase was removed. Preserve grammar.
Output JSON only, no markdown.
If you cannot comply, output {"error":"reject"}."""

    schema = """Output schema (JSON only):
{
  "prompt": "string (original sentence with exactly one '____' blank, grammar intact)",
  "answer": "string (1-3 words, the removed phrase)",
  "rationale": "string (optional)"
}"""

    user = f"""Sentence: {sentence}

The phrase to blank out: {blank_phrase_candidate}

Replace that phrase with ____ in the sentence. Ensure the result is grammatically correct. Output JSON only."""

    return system, user, schema


def polish_short_answer(
    sentence: str,
    draft_question: str,
    draft_answer: str,
) -> Tuple[str, str, str]:
    """
    Return (system_prompt, user_prompt, schema_hint) for short-answer stem cleanup.
    """
    system = """You are a structuring tool. Do not add facts. Do not change meaning; only minor grammar cleanup.
The answer must remain unchanged. Output JSON only, no markdown.
If you cannot comply, output {"error":"reject"}."""

    schema = """Output schema (JSON only):
{
  "question": "string (clearer question stem)",
  "answer": "string (must be identical to the input answer)"
}"""

    user = f"""Source: {sentence}

Draft question: {draft_question}
Draft answer (do not change): {draft_answer}

Rewrite the question stem to be more natural. Keep the answer exactly as given. Output JSON only."""

    return system, user, schema
