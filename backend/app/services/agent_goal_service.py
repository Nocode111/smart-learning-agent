"""
长期目标服务（文档 Section 8 + 执行闭环增强 Section 9.1）

职责：
1. 创建长期学习目标
2. 目标列表查询
3. 目标详情（含步骤和复盘，增强版返回 latest_run/latest_reflection/output_ref）
4. 目标状态管理：暂停/恢复/取消/完成
5. 进度计算
6. 权限校验
7. 步骤 run 历史查询
8. run 详情聚合查询
9. 补救步骤插入
"""

import logging
import re
from datetime import date, datetime

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun, AgentGoalReflection

logger = logging.getLogger(__name__)


_INTERNAL_LABELS = {
    "diagnostic_quiz": "诊断测验",
    "qa_explanation": "知识讲解",
    "inline_practice": "对话练习",
    "exercise_document": "练习文档",
    "review_summary": "阶段总结",
    "recommendation_sync": "推荐同步",
    "profile_check": "画像检查",
    "manual_task": "线下任务",
    "qa_answer": "知识讲解",
    "generate_inline_practice": "对话练习",
    "generate_exercise_document": "练习文档",
}


class AgentGoalService:
    """长期目标 CRUD 服务"""

    # ── 权限辅助 ──────────────────────────────────────────────

    @staticmethod
    def _get_goal_for_user(db: Session, goal_id: int, student_id: int) -> AgentLearningGoal:
        """查询目标并校验所有者（文档 Section 15）"""
        goal = db.query(AgentLearningGoal).filter(
            AgentLearningGoal.id == goal_id
        ).first()
        if not goal:
            raise ValueError("目标不存在")
        if goal.student_id != student_id:
            raise ValueError("无权访问该目标")
        return goal

    # ── 8.1 创建目标 ──────────────────────────────────────────

    def create_goal(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        goal_text: str,
        title: str | None = None,
        target_score: float | None = 80,
        target_knowledge_point_ids: list[int] | None = None,
        due_date: date | None = None,
    ) -> dict:
        """创建长期学习目标"""
        from app.services.profile_service import profile_service

        # 自动生成标题
        if not title:
            title = goal_text[:80] if len(goal_text) > 80 else goal_text

        # 读取当前画像分数作为 current_score
        current_score = None
        try:
            profile = profile_service.get_profile_for_agent(db, student_id, course_id)
            masteries = profile.get("knowledge_mastery", [])
            target_ids = target_knowledge_point_ids or []
            if target_ids and masteries:
                target_masteries = [
                    m for m in masteries
                    if m.get("knowledge_point_id") in target_ids
                ]
                if target_masteries:
                    current_score = sum(m["mastery_score"] for m in target_masteries) / len(target_masteries)
                else:
                    current_score = profile.get("overall_level_score")
            else:
                if masteries:
                    current_score = sum(m["mastery_score"] for m in masteries) / len(masteries)
        except Exception:
            logger.debug("读取画像分数失败，跳过 current_score", exc_info=True)

        goal = AgentLearningGoal(
            student_id=student_id,
            course_id=course_id,
            title=title,
            goal_text=goal_text,
            target_score=target_score,
            current_score=current_score,
            progress_percent=0,
            target_knowledge_point_ids=target_knowledge_point_ids or [],
            start_date=date.today(),
            due_date=due_date,
            status="draft",
            planning_status="none",
        )
        db.add(goal)
        db.flush()
        db.commit()
        db.refresh(goal)

        # 自动创建守护配置（文档 Section 19）
        try:
            from app.services.agent_goal_guardian_service import agent_goal_guardian_service
            agent_goal_guardian_service.ensure_config_for_goal(db, goal)
        except Exception:
            logger.debug("创建守护配置失败，不阻塞目标创建", exc_info=True)

        logger.info("创建长期目标 goal_id=%s student_id=%s course_id=%s", goal.id, student_id, course_id)

        return self._serialize_goal(goal)

    # ── 8.2 目标列表 ──────────────────────────────────────────

    def list_goals(
        self,
        db: Session,
        student_id: int,
        course_id: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """查询当前用户的目标列表，按 updated_at desc"""
        query = db.query(AgentLearningGoal).filter(
            AgentLearningGoal.student_id == student_id
        )
        if course_id:
            query = query.filter(AgentLearningGoal.course_id == course_id)
        if status:
            query = query.filter(AgentLearningGoal.status == status)

        goals = query.order_by(desc(AgentLearningGoal.updated_at)).all()
        return [self._serialize_goal(g) for g in goals]

    # ── 8.3 目标详情（增强版 — 文档 Section 9.1） ────────────

    def get_goal_detail(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
    ) -> dict:
        """
        目标详情（含步骤和最近复盘）。

        增强：每个 step 附加 latest_run、latest_reflection、output_ref。
        """
        goal = self._get_goal_for_user(db, goal_id, student_id)

        steps = (
            db.query(AgentGoalStep)
            .filter(AgentGoalStep.goal_id == goal_id)
            .order_by(AgentGoalStep.step_order)
            .all()
        )

        # 最近复盘，按步骤聚合（取每个步骤的最新复盘）
        latest_reflections = (
            db.query(AgentGoalReflection)
            .filter(
                AgentGoalReflection.goal_id == goal_id,
                AgentGoalReflection.student_id == student_id,
            )
            .order_by(desc(AgentGoalReflection.created_at))
            .limit(20)
            .all()
        )

        # 聚合最近一次推进记录和当前动作建议（文档 Section 15 任务 F）
        current_agent_action = None
        latest_advance_cycle = None

        try:
            from app.models.agent_goal_advance import AgentGoalAdvanceCycle

            latest_cycle = (
                db.query(AgentGoalAdvanceCycle)
                .filter(AgentGoalAdvanceCycle.goal_id == goal_id)
                .order_by(desc(AgentGoalAdvanceCycle.started_at))
                .first()
            )

            if latest_cycle:
                from app.services.agent_goal_advance_service import agent_goal_advance_service

                latest_advance_cycle = agent_goal_advance_service._serialize_cycle(latest_cycle)

                # 构建当前建议动作
                if latest_cycle.action_required:
                    current_agent_action = {
                        "action_type": latest_cycle.action_type,
                        "message": goal.last_agent_summary or latest_cycle.result_summary or "",
                        "payload": latest_cycle.action_payload_json or {},
                    }
        except Exception:
            logger.debug("聚合推进记录失败", exc_info=True)

        return {
            "goal": self._serialize_goal(goal),
            "plan_summary": self._clean_user_facing_text(goal.plan_summary),
            "steps": [self._serialize_step_enhanced(db, s) for s in steps],
            "latest_reflections": [self._serialize_reflection(r) for r in latest_reflections],
            "current_agent_action": current_agent_action,
            "latest_advance_cycle": latest_advance_cycle,
        }

    # ── 步骤 run 历史（文档 Section 8.1） ─────────────────────

    def get_step_runs(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
    ) -> list[dict]:
        """查询某步骤的所有执行历史"""
        self._get_goal_for_user(db, goal_id, student_id)

        step = db.query(AgentGoalStep).filter(
            AgentGoalStep.id == step_id,
            AgentGoalStep.goal_id == goal_id,
        ).first()
        if not step:
            raise ValueError("步骤不存在")

        runs = (
            db.query(AgentGoalRun)
            .filter(
                AgentGoalRun.goal_id == goal_id,
                AgentGoalRun.step_id == step_id,
            )
            .order_by(desc(AgentGoalRun.started_at))
            .all()
        )

        return [self.serialize_run(r) for r in runs]

    # ── Run 详情（文档 Section 8.2） ──────────────────────────

    def get_run_detail(
        self,
        db: Session,
        goal_id: int,
        run_id: int,
        student_id: int,
    ) -> dict:
        """
        获取单次执行的完整详情。
        聚合 run、step、qa、practice、document、reflection。
        """
        self._get_goal_for_user(db, goal_id, student_id)

        run = db.query(AgentGoalRun).filter(
            AgentGoalRun.id == run_id,
            AgentGoalRun.goal_id == goal_id,
        ).first()
        if not run:
            raise ValueError("执行记录不存在")

        step = db.query(AgentGoalStep).filter(
            AgentGoalStep.id == run.step_id,
        ).first()

        # 最近一次复盘
        reflection = (
            db.query(AgentGoalReflection)
            .filter(
                AgentGoalReflection.run_id == run_id,
                AgentGoalReflection.student_id == student_id,
            )
            .order_by(desc(AgentGoalReflection.created_at))
            .first()
        )

        # 聚合 QA
        qa = None
        if run.qa_id:
            from app.models.qa_record import QARecord
            qa_row = db.query(QARecord).filter(QARecord.id == run.qa_id).first()
            if qa_row:
                qa = {
                    "id": qa_row.id,
                    "question": qa_row.question,
                    "answer": qa_row.answer,
                    "related_knowledge_points": qa_row.related_knowledge_points or [],
                }

        # 聚合练习 session
        practice = None
        if run.practice_session_id:
            from app.models.agent_practice import AgentPracticeSession
            ps = db.query(AgentPracticeSession).filter(
                AgentPracticeSession.id == run.practice_session_id
            ).first()
            if ps:
                practice = {
                    "id": ps.id,
                    "status": ps.status,
                    "topic": ps.topic,
                    "question_count": ps.question_count,
                    "answered_count": ps.answered_count,
                    "correct_count": ps.correct_count,
                }

        # 聚合练习文档
        document = None
        if run.generated_document_id:
            from app.models.generated_exercise_document import GeneratedExerciseDocument
            doc = db.query(GeneratedExerciseDocument).filter(
                GeneratedExerciseDocument.id == run.generated_document_id
            ).first()
            if doc:
                document = {
                    "id": doc.id,
                    "title": getattr(doc, "title", ""),
                    "status": getattr(doc, "status", "completed"),
                    "file_name": getattr(doc, "file_name", ""),
                    "preview_content": getattr(doc, "preview_content", ""),
                    "download_url": f"/api/exercise-generation/{doc.id}/download",
                }

        return self.serialize_run_detail(
            run=run,
            step=step,
            reflection=reflection,
            qa=qa,
            practice=practice,
            document=document,
        )

    # ── 插入补救步骤（文档 Section 8.5 & 15） ─────────────────

    def insert_remedial_step(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        after_step_id: int,
        title: str,
        description: str | None = None,
        step_type: str = "qa_explanation",
        tool_name: str = "qa_answer",
        tool_args: dict | None = None,
        target_knowledge_point_ids: list[int] | None = None,
    ) -> dict:
        """手动插入补救步骤"""
        goal = self._get_goal_for_user(db, goal_id, student_id)

        if goal.status in ("completed", "canceled"):
            raise ValueError(f"目标状态为 {goal.status}，不能插入步骤")

        # 找到当前最大 step_order
        max_order = (
            db.query(AgentGoalStep.step_order)
            .filter(AgentGoalStep.goal_id == goal_id)
            .order_by(AgentGoalStep.step_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else 1

        step = AgentGoalStep(
            goal_id=goal_id,
            student_id=student_id,
            course_id=goal.course_id,
            step_order=next_order,
            title=title,
            description=description,
            step_type=step_type,
            tool_name=tool_name,
            tool_args_json=tool_args or {},
            expected_outcome="补救步骤 — 补充学习",
            target_knowledge_point_ids=target_knowledge_point_ids or [],
            status="pending",
            metadata_json={
                "source": "manual_remedial",
                "after_step_id": after_step_id,
            },
        )
        db.add(step)
        db.flush()
        db.commit()
        db.refresh(step)

        # 更新进度（增加步骤后进度可能下降）
        progress = self.recalculate_progress(db, goal_id)
        goal.progress_percent = progress
        db.commit()

        logger.info("手动插入补救步骤 goal_id=%s step_id=%s title=%s", goal_id, step.id, title)

        return self._serialize_step_enhanced(db, step)

    # ── 8.7 暂停/恢复/取消/完成 ───────────────────────────────

    def pause_goal(self, db: Session, goal_id: int, student_id: int) -> dict:
        """暂停目标"""
        goal = self._get_goal_for_user(db, goal_id, student_id)
        if goal.status != "active":
            raise ValueError("只能暂停进行中的目标")
        goal.status = "paused"
        goal.paused_at = datetime.utcnow()
        db.commit()
        logger.info("目标已暂停 goal_id=%s", goal_id)
        return {"id": goal.id, "status": goal.status, "message": "目标已暂停"}

    def resume_goal(self, db: Session, goal_id: int, student_id: int) -> dict:
        """恢复目标"""
        goal = self._get_goal_for_user(db, goal_id, student_id)
        if goal.status != "paused":
            raise ValueError("只能恢复已暂停的目标")
        goal.status = "active"
        goal.paused_at = None
        db.commit()
        logger.info("目标已恢复 goal_id=%s", goal_id)
        return {"id": goal.id, "status": goal.status, "message": "目标已恢复"}

    def cancel_goal(self, db: Session, goal_id: int, student_id: int) -> dict:
        """取消目标"""
        goal = self._get_goal_for_user(db, goal_id, student_id)
        if goal.status in ("completed", "canceled"):
            raise ValueError("该目标已经结束，不能取消")
        goal.status = "canceled"
        goal.canceled_at = datetime.utcnow()
        db.commit()
        logger.info("目标已取消 goal_id=%s", goal_id)
        return {"id": goal.id, "status": goal.status, "message": "目标已取消"}

    def complete_goal(self, db: Session, goal_id: int, student_id: int) -> dict:
        """手动标记目标完成"""
        goal = self._get_goal_for_user(db, goal_id, student_id)
        if goal.status not in ("active", "paused"):
            raise ValueError("只有进行中或已暂停的目标可以标记完成")
        goal.status = "completed"
        goal.progress_percent = 100
        goal.completed_at = datetime.utcnow()
        db.commit()
        logger.info("目标已手动完成 goal_id=%s", goal_id)
        return {"id": goal.id, "status": goal.status, "message": "目标已标记为完成"}

    # ── 进度计算（文档 Section 12） ───────────────────────────

    @staticmethod
    def recalculate_progress(db: Session, goal_id: int) -> float:
        """
        重新计算目标进度。
        progress_percent = completed_steps / total_steps * 100
        """
        total = db.query(AgentGoalStep).filter(
            AgentGoalStep.goal_id == goal_id
        ).count()

        if total == 0:
            return 0

        completed = db.query(AgentGoalStep).filter(
            AgentGoalStep.goal_id == goal_id,
            AgentGoalStep.status == "completed",
        ).count()

        return round(completed / total * 100, 2)

    # ── 检查目标是否可自动完成 ────────────────────────────────

    @staticmethod
    def check_goal_completion(db: Session, goal_id: int) -> bool:
        """
        检查目标是否所有必要步骤已完成。
        如果全部完成，自动标记目标为 completed。
        返回 True 表示目标已完成。
        """
        goal = db.query(AgentLearningGoal).filter(
            AgentLearningGoal.id == goal_id
        ).first()
        if not goal:
            return False

        steps = db.query(AgentGoalStep).filter(
            AgentGoalStep.goal_id == goal_id
        ).all()

        if not steps:
            return False

        all_done = all(
            s.status in ("completed", "skipped")
            for s in steps
        )
        if all_done:
            goal.status = "completed"
            goal.progress_percent = 100
            goal.completed_at = datetime.utcnow()
            db.commit()
            logger.info("目标自动完成 goal_id=%s", goal_id)
            return True

        return False

    # ── 序列化辅助 ────────────────────────────────────────────

    @staticmethod
    def _serialize_goal(goal: AgentLearningGoal) -> dict:
        """序列化目标为字典"""
        return {
            "id": goal.id,
            "course_id": goal.course_id,
            "title": goal.title,
            "goal_text": goal.goal_text,
            "target_score": float(goal.target_score) if goal.target_score else None,
            "current_score": float(goal.current_score) if goal.current_score else None,
            "progress_percent": float(goal.progress_percent),
            "status": goal.status,
            "planning_status": goal.planning_status,
            "plan_summary": AgentGoalService._clean_user_facing_text(goal.plan_summary),
            "due_date": goal.due_date,
            "created_at": goal.created_at,
            "updated_at": goal.updated_at,
        }

    @staticmethod
    def _serialize_step(step: AgentGoalStep) -> dict:
        """序列化步骤为字典（基础版）"""
        return {
            "id": step.id,
            "goal_id": step.goal_id,
            "step_order": step.step_order,
            "title": step.title,
            "description": step.description,
            "step_type": step.step_type,
            "tool_name": step.tool_name,
            "expected_outcome": step.expected_outcome,
            "status": step.status,
            "retry_count": step.retry_count,
            "max_retries": step.max_retries,
            "result_summary": step.result_summary,
            "estimated_minutes": step.estimated_minutes,
            "last_error": step.last_error,
            # 增强字段
            "output_type": step.output_type,
            "output_ref": step.output_ref_json,
            "needs_user_action": bool(step.needs_user_action),
            "user_action_type": step.user_action_type,
            "user_action_status": step.user_action_status,
        }

    @staticmethod
    def _serialize_step_enhanced(db: Session, step: AgentGoalStep) -> dict:
        """序列化步骤为字典（增强版，含 latest_run 和 latest_reflection）"""
        result = {
            "id": step.id,
            "goal_id": step.goal_id,
            "step_order": step.step_order,
            "title": step.title,
            "description": step.description,
            "step_type": step.step_type,
            "tool_name": step.tool_name,
            "expected_outcome": step.expected_outcome,
            "status": step.status,
            "retry_count": step.retry_count,
            "max_retries": step.max_retries,
            "result_summary": step.result_summary,
            "estimated_minutes": step.estimated_minutes,
            "last_error": step.last_error,
            "output_type": step.output_type,
            "output_ref": step.output_ref_json,
            "needs_user_action": bool(step.needs_user_action),
            "user_action_type": step.user_action_type,
            "user_action_status": step.user_action_status,
            "latest_run": None,
            "latest_reflection": None,
        }

        # 最新 run
        candidate_runs = (
            db.query(AgentGoalRun)
            .filter(
                AgentGoalRun.goal_id == step.goal_id,
                AgentGoalRun.step_id == step.id,
            )
            .order_by(desc(AgentGoalRun.started_at))
            .limit(5)
            .all()
        )
        latest_run = None
        for candidate in candidate_runs:
            inferred_type, inferred_ref = AgentGoalService._infer_run_output(candidate)
            if inferred_type or candidate.qa_id or candidate.practice_session_id or candidate.generated_document_id:
                latest_run = candidate
                break
        if latest_run is None and candidate_runs:
            latest_run = candidate_runs[0]

        if latest_run:
            result["latest_run"] = AgentGoalService.serialize_run(latest_run)
            inferred_type, inferred_ref = AgentGoalService._infer_run_output(latest_run)
            if not result["output_type"] and inferred_type:
                result["output_type"] = inferred_type
            if not result["output_ref"] and inferred_ref:
                result["output_ref"] = inferred_ref
            if result["output_type"] == "practice_session" and result["output_ref"]:
                result["needs_user_action"] = True
                result["user_action_type"] = result["user_action_type"] or "answer_practice"
                result["user_action_status"] = result["user_action_status"] or latest_run.user_action_status or "pending"
            elif result["output_type"] == "document" and result["output_ref"]:
                result["needs_user_action"] = True
                result["user_action_type"] = result["user_action_type"] or "read_document"
                result["user_action_status"] = result["user_action_status"] or latest_run.user_action_status or "pending"

        # 最新 reflection
        latest_ref = (
            db.query(AgentGoalReflection)
            .filter(
                AgentGoalReflection.goal_id == step.goal_id,
                AgentGoalReflection.step_id == step.id,
            )
            .order_by(desc(AgentGoalReflection.created_at))
            .first()
        )
        if latest_ref:
            result["latest_reflection"] = AgentGoalService._serialize_reflection(latest_ref)

        return result

    @staticmethod
    def _serialize_reflection(reflection: AgentGoalReflection) -> dict:
        """序列化复盘为字典"""
        if not reflection:
            return None
        return {
            "id": reflection.id,
            "goal_id": reflection.goal_id,
            "step_id": reflection.step_id,
            "run_id": reflection.run_id,
            "reflection_type": reflection.reflection_type,
            "is_success": bool(reflection.is_success),
            "quality_score": float(reflection.quality_score) if reflection.quality_score else None,
            "summary": reflection.summary,
            "issues_json": reflection.issues_json or [],
            "next_action": reflection.next_action,
            "suggested_new_steps_json": reflection.suggested_new_steps_json or [],
            "applied_action_status": reflection.applied_action_status,
            "applied_action_message": reflection.applied_action_message,
            "created_at": reflection.created_at,
        }

    @staticmethod
    def serialize_run(run: AgentGoalRun) -> dict:
        """序列化 run 为列表项字典（文档 Section 9.1）"""
        output_type, output_ref = AgentGoalService._infer_run_output(run)
        return {
            "id": run.id,
            "run_uuid": run.run_uuid,
            "status": run.status,
            "tool_name": run.tool_name,
            "output_type": output_type,
            "output_ref": output_ref,
            "practice_session_id": run.practice_session_id,
            "generated_document_id": run.generated_document_id,
            "qa_id": run.qa_id,
            "user_action_required": bool(run.user_action_required),
            "user_action_status": run.user_action_status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }

    @staticmethod
    def serialize_run_detail(
        run: AgentGoalRun,
        step: AgentGoalStep = None,
        reflection: AgentGoalReflection = None,
        qa: dict = None,
        practice: dict = None,
        document: dict = None,
    ) -> dict:
        """序列化 run 详情（聚合所有关联数据）"""
        output_type, output_ref = AgentGoalService._infer_run_output(run)
        result = {
            "id": run.id,
            "run_uuid": run.run_uuid,
            "goal_id": run.goal_id,
            "step_id": run.step_id,
            "step": {
                "id": step.id,
                "title": step.title,
                "step_type": step.step_type,
                "status": step.status,
                "result_summary": step.result_summary,
                "user_action_type": step.user_action_type,
                "user_action_status": step.user_action_status,
            } if step else None,
            "status": run.status,
            "tool_name": run.tool_name,
            "tool_args": run.tool_args_json,
            "tool_result": run.tool_result_json,
            "agent_steps": run.agent_steps_json or [],
            "retrieved_chunks": run.retrieved_chunks_json or [],
            "output_type": output_type,
            "output_ref": output_ref,
            "qa": qa,
            "practice_session": practice,
            "generated_document": document,
            "reflection": AgentGoalService._serialize_reflection(reflection) if reflection else None,
            "error_message": run.error_message,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
        return result

    @staticmethod
    def _infer_run_output(run: AgentGoalRun) -> tuple[str | None, dict | None]:
        """从 run 的显式字段和历史字段中推断用户可进入的产物入口。"""
        if run.output_type and run.output_ref_json:
            return run.output_type, run.output_ref_json

        tool_result = run.tool_result_json or {}

        if run.practice_session_id:
            return "practice_session", {
                "practice_session_id": run.practice_session_id,
                "question_count": tool_result.get("question_count"),
            }
        if tool_result.get("practice_session_id"):
            return "practice_session", {
                "practice_session_id": tool_result.get("practice_session_id"),
                "question_count": tool_result.get("question_count"),
            }

        if run.generated_document_id:
            return "document", {"document_id": run.generated_document_id}
        if tool_result.get("document_id"):
            return "document", {"document_id": tool_result.get("document_id")}

        if run.qa_id:
            return "qa", {"qa_id": run.qa_id}
        if tool_result.get("qa_id"):
            return "qa", {"qa_id": tool_result.get("qa_id")}

        return run.output_type, run.output_ref_json

    @staticmethod
    def _clean_user_facing_text(text: str | None) -> str | None:
        """隐藏计划摘要中的内部 ID、step_type 和 tool_name。"""
        if not text:
            return text

        cleaned = str(text)
        for raw, label in _INTERNAL_LABELS.items():
            cleaned = re.sub(rf"\b{re.escape(raw)}\b", label, cleaned)

        cleaned = re.sub(r"[（(]\s*ID\s*=\s*\d+(?:\s*[,，]\s*\d+)*\s*[）)]", "", cleaned)
        cleaned = re.sub(r"\bID\s*=\s*\d+(?:\s*[,，]\s*\d+)*\b", "", cleaned)
        cleaned = re.sub(r"Session\s*#\d+", "练习记录", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+([，。；、：])", r"\1", cleaned)
        cleaned = re.sub(r"([（(])\s*([）)])", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()


agent_goal_service = AgentGoalService()
