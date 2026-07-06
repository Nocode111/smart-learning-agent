"""
学习步骤用户动作服务（文档 Section 11）

职责：
1. 创建用户动作
2. 记录阅读心跳
3. 判断是否满足完成条件
4. 完成 step
5. 刷新复盘
6. 更新目标进度
7. 触发下一轮 loop
8. 防重复触发
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun
from app.models.agent_goal_user_action import AgentGoalUserAction
from app.models.agent_goal_loop import AgentGoalLoopRun

logger = logging.getLogger(__name__)

# ── 动作类型到所需秒数映射 ──────────────────────────────────────

_ACTION_REQUIRED_SECONDS = {
    "read_explanation": 30,
    "read_summary": 30,
    "read_document": 30,
    "manual_complete": 0,
    "answer_practice": 0,
    "complete_practice": 0,
}

# ── 动作类型到步骤 user_action_type 映射 ────────────────────────

_ACTION_TO_STEP_ACTION_TYPE = {
    "read_explanation": "read_explanation",
    "read_summary": "read_summary",
    "read_document": "read_document",
    "manual_complete": "manual_complete",
}


class AgentGoalUserActionService:
    """用户学习动作服务"""

    # ═══════════════════════════════════════════════════════════════
    # 开始用户动作（文档 Section 11.3）
    # ═══════════════════════════════════════════════════════════════

    def start_action(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
        course_id: int,
        action_type: str,
        target_type: str | None = None,
        target_id: int | None = None,
    ) -> dict:
        """
        开始用户学习动作。

        如果已有该步骤进行中的动作，复用旧动作，继续累计时间。
        """
        # 查找已有的进行中动作
        existing = db.query(AgentGoalUserAction).filter(
            AgentGoalUserAction.step_id == step_id,
            AgentGoalUserAction.student_id == student_id,
            AgentGoalUserAction.status.in_(["started", "pending"]),
        ).order_by(AgentGoalUserAction.started_at.desc()).first()

        if existing:
            # 复用已有动作，重置 required_seconds
            required = _ACTION_REQUIRED_SECONDS.get(action_type, 30)
            existing.required_seconds = required
            existing.target_type = target_type or existing.target_type
            existing.target_id = target_id or existing.target_id
            db.commit()
            return self._serialize(existing)

        # 查找步骤信息
        step = db.query(AgentGoalStep).filter(
            AgentGoalStep.id == step_id,
            AgentGoalStep.goal_id == goal_id,
        ).first()

        run_id = step.last_run_id if step else None
        required = _ACTION_REQUIRED_SECONDS.get(action_type, 30)

        action_uuid_str = f"goal_action_{uuid.uuid4().hex[:16]}"
        action = AgentGoalUserAction(
            action_uuid=action_uuid_str,
            goal_id=goal_id,
            step_id=step_id,
            run_id=run_id,
            student_id=student_id,
            course_id=course_id,
            action_type=action_type,
            status="started",
            target_type=target_type,
            target_id=target_id,
            required_seconds=required,
            accumulated_seconds=0,
            started_at=datetime.utcnow(),
        )
        db.add(action)
        db.flush()

        # 更新步骤的 user_action_status
        if step:
            step.user_action_status = "started"
            db.flush()

        db.commit()

        logger.info("用户动作已开始 action_uuid=%s step_id=%s type=%s", action_uuid_str, step_id, action_type)
        return self._serialize(action)

    # ═══════════════════════════════════════════════════════════════
    # 阅读心跳（文档 Section 11.3）
    # ═══════════════════════════════════════════════════════════════

    def heartbeat(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
        course_id: int,
        action_uuid: str,
        visible: bool = True,
        active_seconds: int = 5,
        trigger_auto_advance: bool = True,
    ) -> dict:
        """
        记录阅读心跳。

        逻辑：
        - visible=true 才累计时间
        - 累计时间 >= required_seconds 后自动完成
        - 完成后触发自动推进
        """
        action = db.query(AgentGoalUserAction).filter(
            AgentGoalUserAction.action_uuid == action_uuid,
            AgentGoalUserAction.step_id == step_id,
            AgentGoalUserAction.student_id == student_id,
        ).first()

        if not action:
            raise ValueError("用户动作不存在")

        # 已完成的动作不再累计
        if action.status == "completed":
            return {
                **self._serialize(action),
                "completed": True,
            }

        # visible 时才累计
        if visible:
            action.accumulated_seconds = (action.accumulated_seconds or 0) + min(active_seconds, 10)

        action.last_heartbeat_at = datetime.utcnow()
        db.flush()

        # 检查是否满足完成条件（文档 Section 6.4）
        if action.required_seconds > 0 and (action.accumulated_seconds or 0) >= action.required_seconds:
            result = self.complete_action(
                db=db,
                goal_id=goal_id,
                step_id=step_id,
                student_id=student_id,
                course_id=course_id,
                action_uuid=action_uuid,
                trigger_auto_advance=trigger_auto_advance,
            )
            return result

        db.commit()

        return {
            **self._serialize(action),
            "completed": False,
        }

    # ═══════════════════════════════════════════════════════════════
    # 完成用户动作（文档 Section 11.3）
    # ═══════════════════════════════════════════════════════════════

    def complete_action(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
        course_id: int,
        action_uuid: str | None = None,
        action_type: str | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        trigger_auto_advance: bool = True,
    ) -> dict:
        """
        完成用户动作。

        支持两种完成方式：
        1. 按 action_uuid 完成已有动作
        2. 按 action_type 查找最新动作完成（手动完成兜底）
        """
        if action_uuid:
            action = db.query(AgentGoalUserAction).filter(
                AgentGoalUserAction.action_uuid == action_uuid,
                AgentGoalUserAction.step_id == step_id,
                AgentGoalUserAction.student_id == student_id,
            ).first()
        elif action_type:
            action = db.query(AgentGoalUserAction).filter(
                AgentGoalUserAction.step_id == step_id,
                AgentGoalUserAction.student_id == student_id,
                AgentGoalUserAction.action_type == action_type,
                AgentGoalUserAction.status.in_(["started", "pending"]),
            ).order_by(AgentGoalUserAction.started_at.desc()).first()
        else:
            action = db.query(AgentGoalUserAction).filter(
                AgentGoalUserAction.step_id == step_id,
                AgentGoalUserAction.student_id == student_id,
                AgentGoalUserAction.status.in_(["started", "pending"]),
            ).order_by(AgentGoalUserAction.started_at.desc()).first()

        if not action:
            # 没有动作记录时创建一条虚拟完成记录
            action_uuid_str = f"goal_action_{uuid.uuid4().hex[:16]}"
            action = AgentGoalUserAction(
                action_uuid=action_uuid_str,
                goal_id=goal_id,
                step_id=step_id,
                student_id=student_id,
                course_id=course_id,
                action_type=action_type or "manual_complete",
                status="completed",
                target_type=target_type,
                target_id=target_id,
                required_seconds=0,
                accumulated_seconds=0,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
            db.add(action)
            db.flush()

        # 防重复：已完成的动作不重复处理
        if action.status == "completed":
            auto_advance_result = action.metadata_json.get("auto_advance_result") if action.metadata_json else None
            return {
                **self._serialize(action),
                "completed": True,
                "auto_advance_result": auto_advance_result,
            }

        # 标记 action 完成
        action.status = "completed"
        action.completed_at = datetime.utcnow()
        db.flush()

        # 完成步骤（文档 Section 11.4）
        self.complete_step_after_user_action(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=student_id,
            action=action,
        )

        db.commit()

        # 触发自动推进（文档 Section 11.5 + 19）
        auto_advance_result = None
        if trigger_auto_advance:
            auto_advance_result = self.maybe_trigger_auto_advance(
                db=db,
                goal_id=goal_id,
                step_id=step_id,
                student_id=student_id,
                course_id=course_id,
                action=action,
            )

        result = {
            **self._serialize(action),
            "completed": True,
            "auto_advance_result": auto_advance_result,
        }

        logger.info("用户动作已完成 action_uuid=%s step_id=%s type=%s", action.action_uuid, step_id, action.action_type)
        return result

    # ═══════════════════════════════════════════════════════════════
    # 完成步骤（文档 Section 11.4）
    # ═══════════════════════════════════════════════════════════════

    def complete_step_after_user_action(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
        action: AgentGoalUserAction,
    ):
        """
        用户动作完成后，标记步骤完成。

        文档 Section 11.4：
        1. 标记 step 为 completed
        2. 更新 step 的 user_action_status
        3. 更新最新 run 的 user_action_status
        4. 刷新复盘
        5. 更新目标进度
        6. 检查目标完成
        """
        from app.services.agent_goal_service import agent_goal_service as ags
        from app.services.agent_goal_reflection_service import agent_goal_reflection_service

        step = db.query(AgentGoalStep).filter(
            AgentGoalStep.id == step_id,
            AgentGoalStep.goal_id == goal_id,
        ).first()

        if not step:
            return

        # 已完成的步骤不重复处理
        if step.status == "completed":
            return

        # 1. 标记步骤完成
        step.status = "completed"
        step.needs_user_action = 0
        step.user_action_status = "completed"
        step.completed_at = datetime.utcnow()

        # 2. 写入结果摘要
        summary_parts = []
        if action.accumulated_seconds and action.accumulated_seconds > 0:
            summary_parts.append(f"阅读时长 {action.accumulated_seconds} 秒")
        if action.action_type == "manual_complete":
            summary_parts.append("用户手动标记完成")
        if not summary_parts:
            summary_parts.append(f"已完成 {action.action_type}")
        step.result_summary = "；".join(summary_parts)

        # 3. 更新最新 run
        run_id = action.run_id or step.last_run_id
        if run_id:
            run = db.query(AgentGoalRun).filter(
                AgentGoalRun.id == run_id,
            ).first()
            if run:
                run.user_action_status = "completed"

        # 4. 刷新复盘
        try:
            goal = db.query(AgentLearningGoal).filter(
                AgentLearningGoal.id == goal_id
            ).first()
            if goal and run_id:
                run = db.query(AgentGoalRun).filter(AgentGoalRun.id == run_id).first()
                if run:
                    agent_goal_reflection_service.refresh_step_reflection(
                        db=db,
                        goal=goal,
                        step=step,
                        student_id=student_id,
                        force_llm=False,
                    )
        except Exception:
            logger.exception("用户动作完成后刷新复盘失败 step_id=%s", step_id)

        # 5. 更新目标进度
        try:
            progress = ags.recalculate_progress(db, goal_id)
            goal = db.query(AgentLearningGoal).filter(
                AgentLearningGoal.id == goal_id
            ).first()
            if goal:
                goal.progress_percent = progress
        except Exception:
            logger.exception("用户动作完成后更新进度失败 goal_id=%s", goal_id)

        # 6. 检查目标完成
        try:
            ags.check_goal_completion(db, goal_id)
        except Exception:
            logger.exception("用户动作完成后检查目标完成失败 goal_id=%s", goal_id)

        db.flush()

    # ═══════════════════════════════════════════════════════════════
    # 自动触发下一步推进（文档 Section 11.5 + 19）
    # ═══════════════════════════════════════════════════════════════

    def maybe_trigger_auto_advance(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
        course_id: int,
        action: AgentGoalUserAction,
    ) -> dict | None:
        """
        完成用户动作后自动调用 run_goal_loop。

        防重复（文档 Section 19）：
        1. 检查 action.metadata 中的 auto_advance_triggered
        2. 检查是否已有 running loop
        3. 检查目标状态
        """
        # 1. 防重复：检查 action 是否已触发过
        meta = action.metadata_json or {}
        if meta.get("auto_advance_triggered"):
            logger.info("已触发过自动推进，跳过 action_uuid=%s", action.action_uuid)
            return meta.get("auto_advance_result")

        # 2. 检查是否已有 running loop
        running_loop = db.query(AgentGoalLoopRun).filter(
            AgentGoalLoopRun.goal_id == goal_id,
            AgentGoalLoopRun.status == "running",
        ).first()
        if running_loop:
            logger.info("目标已有进行中的循环，跳过自动触发 goal_id=%s", goal_id)
            return None

        # 3. 检查目标状态
        goal = db.query(AgentLearningGoal).filter(
            AgentLearningGoal.id == goal_id
        ).first()
        if not goal or goal.status in ("completed", "canceled", "draft"):
            logger.info("目标状态不适合自动推进 goal_id=%s status=%s", goal_id, goal.status if goal else None)
            return None

        # 4. 触发自动推进（max_iterations=2，不要太多）
        try:
            from app.services.agent_goal_loop_service import agent_goal_loop_service

            auto_advance_result = agent_goal_loop_service.run_goal_loop(
                db=db,
                goal_id=goal_id,
                student_id=student_id,
                course_id=course_id,
                max_iterations=2,
                max_seconds=60,
                allow_generate_plan=True,
                allow_replan=False,
                allow_retry=True,
                stop_on_user_action=True,
                trigger_type="user_action_completed",
            )

            # 5. 记录触发状态到 action metadata（防重复）
            meta["auto_advance_triggered"] = True
            meta["auto_advance_loop_run_id"] = auto_advance_result.get("id")
            meta["auto_advance_result"] = auto_advance_result
            action.metadata_json = meta
            db.commit()

            logger.info("自动推进入完成 goal_id=%s loop_run_id=%s", goal_id, auto_advance_result.get("id"))
            return auto_advance_result

        except Exception:
            logger.exception("自动触发推进失败 goal_id=%s step_id=%s", goal_id, step_id)
            return None

    # ═══════════════════════════════════════════════════════════════
    # 查询最新动作（文档 Section 10.4）
    # ═══════════════════════════════════════════════════════════════

    def get_latest_action(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
    ) -> dict | None:
        """获取步骤最新的用户动作"""
        action = db.query(AgentGoalUserAction).filter(
            AgentGoalUserAction.goal_id == goal_id,
            AgentGoalUserAction.step_id == step_id,
            AgentGoalUserAction.student_id == student_id,
        ).order_by(AgentGoalUserAction.started_at.desc()).first()

        if not action:
            return None

        return self._serialize(action)

    # ═══════════════════════════════════════════════════════════════
    # 序列化
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _serialize(action: AgentGoalUserAction) -> dict:
        """序列化用户动作为前端响应"""
        return {
            "id": action.id,
            "action_uuid": action.action_uuid,
            "goal_id": action.goal_id,
            "step_id": action.step_id,
            "action_type": action.action_type,
            "status": action.status,
            "required_seconds": action.required_seconds,
            "accumulated_seconds": action.accumulated_seconds or 0,
            "completed": action.status == "completed",
            "started_at": action.started_at,
            "last_heartbeat_at": action.last_heartbeat_at,
            "completed_at": action.completed_at,
        }


agent_goal_user_action_service = AgentGoalUserActionService()
