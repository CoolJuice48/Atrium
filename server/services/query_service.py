"""Non-interactive query service for the API layer."""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is on path
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger("atrium.query")


class LibraryUnavailableError(Exception):
    """Raised when library exists but no valid books (all inconsistent)."""


# Searcher cache: keyed by resolved index_root path string
_searcher_cache: Dict[str, object] = {}


def invalidate_searcher_cache(index_root: Optional[str] = None) -> None:
    """Remove cached searcher for index_root, or clear all if index_root is None."""
    if index_root is None:
        _searcher_cache.clear()
        return
    key = str(Path(index_root).resolve())
    _searcher_cache.pop(key, None)


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


def select_candidate_books(question: str, index_root: str) -> List[str]:
    """
    Placeholder: select which books to search for a question.
    Simple heuristic: keyword match on filename/title in library.json; else return all.
    Returns list of book_ids.
    """
    from server.library import load_library, select_candidate_books as _lib_select

    lib = load_library(Path(index_root))
    return _lib_select(question, Path(index_root), lib)


def get_catalog(index_root: str) -> Dict:
    """
    Return book catalog: name and chunk count per book.
    When library.json exists, reads from it (cheap). Else uses TextbookSearchOffline.
    """
    from server.library import load_library

    lib = load_library(Path(index_root))
    if lib:
        ready = [b for b in lib.get("books", []) if b.get("status") == "ready"]
        total_chunks = sum(b.get("chunk_count", 0) for b in ready)
        books = [
            {
                "name": (b.get("title") or b.get("filename") or b.get("book_id", "?")).replace(".pdf", ""),
                "chunk_count": b.get("chunk_count", 0),
            }
            for b in ready
        ]
        return {"books": books, "total_chunks": total_chunks}

    searcher = _get_searcher(index_root)
    book_counts: Dict[str, int] = {}
    for meta in searcher.metadatas:
        bk = meta.get("book", "unknown")
        book_counts[bk] = book_counts.get(bk, 0) + 1
    books = [
        {"name": name, "chunk_count": count}
        for name, count in sorted(book_counts.items())
    ]
    return {"books": books, "total_chunks": len(searcher.documents)}


def answer_question_offline(
    question: str,
    *,
    book: Optional[str] = None,
    top_k: int = 5,
    index_root: str = './textbook_index',
    graph_path: Optional[Path] = None,
    save_last_answer: bool = True,
    runtime: Optional[object] = None,
    settings: Optional[object] = None,
) -> Dict:
    """
    Non-interactive version with relevant-first retrieval.

    1. Verify library consistency (cached); exclude inconsistent books
    2. If library exists but valid_book_ids empty: raise LibraryUnavailableError (503)
    3. select_candidate_books(question) for primary candidates
    4. Primary search restricted to candidates (if non-empty)
    5. If confidence low: expand to all valid books
    6. Enrich results with book_id, title, superseded, lineage
    7. Return meta with search_ms, expanded, expanded_reason, counts

    Returns:
        {question, answer_dict, retrieved_chunks, meta}
    """
    from legacy.textbook_search_offline import compose_answer
    from server.library import (
        load_library,
        verify_library_cached,
        get_book_metadata_map,
        select_candidate_books as _select_candidates,
    )

    min_hits = getattr(settings, 'primary_min_hits', 5) if settings else 5
    min_score = getattr(settings, 'primary_min_top_score', 0.30) if settings else 0.30

    t0 = time.perf_counter()
    index_path = Path(index_root)
    searcher = _get_searcher(index_root)

    book_filter = book
    book_ids: Optional[List[str]] = None
    valid_book_ids: List[str] = []
    candidate_book_ids: List[str] = []
    book_meta_map: Dict[str, Dict] = {}
    expanded = False
    expanded_reason: Optional[str] = None

    lib = load_library(index_path)
    if lib:
        consistency_ok, issues, valid_book_ids = verify_library_cached(index_path, lib)
        if not consistency_ok:
            logger.warning("Library consistency issues: %s", issues)

        # Safety: library exists but no valid books => 503
        if not valid_book_ids:
            raise LibraryUnavailableError(
                "Library exists but no valid books found. Run /index/build or /index/clear."
            )

        book_meta_map = get_book_metadata_map(lib)

        if not book_filter:
            candidates = _select_candidates(question, index_path, lib)
            candidate_book_ids = list(set(candidates) & set(valid_book_ids))
            if candidate_book_ids:
                book_ids = candidate_book_ids

    # Primary search
    if book_filter:
        results = searcher.search(question, n_results=top_k, book_filter=book_filter)
    elif book_ids:
        results = searcher.search(question, n_results=top_k, book_ids=book_ids)
    else:
        results = searcher.search(question, n_results=top_k)

    primary_hits = len(results)
    primary_top_score = float(results[0]["similarity"]) if results else 0.0

    # Confidence check: expand if hits < min or top_score < threshold
    if (
        lib
        and valid_book_ids
        and book_ids
        and len(book_ids) < len(valid_book_ids)
        and (primary_hits < min_hits or primary_top_score < min_score)
    ):
        expanded = True
        expanded_reason = "low_hits" if primary_hits < min_hits else "low_score"
        results = searcher.search(question, n_results=top_k, book_ids=valid_book_ids)
    elif not book_ids and lib and valid_book_ids:
        expanded_reason = "no_candidates"
    elif book_ids and len(book_ids) == len(valid_book_ids) and lib:
        expanded_reason = "forced_all"

    search_ms = int((time.perf_counter() - t0) * 1000)

    meta = {
        "search_ms": search_ms,
        "expanded": expanded,
        "candidate_book_ids_count": len(candidate_book_ids),
        "valid_book_ids_count": len(valid_book_ids),
        "primary_hits": primary_hits,
        "primary_top_score": primary_top_score,
        "expanded_reason": expanded_reason,
    }

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
            'meta': meta,
        }

    composed = compose_answer(question, results)

    if graph_path is not None and runtime is not None:
        _update_graph(question, composed, results, runtime)
    elif graph_path is not None:
        _update_graph_legacy(question, composed, results, graph_path)

    if save_last_answer:
        _save_last_answer(question, composed, results, index_path)

    # Enrich retrieved_chunks with book_id, title, superseded, lineage
    enriched = []
    for r in results[:3]:
        meta_dict = dict(r.get('metadata', r))
        bid = meta_dict.get('book_id')
        if bid and bid in book_meta_map:
            bm = book_meta_map[bid]
            meta_dict['book_id'] = bid
            meta_dict['title'] = bm.get('title', meta_dict.get('book', ''))
            meta_dict['superseded'] = bm.get('superseded', False)
            meta_dict['supersedes'] = bm.get('supersedes', [])
            meta_dict['superseded_by'] = bm.get('superseded_by', [])
        enriched.append({'text': r.get('text', ''), 'metadata': meta_dict})

    return {
        'question': question,
        'answer_dict': composed,
        'retrieved_chunks': enriched,
        'meta': meta,
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
