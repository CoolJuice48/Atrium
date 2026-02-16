"""Tests for structural chunk detection and query filtering."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.structural_chunk import (
    is_structural_chunk,
    is_summary_type_question,
    partition_chunks,
)


def test_structural_chunk_detection_flags_toc():
    """TOC-like chunk with dotted leaders and page numbers is flagged as structural."""
    toc_chunk = """
    Chapter 1 Introduction ............ 1
    Chapter 2 Background .............. 15
    Chapter 3 Methods ................. 42
    3.1 Overview ...................... 43
    3.2 Implementation ............... 50
    Chapter 4 Results ................. 78
    Index ............................ 120
    """
    assert is_structural_chunk(toc_chunk) is True


def test_structural_chunk_detection_flags_index():
    """Index-like chunk with high numeric density and short lines."""
    index_chunk = """
    algorithm 45, 67, 89
    gradient 12, 34, 56
    neural 78, 90, 102
    backprop 23, 45
    """
    assert is_structural_chunk(index_chunk) is True


def test_structural_chunk_detection_does_not_flag_paragraph():
    """Explanatory paragraph is not flagged as structural."""
    paragraph = (
        "Gradient descent is an optimization algorithm used to minimize the loss function "
        "in machine learning models. It works by iteratively moving in the direction of "
        "steepest descent as defined by the negative of the gradient. The learning rate "
        "controls how large each step is, and choosing an appropriate value is critical "
        "for convergence."
    )
    assert is_structural_chunk(paragraph) is False


def test_structural_chunk_detection_does_not_flag_bullet_list():
    """Legitimate bullet list with explanatory content is not over-filtered."""
    bullets = """
    Key points about neural networks:
    - They consist of layers of interconnected nodes called neurons.
    - Each connection has a weight that is learned during training.
    - Activation functions introduce non-linearity into the model.
    - Backpropagation is used to compute gradients for weight updates.
    """
    assert is_structural_chunk(bullets) is False


def test_summary_type_question_detection():
    """Summary keywords are detected."""
    assert is_summary_type_question("Give me a summary of chapter 3") is True
    assert is_summary_type_question("What are the main ideas?") is True
    assert is_summary_type_question("Explain the chapter") is True
    assert is_summary_type_question("What is gradient descent?") is False
    assert is_summary_type_question("How does backpropagation work?") is False


def test_partition_chunks_separates_explanatory_from_structural():
    """partition_chunks correctly separates TOC from explanatory."""
    toc = {
        "text": "Ch 1 Intro .... 1\nCh 2 Methods .... 15\nCh 3 Results .... 42",
        "metadata": {"book": "Test", "section": "1"},
    }
    explanatory = {
        "text": "Gradient descent minimizes the loss function by iteratively updating "
        "parameters in the direction of steepest descent. The learning rate controls "
        "the step size and is critical for convergence.",
        "metadata": {"book": "Test", "section": "4.3"},
    }
    chunks = [toc, explanatory]
    exp, struct = partition_chunks(chunks, "What is gradient descent?")
    assert len(exp) == 1
    assert len(struct) == 1
    assert exp[0]["text"] == explanatory["text"]
    assert struct[0]["text"] == toc["text"]


def test_summary_query_filters_structural_chunks():
    """For summary-type question, explanatory chunk is used over TOC."""
    toc = {
        "text": "Ch 1 .... 1\nCh 2 .... 10\nCh 3 .... 20\nCh 4 .... 35",
        "metadata": {"book": "ML", "section": "toc"},
    }
    explanatory = {
        "text": "Machine learning enables computers to learn from data without being "
        "explicitly programmed. The main approaches include supervised learning, "
        "unsupervised learning, and reinforcement learning. Each has distinct "
        "use cases and algorithms.",
        "metadata": {"book": "ML", "section": "1.1"},
    }
    chunks = [toc, explanatory]
    exp, struct = partition_chunks(chunks, "Give me a summary of the main ideas")
    assert len(exp) >= 1
    assert explanatory in exp or any(
        c.get("text") == explanatory["text"] for c in exp
    )
    assert toc in struct or any(c.get("text") == toc["text"] for c in struct)


def test_fallback_when_all_structural():
    """When all chunks are structural, partition returns all as structural; caller uses original."""
    toc1 = {"text": "Ch 1 .... 1\nCh 2 .... 10", "metadata": {}}
    toc2 = {"text": "Index: a 1, b 2, c 3", "metadata": {}}
    chunks = [toc1, toc2]
    exp, struct = partition_chunks(chunks, "What is this?")
    assert len(exp) == 0
    assert len(struct) == 2


def test_query_service_uses_explanatory_chunks():
    """Integration: answer_question_offline composes from explanatory chunks when available."""
    from unittest.mock import patch, MagicMock

    toc = {
        "text": "Ch 1 .... 1\nCh 2 .... 10\nCh 3 .... 20",
        "metadata": {"book": "Test", "book_id": "b1", "section": "toc"},
        "similarity": 0.5,
    }
    explanatory = {
        "text": "Gradient descent is an optimization algorithm that minimizes the loss "
        "function by iteratively updating parameters. The learning rate controls "
        "the step size and is critical for convergence.",
        "metadata": {"book": "Test", "book_id": "b1", "section": "4.3"},
        "similarity": 0.8,
    }
    mock_results = [toc, explanatory]

    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp) / "index"
        index_dir.mkdir()
        (index_dir / "library.json").write_text(
            '{"version":"0.2","books":[{"book_id":"b1","title":"Test","status":"ready"}]}'
        )
        (index_dir / "books").mkdir()
        (index_dir / "books" / "b1").mkdir()
        (index_dir / "books" / "b1" / "chunks.jsonl").write_text(
            '{"text":"x","book_id":"b1"}\n'
        )
        (index_dir / "books" / "b1" / "book.json").write_text(
            '{"book_id":"b1","title":"Test","status":"ready","chunk_count":1}'
        )

        from server.services import query_service

        query_service._searcher_cache.clear()
        searcher = MagicMock()
        searcher.search.return_value = mock_results
        query_service._searcher_cache[str(index_dir.resolve())] = searcher

        result = query_service.answer_question_offline(
            "What is gradient descent?",
            index_root=str(index_dir),
            top_k=5,
            save_last_answer=False,
        )

        # Answer should come from explanatory chunk, not TOC
        answer = result["answer_dict"].get("answer", "")
        assert "gradient descent" in answer.lower() or "optimization" in answer.lower()
        assert "...." not in answer
        assert "Ch 1" not in answer
