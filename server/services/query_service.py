"""Non-interactive query service for the API layer."""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is on path
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Searcher cache: keyed by resolved index_root path string
_searcher_cache: Dict[str, object] = {}


def _get_searcher(index_root: str):
    """
    Return a cached TextbookSearchOffline instance.

    Caching avoids reloading ~10MB of TF-IDF data on every request.
    """
    from legacy.textbook_search_offline import TextbookSearchOffline

    key = str(Path(index_root).resolve())
    if key not in _searcher_cache:
        _searcher_cache[key] = TextbookSearchOffline(db_path=index_root)
    return _searcher_cache[key]


def get_catalog(index_root: str) -> Dict:
    """
    Return book catalog: name and chunk count per book.

    Returns:
        {books: [{name, chunk_count}, ...], total_chunks: int}
    """
    searcher = _get_searcher(index_root)
    book_counts: Dict[str, int] = {}
    for meta in searcher.metadatas:
        bk = meta.get('book', 'unknown')
        book_counts[bk] = book_counts.get(bk, 0) + 1
    books = [
        {'name': name, 'chunk_count': count}
        for name, count in sorted(book_counts.items())
    ]
    return {'books': books, 'total_chunks': len(searcher.documents)}


def answer_question_offline(
    question: str,
    *,
    book: Optional[str] = None,
    top_k: int = 5,
    index_root: str = './textbook_index',
    graph_path: Optional[Path] = None,
    save_last_answer: bool = True,
    runtime: Optional[object] = None,
) -> Dict:
    """
    Non-interactive version of TextbookSearchOffline.answer().

    1. Retrieve top_k chunks via TF-IDF search
    2. Compose a structured answer via compose_answer()
    3. Update the graph registry (if graph_path provided)
    4. Save _last_answer.json (if save_last_answer=True)

    Returns:
        {question, answer_dict, retrieved_chunks}
    """
    from legacy.textbook_search_offline import compose_answer

    searcher = _get_searcher(index_root)

    results = searcher.search(
        question, n_results=top_k, book_filter=book,
    )

    if not results:
        empty_answer = {
            'answer': '',
            'key_points': [],
            'citations': [],
            'confidence': {
                'level': 'low',
                'evidence_coverage_score': 0.0,
                'source_diversity_score': 0,
                'redundancy_score': 0.0,
                'contradiction_flag': False,
            },
        }
        return {
            'question': question,
            'answer_dict': empty_answer,
            'retrieved_chunks': [],
        }

    composed = compose_answer(question, results)

    if graph_path is not None and runtime is not None:
        _update_graph(question, composed, results, runtime)
    elif graph_path is not None:
        _update_graph_legacy(question, composed, results, graph_path)

    if save_last_answer:
        _save_last_answer(question, composed, results, Path(index_root))

    retrieved_chunks = [
        {'text': r.get('text', ''), 'metadata': r.get('metadata', r)}
        for r in results[:3]
    ]

    return {
        'question': question,
        'answer_dict': composed,
        'retrieved_chunks': retrieved_chunks,
    }


