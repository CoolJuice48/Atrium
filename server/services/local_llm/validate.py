"""Hard validation for local LLM outputs. Reject invalid; fall back to deterministic."""

import re
from typing import Tuple

# Reuse exam_stems rejection lists
_TERM_FIRST_TOKEN_REJECT = frozenset(
    "a an the any this that these those some each "
    "then thus however therefore because if but so also "
    "it they we you he she i them us his her their its".split()
)
_FIB_STOPWORDS = frozenset(
    "this that the a an it is are was were have has had do does "
    "any some each then thus however therefore because".split()
)


def validate_definition_polish(obj: dict) -> Tuple[bool, str]:
    """
    Validate definition polish output. Returns (ok, reason).
    """
    if not isinstance(obj, dict):
        return False, "not a dict"
    if obj.get("error") == "reject":
        return False, "model rejected"
    term = obj.get("term")
    question = obj.get("question")
    answer = obj.get("answer")
    if not term or not isinstance(term, str):
        return False, "missing term"
    if not question or not isinstance(question, str):
        return False, "missing question"
    if not answer or not isinstance(answer, str):
        return False, "missing answer"
    term = term.strip()
    question = question.strip()
    answer = answer.strip()
    tokens = re.findall(r"[a-zA-Z]+", term)
    if len(tokens) < 2 or len(tokens) > 6:
        return False, f"term token count {len(tokens)}"
    if tokens[0].lower() in _TERM_FIRST_TOKEN_REJECT:
        return False, "term starts with determiner/discourse/pronoun"
    if not re.match(r"^[a-zA-Z\s\-]+$", term):
        return False, "term has invalid chars"
    if not re.match(r'^What is [A-Za-z0-9].+\?$', question):
        return False, "question format invalid"
    if len(question.split()) > 12:
        return False, "question too long"
    ans_words = answer.split()
    if len(ans_words) < 5 or len(ans_words) > 30:
        return False, f"answer word count {len(ans_words)}"
    if "\n" in answer:
        return False, "answer multiline"
    if re.search(r"chapter|figure|table", answer, re.I):
        return False, "answer has structural refs"
    if answer.count(",") >= 2 and len(ans_words) > 20:
        return False, "answer citation-like"
    return True, ""


def validate_fill_blank_polish(obj: dict) -> Tuple[bool, str]:
    """
    Validate fill-in-blank polish output. Returns (ok, reason).
    """
    if not isinstance(obj, dict):
        return False, "not a dict"
    if obj.get("error") == "reject":
        return False, "model rejected"
    prompt = obj.get("prompt")
    answer = obj.get("answer")
    if not prompt or not isinstance(prompt, str):
        return False, "missing prompt"
    if not answer or not isinstance(answer, str):
        return False, "missing answer"
    prompt = prompt.strip()
    answer = answer.strip()
    if len(re.findall(r"_{2,}", prompt)) != 1:
        return False, "prompt must have exactly one blank (____)"
    if len(prompt) > 200:
        return False, "prompt too long"
    ans_words = answer.split()
    if len(ans_words) < 1 or len(ans_words) > 3:
        return False, f"answer word count {len(ans_words)}"
    if any(w.lower() in _FIB_STOPWORDS for w in ans_words):
        return False, "answer contains stopwords"
    if not answer.replace(" ", "").isalpha():
        return False, "answer must be alphabetic"
    return True, ""
