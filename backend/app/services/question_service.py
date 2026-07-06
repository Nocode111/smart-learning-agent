from datetime import datetime
from sqlalchemy.orm import Session

from app.models.question import Question, QuestionAttempt
from app.services.profile_service import profile_service
from app.services.behavior_service import behavior_service
from app.services.recommendation_service import recommendation_service


class QuestionService:
    def get_questions(self, db: Session, course_id: int, knowledge_point_id: int | None = None) -> list[Question]:
        query = db.query(Question).filter(Question.course_id == course_id)
        if knowledge_point_id:
            query = query.filter(Question.knowledge_point_id == knowledge_point_id)
        return query.all()

    def create_question(
        self, db: Session,
        course_id: int, knowledge_point_id: int, question_type: str,
        stem: str, answer: str,
        options_json: dict | None = None, explanation: str | None = None,
        difficulty: int = 1,
    ) -> Question:
        question = Question(
            course_id=course_id,
            knowledge_point_id=knowledge_point_id,
            question_type=question_type,
            stem=stem,
            options_json=options_json,
            answer=answer,
            explanation=explanation,
            difficulty=difficulty,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(question)
        db.commit()
        db.refresh(question)
        return question

    def submit_answer(
        self, db: Session,
        student_id: int, question_id: int, submitted_answer: str,
    ) -> dict:
        question = db.query(Question).filter(Question.id == question_id).first()
        if not question:
            raise ValueError("题目不存在")

        is_correct = (submitted_answer.strip().upper() == question.answer.strip().upper())

        # 记录答题记录
        attempt = QuestionAttempt(
            student_id=student_id,
            question_id=question_id,
            course_id=question.course_id,
            knowledge_point_id=question.knowledge_point_id,
            submitted_answer=submitted_answer,
            is_correct=1 if is_correct else 0,
            created_at=datetime.utcnow(),
        )
        db.add(attempt)

        # 记录行为
        behavior_service.record(
            db=db,
            student_id=student_id,
            course_id=question.course_id,
            knowledge_point_id=question.knowledge_point_id,
            behavior_type="answer_question",
            content=question.stem,
            result="correct" if is_correct else "wrong",
            source="question_page",
        )

        # 更新掌握度
        if is_correct:
            profile_service.increase_correct_count(db, student_id, question.course_id, question.knowledge_point_id)
        else:
            profile_service.increase_wrong_count(db, student_id, question.course_id, question.knowledge_point_id)

        updated = profile_service.refresh_point_mastery(db, student_id, question.course_id, question.knowledge_point_id)

        # 如果薄弱，触发推荐
        if float(updated.mastery_score) < 60:
            recommendation_service.generate_for_weak_point(
                db=db,
                student_id=student_id,
                course_id=question.course_id,
                knowledge_point_id=question.knowledge_point_id,
            )

        db.commit()

        return {
            "is_correct": is_correct,
            "correct_answer": question.answer,
            "explanation": question.explanation,
        }


question_service = QuestionService()
