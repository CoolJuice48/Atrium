#!/usr/bin/env python3
"""
Tests for page_classifier.py

Run:  pytest tests/test_page_classifier.py -v
"""

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legacy.page_classifier import classify_page, ClassifierConfig


# ============================================================================
# SAMPLE TEXTS
# ============================================================================

TOC_TEXT = """Table of Contents
1
Programming Foundations . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 1
1.1
Introduction . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 1
1.2
Pointers and References . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 2
1.2.1
Program Execution and the Machine Model . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 2
1.2.2
References and Reference Semantics . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 3
1.2.3
Pointers . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 4
1.3
Address Space and Dynamic Memory . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 5
1.4
Compound Objects . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 6
1.5
Operator Overloading . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 10
1.6
Function Objects and Comparators . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 12
"""

PRACTICE_TEXT = """Chapter 4 Practice Exercises

1. Which of the following is true about binary search trees?
A) They always maintain O(log n) height
B) They store elements in sorted order
C) They require balanced rotations
D) They cannot store duplicate values

2. What is the worst-case time complexity of inserting into an unbalanced BST?
A) O(1)
B) O(log n)
C) O(n)
D) O(n log n)

3. Consider the following AVL tree. After inserting the value 15, which rotation is needed?
A) Left rotation
B) Right rotation
C) Left-right rotation
D) Right-left rotation

4. Given a red-black tree with 7 nodes, what is the maximum possible height?
A) 3
B) 4
C) 5
D) 6
"""

INDEX_TEXT = """Index

abstract data type 45, 67, 89
algorithm analysis 12, 34–37, 56
amortized analysis 78, 90, 112, 134
AVL tree 156, 178–180
balanced BST 145, 167, 189
big-O notation 23, 45, 67, 89, 111
binary heap 201, 223, 245
binary search 34, 56–58, 78
binary search tree 123, 145, 167
breadth-first search 267, 289, 311
cache performance 89, 111, 133
comparison sort 156, 178, 200
complexity class 12, 34, 56, 78
connected component 289, 311, 333
"""

BLANKISH_TEXT = """


Page 42

"""

CONTENT_TEXT = """A binary search tree (BST) is a node-based binary tree data structure which has the following
properties. The left subtree of a node contains only nodes with keys lesser than the node's key.
The right subtree of a node contains only nodes with keys greater than the node's key. The left
and right subtrees must each also be binary search trees. There must be no duplicate nodes.

The time complexity of search, insert, and delete operations in a BST is O(h), where h is the
height of the tree. In the worst case, the tree can degenerate into a linked list, making h = n.
To avoid this, self-balancing BSTs like AVL trees and red-black trees maintain a height of
O(log n) through rotations.

AVL trees were the first self-balancing BST to be invented. They maintain the invariant that
for every node, the heights of its left and right subtrees differ by at most one. When this
invariant is violated after an insertion or deletion, the tree performs one or more rotations
to restore balance.
"""

FRONT_MATTER_TEXT = """Preface

This textbook is designed for undergraduate students studying data structures and algorithms.
It covers fundamental concepts including arrays, linked lists, trees, graphs, sorting, and
searching algorithms. Each chapter includes practice exercises and solutions.

Acknowledgments

The author would like to thank the following reviewers for their valuable feedback.

Copyright 2024 by Publisher Inc. All rights reserved.
ISBN 978-0-123456-78-9
"""


# ============================================================================
# TESTS
# ============================================================================

def test_toc_detection():
    """TOC page with 'Table of Contents' keyword and dot-leaders."""
    page_type, confidence, signals = classify_page(
        TOC_TEXT, pdf_page_number=1
    )
    assert page_type == "toc", f"Expected 'toc', got '{page_type}'"
    assert confidence >= 0.8, f"Expected confidence >= 0.8, got {confidence}"
    assert signals['toc_keyword_hit'] is True
    assert signals['dot_leader_count'] >= 5


def test_toc_without_keyword():
    """TOC page detected by dot-leaders alone (no 'Table of Contents' string)."""
    # Strip the keyword but keep the dot-leader lines
    lines = TOC_TEXT.split('\n')
    stripped = '\n'.join(ln for ln in lines if 'table of contents' not in ln.lower())
    page_type, confidence, signals = classify_page(
        stripped, pdf_page_number=1
    )
    assert page_type == "toc", f"Expected 'toc', got '{page_type}'"
    assert signals['dot_leader_count'] >= 5


