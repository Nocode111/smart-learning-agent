from datetime import datetime
from sqlalchemy.orm import Session

from app.models.behavior import LearningBehavior


class BehaviorService:
    def record(
        self, db: Session,
        student_id: int, course_id: int | None, knowledge_point_id: int | None,
        behavior_type: str, content: str | None = None,
        result: str | None = None, duration_seconds: int | None = None,
        source: str | None = None,
    ) -> LearningBehavior:
        behavior = LearningBehavior(
            student_id=student_id,
            course_id=course_id,
            knowledge_point_id=knowledge_point_id,
            behavior_type=behavior_type,
            content=content,
            result=result,
            duration_seconds=duration_seconds,
            source=source,
            created_at=datetime.utcnow(),
        )
        db.add(behavior)
        return behavior

    def get_behaviors(self, db: Session, student_id: int, limit: int = 50) -> list[LearningBehavior]:
        return (
            db.query(LearningBehavior)
            .filter(LearningBehavior.student_id == student_id)
            .order_by(LearningBehavior.created_at.desc())
            .limit(limit)
            .all()
        )


behavior_service = BehaviorService()
