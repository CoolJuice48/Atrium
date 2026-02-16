"""Evaluation service wrapper -- delegates to eval.evaluator.run_eval."""

import sys
from pathlib import Path
from typing import Dict

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from eval.evaluator import run_eval


def run_evaluation(
    golden_path: Path,
    index_root: str,
    top_k: int = 10,
) -> Dict:
    """
    Run the evaluation harness over a golden set file.

    Args:
        golden_path:  Absolute path to a golden set JSONL file.
        index_root:   Path to the textbook_index directory.
        top_k:        Number of chunks to retrieve per question.

    Returns:
        {summary: {...}, per_question: [...]}
    """
    return run_eval(golden_path, index_root=index_root, top_k=top_k)
