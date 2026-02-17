"""Tests for strong text normalization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.text_normalize_strong import (
    is_math_heavy,
    math_density,
    normalize_text_strong,
    normalize_unicode_basics,
    repair_hyphenated_linebreaks,
    strip_inline_garbage,
)


def test_hyphen_linebreak_merge():
    """Hyphenated line breaks are merged."""
    assert repair_hyphenated_linebreaks("af- terposition") == "afterposition"
    # "di- ferent" merges to "diferent" (di+ferent); "diff- erent" would yield "different"
    assert repair_hyphenated_linebreaks("di- ferent") == "diferent"


def test_ligature_replacements():
    """Ligatures are replaced with ASCII."""
    s = "ﬁ ﬂ \ufb00"
    out = normalize_unicode_basics(s)
    assert "fi" in out
    assert "fl" in out
    assert "ff" in out


def test_pdf_weird_f_between_letters():
    """Sutton/Barto di↵erent -> diferent (↵ replaced with f). Standalone ↵ removed."""
    s = "di\u21b5erent"
    out = normalize_unicode_basics(s)
    assert "\u21b5" not in out
    assert "diferent" in out or "different" in out
    s2 = "word \u21b5 more"
    out2 = normalize_unicode_basics(s2)
    assert "\u21b5" not in out2


def test_remove_arrows_and_replacement_char():
    """Arrows and replacement char removed."""
    s = "text \u2190 arrow \ufffd replacement"
    out = normalize_unicode_basics(s)
    assert "\u2190" not in out
    assert "\ufffd" not in out


def test_is_math_heavy():
    """Equation-like string -> True. Normal prose -> False."""
    assert is_math_heavy("E = mc^2 and x = y + z") is True
    assert is_math_heavy("The gradient descent algorithm minimizes the loss.") is False
    assert is_math_heavy("(9.14) x = ∑ α_i") is True
