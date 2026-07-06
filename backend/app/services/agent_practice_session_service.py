"""
AgentPracticeSessionService — 对话式练习 Session 核心服务。

职责（文档 Section 10）：
1. 生成对话式练习题
2. 创建 Practice Session
3. 保存 Practice Questions
4. 解析学生答案
5. 批改答案
6. 保存 Practice Attempt
7. 更新 Session 进度
8. 更新学习行为和画像

文档参考：docs/对话式练习Session方案_详细技术实现文档.md Section 10
"""

import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.agent_practice import (
    AgentPracticeSession,
    AgentPracticeQuestion,
    AgentPracticeAttempt,
)
from app.prompts.inline_practice_prompt import (
    INLINE_PRACTICE_SYSTEM_PROMPT,
    INLINE_PRACTICE_USER_PROMPT_TEMPLATE,
    parse_json_object,
    validate_questions,
)
from app.services.qwen_client import qwen_client

logger = logging.getLogger(__name__)

# 中文数字映射（文档 Section 10.3）
CHINESE_NUM_MAP = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                   "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# 答案归一化映射（文档 Section 23.3）
TRUE_NORMALIZE = {"对", "正确", "t", "true", "是", "yes", "y"}
FALSE_NORMALIZE = {"错", "错误", "f", "false", "否", "no", "n"}


