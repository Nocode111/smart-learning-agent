from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Text

from app.database import Base


class AgentPracticeSession(Base):
    __tablename__ = "agent_practice_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    # 目标执行闭环关联字段（文档 Section 6.3）
    goal_id = Column(BigInteger)
    goal_step_id = Column(BigInteger)
    goal_run_id = Column(BigInteger)
    topic = Column(String(255))
    knowledge_point_ids = Column(JSON)
    source_message_id = Column(BigInteger)
    status = Column(String(32), nullable=False, default="active")
    delivery_mode = Column(String(32), nullable=False, default="inline")
    grading_mode = Column(String(32), nullable=False, default="interactive")
    question_count = Column(Integer, nullable=False, default=0)
    answered_count = Column(Integer, nullable=False, default=0)
    correct_count = Column(Integer, nullable=False, default=0)
    current_question_no = Column(Integer)
    include_answer_on_display = Column(Integer, nullable=False, default=0)
    include_explanation_on_display = Column(Integer, nullable=False, default=0)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_agent_practice_session_conversation", "conversation_id"),
        Index("idx_agent_practice_session_student_course", "student_id", "course_id"),
        Index("idx_agent_practice_session_status", "status"),
        Index("idx_agent_practice_session_updated_at", "updated_at"),
    )


class AgentPracticeQuestion(Base):
    __tablename__ = "agent_practice_questions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, nullable=False)
    conversation_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    knowledge_point_id = Column(BigInteger)
    question_no = Column(Integer, nullable=False)
    question_type = Column(String(32), nullable=False, default="single_choice")
    stem = Column(Text, nullable=False)
    options_json = Column(JSON)
    correct_answer = Column(Text, nullable=False)
    explanation = Column(Text)
    difficulty = Column(String(32), nullable=False, default="adaptive")
    source = Column(String(32), nullable=False, default="llm")
    status = Column(String(32), nullable=False, default="unanswered")
    raw_llm_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_practice_question_session", "session_id"),
        Index("idx_practice_question_conversation", "conversation_id"),
        Index("idx_practice_question_kp", "knowledge_point_id"),
    )


class AgentPracticeAttempt(Base):
    __tablename__ = "agent_practice_attempts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, nullable=False)
    question_id = Column(BigInteger, nullable=False)
    conversation_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    question_no = Column(Integer, nullable=False)
    submitted_answer = Column(Text, nullable=False)
    normalized_answer = Column(Text)
    is_correct = Column(Integer, nullable=False, default=0)
    grading_method = Column(String(32), nullable=False, default="rule")
    feedback_text = Column(Text)
    llm_grading_json = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_practice_attempt_session", "session_id"),
        Index("idx_practice_attempt_question", "question_id"),
        Index("idx_practice_attempt_student_course", "student_id", "course_id"),
        Index("idx_practice_attempt_created_at", "created_at"),
    )
