#!/usr/bin/env python3
"""
Tests for legacy/textbook_search_offline.py

Covers:
  - pagerank_stable: dangling rows, convergence, NaN safety
  - compose_answer: coherent output with citations, heading penalty
  - _score_sentence: heading-like fragment detection
  - chunk-size diagnostic warning

Run:  pytest tests/test_search_offline.py -v
"""

import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from legacy.textbook_search_offline import (
   pagerank_stable,
   compose_answer,
   _score_sentence,
   _tokenize_simple,
   _tokenize_symbols,
   _is_definition_question,
   _is_comparison_question,
   _detect_contradiction,
   _compute_redundancy,
)


# ============================================================================
# HELPERS
# ============================================================================

def _make_chunks(texts, book="test_book", section="2.1", pages="10-11"):
   """Build fake result dicts matching the shape compose_answer expects."""
   return [
      {
         'text': t,
         'metadata': {
            'book': book,
            'section': section,
            'pages': pages,
         },
      }
      for t in texts
   ]


# ============================================================================
# TESTS: pagerank_stable
# ============================================================================

def test_pagerank_zero_row_no_nan():
   """A transition matrix with a zero row should NOT produce NaN/inf."""
   # 3x3 matrix; row 1 is all zeros (dangling node)
   T = np.array([
      [0.0, 0.5, 0.5],
      [0.0, 0.0, 0.0],   # <-- dangling
      [0.3, 0.3, 0.4],
   ])
   scores, fell_back = pagerank_stable(T)
   assert scores.shape == (3,)
   assert np.all(np.isfinite(scores)), f"Got non-finite scores: {scores}"
   assert abs(scores.sum() - 1.0) < 1e-6, f"Scores should sum to 1, got {scores.sum()}"


def test_pagerank_all_zero_rows():
   """All-zero matrix should still return finite uniform-ish scores."""
   T = np.zeros((4, 4))
   scores, fell_back = pagerank_stable(T)
   assert scores.shape == (4,)
   assert np.all(np.isfinite(scores))
   assert abs(scores.sum() - 1.0) < 1e-6


def test_pagerank_empty_matrix():
   """Empty matrix returns empty array."""
   T = np.zeros((0, 0))
   scores, fell_back = pagerank_stable(T)
   assert scores.shape == (0,)


def test_pagerank_single_node():
   """Single node: score should be 1.0."""
   T = np.array([[1.0]])
   scores, fell_back = pagerank_stable(T)
   assert scores.shape == (1,)
   assert abs(scores[0] - 1.0) < 1e-6


def test_pagerank_identity():
   """Identity matrix (each node links only to itself)."""
   T = np.eye(3)
   scores, fell_back = pagerank_stable(T)
   assert np.all(np.isfinite(scores))
   # Should be uniform (each node is equally important in isolation)
   assert abs(scores[0] - scores[1]) < 1e-3


def test_pagerank_convergence():
   """Well-formed stochastic matrix converges to stable distribution."""
   T = np.array([
      [0.0, 1.0, 0.0],
      [0.5, 0.0, 0.5],
      [0.0, 1.0, 0.0],
   ])
   scores, fell_back = pagerank_stable(T, max_iter=200, tol=1e-12)
   # Node 1 (index 1) should have highest score — it receives most links
   assert scores[1] > scores[0]
   assert scores[1] > scores[2]


def test_pagerank_large_matrix_with_dangling():
   """Larger matrix with several dangling rows stays finite."""
   n = 50
   rng = np.random.RandomState(42)
   T = rng.rand(n, n)
   # Zero out 10 random rows
   for i in rng.choice(n, 10, replace=False):
      T[i, :] = 0.0
   scores, fell_back = pagerank_stable(T)
   assert scores.shape == (n,)
   assert np.all(np.isfinite(scores))
   assert abs(scores.sum() - 1.0) < 1e-6


# ============================================================================
# TESTS: compose_answer
# ============================================================================

