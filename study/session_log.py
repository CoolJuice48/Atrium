"""Session logging -- writes a JSONL line after each review session."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def log_session(
    log_path: Path,
    summary: Dict,
    cards_reviewed: List[Dict],
) -> Dict:
    """
    Append a session record to the JSONL log file.

    Args:
        log_path:       Path to the session log file
        summary:        Summary dict from run_review_session
        cards_reviewed: List of per-card dicts with card_id, quality, card_type, book, tags

    Returns:
        The session record dict that was written.
    """
    # Quality histogram
    histogram = {str(q): 0 for q in range(6)}
    books_touched = set()
    tag_counts: Dict[str, int] = {}

    for cr in cards_reviewed:
        q = str(cr.get('quality', 0))
        if q in histogram:
            histogram[q] += 1
        bk = cr.get('book', '')
        if bk:
            books_touched.add(bk)
        for tag in cr.get('tags', []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Weakest tags: tags with lowest average quality
    tag_qualities: Dict[str, List[int]] = {}
    for cr in cards_reviewed:
        q = cr.get('quality', 0)
        for tag in cr.get('tags', []):
            tag_qualities.setdefault(tag, []).append(q)
    weakest_tags = sorted(
        [(t, sum(qs) / len(qs)) for t, qs in tag_qualities.items()],
        key=lambda x: x[1],
    )[:5]

    avg_quality = 0.0
    if cards_reviewed:
        total_q = sum(cr.get('quality', 0) for cr in cards_reviewed)
        avg_quality = round(total_q / len(cards_reviewed), 2)

    record = {
        'timestamp': datetime.now().isoformat(),
        'cards_reviewed': summary.get('reviewed', 0),
        'correct': summary.get('correct', 0),
        'incorrect': summary.get('incorrect', 0),
        'skipped': summary.get('skipped', 0),
        'expanded': summary.get('expanded', 0),
        'remediation_inserted_count': summary.get('remediation_inserted_count', 0),
        'prereq_concepts_used': summary.get('prereq_concepts_used', []),
        'avg_quality': avg_quality,
        'quality_histogram': histogram,
        'books_touched': sorted(books_touched),
        'weakest_tags': weakest_tags,
        'card_details': cards_reviewed,
    }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    return record


def read_session_log(log_path: Path) -> List[Dict]:
    """Read all session records from the log file."""
    records = []
    if not log_path.exists():
        return records
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
