"""Tests for deterministic bullet-structured summary composition."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.summary_compose import (
    clean_text,
    split_sentences,
    is_noisy_sentence,
    compose_bulleted_summary,
    compose_summary_from_chunks,
)


def test_noise_filter_removes_latex_and_digit_heavy():
    """Input with TeX fragments and digit lists should be excluded."""
    # LaTeX noise
    assert is_noisy_sentence(r"The formula uses \alpha and \lambda for parameters.") is True
    assert is_noisy_sentence(r"Given $\sum_{i=1}^n x_i$ we compute.") is True

    # Digit-heavy
    assert is_noisy_sentence("The values 1 2 3 4 5 6 7 8 9 0 are listed.") is True

    # Figure/table ref
    assert is_noisy_sentence("Figure 3.2 shows the results.") is True
    assert is_noisy_sentence("Table 1 summarizes the data.") is True

    # Normal prose kept
    assert is_noisy_sentence(
        "Gradient descent is an optimization algorithm that minimizes the loss function."
    ) is False
    assert is_noisy_sentence(
        "Neural networks consist of layers of interconnected nodes called neurons."
    ) is False


def test_compose_bulleted_summary_is_readable():
    """Feed paragraphs; assert output has ### Summary, bullets <= 10, no raw TeX."""
    paragraphs = [
        "Machine learning enables computers to learn from data without being explicitly programmed. "
        "The main approaches include supervised learning, unsupervised learning, and reinforcement learning. "
        "Each has distinct use cases and algorithms.",
        "Gradient descent minimizes the loss function by iteratively updating parameters. "
        "The learning rate controls the step size and is critical for convergence. "
        "Batch gradient descent uses the entire dataset for each update.",
        "Neural networks consist of layers of interconnected nodes. "
        "Backpropagation computes gradients for each weight in the network. "
        "Deep learning refers to networks with many hidden layers.",
    ]
    text = " ".join(paragraphs)
    sentences = split_sentences(text)
    assert len(sentences) >= 3

    output = compose_bulleted_summary(sentences, "summary of machine learning", max_bullets=10)

    assert "### Summary" in output
    bullets = [l for l in output.split("\n") if l.strip().startswith("- ")]
    assert len(bullets) <= 10
    assert len(bullets) >= 1

    for b in bullets:
        assert len(b) < 250  # bullet line length
        assert "\\alpha" not in b
        assert "\\lambda" not in b
        assert "$" not in b

    # Deterministic: same input -> same output
    output2 = compose_bulleted_summary(sentences, "summary of machine learning", max_bullets=10)
    assert output == output2


def test_query_service_summary_uses_bulleted_summary():
    """Provide chunks with noisy math + normal prose; ensure bullet-form response."""
    chunks = [
        {
            "text": r"The equation $\sum_{i=1}^n \alpha_i x_i$ uses parameters. "
            "Gradient descent is an optimization algorithm that minimizes the loss function. "
            "The learning rate controls the step size and is critical for convergence.",
            "metadata": {
                "book": "ML Book",
                "book_id": "b1",
                "section": "4.3",
                "pages": "80-85",
            },
        },
        {
            "text": "Neural networks consist of layers of interconnected nodes called neurons. "
            "Backpropagation computes gradients for each weight in the network. "
            "Deep learning refers to networks with many hidden layers.",
            "metadata": {
                "book": "ML Book",
                "book_id": "b1",
                "section": "6.1",
                "pages": "164-170",
            },
        },
    ]

    result = compose_summary_from_chunks(
        chunks,
        "Give me a summary of the main ideas",
        max_chunks=12,
        max_bullets=10,
    )

    assert "answer" in result
    assert "key_points" in result
    assert "citations" in result
    assert "confidence" in result

    answer = result["answer"]
    assert "### Summary" in answer
    assert "gradient" in answer.lower() or "neural" in answer.lower()
    assert "$" not in answer
    assert r"\sum" not in answer
    assert r"\alpha" not in answer

    bullets = result["key_points"]
    assert len(bullets) <= 10
    assert len(result["citations"]) >= 1


def test_normal_qa_unchanged():
    """Non-summary queries still use paragraph-style compose_answer, not bullet summary."""
    from server.services import query_service

    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        (index_dir / "library.json").write_text(
            '{"version":"0.2","books":[{"book_id":"b1","title":"Test","status":"ready"}]}'
        )
        (index_dir / "books").mkdir()
        (index_dir / "books" / "b1").mkdir()
        (index_dir / "books" / "b1" / "chunks.jsonl").write_text('{"text":"x","book_id":"b1"}\n')
        (index_dir / "books" / "b1" / "book.json").write_text(
            '{"book_id":"b1","title":"Test","status":"ready","chunk_count":1}'
        )

        chunk = {
            "text": "Gradient descent is an optimization algorithm that minimizes the loss function.",
            "metadata": {"book": "Test", "book_id": "b1", "section": "4.3"},
            "similarity": 0.9,
        }
        query_service._searcher_cache.clear()
        searcher = MagicMock()
        searcher.search.return_value = [chunk]
        query_service._searcher_cache[str(index_dir.resolve())] = searcher

        result = query_service.answer_question_offline(
            "What is gradient descent?",
            index_root=str(index_dir),
            top_k=5,
            save_last_answer=False,
        )

        # Non-summary: should NOT have ### Summary header (paragraph style)
        answer = result["answer_dict"].get("answer", "")
        assert "### Summary" not in answer
        assert "gradient" in answer.lower()


def test_clean_text_normalizes():
    """clean_text collapses whitespace and removes dot leaders."""
    dirty = "  word-\nword   \n\n\n  ....  more  \t text  "
    out = clean_text(dirty)
    assert "  " not in out or out.count("  ") < 2
    assert "...." not in out
    assert "wordword" in out or "word word" in out


def test_split_sentences_filters_short_and_long():
    """split_sentences keeps 30-240 chars, min 6 words."""
    short = "Too short."
    long_frag = "A" * 300 + "."
    good = "This sentence has exactly six words in it."
    out = split_sentences(f"{short} {long_frag} {good}")
    # Good sentence (without period) should be present
    good_stem = "This sentence has exactly six words in it"
    assert any(good_stem in s for s in out)
    assert not any(s == short for s in out)
    assert not any(len(s) > 240 for s in out)