def _update_graph(
    question: str,
    composed: Dict,
    results: List[Dict],
    runtime: object,
) -> None:
    """Update graph via Runtime (cached, atomic save)."""
    try:
        from graph.models import GraphRegistry, QNode, make_question_id
        from graph.concepts import extract_concepts, make_concept_nodes
        from graph.terminality import compute_terminality

        greg = runtime.get_graph()
        if greg is None:
            greg = GraphRegistry()

        conf = composed.get('confidence', {})
        qid = make_question_id(question)

        g_books: List[str] = []
        g_sections: List[str] = []
        g_chunk_ids: List[str] = []
        for r in results[:3]:
            meta = r.get('metadata', r)
            bk = meta.get('book') or meta.get('book_name', '')
            if bk and bk not in g_books:
                g_books.append(bk)
            sec = meta.get('section') or meta.get('section_number', '')
            if sec and sec not in g_sections:
                g_sections.append(str(sec))
            cid = meta.get('chunk_id', '')
            if cid:
                g_chunk_ids.append(cid)

        qnode = QNode(
            question_id=qid,
            question_text=question,
            citations=g_chunk_ids,
            books=g_books,
            sections=g_sections,
            terminality_score=compute_terminality(conf),
            confidence_snapshot=conf,
        )
        greg.add_qnode(qnode)

        terms = extract_concepts(
            question, composed,
            [{'text': r.get('text', ''), 'metadata': r.get('metadata', r)}
             for r in results[:3]],
        )
        cnodes = make_concept_nodes(terms, g_books, g_sections, qid)
        concept_ids = []
        for cn in cnodes:
            greg.add_concept(cn)
            concept_ids.append(cn.concept_id)
        greg.link_qnode_concepts(qid, concept_ids)

        for i, ca in enumerate(concept_ids):
            for cb in concept_ids[i + 1:]:
                greg.link_concept_cooccurrence(ca, cb)

        runtime.save_graph_atomic(greg)
    except Exception:
        pass  # Non-fatal, matching original behavior


def _update_graph_legacy(
    question: str,
    composed: Dict,
    results: List[Dict],
    graph_path: Path,
) -> None:
    """Fallback when runtime not provided (e.g. direct service calls)."""
    try:
        from graph.models import GraphRegistry, QNode, make_question_id
        from graph.concepts import extract_concepts, make_concept_nodes
        from graph.terminality import compute_terminality

        greg = GraphRegistry()
        greg.load(graph_path)

        conf = composed.get('confidence', {})
        qid = make_question_id(question)

        g_books: List[str] = []
        g_sections: List[str] = []
        g_chunk_ids: List[str] = []
        for r in results[:3]:
            meta = r.get('metadata', r)
            bk = meta.get('book') or meta.get('book_name', '')
            if bk and bk not in g_books:
                g_books.append(bk)
            sec = meta.get('section') or meta.get('section_number', '')
            if sec and sec not in g_sections:
                g_sections.append(str(sec))
            cid = meta.get('chunk_id', '')
            if cid:
                g_chunk_ids.append(cid)

        qnode = QNode(
            question_id=qid,
            question_text=question,
            citations=g_chunk_ids,
            books=g_books,
            sections=g_sections,
            terminality_score=compute_terminality(conf),
            confidence_snapshot=conf,
        )
        greg.add_qnode(qnode)

        terms = extract_concepts(
            question, composed,
            [{'text': r.get('text', ''), 'metadata': r.get('metadata', r)}
             for r in results[:3]],
        )
        cnodes = make_concept_nodes(terms, g_books, g_sections, qid)
        concept_ids = []
        for cn in cnodes:
            greg.add_concept(cn)
            concept_ids.append(cn.concept_id)
        greg.link_qnode_concepts(qid, concept_ids)

        for i, ca in enumerate(concept_ids):
            for cb in concept_ids[i + 1:]:
                greg.link_concept_cooccurrence(ca, cb)

        greg.save(graph_path)
    except Exception:
        pass  # Non-fatal, matching original behavior


def _save_last_answer(
    question: str,
    composed: Dict,
    results: List[Dict],
    index_root: Path,
) -> None:
    """Replicate the _last_answer.json hook from answer() lines 831-847."""
    try:
        last_answer_path = index_root / '_last_answer.json'
        last_answer_data = {
            'question': question,
            'answer_dict': composed,
            'retrieved_chunks': [
                {'text': r.get('text', ''), 'metadata': r.get('metadata', r)}
                for r in results[:3]
            ],
        }
        with open(last_answer_path, 'w', encoding='utf-8') as f:
            json.dump(last_answer_data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # Non-fatal

_index_cache = {}

def _get_search_engine(index_root):
    if index_root not in _index_cache:
        _index_cache[index_root] = build_engine(index_root)
    return _index_cache[index_root]