class AgentPracticeSessionService:
    """对话式练习 Session 服务"""

    # ================================================================
    # 10.1 create_inline_practice（文档 Section 10.1）
    # ================================================================

    def create_inline_practice(
        self,
        db: Session,
        conversation_id: int,
        student_id: int,
        course_id: int,
        topic: str | None,
        knowledge_point_ids: list[int],
        question_count: int,
        difficulty: str = "adaptive",
        include_answer_on_display: bool = False,
        include_explanation_on_display: bool = False,
    ) -> tuple[AgentPracticeSession, list[AgentPracticeQuestion], list[dict]]:
        """
        创建对话式练习。

        返回：(session, questions, agent_steps)
        """
        # 1. 如果当前 conversation 下存在 active session，先取消旧 session
        existing = self.get_active_session(db, conversation_id, student_id, course_id)
        if existing:
            existing.status = "cancelled"
            existing.updated_at = datetime.utcnow()

        # 2. 获取知识点名称和课程资料
        knowledge_point_names = self._get_knowledge_point_names(db, knowledge_point_ids)
        profile = self._get_student_profile(db, student_id, course_id)
        retrieved_chunks = self._retrieve_course_chunks(db, course_id, topic)

        # 3. 调用 LLM 生成题目 JSON
        user_prompt = INLINE_PRACTICE_USER_PROMPT_TEMPLATE.format(
            question_count=question_count,
            course_id=course_id,
            topic=topic or "通用",
            knowledge_point_names="、".join(knowledge_point_names) if knowledge_point_names else "无",
            profile=json.dumps(profile, ensure_ascii=False),
            retrieved_chunks=json.dumps(retrieved_chunks, ensure_ascii=False),
        )

        llm_messages = [
            {"role": "system", "content": INLINE_PRACTICE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        parsed = None
        last_error = None
        for attempt in range(2):  # 最多重试1次
            try:
                raw_response = qwen_client.chat(
                    messages=llm_messages,
                    temperature=0.3,
                )
                parsed = parse_json_object(raw_response)
                questions_data = parsed.get("questions", [])
                errors = validate_questions(questions_data)
                if not errors:
                    break
                last_error = "; ".join(errors)
                logger.warning("题目校验失败(attempt %d): %s", attempt + 1, last_error)
                # 重试时附加错误信息
                llm_messages.append(
                    {"role": "user", "content": f"上次输出校验失败：{last_error}\n请修正后重新输出严格 JSON。"}
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning("LLM 题目生成失败(attempt %d): %s", attempt + 1, exc)

        if parsed is None or not parsed.get("questions"):
            raise ValueError(f"练习题生成失败：{last_error or 'LLM 未返回有效题目'}")

        questions_data = parsed.get("questions", [])
        # 限制最多 20 题
        questions_data = questions_data[:20]

        # 4. 写入 agent_practice_sessions
        now = datetime.utcnow()
        session = AgentPracticeSession(
            conversation_id=conversation_id,
            student_id=student_id,
            course_id=course_id,
            topic=topic,
            knowledge_point_ids=knowledge_point_ids if knowledge_point_ids else None,
            status="active",
            delivery_mode="inline",
            grading_mode="interactive",
            question_count=len(questions_data),
            answered_count=0,
            correct_count=0,
            current_question_no=1,
            include_answer_on_display=1 if include_answer_on_display else 0,
            include_explanation_on_display=1 if include_explanation_on_display else 0,
            metadata_json={"difficulty": difficulty, "source": "llm"},
            created_at=now,
            updated_at=now,
        )
        db.add(session)
        db.flush()

        # 5. 写入 agent_practice_questions
        db_questions = []
        for q_data in questions_data:
            q_no = q_data.get("question_no", 0)
            question = AgentPracticeQuestion(
                session_id=session.id,
                conversation_id=conversation_id,
                student_id=student_id,
                course_id=course_id,
                knowledge_point_id=knowledge_point_ids[0] if knowledge_point_ids else None,
                question_no=q_no,
                question_type=q_data.get("question_type", "single_choice"),
                stem=q_data.get("stem", ""),
                options_json=q_data.get("options"),
                correct_answer=q_data.get("correct_answer", ""),
                explanation=q_data.get("explanation"),
                difficulty=q_data.get("difficulty", difficulty),
                source="llm",
                status="unanswered",
                raw_llm_json=q_data,
                created_at=now,
                updated_at=now,
            )
            db.add(question)
            db_questions.append(question)

        db.flush()

        # 6. 记录学习行为
        self._record_behavior(
            db, student_id, course_id,
            knowledge_point_ids[0] if knowledge_point_ids else None,
            "generate_inline_practice",
            json.dumps({"session_id": session.id, "question_count": len(questions_data)}, ensure_ascii=False),
            "created",
            "agent_chat",
        )

        # 7. 构建 agent_steps
        agent_steps = [
            {
                "title": "生成对话式练习",
                "detail": f"基于主题「{topic or '通用'}」生成 {len(questions_data)} 道单选题",
                "status": "done",
            },
            {
                "title": "保存练习题目",
                "detail": f"已保存到 Session #{session.id}，等待用户逐题作答",
                "status": "done",
            },
        ]

        return session, db_questions, agent_steps

    # ================================================================
    # 10.2 get_active_session（文档 Section 10.2）
    # ================================================================

    def get_active_session(
        self,
        db: Session,
        conversation_id: int,
        student_id: int,
        course_id: int,
    ) -> AgentPracticeSession | None:
        """获取当前活跃的练习 Session"""
        sessions = (
            db.query(AgentPracticeSession)
            .filter(
                AgentPracticeSession.conversation_id == conversation_id,
                AgentPracticeSession.student_id == student_id,
                AgentPracticeSession.course_id == course_id,
                AgentPracticeSession.status == "active",
                AgentPracticeSession.delivery_mode == "inline",
            )
            .order_by(AgentPracticeSession.updated_at.desc())
            .all()
        )

        if not sessions:
            return None

        # 如果有多个 active session，只取最新的，旧的标记为 cancelled
        if len(sessions) > 1:
            for old in sessions[1:]:
                old.status = "cancelled"
                old.updated_at = datetime.utcnow()
            db.flush()

        # 检查过期（60 分钟无更新，文档 Section 27）
        latest = sessions[0]
        if datetime.utcnow() - latest.updated_at > timedelta(minutes=60):
            latest.status = "expired"
            latest.updated_at = datetime.utcnow()
            db.flush()
            return None

        return latest

    # ================================================================
    # 10.3 parse_answer_reference（文档 Section 10.3）
    # ================================================================

    def parse_answer_reference(
        self,
        message: str,
        current_question_no: int | None = None,
    ) -> dict | None:
        """
        解析用户作答语句。

        返回 {"question_no": int, "submitted_answer": str} 或 None。
        """
        message = (message or "").strip()
        if not message:
            return None

        question_no = None

        # 规则1：用户明确说"第几题"
        # 匹配"第N题" / "第 N 题" / "第N道"
        for pattern in [r"第?\s*(\d+)\s*[题道]", r"第?\s*([一二两三四五六七八九十])\s*[题道]"]:
            match = re.search(pattern, message)
            if match:
                num_str = match.group(1)
                if num_str.isdigit():
                    question_no = int(num_str)
                else:
                    question_no = CHINESE_NUM_MAP.get(num_str)
                break

        # 匹配纯数字开头如 "1 A" / "1. A" / "1、A"
        if question_no is None:
            match = re.match(r"^\s*(\d+)\s*[.、\s]", message)
            if match:
                question_no = int(match.group(1))

        # 规则2：用户只说 A/B/C/D，使用 current_question_no
        if question_no is None:
            question_no = current_question_no

        if question_no is None:
            return None  # 无法确定题号

        # 提取答案
        submitted_answer = None

        # 匹配"选 X" / "选X" / "选择 X"
        for pattern in [r"选\s*([A-Da-d])", r"选\s*择?\s*([A-Da-d])"]:
            match = re.search(pattern, message)
            if match:
                submitted_answer = match.group(1).upper()
                break

        # 匹配"答案是 X"
        if submitted_answer is None:
            match = re.search(r"答案\s*是?\s*([A-Da-d])", message)
            if match:
                submitted_answer = match.group(1).upper()

        # 匹配判断题
        if submitted_answer is None:
            for pattern in TRUE_NORMALIZE:
                if message.strip() == pattern or message.strip().startswith(pattern):
                    submitted_answer = "T"
                    break
            if submitted_answer is None:
                for pattern in FALSE_NORMALIZE:
                    if message.strip() == pattern or message.strip().startswith(pattern):
                        submitted_answer = "F"
                        break

        # 兜底：直接匹配单个 A/B/C/D
        if submitted_answer is None:
            match = re.search(r"\b([A-Da-d])\b", message)
            if match:
                submitted_answer = match.group(1).upper()

        if submitted_answer is None:
            return None  # 无法提取答案

        return {
            "question_no": question_no,
            "submitted_answer": submitted_answer,
        }

    # ================================================================
    # 10.4 grade_answer（文档 Section 10.4）
    # ================================================================

    def grade_answer(
        self,
        db: Session,
        conversation_id: int,
        student_id: int,
        course_id: int,
        message: str,
    ) -> dict:
        """
        批改用户作答。

        返回结构包含 practice_result，供 ToolExecutor 和前端使用。
        """
        # 1. 查 active session
        session = self.get_active_session(db, conversation_id, student_id, course_id)
        if not session:
            return {
                "type": "answer",
                "text": "我没有找到当前正在进行的练习。你可以先让我出几道题，例如：\"帮我出3道关于图的单选题，文字发给我就行\"。",
                "qa_id": None,
                "document": None,
                "agent_steps": [
                    {"title": "查找练习", "detail": "未找到 active practice session", "status": "done"}
                ],
                "retrieved_chunks": [],
                "related_knowledge_point_ids": [],
                "practice_result": None,
                "pending_action_update": None,
                "skip_reply_action_detection": True,
            }

        # 2. 解析用户作答
        parsed = self.parse_answer_reference(message, session.current_question_no)
        if not parsed:
            return {
                "type": "clarification",
                "text": "我无法确定你想回答的是哪一题、选了什么。你可以说\"第一题选 A\"。",
                "qa_id": None,
                "document": None,
                "agent_steps": [
                    {"title": "解析作答", "detail": "无法从用户输入中解析题号和答案", "status": "need_user_input"}
                ],
                "retrieved_chunks": [],
                "related_knowledge_point_ids": [],
                "practice_result": None,
                "pending_action_update": {
                    "type": "inline_practice_waiting_answer",
                    "session_id": session.id,
                    "current_question_no": session.current_question_no,
                    "confirm_action": "grade_practice_answer",
                    "negative_action": "cancel_pending_action",
                    "created_at": datetime.utcnow().isoformat(),
                    "expires_at": (datetime.utcnow() + timedelta(minutes=60)).isoformat(),
                },
                "skip_reply_action_detection": True,
            }

        question_no = parsed["question_no"]
        submitted_answer = parsed["submitted_answer"]

        # 3. 查询对应题目
        question = (
            db.query(AgentPracticeQuestion)
            .filter(
                AgentPracticeQuestion.session_id == session.id,
                AgentPracticeQuestion.question_no == question_no,
            )
            .first()
        )

        if not question:
            return {
                "type": "answer",
                "text": f"我没有找到第 {question_no} 题。当前练习共有 {session.question_count} 道题。",
                "qa_id": None,
                "document": None,
                "agent_steps": [],
                "retrieved_chunks": [],
                "related_knowledge_point_ids": [],
                "practice_result": None,
                "pending_action_update": None,
                "skip_reply_action_detection": True,
            }

        # 4. 按题型批改
        if question.question_type in ("single_choice", "multiple_choice"):
            normalized_answer = submitted_answer.strip().upper()
            correct_answer = (question.correct_answer or "").strip().upper()
            is_correct = normalized_answer == correct_answer
            grading_method = "rule"
            feedback_text = self._build_choice_feedback(
                question, submitted_answer, is_correct
            )

        elif question.question_type == "judge":
            # 判断题归一化
            if submitted_answer.upper() in TRUE_NORMALIZE or submitted_answer in TRUE_NORMALIZE:
                normalized_answer = "T"
            elif submitted_answer.upper() in FALSE_NORMALIZE or submitted_answer in FALSE_NORMALIZE:
                normalized_answer = "F"
            else:
                normalized_answer = submitted_answer
            correct_answer = (question.correct_answer or "").strip().upper()
            is_correct = normalized_answer == correct_answer
            grading_method = "rule"
            feedback_text = self._build_choice_feedback(
                question, submitted_answer, is_correct
            )

        elif question.question_type == "short_answer":
            # 简答题：第一版不自动批改
            normalized_answer = submitted_answer
            is_correct = False
            grading_method = "rule"
            feedback_text = "这类开放题需要我根据要点帮你判断。请等待后续版本支持自动批改。"
        else:
            normalized_answer = submitted_answer
            is_correct = False
            grading_method = "rule"
            feedback_text = f"未知题型 {question.question_type}，请联系老师。"

        # 5. 写入 agent_practice_attempts
        now = datetime.utcnow()
        attempt = AgentPracticeAttempt(
            session_id=session.id,
            question_id=question.id,
            conversation_id=conversation_id,
            student_id=student_id,
            course_id=course_id,
            question_no=question_no,
            submitted_answer=submitted_answer,
            normalized_answer=normalized_answer,
            is_correct=1 if is_correct else 0,
            grading_method=grading_method,
            feedback_text=feedback_text,
            created_at=now,
            updated_at=now,
        )
        db.add(attempt)

        # 6. 更新 question.status
        question.status = "answered"
        question.updated_at = now

        # 7. 更新 session 计数
        session.answered_count = (session.answered_count or 0) + 1
        if is_correct:
            session.correct_count = (session.correct_count or 0) + 1
        session.updated_at = now

        # 8. 判断是否全部答完
        completed = session.answered_count >= session.question_count
        if completed:
            session.status = "completed"
            session.completed_at = now
            session.current_question_no = None
        else:
            # 找到下一道未答的题
            next_no = self._find_next_unanswered(db, session.id, question_no)
            session.current_question_no = next_no

        db.flush()

        # 9. 记录学习行为
        self._record_behavior(
            db, student_id, course_id,
            question.knowledge_point_id,
            "answer_question",
            json.dumps({
                "session_id": session.id,
                "question_id": question.id,
                "question_no": question_no,
                "submitted_answer": submitted_answer,
                "correct_answer": question.correct_answer,
            }, ensure_ascii=False),
            "correct" if is_correct else "wrong",
            "agent_inline_practice",
        )

        # 10. 更新学习画像
        if question.knowledge_point_id:
            try:
                from app.services.profile_service import profile_service
                if is_correct:
                    profile_service.increase_correct_count(db, student_id, course_id, question.knowledge_point_id)
                else:
                    profile_service.increase_wrong_count(db, student_id, course_id, question.knowledge_point_id)
                profile_service.refresh_point_mastery(db, student_id, course_id, question.knowledge_point_id)
            except Exception as exc:
                logger.warning("更新画像失败: %s", exc)

        # 11. 构建返回
        if completed:
            summary = self._build_summary(session)
            text = f"第 {question_no} 题{'正确' if is_correct else '不正确'}。{feedback_text}\n\n{summary}"
            pending_action_update = None
        else:
            text = f"第 {question_no} 题{'正确' if is_correct else '不正确'}。{feedback_text}\n\n你可以继续回答第 {session.current_question_no} 题。"
            pending_action_update = {
                "type": "inline_practice_waiting_answer",
                "session_id": session.id,
                "topic": session.topic,
                "knowledge_point_ids": session.knowledge_point_ids or [],
                "current_question_no": session.current_question_no,
                "confirm_action": "grade_practice_answer",
                "negative_action": "cancel_pending_action",
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(minutes=60)).isoformat(),
            }

        return {
            "type": "answer",
            "text": text,
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {"title": "批改答题", "detail": f"第{question_no}题，用户答案：{submitted_answer}，{'正确' if is_correct else '错误'}", "status": "done"}
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [question.knowledge_point_id] if question.knowledge_point_id else [],
            "practice_result": {
                "session_id": session.id,
                "question_no": question_no,
                "submitted_answer": submitted_answer,
                "normalized_answer": normalized_answer,
                "is_correct": is_correct,
                "correct_answer": question.correct_answer,
                "feedback_text": feedback_text,
                "completed": completed,
            },
            "practice_session": {
                "session_id": session.id,
                "topic": session.topic,
                "status": session.status,
                "question_count": session.question_count,
                "answered_count": session.answered_count,
                "correct_count": session.correct_count,
                "current_question_no": session.current_question_no,
            },
            "pending_action_update": pending_action_update,
            "skip_reply_action_detection": True,
        }

    # ================================================================
    # 10.5 cancel_active_session（文档 Section 14.3）
    # ================================================================

    def cancel_active_session(
        self,
        db: Session,
        conversation_id: int,
        student_id: int,
        course_id: int,
    ) -> AgentPracticeSession | None:
        """取消当前活跃的练习 Session"""
        session = self.get_active_session(db, conversation_id, student_id, course_id)
        if session:
            session.status = "cancelled"
            session.updated_at = datetime.utcnow()
            db.flush()
        return session

    # ================================================================
    # 辅助方法
    # ================================================================

    def _find_next_unanswered(self, db: Session, session_id: int, current_no: int) -> int | None:
        """找到下一道未答的题号"""
        answered_nos = set()
        attempts = (
            db.query(AgentPracticeAttempt)
            .filter(AgentPracticeAttempt.session_id == session_id)
            .all()
        )
        for a in attempts:
            answered_nos.add(a.question_no)

        questions = (
            db.query(AgentPracticeQuestion)
            .filter(AgentPracticeQuestion.session_id == session_id)
            .order_by(AgentPracticeQuestion.question_no)
            .all()
        )
        for q in questions:
            if q.question_no not in answered_nos:
                return q.question_no
        return None

    def _build_choice_feedback(
        self, question: AgentPracticeQuestion, submitted: str, is_correct: bool
    ) -> str:
        """构建选择题批改反馈"""
        if is_correct:
            text = f"你选的是 {submitted}，回答正确！"
        else:
            text = f"你选的是 {submitted}，正确答案是 {question.correct_answer}。"
        if question.explanation:
            text += f"\n\n解析：{question.explanation}"
        return text

    def _build_summary(self, session: AgentPracticeSession) -> str:
        """构建练习完成总结"""
        total = session.question_count
        correct = session.correct_count or 0
        wrong = total - correct
        return (
            f"🎉 这组练习已完成！你一共答对 {correct}/{total} 题。\n"
            + (f"主要薄弱点需要加强复习。" if wrong > 0 else "全部正确，表现很好！")
        )

    def _get_knowledge_point_names(self, db: Session, ids: list[int]) -> list[str]:
        if not ids:
            return []
        from app.models.knowledge_point import KnowledgePoint
        points = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(ids)).all()
        return [p.name for p in points]

    def _get_student_profile(self, db: Session, student_id: int, course_id: int) -> dict:
        try:
            from app.services.profile_service import profile_service
            return profile_service.get_profile_for_agent(db, student_id, course_id)
        except Exception:
            return {"overall_level": "未知"}

    def _retrieve_course_chunks(self, db: Session, course_id: int, topic: str | None) -> list[dict]:
        try:
            from app.services.rag_service import rag_service
            chunks = rag_service.retrieve(
                db=db,
                course_id=course_id,
                query=topic or "",
                top_k=5,
            )
            return [{"text": c.get("text", "")} for c in (chunks or [])]
        except Exception:
            return []

    def _record_behavior(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        knowledge_point_id: int | None,
        behavior_type: str,
        content: str,
        result: str,
        source: str,
    ):
        try:
            from app.models.behavior import LearningBehavior
            behavior = LearningBehavior(
                student_id=student_id,
                course_id=course_id,
                knowledge_point_id=knowledge_point_id,
                behavior_type=behavior_type,
                content=content,
                result=result,
                source=source,
                created_at=datetime.utcnow(),
            )
            db.add(behavior)
        except Exception as exc:
            logger.warning("记录学习行为失败: %s", exc)


agent_practice_session_service = AgentPracticeSessionService()
