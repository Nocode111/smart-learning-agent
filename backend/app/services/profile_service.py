from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.profile import StudentProfile, StudentKnowledgeMastery
from app.models.behavior import LearningBehavior
from app.models.knowledge_point import KnowledgePoint


class ProfileService:
    def calculate_mastery_score(self, mastery: StudentKnowledgeMastery) -> float:
        total_answer = mastery.correct_count + mastery.wrong_count
        correct_rate = mastery.correct_count / total_answer if total_answer > 0 else 0.5
        task_score = min(mastery.completed_task_count / 3, 1)
        qa_score = 1 - min(mastery.unresolved_count / max(mastery.ask_count, 1), 1)
        resource_score = min(mastery.resource_view_count / 3, 1)

        score = (
            correct_rate * 50
            + task_score * 20
            + qa_score * 15
            + resource_score * 15
        )
        return round(score, 2)

    def get_status(self, score: float) -> str:
        if score >= 80:
            return "掌握良好"
        if score >= 60:
            return "基本掌握"
        return "薄弱"

    def get_or_create_mastery(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int) -> StudentKnowledgeMastery:
        mastery = (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.knowledge_point_id == knowledge_point_id,
            )
            .first()
        )
        if not mastery:
            mastery = StudentKnowledgeMastery(
                student_id=student_id,
                course_id=course_id,
                knowledge_point_id=knowledge_point_id,
                mastery_score=0,
                updated_at=datetime.utcnow(),
            )
            db.add(mastery)
            db.flush()
        return mastery

    def increase_ask_count(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int):
        mastery = self.get_or_create_mastery(db, student_id, course_id, knowledge_point_id)
        mastery.ask_count += 1
        mastery.updated_at = datetime.utcnow()
        db.flush()

    def increase_correct_count(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int):
        mastery = self.get_or_create_mastery(db, student_id, course_id, knowledge_point_id)
        mastery.correct_count += 1
        mastery.updated_at = datetime.utcnow()
        db.flush()

    def increase_wrong_count(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int):
        mastery = self.get_or_create_mastery(db, student_id, course_id, knowledge_point_id)
        mastery.wrong_count += 1
        mastery.updated_at = datetime.utcnow()
        db.flush()

    def increase_resource_view(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int):
        mastery = self.get_or_create_mastery(db, student_id, course_id, knowledge_point_id)
        mastery.resource_view_count += 1
        mastery.updated_at = datetime.utcnow()
        db.flush()

    def increase_completed_task(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int):
        mastery = self.get_or_create_mastery(db, student_id, course_id, knowledge_point_id)
        mastery.completed_task_count += 1
        mastery.updated_at = datetime.utcnow()
        db.flush()

    def increase_unresolved_count(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int):
        mastery = self.get_or_create_mastery(db, student_id, course_id, knowledge_point_id)
        mastery.unresolved_count += 1
        mastery.updated_at = datetime.utcnow()
        db.flush()

    def refresh_point_mastery(self, db: Session, student_id: int, course_id: int, knowledge_point_id: int) -> StudentKnowledgeMastery:
        mastery = self.get_or_create_mastery(db, student_id, course_id, knowledge_point_id)
        mastery.mastery_score = self.calculate_mastery_score(mastery)
        mastery.updated_at = datetime.utcnow()
        db.flush()
        return mastery

    def get_mastery(self, db: Session, student_id: int, knowledge_point_id: int) -> StudentKnowledgeMastery | None:
        return (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.knowledge_point_id == knowledge_point_id,
            )
            .first()
        )

    def get_all_mastery_for_course(self, db: Session, student_id: int, course_id: int) -> list[StudentKnowledgeMastery]:
        return (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.course_id == course_id,
            )
            .all()
        )

    def get_or_create_profile(self, db: Session, student_id: int, course_id: int) -> StudentProfile:
        profile = (
            db.query(StudentProfile)
            .filter(
                StudentProfile.student_id == student_id,
                StudentProfile.course_id == course_id,
            )
            .first()
        )
        if not profile:
            profile = StudentProfile(
                student_id=student_id,
                course_id=course_id,
                updated_at=datetime.utcnow(),
            )
            db.add(profile)
            db.flush()
        return profile

    def get_weak_points(self, db: Session, student_id: int, course_id: int) -> list[dict]:
        masteries = self.get_all_mastery_for_course(db, student_id, course_id)
        weak = []
        for mastery in masteries:
            score = mastery.mastery_score
            if float(score) < 60:
                point = db.query(KnowledgePoint).filter(KnowledgePoint.id == mastery.knowledge_point_id).first()
                weak.append({
                    "knowledge_point_id": mastery.knowledge_point_id,
                    "name": point.name if point else "未知",
                    "mastery_score": float(score),
                    "status": self.get_status(float(score)),
                    "reason": f"掌握度为 {score}，低于 60",
                })
        return weak

    def get_profile_for_agent(self, db: Session, student_id: int, course_id: int) -> dict:
        profile = self.get_or_create_profile(db, student_id, course_id)
        masteries = self.get_all_mastery_for_course(db, student_id, course_id)
        weak_points = self.get_weak_points(db, student_id, course_id)

        knowledge_mastery = []
        for mastery in masteries:
            point = db.query(KnowledgePoint).filter(KnowledgePoint.id == mastery.knowledge_point_id).first()
            knowledge_mastery.append({
                "knowledge_point_id": mastery.knowledge_point_id,
                "name": point.name if point else "未知",
                "mastery_score": float(mastery.mastery_score),
                "status": self.get_status(float(mastery.mastery_score)),
            })

        return {
            "student_id": student_id,
            "course_id": course_id,
            "overall_level": profile.overall_level or "未知",
            "weak_points": weak_points,
            "knowledge_mastery": knowledge_mastery,
        }

    def update_profile(self, db: Session, student_id: int, course_id: int) -> StudentProfile:
        profile = self.get_or_create_profile(db, student_id, course_id)
        masteries = self.get_all_mastery_for_course(db, student_id, course_id)

        if masteries:
            avg_score = sum(float(m.mastery_score) for m in masteries) / len(masteries)
            if avg_score >= 80:
                profile.overall_level = "掌握良好"
            elif avg_score >= 60:
                profile.overall_level = "基本掌握"
            else:
                profile.overall_level = "基础薄弱"
        else:
            profile.overall_level = "暂无数据"

        weak_points = self.get_weak_points(db, student_id, course_id)
        profile.weak_points_json = weak_points
        profile.updated_at = datetime.utcnow()
        db.flush()
        return profile


profile_service = ProfileService()
