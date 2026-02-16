"""Learning plan generation from syllabus features (zero-knowledge: no syllabus content)."""

import uuid
from typing import Any, Dict, List

from sqlalchemy.orm import Session as DBSession

from server.db.models import LearningPlan


def generate_plan_from_features(
    db: DBSession,
    user_id: str,
    syllabus_id: str,
    path_id: str,
    features: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate plan from features (topics, weeks, textbooks).
    Does NOT access syllabus content. Returns {plan_id, summary}.
    """
    topics = features.get("topics", [])
    weeks = features.get("weeks", [])
    textbooks = features.get("textbooks", [])

    plan_json = {
        "syllabus_id": syllabus_id,
        "path_id": path_id,
        "topics": topics,
        "weeks": weeks,
        "textbooks": textbooks,
        "modules": [],
    }
    # Simple heuristic: create one module per topic
    for i, t in enumerate(topics[:10]):
        plan_json["modules"].append({
            "id": f"mod-{i}",
            "title": t if isinstance(t, str) else str(t),
            "order": i + 1,
            "prereqs": [],
        })

    plan_id = str(uuid.uuid4())
    row = LearningPlan(
        user_id=user_id,
        plan_id=plan_id,
        path_id=path_id,
        plan_json=plan_json,
    )
    db.add(row)
    db.flush()

    summary = {
        "plan_id": plan_id,
        "path_id": path_id,
        "topic_count": len(topics),
        "week_count": len(weeks),
        "textbook_count": len(textbooks),
    }
    return {"plan_id": plan_id, "summary": summary, "plan_json": plan_json}