def test_compose_answer_returns_definition():
   """compose_answer picks a definition sentence over a heading-like fragment."""
   chunks = _make_chunks([
      "A binary search tree is a data structure that maintains sorted order "
      "for efficient lookup and insertion.  BSTs support O(log n) operations "
      "in balanced cases.",

      "gradient descent (Section 8.6.1).",
   ])

   result = compose_answer("What is a binary search tree?", chunks)

   assert 'answer' in result
   assert 'key_points' in result
   assert 'citations' in result
   assert len(result['answer']) > 0
   # The definition sentence should appear, not the heading fragment
   assert "binary search tree" in result['answer'].lower()
   assert "Section 8.6.1" not in result['answer']


def test_compose_answer_includes_citations():
   """Each key point should have a matching citation."""
   chunks = _make_chunks([
      "AVL trees maintain balance through rotations.  Each node stores a "
      "balance factor that is the difference in heights of left and right "
      "subtrees.",
   ], section="3.2", pages="45-46")

   result = compose_answer("How do AVL trees work?", chunks)

   assert len(result['citations']) == len(result['key_points'])
   for cite in result['citations']:
      assert "test_book" in cite
      assert "3.2" in cite


def test_compose_answer_diversity_cap():
   """No more than max_per_chunk sentences from a single chunk."""
   long_text = (
      "Sentence one about algorithms.  "
      "Sentence two about algorithms.  "
      "Sentence three about algorithms.  "
      "Sentence four about algorithms.  "
      "Sentence five about algorithms."
   )
   chunks = _make_chunks([long_text])

   result = compose_answer(
      "algorithms", chunks,
      max_sentences=4, max_per_chunk=2,
   )

   # At most 2 sentences from the single chunk
   assert len(result['key_points']) <= 2


def test_compose_answer_empty_chunks():
   """Empty input returns empty result."""
   result = compose_answer("anything", [])
   assert result['answer'] == ''
   assert result['key_points'] == []
   assert result['citations'] == []


# ============================================================================
# TESTS: _score_sentence (heading penalty)
# ============================================================================

def test_heading_like_penalised():
   """Heading-like sentences get penalised relative to definition sentences."""
   q_tokens = _tokenize_simple("What is gradient descent?")
   q_symbols = _tokenize_symbols("What is gradient descent?")

   heading = "gradient descent (Section 8.6.1)."
   definition = (
      "Gradient descent is an iterative optimization algorithm that "
      "minimises a function by moving in the direction of steepest descent."
   )

   score_heading = _score_sentence(heading, q_tokens, q_symbols)
   score_definition = _score_sentence(definition, q_tokens, q_symbols)

   assert score_definition > score_heading, \
      f"Definition ({score_definition}) should score higher than heading ({score_heading})"


def test_very_short_sentence_negative():
   """Sentences with < 6 words get score -1."""
   q_tokens = _tokenize_simple("test")
   q_symbols = set()
   score = _score_sentence("Too short.", q_tokens, q_symbols)
   assert score == -1.0


def test_section_ref_penalised():
   """'see Chapter 3.' style fragments should be penalised."""
   q_tokens = _tokenize_simple("What is a hash table?")
   q_symbols = set()

   ref_sentence = "Hash tables are discussed further (Chapter 3)."
   real_sentence = (
      "A hash table uses a hash function to map keys to array indices "
      "for constant-time average-case lookups."
   )

   score_ref = _score_sentence(ref_sentence, q_tokens, q_symbols)
   score_real = _score_sentence(real_sentence, q_tokens, q_symbols)

   assert score_real > score_ref


def test_score_sentence_symbol_bonus():
   """Sentences matching code symbols get a bonus."""
   q_tokens = _tokenize_simple("std::cout << value")
   q_symbols = _tokenize_symbols("std::cout << value")

   with_symbols = "Use std::cout << value to print output to the console in C++ programs."
   without_symbols = "Use the print function to output values to the console in programs."

   score_with = _score_sentence(with_symbols, q_tokens, q_symbols)
   score_without = _score_sentence(without_symbols, q_tokens, q_symbols)

   assert score_with > score_without


