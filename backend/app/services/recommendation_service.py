from datetime import datetime

from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint
from app.models.profile import StudentKnowledgeMastery
from app.models.question import Question
from app.models.recommendation import RecommendationPlan, RecommendationTask
from app.models.resource import LearningResource
from app.services.behavior_service import behavior_service
from app.services.profile_service import profile_service


class RecommendationService:
    def generate_for_weak_point(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        knowledge_point_id: int,
    ) -> RecommendationPlan | None:
        point = db.query(KnowledgePoint).filter(KnowledgePoint.id == knowledge_point_id).first()
        if not point:
            return None

        mastery = (
            db.query(StudentKnowledgeMastery)
            .filter(
                StudentKnowledgeMastery.student_id == student_id,
                StudentKnowledgeMastery.knowledge_point_id == knowledge_point_id,
            )
            .first()
        )

        existing = self.get_pending_plan(db, student_id, course_id, knowledge_point_id)
        if existing:
            return existing

        score = float(mastery.mastery_score) if mastery else 0

        plan = RecommendationPlan(
            student_id=student_id,
            course_id=course_id,
            title=f"{point.name}专项巩固计划",
            reason=f"系统检测到你在「{point.name}」上的掌握度为 {score}，建议优先复习。",
            status="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(plan)
        db.flush()

        resource = (
            db.query(LearningResource)
            .filter(
                LearningResource.course_id == course_id,
                LearningResource.knowledge_point_id == knowledge_point_id,
            )
            .first()
        )
        if resource:
            db.add(
                RecommendationTask(
                    plan_id=plan.id,
                    task_type="resource",
                    title=f"阅读资源：{resource.title}",
                    target_id=resource.id,
                    estimated_minutes=8,
                    status="pending",
                    created_at=datetime.utcnow(),
                )
            )

        question_count = (
            db.query(Question)
            .filter(
                Question.course_id == course_id,
                Question.knowledge_point_id == knowledge_point_id,
            )
            .count()
        )
        if question_count:
            db.add(
                RecommendationTask(
                    plan_id=plan.id,
                    task_type="practice",
                    title=f"完成 {point.name} 基础练习",
                    target_id=knowledge_point_id,
                    estimated_minutes=15,
                    status="pending",
                    created_at=datetime.utcnow(),
                )
            )

        db.add(
            RecommendationTask(
                plan_id=plan.id,
                task_type="qa",
                title=f"向 AI 复述你对 {point.name} 的理解",
                target_id=knowledge_point_id,
                estimated_minutes=5,
                status="pending",
                created_at=datetime.utcnow(),
            )
        )

        db.flush()
        return plan

    def get_plans(self, db: Session, student_id: int, course_id: int) -> list[RecommendationPlan]:
        return (
            db.query(RecommendationPlan)
            .filter(
                RecommendationPlan.student_id == student_id,
                RecommendationPlan.course_id == course_id,
            )
            .order_by(RecommendationPlan.created_at.desc())
            .all()
        )

    def get_tasks(self, db: Session, plan_id: int) -> list[RecommendationTask]:
        return db.query(RecommendationTask).filter(RecommendationTask.plan_id == plan_id).all()

    def complete_task(self, db: Session, task_id: int) -> RecommendationTask:
        task = db.query(RecommendationTask).filter(RecommendationTask.id == task_id).first()
        if not task:
            raise ValueError("任务不存在")

        task.status = "completed"
        task.completed_at = datetime.utcnow()
        db.flush()

        plan = db.query(RecommendationPlan).filter(RecommendationPlan.id == task.plan_id).first()
        if plan:
            knowledge_point_id = self.resolve_task_knowledge_point(db, task)
            behavior_service.record(
                db=db,
                student_id=plan.student_id,
                course_id=plan.course_id,
                knowledge_point_id=knowledge_point_id,
                behavior_type="complete_task",
                content=task.title,
                result="completed",
                source="recommendation_page",
            )
            if knowledge_point_id:
                profile_service.increase_completed_task(db, plan.student_id, plan.course_id, knowledge_point_id)
                profile_service.refresh_point_mastery(db, plan.student_id, plan.course_id, knowledge_point_id)

            pending_tasks = (
                db.query(RecommendationTask)
                .filter(
                    RecommendationTask.plan_id == plan.id,
                    RecommendationTask.status == "pending",
                )
                .count()
            )
            if pending_tasks == 0:
                plan.status = "completed"
                plan.updated_at = datetime.utcnow()
                db.flush()

        return task

    def resolve_task_knowledge_point(self, db: Session, task: RecommendationTask) -> int | None:
        if task.task_type in ("practice", "qa", "review") and task.target_id:
            return int(task.target_id)
        if task.task_type == "resource" and task.target_id:
            resource = db.query(LearningResource).filter(LearningResource.id == task.target_id).first()
            return resource.knowledge_point_id if resource else None
        return None

    def get_pending_plan(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        knowledge_point_id: int,
    ) -> RecommendationPlan | None:
        return (
            db.query(RecommendationPlan)
            .join(RecommendationTask, RecommendationTask.plan_id == RecommendationPlan.id)
            .filter(
                RecommendationPlan.student_id == student_id,
                RecommendationPlan.course_id == course_id,
                RecommendationPlan.status == "pending",
                RecommendationTask.target_id == knowledge_point_id,
            )
            .first()
        )


recommendation_service = RecommendationService()
