from datetime import datetime
from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint


class KnowledgePointService:
    def get_points(self, db: Session, course_id: int) -> list[KnowledgePoint]:
        return db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id).order_by(KnowledgePoint.sort_order).all()

    def get_point(self, db: Session, point_id: int) -> KnowledgePoint | None:
        return db.query(KnowledgePoint).filter(KnowledgePoint.id == point_id).first()

    def create_point(
        self, db: Session, course_id: int, name: str,
        parent_id: int | None = None, description: str | None = None,
        difficulty: int = 1, sort_order: int = 0,
    ) -> KnowledgePoint:
        point = KnowledgePoint(
            course_id=course_id,
            parent_id=parent_id,
            name=name,
            description=description,
            difficulty=difficulty,
            sort_order=sort_order,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(point)
        db.commit()
        db.refresh(point)
        return point

    def update_point(
        self, db: Session, point_id: int,
        name: str | None = None, description: str | None = None,
        difficulty: int | None = None, sort_order: int | None = None,
    ) -> KnowledgePoint:
        point = db.query(KnowledgePoint).filter(KnowledgePoint.id == point_id).first()
        if not point:
            raise ValueError("知识点不存在")
        if name is not None:
            point.name = name
        if description is not None:
            point.description = description
        if difficulty is not None:
            point.difficulty = difficulty
        if sort_order is not None:
            point.sort_order = sort_order
        point.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(point)
        return point

    def delete_point(self, db: Session, point_id: int):
        point = db.query(KnowledgePoint).filter(KnowledgePoint.id == point_id).first()
        if not point:
            raise ValueError("知识点不存在")
        db.delete(point)
        db.commit()


knowledge_point_service = KnowledgePointService()