# ============================================================================
# TESTS: Evidence metrics (Part 1)
# ============================================================================

def test_compose_answer_high_confidence():
   """High confidence when coverage >= 0.3 and diversity >= 2."""
   # Two chunks from different books with strong overlap
   chunks = [
      {
         'text': (
            "Gradient descent is an iterative optimization algorithm that "
            "finds local minima by following the negative gradient."
         ),
         'metadata': {'book': 'BookA', 'section': '1.1', 'pages': '5'},
      },
      {
         'text': (
            "Gradient descent updates parameters by subtracting the gradient "
            "scaled by the learning rate at each step."
         ),
         'metadata': {'book': 'BookB', 'section': '3.2', 'pages': '42'},
      },
   ]
   result = compose_answer("What is gradient descent?", chunks)
   conf = result['confidence']
   assert conf['level'] == 'high', f"Expected high, got {conf['level']}"
   assert conf['source_diversity_score'] >= 2
   assert conf['evidence_coverage_score'] > 0
   assert conf['contradiction_flag'] is False


def test_compose_answer_low_confidence_empty():
   """Empty chunks produce low confidence."""
   result = compose_answer("anything", [])
   conf = result['confidence']
   assert conf['level'] == 'low'
   assert conf['evidence_coverage_score'] == 0.0
   assert conf['source_diversity_score'] == 0


def test_compose_answer_low_confidence_single_book():
   """Single book can't reach 'high' (needs diversity >= 2)."""
   chunks = _make_chunks([
      "Gradient descent is an optimization algorithm that minimizes loss functions."
   ], book="OnlyBook")
   result = compose_answer("What is gradient descent?", chunks)
   conf = result['confidence']
   # With only 1 book, level should be medium at best (not high)
   assert conf['level'] in ('medium', 'low'), f"Got {conf['level']}"
   assert conf['source_diversity_score'] == 1


# ============================================================================
# TESTS: Contradiction detection (Part 1)
# ============================================================================

def test_detect_contradiction_negation_asymmetry():
   """Two sentences about the same topic but one negated → contradiction."""
   sentences = [
      "Gradient descent always converges to the global minimum in convex functions.",
      "Gradient descent does not always converge to the global minimum in practice.",
   ]
   q_tokens = _tokenize_simple("does gradient descent converge")
   assert _detect_contradiction(sentences, q_tokens) is True


def test_detect_contradiction_no_conflict():
   """Two agreeing sentences should not flag contradiction."""
   sentences = [
      "Binary search trees maintain sorted order for efficient lookups.",
      "Binary search trees support logarithmic time search in balanced cases.",
   ]
   q_tokens = _tokenize_simple("binary search trees")
   assert _detect_contradiction(sentences, q_tokens) is False


def test_detect_contradiction_single_sentence():
   """A single sentence can't contradict itself."""
   sentences = ["Gradient descent is an optimization algorithm."]
   q_tokens = _tokenize_simple("gradient descent")
   assert _detect_contradiction(sentences, q_tokens) is False


# ============================================================================
# TESTS: Redundancy (Part 1)
# ============================================================================

def test_compute_redundancy_identical():
   """Identical sentences have high redundancy."""
   sentences = [
      "Gradient descent minimizes loss functions iteratively.",
      "Gradient descent minimizes loss functions iteratively.",
   ]
   r = _compute_redundancy(sentences)
   assert r == 1.0


def test_compute_redundancy_different():
   """Very different sentences have low redundancy."""
   sentences = [
      "The sun rises in the east and sets in the west every day.",
      "Binary search trees maintain sorted order for efficient lookups.",
   ]
   r = _compute_redundancy(sentences)
   assert r < 0.2


def test_compute_redundancy_single():
   """Single sentence → redundancy 0."""
   assert _compute_redundancy(["Only one sentence."]) == 0.0


