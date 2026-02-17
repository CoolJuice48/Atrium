"""Tests for quality gates."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.services.exam_stats import ExamArtifactStats
from server.services.quality_gates import (
    InsufficientQualityError,
    build_quality_report,
    check_quality_gates,
)


def test_quality_gate_insufficient_candidates():
    """When emitted < requested*0.5, gates fail and suggest 422."""
    stats = ExamArtifactStats()
    stats.definition.emitted = 2
    stats.fill_blank.emitted = 1
    stats.short_answer.emitted = 0
    emitted = 3
    requested = 20
    pass_gates, msg, suggested = check_quality_gates(stats, emitted, requested)
    assert not pass_gates
    assert "Insufficient" in (msg or "")
    assert msg is not None


def test_quality_gate_reallocates_distribution():
    """When no_causal_cue dominates, suggested_distribution lowers short-answer."""
    stats = ExamArtifactStats()
    stats.short_answer.seen = 20
    stats.short_answer.no_causal_cue = 18
    stats.definition.emitted = 2
    stats.fill_blank.emitted = 1
    emitted = 3
    requested = 20
    pass_gates, msg, suggested = check_quality_gates(stats, emitted, requested)
    assert not pass_gates
    assert suggested is not None
    assert suggested.get("short", 0) < suggested.get("definition", 0)
    assert sum(suggested.values()) <= requested + 5


def test_quality_report_has_totals_and_recommendations():
    """build_quality_report returns totals, top_reasons, recommended_adjustments."""
    stats = ExamArtifactStats()
    stats.short_answer.seen = 20
    stats.short_answer.no_causal_cue = 18
    stats.short_answer.meta_text_rejected = 5
    report = build_quality_report(stats)
    assert "totals" in report
    assert "top_reasons" in report
    assert "recommended_adjustments" in report
    assert "no_causal_cue_dominates" in str(report["recommended_adjustments"])
