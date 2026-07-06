"""
目标Agent多轮自主推进循环服务（文档 Section 16）

职责：
1. 在"推进一次"外面加一个安全的循环控制器
2. 每轮调用 advance_once
3. 每轮观察执行结果
4. 每轮自我评估
5. 决定继续、暂停、重试还是停止
6. 记录循环轨迹
7. 控制预算（最大轮数、最大时间）
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun, AgentGoalReflection
from app.models.agent_goal_loop import AgentGoalLoopRun, AgentGoalLoopIteration

logger = logging.getLogger(__name__)

# ── 停止原因常量（文档 Section 9.3） ──────────────────────────

STOP_USER_ACTION_REQUIRED = "user_action_required"
STOP_MAX_ITERATIONS = "max_iterations_reached"
STOP_MAX_SECONDS = "max_seconds_reached"
STOP_GOAL_COMPLETED = "goal_completed"
STOP_REPLAN_REQUIRED = "replan_required"
STOP_MANUAL_TASK = "manual_task_required"
STOP_FAILED_FINAL = "failed_final"
STOP_BLOCKED = "blocked"
STOP_NO_ACTION = "no_action_available"
STOP_UNSAFE_ACTION = "unsafe_action"
STOP_ERROR = "error"

# ── 需要用户操作的动作类型（文档 Section 11.2） ───────────────

USER_ACTION_TYPES = {
    "practice_session",
    "read_document",
    "manual_complete",
    "confirm_replan",
    "resolve_failure",
    "read_explanation",
    "read_summary",
    "complete_practice",
    "answer_practice",
}

# ── 停止原因中文映射（文档 Section 25.3） ─────────────────────

STOP_REASON_CN = {
    STOP_USER_ACTION_REQUIRED: "需要你完成当前操作",
    STOP_MAX_ITERATIONS: "已达到本次自主推进轮数上限",
    STOP_MAX_SECONDS: "已达到本次运行时间上限",
    STOP_GOAL_COMPLETED: "目标已完成",
    STOP_REPLAN_REQUIRED: "需要你确认重新规划",
    STOP_MANUAL_TASK: "需要你完成线下任务",
    STOP_FAILED_FINAL: "当前步骤多次失败",
    STOP_BLOCKED: "当前目标被阻塞",
}

# ── 用户下一步操作中文映射 ────────────────────────────────────

NEXT_ACTION_CN = {
    "practice_session": "请完成当前练习",
    "diagnostic_quiz": "请完成诊断测验",
    "read_document": "请阅读练习文档",
    "manual_complete": "请完成线下任务后标记完成",
    "confirm_replan": "请确认是否重新规划目标",
    "resolve_failure": "请查看失败原因并决定如何处理",
}


class AgentGoalLoopService:
    """目标多轮自主推进循环服务"""

    # ═══════════════════════════════════════════════════════════════
    # 主入口：运行多轮自主推进（文档 Section 16.3）
    # ═══════════════════════════════════════════════════════════════

    def run_goal_loop(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        course_id: int,
        conversation_id: int | None = None,
        max_iterations: int = 3,
        max_seconds: int = 60,
        allow_generate_plan: bool = True,
        allow_replan: bool = False,
        allow_retry: bool = True,
        stop_on_user_action: bool = True,
        trigger_type: str = "user_click",
    ) -> dict:
        """
        为目标运行多轮自主推进循环。

        流程（文档 Section 8 流程图）：
        1. 校验目标归属和状态
        2. 检查是否已有 running loop
        3. 创建 loop_run
        4. 循环：Think → Act(advance_once) → Observe → Evaluate
        5. 写入 loop_run 总结
        6. 返回结果
        """
        from app.services.agent_goal_service import agent_goal_service as ags
        from app.services.agent_goal_advance_service import agent_goal_advance_service

        # 1. 校验目标归属
        goal = ags._get_goal_for_user(db, goal_id, student_id)

        # 2. 并发保护：检查是否已有 running loop
        running_loop = db.query(AgentGoalLoopRun).filter(
            AgentGoalLoopRun.goal_id == goal_id,
            AgentGoalLoopRun.status == "running",
        ).first()
        if running_loop:
            raise ValueError("目标正在自主推进中，请稍后再试")

        # 3. 创建 loop_run
        loop_uuid_str = f"goal_loop_{uuid.uuid4().hex[:12]}"
        loop_run = AgentGoalLoopRun(
            loop_uuid=loop_uuid_str,
            goal_id=goal_id,
            student_id=student_id,
            course_id=course_id,
            conversation_id=conversation_id,
            trigger_type=trigger_type,
            status="running",
            max_iterations=max_iterations,
            max_seconds=max_seconds,
            started_at=datetime.utcnow(),
        )
        db.add(loop_run)
        db.flush()
        _loop_run_id = loop_run.id

        started_at = datetime.utcnow()
        iterations = []

        try:
            # 4. 循环迭代
            for i in range(1, max_iterations + 1):
                # 4a. 检查时间预算
                elapsed = (datetime.utcnow() - started_at).total_seconds()
                if elapsed > max_seconds:
                    self._finish_loop(
                        db=db,
                        loop_run=loop_run,
                        status="budget_exhausted",
                        stop_reason=STOP_MAX_SECONDS,
                        summary=self._build_summary(
                            iterations,
                            STOP_MAX_SECONDS,
                            max_iterations,
                        ),
                        goal=goal,
                    )
                    break

                # 4b. 创建 iteration
                iteration = AgentGoalLoopIteration(
                    loop_run_id=loop_run.id,
                    iteration_no=i,
                    goal_id=goal_id,
                    status="running",
                    started_at=datetime.utcnow(),
                )
                db.add(iteration)
                db.flush()

                # 4c. Act: 调用 advance_once
                try:
                    advance_result = agent_goal_advance_service.advance_once(
                        db=db,
                        goal_id=goal_id,
                        student_id=student_id,
                        course_id=course_id,
                        allow_generate_plan=allow_generate_plan,
                        allow_replan=allow_replan,
                        allow_retry=allow_retry,
                    )
                except ValueError as exc:
                    # advance_once 失败，记录并停止
                    iteration.status = "failed"
                    iteration.error_message = str(exc)
                    iteration.finished_at = datetime.utcnow()
                    db.flush()
                    iterations.append(iteration)
                    self._finish_loop(
                        db=db,
                        loop_run=loop_run,
                        status="failed",
                        stop_reason=STOP_ERROR,
                        error_message=str(exc),
                        summary=self._build_summary(
                            iterations,
                            STOP_ERROR,
                            max_iterations,
                        ),
                        goal=goal,
                    )
                    break

                # 4d. Observe: 构建观察
                observation = self.build_observation(db, goal_id, advance_result)

                # 4e. Evaluate: 评估是否继续
                evaluation = self.evaluate_iteration(
                    db=db,
                    goal=goal,
                    advance_result=advance_result,
                    iteration_no=i,
                    stop_on_user_action=stop_on_user_action,
                )

                # 4f. 更新 iteration
                iteration.advance_cycle_id = advance_result.get("cycle_id")
                iteration.step_id = advance_result.get("selected_step_id")
                iteration.run_id = advance_result.get("selected_run_id")
                # 从 advance_result 查找 reflection
                if advance_result.get("reflection"):
                    iteration.reflection_id = advance_result["reflection"].get("id")
                iteration.decision_type = advance_result.get("decision_type")
                iteration.action_summary = advance_result.get("result_summary")
                iteration.observation_json = observation
                iteration.evaluation_json = evaluation
                iteration.status = "completed"
                iteration.stop_reason = evaluation.get("stop_reason")
                iteration.stop_after_iteration = (
                    1 if not evaluation.get("continue_loop", True) else 0
                )
                iteration.finished_at = datetime.utcnow()
                db.flush()
                iterations.append(iteration)

                # 4g. 更新 completed_iterations
                loop_run.completed_iterations = i

                # 4h. 判断是否继续
                if not evaluation.get("continue_loop", True):
                    final_status = evaluation.get("loop_status", "completed")
                    stop_reason = evaluation.get("stop_reason")
                    self._finish_loop(
                        db=db,
                        loop_run=loop_run,
                        status=final_status,
                        stop_reason=stop_reason,
                        action_required=evaluation.get("action_required", False),
                        action_type=evaluation.get("action_type"),
                        action_payload=evaluation.get("action_payload"),
                        summary=self._build_summary(
                            iterations,
                            stop_reason,
                            max_iterations,
                        ),
                        goal=goal,
                        final_advance_result=advance_result,
                    )
                    break
            else:
                # 循环自然结束（达到 max_iterations）
                self._finish_loop(
                    db=db,
                    loop_run=loop_run,
                    status="budget_exhausted",
                    stop_reason=STOP_MAX_ITERATIONS,
                    summary=self._build_summary(
                        iterations,
                        STOP_MAX_ITERATIONS,
                        max_iterations,
                    ),
                    goal=goal,
                )

            db.commit()

            logger.info(
                "自主推进完成 goal_id=%s loop_run_id=%s iterations=%s stop_reason=%s",
                goal_id, loop_run.id, len(iterations), loop_run.stop_reason,
            )

            return self.serialize_loop_run(loop_run, iterations, db)

        except Exception as exc:
            db.rollback()
            self._mark_loop_failed(db, _loop_run_id, str(exc))
            logger.exception("自主推进异常 goal_id=%s loop_run_id=%s", goal_id, _loop_run_id)
            raise ValueError("自主推进失败，请稍后重试。")

    # ═══════════════════════════════════════════════════════════════
    # 评估本轮是否继续（文档 Section 17）
    # ═══════════════════════════════════════════════════════════════

    def evaluate_iteration(
        self,
        db: Session,
        goal: AgentLearningGoal,
        advance_result: dict,
        iteration_no: int,
        stop_on_user_action: bool,
    ) -> dict:
        """
        评估本轮执行结果，决定是否继续。

        返回（文档 Section 19）：
        {
            "continue_loop": bool,
            "loop_status": str,
            "stop_reason": str | None,
            "risk_level": str,
            "quality_passed": bool,
            "action_required": bool,
            "action_type": str | None,
            "action_payload": dict | None,
            "reason": str,
        }
        """
        decision_type = advance_result.get("decision_type")
        action_required = advance_result.get("action_required", False)
        action_type = advance_result.get("action_type")
        action_payload = advance_result.get("action_payload")

        # ── 必须停止的条件（文档 Section 17.1） ──

        # 需要用户操作
        if action_required and stop_on_user_action:
            return {
                "continue_loop": False,
                "loop_status": "waiting_user_action",
                "stop_reason": STOP_USER_ACTION_REQUIRED,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": True,
                "action_type": action_type,
                "action_payload": action_payload,
                "reason": self._stop_reason_message(action_type, action_payload),
            }

        # 用户动作类型（练习、文档、手动任务、重规划确认等）
        if action_type in USER_ACTION_TYPES and stop_on_user_action:
            return {
                "continue_loop": False,
                "loop_status": "waiting_user_action",
                "stop_reason": STOP_USER_ACTION_REQUIRED,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": True,
                "action_type": action_type,
                "action_payload": action_payload,
                "reason": self._stop_reason_message(action_type, action_payload),
            }

        # 阻塞
        if decision_type == "blocked":
            return {
                "continue_loop": False,
                "loop_status": "blocked",
                "stop_reason": STOP_BLOCKED,
                "risk_level": "high",
                "quality_passed": False,
                "action_required": action_required,
                "action_type": action_type,
                "action_payload": action_payload,
                "reason": advance_result.get("decision_reason", "目标被阻塞"),
            }

        # 无动作
        if decision_type == "noop":
            return {
                "continue_loop": False,
                "loop_status": "blocked",
                "stop_reason": STOP_NO_ACTION,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "reason": advance_result.get("decision_reason", "当前无需推进"),
            }

        # 目标完成
        if decision_type == "complete_goal":
            return {
                "continue_loop": False,
                "loop_status": "goal_completed",
                "stop_reason": STOP_GOAL_COMPLETED,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "reason": "目标所有步骤已完成",
            }

        # 需要重规划但未允许
        if goal.planning_status == "replan_needed":
            return {
                "continue_loop": False,
                "loop_status": "blocked",
                "stop_reason": STOP_REPLAN_REQUIRED,
                "risk_level": "medium",
                "quality_passed": False,
                "action_required": True,
                "action_type": "confirm_replan",
                "action_payload": None,
                "reason": "目标需要重新规划",
            }

        # 步骤最终失败
        if advance_result.get("status") == "failed":
            return {
                "continue_loop": False,
                "loop_status": "failed",
                "stop_reason": STOP_FAILED_FINAL,
                "risk_level": "high",
                "quality_passed": False,
                "action_required": True,
                "action_type": "resolve_failure",
                "action_payload": None,
                "reason": "当前步骤执行失败",
            }

        # 目标已完成
        if goal.status == "completed":
            return {
                "continue_loop": False,
                "loop_status": "goal_completed",
                "stop_reason": STOP_GOAL_COMPLETED,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "reason": "目标已完成",
            }

        # ── 可以继续（文档 Section 17.2） ──

        # 生成计划后可以继续推进
        if decision_type == "generate_plan":
            return {
                "continue_loop": True,
                "loop_status": "running",
                "stop_reason": None,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "reason": "已生成学习计划，继续推进下一步。",
            }

        # 重新规划后可以继续
        if decision_type == "replan_goal":
            return {
                "continue_loop": True,
                "loop_status": "running",
                "stop_reason": None,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "reason": "已重新规划目标，继续推进。",
            }

        # 普通步骤执行成功
        if decision_type in ("execute_step", "retry_step"):
            return {
                "continue_loop": True,
                "loop_status": "running",
                "stop_reason": None,
                "risk_level": "low",
                "quality_passed": True,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "reason": "本轮步骤执行完成，可以继续推进下一步。",
            }

        # 默认：可以继续
        return {
            "continue_loop": True,
            "loop_status": "running",
            "stop_reason": None,
            "risk_level": "low",
            "quality_passed": True,
            "action_required": False,
            "action_type": None,
            "action_payload": None,
            "reason": "可以继续推进。",
        }

    # ═══════════════════════════════════════════════════════════════
    # 构建观察（文档 Section 18）
    # ═══════════════════════════════════════════════════════════════

    def build_observation(
        self,
        db: Session,
        goal_id: int,
        advance_result: dict,
    ) -> dict:
        """构建本轮观察数据"""
        from app.services.agent_goal_service import agent_goal_service

        goal = db.query(AgentLearningGoal).filter(
            AgentLearningGoal.id == goal_id
        ).first()

        observation = {
            "goal": {
                "status": goal.status if goal else None,
                "planning_status": goal.planning_status if goal else None,
                "progress_percent": float(goal.progress_percent) if goal and goal.progress_percent else 0,
            },
            "advance": {
                "cycle_id": advance_result.get("cycle_id"),
                "decision_type": advance_result.get("decision_type"),
                "status": advance_result.get("status"),
                "action_required": advance_result.get("action_required", False),
                "action_type": advance_result.get("action_type"),
            },
            "step": None,
            "run": None,
            "reflection": None,
        }

        # 关联步骤
        step_id = advance_result.get("selected_step_id")
        if step_id:
            step = db.query(AgentGoalStep).filter(
                AgentGoalStep.id == step_id
            ).first()
            if step:
                observation["step"] = {
                    "id": step.id,
                    "title": step.title,
                    "status": step.status,
                    "step_type": step.step_type,
                }

        # 关联 run
        run_id = advance_result.get("selected_run_id")
        if run_id:
            run = db.query(AgentGoalRun).filter(
                AgentGoalRun.id == run_id
            ).first()
            if run:
                observation["run"] = {
                    "id": run.id,
                    "status": run.status,
                }

        # 关联 reflection
        if advance_result.get("reflection"):
            ref = advance_result["reflection"]
            observation["reflection"] = {
                "quality_score": ref.get("quality_score"),
                "next_action": ref.get("next_action"),
            }

        return observation

    # ═══════════════════════════════════════════════════════════════
    # 判断是否应该继续（文档 Section 16.2）
    # ═══════════════════════════════════════════════════════════════

    def should_continue(
        self,
        evaluation: dict,
        loop_started_at: datetime,
        max_seconds: int,
        iteration_no: int,
        max_iterations: int,
    ) -> tuple[bool, str | None]:
        """
        基于评估结果和时间/预算判断是否应该继续。

        返回 (是否继续, 停止原因)
        """
        # 评估结果说不继续
        if not evaluation.get("continue_loop", True):
            return False, evaluation.get("stop_reason")

        # 时间预算耗尽
        elapsed = (datetime.utcnow() - loop_started_at).total_seconds()
        if elapsed > max_seconds:
            return False, STOP_MAX_SECONDS

        # 达到最大轮数
        if iteration_no >= max_iterations:
            return False, STOP_MAX_ITERATIONS

        return True, None

    # ═══════════════════════════════════════════════════════════════
    # 序列化（文档 Section 16.2）
    # ═══════════════════════════════════════════════════════════════

    def serialize_loop_run(
        self,
        loop_run: AgentGoalLoopRun,
        iterations: list[AgentGoalLoopIteration],
        db: Session,
    ) -> dict:
        """序列化 loop_run 为前端响应"""
        return {
            "id": loop_run.id,
            "loop_uuid": loop_run.loop_uuid,
            "goal_id": loop_run.goal_id,
            "status": loop_run.status,
            "completed_iterations": loop_run.completed_iterations,
            "max_iterations": loop_run.max_iterations,
            "stop_reason": loop_run.stop_reason,
            "action_required": bool(loop_run.action_required),
            "action_type": loop_run.action_type,
            "action_payload": loop_run.action_payload_json,
            "summary": loop_run.summary,
            "error_message": loop_run.error_message,
            "iterations": [self._serialize_iteration(it) for it in iterations],
        }

    @staticmethod
    def _serialize_iteration(iteration: AgentGoalLoopIteration) -> dict:
        """序列化单轮迭代"""
        return {
            "id": iteration.id,
            "iteration_no": iteration.iteration_no,
            "status": iteration.status,
            "decision_type": iteration.decision_type,
            "thought_summary": iteration.thought_summary,
            "action_summary": iteration.action_summary,
            "observation": iteration.observation_json,
            "evaluation": iteration.evaluation_json,
            "stop_after_iteration": bool(iteration.stop_after_iteration),
            "stop_reason": iteration.stop_reason,
            "advance_cycle_id": iteration.advance_cycle_id,
            "step_id": iteration.step_id,
            "run_id": iteration.run_id,
            "reflection_id": iteration.reflection_id,
        }

    # ═══════════════════════════════════════════════════════════════
    # 查询方法
    # ═══════════════════════════════════════════════════════════════

    def list_loop_runs(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        limit: int = 10,
    ) -> list[dict]:
        """获取目标的循环运行记录列表"""
        from app.services.agent_goal_service import agent_goal_service

        agent_goal_service._get_goal_for_user(db, goal_id, student_id)

        runs = db.query(AgentGoalLoopRun).filter(
            AgentGoalLoopRun.goal_id == goal_id,
        ).order_by(AgentGoalLoopRun.started_at.desc()).limit(limit).all()

        result = []
        for run in runs:
            iterations = db.query(AgentGoalLoopIteration).filter(
                AgentGoalLoopIteration.loop_run_id == run.id
            ).order_by(AgentGoalLoopIteration.iteration_no).all()
            result.append(self.serialize_loop_run(run, iterations, db))

        return result

    def get_loop_run_detail(
        self,
        db: Session,
        goal_id: int,
        loop_run_id: int,
        student_id: int,
    ) -> dict:
        """获取单次循环运行详情"""
        from app.services.agent_goal_service import agent_goal_service

        agent_goal_service._get_goal_for_user(db, goal_id, student_id)

        run = db.query(AgentGoalLoopRun).filter(
            AgentGoalLoopRun.id == loop_run_id,
            AgentGoalLoopRun.goal_id == goal_id,
        ).first()

        if not run:
            raise ValueError("循环记录不存在")

        iterations = db.query(AgentGoalLoopIteration).filter(
            AgentGoalLoopIteration.loop_run_id == run.id
        ).order_by(AgentGoalLoopIteration.iteration_no).all()

        result = self.serialize_loop_run(run, iterations, db)

        # 附加每轮关联的 advance_cycle 详情
        from app.services.agent_goal_advance_service import agent_goal_advance_service

        for i, it in enumerate(iterations):
            if it.advance_cycle_id:
                try:
                    result["iterations"][i]["advance_cycle"] = (
                        agent_goal_advance_service.get_advance_cycle_detail(
                            db=db,
                            goal_id=goal_id,
                            cycle_id=it.advance_cycle_id,
                            student_id=student_id,
                        )
                    )
                except Exception:
                    result["iterations"][i]["advance_cycle"] = None

        return result

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    def _finish_loop(
        self,
        db: Session,
        loop_run: AgentGoalLoopRun,
        status: str,
        stop_reason: str | None,
        summary: str | None = None,
        action_required: bool = False,
        action_type: str | None = None,
        action_payload: dict | None = None,
        error_message: str | None = None,
        goal: AgentLearningGoal | None = None,
        final_advance_result: dict | None = None,
    ):
        """更新 loop_run 为最终状态"""
        loop_run.status = status
        loop_run.stop_reason = stop_reason
        loop_run.summary = summary
        loop_run.error_message = error_message
        loop_run.action_required = 1 if action_required else 0
        loop_run.action_type = action_type
        loop_run.action_payload_json = action_payload
        loop_run.finished_at = datetime.utcnow()

        # 保存目标快照
        if goal:
            from app.services.agent_goal_advance_service import agent_goal_advance_service
            loop_run.final_goal_snapshot_json = (
                agent_goal_advance_service.build_goal_snapshot(db, goal)
            )

        # 如果有 action_required，也接收 advance_result 的 action 信息
        if final_advance_result and final_advance_result.get("action_required"):
            loop_run.action_required = 1
            loop_run.action_type = (
                loop_run.action_type
                or final_advance_result.get("action_type")
            )
            loop_run.action_payload_json = (
                loop_run.action_payload_json
                or final_advance_result.get("action_payload")
            )

        db.flush()

    def _build_summary(
        self,
        iterations: list,
        stop_reason: str | None,
        max_iterations: int,
    ) -> str:
        """
        构建面向用户的循环摘要（文档 Section 25）。

        规则生成，不调用 LLM。
        """
        n = len([it for it in iterations if it.status == "completed"])

        # 收集每轮动作摘要
        action_summaries = []
        for it in iterations:
            if it.action_summary:
                action_summaries.append(it.action_summary)

        # 停止原因中文
        stop_text = STOP_REASON_CN.get(stop_reason, "已暂停")

        # 下一步提示
        next_text = self._next_action_text(stop_reason)

        if n == 0:
            return f"本次自主推进未能完成任何步骤。因「{stop_text}」而停止。{next_text}"

        if n == 1:
            if action_summaries:
                return f"我已帮你推进 1 轮：{action_summaries[0]}。当前因「{stop_text}」暂停。{next_text}"
            return f"我已帮你推进 1 轮。当前因「{stop_text}」暂停。{next_text}"

        # 多轮
        summary_parts = "、".join(action_summaries[:3])
        if len(action_summaries) > 3:
            summary_parts += "等"

        return (
            f"我已帮你推进 {n} 轮：{summary_parts}。"
            f"当前因「{stop_text}」暂停。{next_text}"
        )

    @staticmethod
    def _stop_reason_message(
        action_type: str | None,
        action_payload: dict | None,
    ) -> str:
        """生成停止原因的用户可读消息"""
        if action_type == "practice_session":
            qc = ""
            if action_payload and action_payload.get("question_count"):
                qc = f"（共 {action_payload['question_count']} 题）"
            return f"已生成练习题{qc}，需要用户作答。"
        if action_type == "read_document":
            return "已生成练习文档，需要用户阅读。"
        if action_type == "manual_complete":
            return "当前步骤需要用户线下完成。"
        if action_type == "confirm_replan":
            return "需要用户确认是否重新规划。"
        if action_type == "resolve_failure":
            return "当前步骤执行失败，需要用户决定如何处理。"
        return "需要用户完成当前操作。"

    @staticmethod
    def _next_action_text(stop_reason: str | None) -> str:
        """生成下一步需要用户做什么的提示"""
        if stop_reason == STOP_USER_ACTION_REQUIRED:
            return "请完成后，我才能继续推进目标。"
        if stop_reason == STOP_MAX_ITERATIONS:
            return "你可以再次点击「自主推进」继续。"
        if stop_reason == STOP_MAX_SECONDS:
            return "你可以再次点击「自主推进」继续。"
        if stop_reason == STOP_GOAL_COMPLETED:
            return "恭喜你完成了目标！"
        if stop_reason == STOP_REPLAN_REQUIRED:
            return "请确认后继续。"
        if stop_reason == STOP_MANUAL_TASK:
            return "请完成后标记完成，我会继续推进。"
        if stop_reason == STOP_FAILED_FINAL:
            return "请查看失败原因，决定是否重新规划。"
        if stop_reason == STOP_BLOCKED:
            return "请查看阻塞原因后处理。"
        return ""

    def _mark_loop_failed(
        self,
        db: Session,
        loop_run_id: int,
        error_message: str,
    ):
        """将循环标记为失败"""
        try:
            loop_run = db.query(AgentGoalLoopRun).filter(
                AgentGoalLoopRun.id == loop_run_id
            ).first()
            if loop_run:
                loop_run.status = "failed"
                loop_run.error_message = error_message
                loop_run.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            logger.exception("标记 loop 失败时出错 loop_run_id=%s", loop_run_id)
            try:
                db.rollback()
            except Exception:
                pass


agent_goal_loop_service = AgentGoalLoopService()