# ============================================================================
# TESTS: Definition bias (Part 2)
# ============================================================================

def test_definition_mode_boosts_is_sentence():
   """In definition mode, 'X is Y' sentences get boosted."""
   q_tokens = _tokenize_simple("What is a neural network?")
   q_symbols = set()

   definition = (
      "A neural network is a computational model inspired by biological neurons "
      "that learns patterns from data."
   )
   non_definition = (
      "Neural networks have been applied successfully to image recognition "
      "and natural language processing tasks."
   )

   score_def = _score_sentence(definition, q_tokens, q_symbols, definition_mode=True)
   score_nodef = _score_sentence(non_definition, q_tokens, q_symbols, definition_mode=True)

   assert score_def > score_nodef, \
      f"Definition ({score_def}) should outscore non-definition ({score_nodef}) in definition mode"


def test_definition_mode_defined_as_bonus():
   """'defined as' gets an extra boost in definition mode."""
   q_tokens = _tokenize_simple("What is entropy?")
   q_symbols = set()

   defined_as = (
      "Entropy is defined as the expected value of the information content "
      "of a random variable in information theory."
   )
   plain_is = (
      "Entropy is a measure of uncertainty or randomness in a probability "
      "distribution used in information theory."
   )

   score_defined = _score_sentence(defined_as, q_tokens, q_symbols, definition_mode=True)
   score_plain = _score_sentence(plain_is, q_tokens, q_symbols, definition_mode=True)

   assert score_defined > score_plain, \
      f"'defined as' ({score_defined}) should outscore plain 'is' ({score_plain})"


def test_is_definition_question():
   """Detect definition-style questions."""
   assert _is_definition_question("What is gradient descent?") is True
   assert _is_definition_question("What are neural networks?") is True
   assert _is_definition_question("Define entropy") is True
   assert _is_definition_question("Explain backpropagation") is True
   assert _is_definition_question("How does gradient descent work?") is False
   assert _is_definition_question("Compare SGD vs Adam") is False


# ============================================================================
# TESTS: Comparison mode (Part 3)
# ============================================================================

def test_is_comparison_question():
   """Detect comparison-style questions."""
   assert _is_comparison_question("Compare SGD vs Adam") is True
   assert _is_comparison_question("What is the difference between CNN and RNN?") is True
   assert _is_comparison_question("SGD versus Adam optimizer") is True
   assert _is_comparison_question("What is gradient descent?") is False


def test_comparison_mode_structured_output():
   """Comparison question produces comparison dict with concept_a/concept_b."""
   chunks = [
      {
         'text': (
            "SGD updates parameters using the gradient of a single sample, "
            "making it faster but noisier than batch gradient descent."
         ),
         'metadata': {'book': 'BookA', 'section': '4.1', 'pages': '80'},
      },
      {
         'text': (
            "Adam combines momentum and adaptive learning rates, maintaining "
            "per-parameter learning rates for faster convergence."
         ),
         'metadata': {'book': 'BookB', 'section': '4.3', 'pages': '92'},
      },
   ]
   result = compose_answer("Compare SGD vs Adam", chunks)
   # Should have comparison key (if concepts were split successfully)
   if 'comparison' in result:
      comp = result['comparison']
      assert 'concept_a' in comp
      assert 'concept_b' in comp
      assert 'differences' in comp
      assert 'name' in comp['concept_a']
      assert 'name' in comp['concept_b']
   # Either way, must have confidence
   assert 'confidence' in result
   assert result['confidence']['level'] in ('high', 'medium', 'low')


def test_comparison_mode_falls_back():
   """If comparison split fails, falls back to normal answer."""
   # Question has comparison keyword but only one concept
   chunks = _make_chunks([
      "Machine learning algorithms learn patterns from training data and "
      "generalize to unseen examples."
   ])
   result = compose_answer("compare", chunks)
   # Should still return valid result (fallback to normal compose)
   assert 'answer' in result
   assert 'confidence' in result