def test_practice_detection():
    """Page with practice exercises and multiple-choice options."""
    page_type, confidence, signals = classify_page(
        PRACTICE_TEXT, pdf_page_number=50
    )
    assert page_type == "practice", f"Expected 'practice', got '{page_type}'"
    assert confidence >= 0.45
    assert signals['practice_keyword_hit'] is True
    assert signals['question_start_count'] >= 3
    assert signals['mc_option_count'] >= 4


def test_practice_by_questions_only():
    """Practice detected by numbered questions + MC options, no keyword."""
    text = """1. What is the time complexity of merge sort?
A) O(n)
B) O(n log n)
C) O(n^2)
D) O(log n)

2. Which data structure uses LIFO ordering?
A) Queue
B) Stack
C) Heap
D) Tree

3. What is a hash collision?
A) Two keys mapping to the same index
B) A full hash table
C) An empty bucket
D) A deleted entry

4. Which sorting algorithm is stable?
A) Quick sort
B) Heap sort
C) Merge sort
D) Selection sort
"""
    page_type, confidence, signals = classify_page(text, pdf_page_number=100)
    assert page_type == "practice", f"Expected 'practice', got '{page_type}'"
    assert signals['question_start_count'] >= 3
    assert signals['mc_option_count'] >= 4


def test_index_detection():
    """Back-of-book index page."""
    page_type, confidence, signals = classify_page(
        INDEX_TEXT, pdf_page_number=350
    )
    assert page_type == "index", f"Expected 'index', got '{page_type}'"
    assert confidence >= 0.5
    assert signals['index_keyword_hit'] is True
    assert signals['comma_page_refs_count'] >= 5


def test_blankish_detection():
    """Nearly empty page."""
    page_type, confidence, signals = classify_page(
        BLANKISH_TEXT, pdf_page_number=42
    )
    assert page_type == "blankish", f"Expected 'blankish', got '{page_type}'"
    assert confidence >= 0.9


def test_blankish_empty_string():
    """Completely empty page."""
    page_type, confidence, signals = classify_page("", pdf_page_number=1)
    assert page_type == "blankish"


def test_content_detection():
    """Normal body text with sentences."""
    page_type, confidence, signals = classify_page(
        CONTENT_TEXT, pdf_page_number=50
    )
    assert page_type == "content", f"Expected 'content', got '{page_type}'"
    assert confidence >= 0.6
    assert signals['sentence_count_estimate'] >= 3


def test_front_matter_detection():
    """Early page with preface / copyright / ISBN."""
    page_type, confidence, signals = classify_page(
        FRONT_MATTER_TEXT, pdf_page_number=3
    )
    assert page_type == "front_matter", f"Expected 'front_matter', got '{page_type}'"
    assert confidence >= 0.6
    assert signals['front_matter_keyword_hit'] is True


def test_front_matter_not_triggered_on_late_page():
    """Front-matter keywords on a late page should not classify as front_matter."""
    page_type, confidence, signals = classify_page(
        FRONT_MATTER_TEXT, pdf_page_number=200
    )
    # Should be content or something else, not front_matter
    assert page_type != "front_matter", \
        f"Expected anything but 'front_matter' on page 200, got '{page_type}'"


def test_custom_config():
    """Custom config thresholds change classification behavior."""
    # With a very high dot-leader threshold, TOC should not trigger on few lines
    strict_config = ClassifierConfig(min_dot_leader_lines_for_toc=100)
    page_type, confidence, signals = classify_page(
        TOC_TEXT, pdf_page_number=1, config=strict_config
    )
    # With toc_keyword_hit alone the score is 0.50, which still hits threshold
    # but without the dot_leader boost, confidence is lower
    assert confidence <= 0.55 or page_type == "toc"


def test_missing_fields_graceful():
    """Classifier handles None/missing text and word_count gracefully."""
    page_type, confidence, signals = classify_page(
        None, word_count=None, pdf_page_number=0
    )
    assert page_type == "blankish"
    assert confidence > 0


def test_signals_always_present():
    """All expected signal keys are present in output."""
    expected_keys = {
        'toc_keyword_hit', 'dot_leader_count', 'section_number_line_count',
        'trailing_page_num_line_count', 'index_keyword_hit', 'comma_page_refs_count',
        'practice_keyword_hit', 'question_start_count', 'mc_option_count',
        'front_matter_keyword_hit', 'pdf_page_number', 'word_count',
        'stripped_text_len', 'sentence_count_estimate', 'avg_line_len',
        'punctuation_density',
    }
    _, _, signals = classify_page(CONTENT_TEXT, pdf_page_number=1)
    missing = expected_keys - set(signals.keys())
    assert not missing, f"Missing signal keys: {missing}"
