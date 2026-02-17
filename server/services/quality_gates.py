"""
Quality gates for practice exam generation.

Uses ExamArtifactStats to avoid bad outputs and surface actionable diagnostics.
"""

from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional, Tuple

# Threshold: emit ratio below this triggers 422
INSUFFICIENT_RATIO = 0.5

# Dominance threshold: rejection reason is "dominant" if > this fraction of its category
DOMINANCE_THRESHOLD = 0.4


class InsufficientQualityError(ValueError):
    """Raised when quality gates fail. Maps to HTTP 422."""
    def __init__(self, message: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.detail = detail or {}


def _total_emitted(stats: Any) -> int:
    """Sum emitted across definition, fill_blank, short_answer."""
    if not stats:
        return 0
    total = 0
    for name in ("definition", "fill_blank", "short_answer"):
        obj = getattr(stats, name, None)
        if obj and hasattr(obj, "emitted"):
            total += getattr(obj, "emitted", 0)
    return total


def _rejection_totals(stats: Any) -> Dict[str, int]:
    """Aggregate all rejection counters by reason. No text."""
    if not stats:
        return {}
    totals: Dict[str, int] = {}
    for name, obj in [
        ("def", getattr(stats, "definition", None)),
        ("fib", getattr(stats, "fill_blank", None)),
        ("short", getattr(stats, "short_answer", None)),
    ]:
        if not obj:
            continue
        for f in fields(obj):
            if f.name.startswith("rejected_") or f.name in (
                "no_causal_cue", "meta_text_rejected",
                "split_rejected", "lhs_rejected", "rhs_rejected",
                "prep_rejected", "mid_aux_rejected", "build_question_failed",
                "validation_failed",
            ):
                val = getattr(obj, f.name, 0)
                if isinstance(val, int) and val > 0:
                    key = f"{name}_{f.name}"
                    totals[key] = totals.get(key, 0) + val
    return totals


def _meta_text_total(stats: Any) -> int:
    """Sum of meta_text rejections across stats."""
    if not stats:
        return 0
    total = 0
    if hasattr(stats, "definition") and hasattr(stats.definition, "rejected_meta_text"):
        total += stats.definition.rejected_meta_text
    if hasattr(stats, "short_answer") and hasattr(stats.short_answer, "meta_text_rejected"):
        total += stats.short_answer.meta_text_rejected
    return total


def _no_causal_cue_total(stats: Any) -> int:
    """Short-answer no_causal_cue count."""
    if not stats or not hasattr(stats, "short_answer"):
        return 0
    return getattr(stats.short_answer, "no_causal_cue", 0)


def _short_answer_seen(stats: Any) -> int:
    """Short-answer seen count."""
    if not stats or not hasattr(stats, "short_answer"):
        return 0
    return getattr(stats.short_answer, "seen", 0)


def check_quality_gates(
    artifact_stats: Optional[Any],
    emitted_count: int,
    requested_count: int,
) -> Tuple[bool, Optional[str], Optional[Dict[str, int]]]:
    """
    Check quality gates. Returns (pass, error_message, suggested_distribution).
    If pass is False, error_message is set and suggested_distribution may indicate reallocation.
    """
    if requested_count <= 0:
        return True, None, None

    ratio = emitted_count / requested_count
    if ratio < INSUFFICIENT_RATIO:
        msg = (
            "Insufficient high-quality material; reduce scope or pick different section."
        )
        suggested = None
        if artifact_stats:
            meta = _meta_text_total(artifact_stats)
            no_causal = _no_causal_cue_total(artifact_stats)
            short_seen = _short_answer_seen(artifact_stats)
            if meta > 0 and _rejection_dominates(meta, artifact_stats, "meta_text"):
                msg += " Document appears narrative/meta; try narrower scope."
            if no_causal > 0 and short_seen > 0 and no_causal / max(1, short_seen) >= DOMINANCE_THRESHOLD:
                suggested = _suggested_distribution_no_causal(requested_count)
        return False, msg, suggested

    return True, None, None


def _rejection_dominates(count: int, stats: Any, category: str) -> bool:
    """True if count dominates total rejections in its category."""
    totals = _rejection_totals(stats)
    total = sum(totals.values())
    if total == 0:
        return count > 0
    return count / total >= DOMINANCE_THRESHOLD


def _suggested_distribution_no_causal(total: int) -> Dict[str, int]:
    """Lower short-answer, increase definition/list when no_causal_cue dominates."""
    raw = {
        "definition": max(6, total // 3),
        "fib": max(3, total // 5),
        "tf": max(3, total // 5),
        "short": max(1, total // 10),
        "list": max(4, total // 4),
    }
    s = sum(raw.values())
    if s > total:
        scale = total / s
        raw = {k: max(1, int(v * scale)) for k, v in raw.items()}
        raw["definition"] += total - sum(raw.values())
    return raw


def build_quality_report(artifact_stats: Optional[Any]) -> Dict[str, Any]:
    """
    Debug-only quality report: totals by rejection reason, top reasons, recommended adjustments.
    Deterministic. No text stored.
    """
    if not artifact_stats:
        return {"totals": {}, "top_reasons": [], "recommended_adjustments": []}

    totals = _rejection_totals(artifact_stats)
    top = sorted(
        [(k, v) for k, v in totals.items() if v > 0],
        key=lambda x: -x[1],
    )[:10]
    top_reasons = [{"reason": k, "count": v} for k, v in top]

    adjustments: List[str] = []
    meta = _meta_text_total(artifact_stats)
    no_causal = _no_causal_cue_total(artifact_stats)
    short_seen = _short_answer_seen(artifact_stats)
    total_rej = sum(totals.values())

    if meta > 0 and total_rej > 0 and meta / total_rej >= DOMINANCE_THRESHOLD:
        adjustments.append("meta_text_dominates: document is narrative/meta; try narrower scope")
    if no_causal > 0 and short_seen > 0 and no_causal / max(1, short_seen) >= DOMINANCE_THRESHOLD:
        adjustments.append("no_causal_cue_dominates: lower short-answer count, increase definition/list")

    return {
        "totals": totals,
        "top_reasons": top_reasons,
        "recommended_adjustments": adjustments,
    }
