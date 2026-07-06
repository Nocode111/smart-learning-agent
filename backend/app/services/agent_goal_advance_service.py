"""
目标推进服务（文档 Section 12）

职责：
1. 读取目标当前状态
2. 生成目标快照
3. 判断下一步动作（规则优先）
4. 调用已有 planner、runner、reflection 服务
5. 写入推进记录（agent_goal_advance_cycles）
6. 处理异常和回滚
7. 返回统一响应
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun, AgentGoalReflection
from app.models.agent_goal_advance import AgentGoalAdvanceCycle

logger = logging.getLogger(__name__)

# ── 推进决策类型 ──────────────────────────────────────────────

DECISION_GENERATE_PLAN = "generate_plan"
DECISION_EXECUTE_STEP = "execute_step"
DECISION_RETRY_STEP = "retry_step"
DECISION_WAIT_USER_ACTION = "wait_user_action"
DECISION_REFRESH_REFLECTION = "refresh_reflection"
DECISION_REPLAN_GOAL = "replan_goal"
DECISION_COMPLETE_GOAL = "complete_goal"
DECISION_BLOCKED = "blocked"
DECISION_NOOP = "noop"

# ── 用户动作类型 ──────────────────────────────────────────────

ACTION_PRACTICE_SESSION = "practice_session"
ACTION_READ_DOCUMENT = "read_document"
ACTION_MANUAL_COMPLETE = "manual_complete"
ACTION_CONFIRM_REPLAN = "confirm_replan"
ACTION_RESOLVE_FAILURE = "resolve_failure"
ACTION_CONFIRM_GENERATE_PLAN = "confirm_generate_plan"

# ── 用户动作类型 -> 步骤类型映射（供前端判断） ────────────────

USER_ACTION_STEP_TYPE_MAP = {
    "inline_practice": ACTION_PRACTICE_SESSION,
    "diagnostic_quiz": ACTION_PRACTICE_SESSION,
    "exercise_document": ACTION_READ_DOCUMENT,
    "manual_task": ACTION_MANUAL_COMPLETE,
    "qa_explanation": "read_explanation",
    "review_summary": "read_summary",
}


class AgentGoalAdvanceService:
    """目标推进服务"""

    # ═══════════════════════════════════════════════════════════════
    # 主入口：推进目标一次（文档 Section 12.3）
    # ═══════════════════════════════════════════════════════════════

    def advance_once(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        course_id: int,
        allow_generate_plan: bool = True,
        allow_replan: bool = False,
        allow_retry: bool = True,
        force_step_id: int | None = None,
    ) -> dict:
        """
        推进目标一次。

        流程:
        1. 查询目标并校验归属
        2. 检查并发（是否已有 running cycle）
        3. 创建 cycle，记录 before_snapshot
        4. 决策下一步动作
        5. 执行决策
        6. 记录 after_snapshot
        7. 更新 cycle 状态和目标缓存
        8. 返回统一响应
        """
        from app.services.agent_goal_service import agent_goal_service as ags

        # 1. 查询目标并校验归属
        goal = ags._get_goal_for_user(db, goal_id, student_id)

        # 2. 并发保护（文档 Section 12.4）
        running_cycle = db.query(AgentGoalAdvanceCycle).filter(
            AgentGoalAdvanceCycle.goal_id == goal_id,
            AgentGoalAdvanceCycle.status == "running",
        ).first()

        if running_cycle:
            raise ValueError("目标正在推进中，请稍后刷新")

        # 也检查是否有 running 的步骤
        running_step = db.query(AgentGoalStep).filter(
            AgentGoalStep.goal_id == goal_id,
            AgentGoalStep.status == "running",
        ).first()
        if running_step:
            raise ValueError("有步骤正在执行中，请稍后刷新")

        # 3. 创建 cycle
        cycle_uuid_str = f"goal_adv_{uuid.uuid4().hex[:12]}"
        cycle = AgentGoalAdvanceCycle(
            goal_id=goal_id,
            student_id=student_id,
            course_id=course_id,
            cycle_uuid=cycle_uuid_str,
            trigger_type="user_click",
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(cycle)
        db.flush()

        # 保存 cycle ID 以备异常处理使用
        _cycle_id = cycle.id

        try:
            # 4. 记录 before_snapshot
            cycle.before_snapshot_json = self.build_goal_snapshot(db, goal)

            # 5. 决策
            decision = self.decide_next_action(
                db=db,
                goal=goal,
                allow_generate_plan=allow_generate_plan,
                allow_replan=allow_replan,
                allow_retry=allow_retry,
                force_step_id=force_step_id,
            )

            cycle.decision_type = decision["decision_type"]
            cycle.decision_reason = decision.get("decision_reason")

            # 6. 执行决策
            exec_result = self.execute_decision(
                db=db,
                goal=goal,
                cycle=cycle,
                decision=decision,
                student_id=student_id,
                course_id=course_id,
            )

            # 7. 写入执行结果
            cycle.selected_step_id = exec_result.get("selected_step_id")
            cycle.selected_run_id = exec_result.get("selected_run_id")
            cycle.selected_reflection_id = exec_result.get("selected_reflection_id")
            cycle.action_required = 1 if exec_result.get("action_required") else 0
            cycle.action_type = exec_result.get("action_type")
            cycle.action_payload_json = exec_result.get("action_payload")
            cycle.result_summary = exec_result.get("result_summary")

            # 8. 记录 after_snapshot
            cycle.after_snapshot_json = self.build_goal_snapshot(db, goal)

            # 9. 更新 cycle 状态
            final_status = exec_result.get("cycle_status", "completed")
            cycle.status = final_status
            cycle.finished_at = datetime.utcnow()

            # 10. 更新目标缓存字段
            goal_from_db = db.query(AgentLearningGoal).filter(
                AgentLearningGoal.id == goal_id
            ).first()
            if goal_from_db:
                goal_from_db.last_advance_cycle_id = cycle.id
                goal_from_db.next_action_type = exec_result.get("action_type")
                goal_from_db.next_action_payload_json = exec_result.get("action_payload")
                # 构建面向用户的摘要
                goal_from_db.last_agent_summary = self._build_user_message(
                    decision=decision,
                    exec_result=exec_result,
                )

            db.commit()

            logger.info(
                "目标推进完成 goal_id=%s cycle_id=%s decision=%s status=%s",
                goal_id, cycle.id, decision["decision_type"], final_status,
            )

            # 构建响应
            return self._build_response(
                cycle=cycle,
                goal=goal,
                decision=decision,
                exec_result=exec_result,
                db=db,
                goal_id=goal_id,
                student_id=student_id,
            )

        except ValueError:
            db.rollback()
            self._mark_cycle_failed(db, _cycle_id, goal_id)
            raise
        except Exception as exc:
            db.rollback()
            self._mark_cycle_failed(db, _cycle_id, goal_id, str(exc))
            logger.exception("目标推进异常 goal_id=%s cycle_id=%s", goal_id, _cycle_id)
            raise ValueError("目标推进失败，请稍后重试。")

    # ═══════════════════════════════════════════════════════════════
    # 决策：判断下一步应该做什么（文档 Section 13）
    # ═══════════════════════════════════════════════════════════════

    def decide_next_action(
        self,
        db: Session,
        goal: AgentLearningGoal,
        allow_generate_plan: bool,
        allow_replan: bool,
        allow_retry: bool,
        force_step_id: int | None,
    ) -> dict:
        """
        规则优先决策（文档 Section 7.2 决策顺序）。

        返回:
        {
            "decision_type": str,
            "decision_reason": str,
            "target_step_id": int | None,
            "action_required": bool,
            "action_type": str | None,
            "action_payload": dict | None,
        }
        """
        # 2. 目标 canceled/completed → noop
        if goal.status == "canceled":
            return {
                "decision_type": DECISION_NOOP,
                "decision_reason": "目标已取消",
                "target_step_id": None,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
            }
        if goal.status == "completed":
            return {
                "decision_type": DECISION_NOOP,
                "decision_reason": "目标已完成",
                "target_step_id": None,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
            }

        # 3. 目标 paused → blocked
        if goal.status == "paused":
            return {
                "decision_type": DECISION_BLOCKED,
                "decision_reason": "目标已暂停，请先恢复目标",
                "target_step_id": None,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
            }

        # 5. planning_status = none/failed → 生成计划
        if goal.planning_status in ("none", "failed"):
            if allow_generate_plan:
                return {
                    "decision_type": DECISION_GENERATE_PLAN,
                    "decision_reason": "目标尚未生成学习计划",
                    "target_step_id": None,
                    "action_required": False,
                    "action_type": None,
                    "action_payload": None,
                }
            else:
                return {
                    "decision_type": DECISION_BLOCKED,
                    "decision_reason": "目标尚未生成学习计划",
                    "target_step_id": None,
                    "action_required": True,
                    "action_type": ACTION_CONFIRM_GENERATE_PLAN,
                    "action_payload": None,
                }

        # 6. planning_status = planning → blocked
        if goal.planning_status == "planning":
            return {
                "decision_type": DECISION_BLOCKED,
                "decision_reason": "计划正在生成中，请稍后再试",
                "target_step_id": None,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
            }

        # 7. planning_status = replan_needed → 重规划或提示用户
        if goal.planning_status == "replan_needed":
            if allow_replan:
                return {
                    "decision_type": DECISION_REPLAN_GOAL,
                    "decision_reason": "目标需要重新规划，当前已允许自动重规划",
                    "target_step_id": None,
                    "action_required": False,
                    "action_type": None,
                    "action_payload": None,
                }
            else:
                return {
                    "decision_type": DECISION_BLOCKED,
                    "decision_reason": "目标需要重新规划",
                    "target_step_id": None,
                    "action_required": True,
                    "action_type": ACTION_CONFIRM_REPLAN,
                    "action_payload": None,
                }

        # 调试用：强制指定步骤
        if force_step_id:
            step = db.query(AgentGoalStep).filter(
                AgentGoalStep.id == force_step_id,
                AgentGoalStep.goal_id == goal.id,
            ).first()
            if step and step.status in ("pending", "failed_retryable"):
                return {
                    "decision_type": DECISION_EXECUTE_STEP,
                    "decision_reason": f"强制指定步骤：{step.title}",
                    "target_step_id": step.id,
                    "action_required": False,
                    "action_type": None,
                    "action_payload": None,
                }

        # 查询所有步骤
        steps = db.query(AgentGoalStep).filter(
            AgentGoalStep.goal_id == goal.id
        ).order_by(AgentGoalStep.step_order).all()

        # 8. 存在真实等待用户动作的步骤 → wait_user_action。
        # 历史/异常数据中可能出现没有产物、没有 run 的 waiting_user_action；
        # 这种步骤还没被执行过，应允许后续 pending/executable 逻辑继续处理。
        waiting_steps = [s for s in steps if self._is_real_waiting_user_action(db, s)]
        if waiting_steps:
            ws = waiting_steps[0]  # 取第一个等待中的步骤
            action_type, action_payload = self._infer_user_action(db, ws)
            return {
                "decision_type": DECISION_WAIT_USER_ACTION,
                "decision_reason": f"当前步骤需要用户操作：{ws.title}",
                "target_step_id": ws.id,
                "action_required": True,
                "action_type": action_type,
                "action_payload": action_payload,
            }

        # 9. 存在 failed_retryable 步骤 → retry_step
        retryable_steps = [s for s in steps if s.status == "failed_retryable"]
        if retryable_steps:
            rs = retryable_steps[0]
            if allow_retry:
                return {
                    "decision_type": DECISION_RETRY_STEP,
                    "decision_reason": f"发现可重试的失败步骤：{rs.title}",
                    "target_step_id": rs.id,
                    "action_required": False,
                    "action_type": None,
                    "action_payload": None,
                }
            else:
                return {
                    "decision_type": DECISION_BLOCKED,
                    "decision_reason": f"步骤 {rs.title} 执行失败，需要处理",
                    "target_step_id": rs.id,
                    "action_required": True,
                    "action_type": ACTION_RESOLVE_FAILURE,
                    "action_payload": {"step_id": rs.id, "last_error": rs.last_error},
                }

        # 10. 存在 pending 步骤 → execute_step
        pending_steps = [
            s for s in steps
            if s.status == "pending" or self._is_unprepared_waiting_step(db, s)
        ]
        if pending_steps:
            ps = pending_steps[0]
            return {
                "decision_type": DECISION_EXECUTE_STEP,
                "decision_reason": f"发现下一个待执行步骤：{ps.title}",
                "target_step_id": ps.id,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
            }

        # 11. 所有必要步骤 completed/skipped → complete_goal
        all_done = all(s.status in ("completed", "skipped") for s in steps)
        if all_done and steps:
            return {
                "decision_type": DECISION_COMPLETE_GOAL,
                "decision_reason": "所有步骤已完成，可以完成目标",
                "target_step_id": None,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
            }

        # 12. 存在 failed_final/blocked → blocked
        failed_final_steps = [s for s in steps if s.status in ("failed_final", "blocked")]
        if failed_final_steps:
            fs = failed_final_steps[0]
            return {
                "decision_type": DECISION_BLOCKED,
                "decision_reason": f"步骤 {fs.title} 处于 {fs.status} 状态，需要用户处理",
                "target_step_id": fs.id,
                "action_required": True,
                "action_type": ACTION_RESOLVE_FAILURE,
                "action_payload": {"step_id": fs.id, "last_error": fs.last_error},
            }

        # 13. 其他情况 → noop
        return {
            "decision_type": DECISION_NOOP,
            "decision_reason": "当前无需推进",
            "target_step_id": None,
            "action_required": False,
            "action_type": None,
            "action_payload": None,
        }

    # ═══════════════════════════════════════════════════════════════
    # 执行决策（文档 Section 13）
    # ═══════════════════════════════════════════════════════════════

    def execute_decision(
        self,
        db: Session,
        goal: AgentLearningGoal,
        cycle: AgentGoalAdvanceCycle,
        decision: dict,
        student_id: int,
        course_id: int,
    ) -> dict:
        """
        执行决策，返回执行结果字典。
        """
        decision_type = decision["decision_type"]
        target_step_id = decision.get("target_step_id")
        goal_id = goal.id

        # ── generate_plan ──
        if decision_type == DECISION_GENERATE_PLAN:
            from app.services.agent_goal_planner_service import agent_goal_planner_service

            plan_result = agent_goal_planner_service.plan_goal(
                db=db,
                goal_id=goal_id,
                student_id=student_id,
                course_id=course_id,
            )
            return {
                "selected_step_id": None,
                "selected_run_id": None,
                "selected_reflection_id": None,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "result_summary": f"已生成 {plan_result['step_count']} 个学习步骤",
                "cycle_status": "completed",
            }

        # ── execute_step / retry_step ──
        if decision_type in (DECISION_EXECUTE_STEP, DECISION_RETRY_STEP):
            from app.services.agent_goal_step_runner_service import agent_goal_step_runner_service

            try:
                run_result = agent_goal_step_runner_service.run_next_step(
                    db=db,
                    goal_id=goal_id,
                    student_id=student_id,
                    course_id=course_id,
                )

                selected_step_id = run_result.get("step_id")
                selected_run_id = run_result.get("run_id")

                # 检查是否需要用户操作
                step = db.query(AgentGoalStep).filter(
                    AgentGoalStep.id == selected_step_id
                ).first() if selected_step_id else None

                if step and step.status == "waiting_user_action":
                    action_type, action_payload = self._infer_user_action(db, step)
                    return {
                        "selected_step_id": selected_step_id,
                        "selected_run_id": selected_run_id,
                        "selected_reflection_id": None,
                        "action_required": True,
                        "action_type": action_type,
                        "action_payload": action_payload,
                        "result_summary": run_result.get("text"),
                        "cycle_status": "waiting_user_action",
                    }

                # 检查执行是否成功
                run = db.query(AgentGoalRun).filter(
                    AgentGoalRun.id == selected_run_id
                ).first() if selected_run_id else None

                if run and run.status == "failed":
                    return {
                        "selected_step_id": selected_step_id,
                        "selected_run_id": selected_run_id,
                        "selected_reflection_id": None,
                        "action_required": False,
                        "action_type": None,
                        "action_payload": None,
                        "result_summary": run_result.get("text"),
                        "cycle_status": "failed",
                    }

                # 查找关联的 reflection
                reflection = None
                if selected_step_id:
                    reflection = db.query(AgentGoalReflection).filter(
                        AgentGoalReflection.step_id == selected_step_id,
                        AgentGoalReflection.run_id == selected_run_id,
                    ).order_by(AgentGoalReflection.created_at.desc()).first()

                return {
                    "selected_step_id": selected_step_id,
                    "selected_run_id": selected_run_id,
                    "selected_reflection_id": reflection.id if reflection else None,
                    "action_required": False,
                    "action_type": None,
                    "action_payload": None,
                    "result_summary": run_result.get("text"),
                    "cycle_status": "completed",
                }

            except ValueError:
                # run_next_step 可能抛出 "没有可执行的步骤" 等错误
                raise

        # ── wait_user_action ──
        if decision_type == DECISION_WAIT_USER_ACTION:
            # 不执行任何操作，直接返回已有动作信息
            return {
                "selected_step_id": decision.get("target_step_id"),
                "selected_run_id": None,
                "selected_reflection_id": None,
                "action_required": True,
                "action_type": decision.get("action_type"),
                "action_payload": decision.get("action_payload"),
                "result_summary": None,
                "cycle_status": "waiting_user_action",
            }

        # ── replan_goal ──
        if decision_type == DECISION_REPLAN_GOAL:
            from app.services.agent_goal_planner_service import agent_goal_planner_service

            replan_result = agent_goal_planner_service.replan_goal(
                db=db,
                goal_id=goal_id,
                student_id=student_id,
                course_id=course_id,
                reason="Agent 自动检测到需要重规划",
                preserve_completed_steps=True,
            )
            return {
                "selected_step_id": None,
                "selected_run_id": None,
                "selected_reflection_id": None,
                "action_required": False,
                "action_type": None,
                "action_payload": None,
                "result_summary": f"已重新规划，新增 {replan_result['step_count']} 个步骤",
                "cycle_status": "completed",
            }

        # ── complete_goal ──
        if decision_type == DECISION_COMPLETE_GOAL:
            from app.services.agent_goal_service import agent_goal_service as ags

            completed = ags.check_goal_completion(db, goal_id)
            if completed:
                return {
                    "selected_step_id": None,
                    "selected_run_id": None,
                    "selected_reflection_id": None,
                    "action_required": False,
                    "action_type": None,
                    "action_payload": None,
                    "result_summary": "恭喜，目标已完成！",
                    "cycle_status": "completed",
                }
            else:
                # 如果检查发现没有全部完成，退回 noop
                return {
                    "selected_step_id": None,
                    "selected_run_id": None,
                    "selected_reflection_id": None,
                    "action_required": False,
                    "action_type": None,
                    "action_payload": None,
                    "result_summary": "目标尚未满足完成条件",
                    "cycle_status": "blocked",
                }

        # ── blocked / noop ──
        return {
            "selected_step_id": decision.get("target_step_id"),
            "selected_run_id": None,
            "selected_reflection_id": None,
            "action_required": decision.get("action_required", False),
            "action_type": decision.get("action_type"),
            "action_payload": decision.get("action_payload"),
            "result_summary": None,
            "cycle_status": decision_type if decision_type in ("blocked", "noop") else "completed",
        }

    # ═══════════════════════════════════════════════════════════════
    # 目标快照（文档 Section 12.2）
    # ═══════════════════════════════════════════════════════════════

    def build_goal_snapshot(self, db: Session, goal: AgentLearningGoal) -> dict:
        """生成目标当前状态快照，用于 before/after 对比"""
        steps = db.query(AgentGoalStep).filter(
            AgentGoalStep.goal_id == goal.id
        ).order_by(AgentGoalStep.step_order).all()

        return {
            "goal_status": goal.status,
            "planning_status": goal.planning_status,
            "progress_percent": float(goal.progress_percent) if goal.progress_percent else 0,
            "steps": [
                {
                    "id": s.id,
                    "step_order": s.step_order,
                    "title": s.title,
                    "status": s.status,
                    "step_type": s.step_type,
                    "needs_user_action": bool(s.needs_user_action),
                }
                for s in steps
            ],
            "snapshot_at": datetime.utcnow().isoformat(),
        }

    # ═══════════════════════════════════════════════════════════════
    # 推进记录查询
    # ═══════════════════════════════════════════════════════════════

    def list_advance_cycles(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        limit: int = 10,
    ) -> list[dict]:
        """获取目标的推进记录列表"""
        from app.services.agent_goal_service import agent_goal_service

        agent_goal_service._get_goal_for_user(db, goal_id, student_id)

        cycles = db.query(AgentGoalAdvanceCycle).filter(
            AgentGoalAdvanceCycle.goal_id == goal_id,
        ).order_by(AgentGoalAdvanceCycle.started_at.desc()).limit(limit).all()

        return [self._serialize_cycle(c) for c in cycles]

    def get_advance_cycle_detail(
        self,
        db: Session,
        goal_id: int,
        cycle_id: int,
        student_id: int,
    ) -> dict:
        """获取单次推进详情（含快照和追踪信息）"""
        from app.services.agent_goal_service import agent_goal_service

        agent_goal_service._get_goal_for_user(db, goal_id, student_id)

        cycle = db.query(AgentGoalAdvanceCycle).filter(
            AgentGoalAdvanceCycle.id == cycle_id,
            AgentGoalAdvanceCycle.goal_id == goal_id,
        ).first()

        if not cycle:
            raise ValueError("推进记录不存在")

        result = self._serialize_cycle(cycle)
        result["before_snapshot"] = cycle.before_snapshot_json
        result["after_snapshot"] = cycle.after_snapshot_json
        result["agent_trace"] = cycle.agent_trace_json

        # 关联步骤信息
        if cycle.selected_step_id:
            step = db.query(AgentGoalStep).filter(
                AgentGoalStep.id == cycle.selected_step_id
            ).first()
            if step:
                result["selected_step"] = {
                    "id": step.id,
                    "title": step.title,
                    "step_type": step.step_type,
                    "status": step.status,
                }

        # 关联 run 信息
        if cycle.selected_run_id:
            run = db.query(AgentGoalRun).filter(
                AgentGoalRun.id == cycle.selected_run_id
            ).first()
            if run:
                from app.services.agent_goal_service import agent_goal_service
                result["selected_run"] = agent_goal_service.serialize_run(run)

        return result

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    def _is_real_waiting_user_action(self, db: Session, step: AgentGoalStep) -> bool:
        """Return True only when the step has generated something for the user."""
        if step.status != "waiting_user_action":
            return False
        if step.user_action_status == "completed":
            return False
        if step.needs_user_action:
            return True
        if step.output_ref_json:
            return True
        if step.last_run_id:
            return True
        latest_run = (
            db.query(AgentGoalRun.id)
            .filter(AgentGoalRun.step_id == step.id)
            .first()
        )
        return latest_run is not None

    def _is_unprepared_waiting_step(self, db: Session, step: AgentGoalStep) -> bool:
        """Treat stale waiting_user_action without output as executable."""
        return step.status == "waiting_user_action" and not self._is_real_waiting_user_action(db, step)

    def _infer_user_action(self, db: Session, step: AgentGoalStep) -> tuple[str | None, dict | None]:
        """
        从步骤推断用户需要做什么（文档 Section 13.2）。

        返回 (action_type, action_payload)
        """
        # 优先使用步骤显式字段
        if step.user_action_type:
            action_type = step.user_action_type
        else:
            action_type = USER_ACTION_STEP_TYPE_MAP.get(step.step_type)

        # 构建 payload
        payload = {}
        if step.output_ref_json:
            payload = dict(step.output_ref_json)

        # 练习类：从 output_ref 或 run 中找 session_id
        if action_type in (ACTION_PRACTICE_SESSION, "answer_practice"):
            action_type = ACTION_PRACTICE_SESSION
            if not payload.get("session_id"):
                # 从最近的 run 中找 practice_session_id
                latest_run = db.query(AgentGoalRun).filter(
                    AgentGoalRun.step_id == step.id,
                ).order_by(AgentGoalRun.started_at.desc()).first()
                if latest_run and latest_run.practice_session_id:
                    payload["session_id"] = latest_run.practice_session_id
                    if not payload.get("question_count"):
                        payload["question_count"] = (
                            latest_run.tool_result_json or {}
                        ).get("question_count")

        # 文档类：从 output_ref 或 run 中找 document_id
        if action_type == ACTION_READ_DOCUMENT:
            if not payload.get("document_id"):
                latest_run = db.query(AgentGoalRun).filter(
                    AgentGoalRun.step_id == step.id,
                ).order_by(AgentGoalRun.started_at.desc()).first()
                if latest_run and latest_run.generated_document_id:
                    payload["document_id"] = latest_run.generated_document_id

        return action_type, (payload if payload else None)

    def _build_user_message(
        self,
        decision: dict,
        exec_result: dict,
    ) -> str:
        """
        构建面向用户的自然语言摘要（文档 Section 5.2）。
        不能出现 step_type、tool_name、ID=14 等内部字段。
        """
        decision_type = decision["decision_type"]

        if decision_type == DECISION_GENERATE_PLAN:
            return exec_result.get("result_summary", "已生成学习计划，可以继续推进第一步。")

        if decision_type == DECISION_EXECUTE_STEP:
            result = exec_result.get("result_summary", "")
            if result:
                return result
            return "已完成当前步骤，可以继续推进下一步。"

        if decision_type == DECISION_RETRY_STEP:
            result = exec_result.get("result_summary", "")
            if result:
                return result
            return "已重试失败步骤。"

        if decision_type == DECISION_WAIT_USER_ACTION:
            action_type = exec_result.get("action_type", "")
            if action_type == ACTION_PRACTICE_SESSION:
                qc = ""
                payload = exec_result.get("action_payload") or {}
                if payload.get("question_count"):
                    qc = f"（共 {payload['question_count']} 题）"
                return f"请先完成当前练习{qc}，完成后我会继续推进目标。"
            elif action_type == ACTION_READ_DOCUMENT:
                return "请先阅读练习文档，完成后我会继续推进目标。"
            elif action_type == ACTION_MANUAL_COMPLETE:
                return "请完成当前线下任务后标记完成，我会继续推进目标。"
            else:
                return "请先完成当前步骤，完成后我会继续推进目标。"

        if decision_type == DECISION_REPLAN_GOAL:
            return exec_result.get("result_summary", "目标已重新规划。")

        if decision_type == DECISION_COMPLETE_GOAL:
            return "恭喜！目标所有步骤已完成，目标达成！"

        if decision_type == DECISION_BLOCKED:
            action_type = exec_result.get("action_type", "")
            if action_type == ACTION_CONFIRM_REPLAN:
                return "当前目标需要重新规划，请确认后继续。"
            elif action_type == ACTION_RESOLVE_FAILURE:
                return "当前步骤执行失败，请查看失败原因并决定是否重试。"
            elif action_type == ACTION_CONFIRM_GENERATE_PLAN:
                return "目标尚未生成学习计划，请先生成计划。"
            else:
                return decision.get("decision_reason", "当前无法继续推进。")

        if decision_type == DECISION_NOOP:
            return decision.get("decision_reason", "当前无需推进。")

        return "目标推进完成。"

    def _build_response(
        self,
        cycle: AgentGoalAdvanceCycle,
        goal: AgentLearningGoal,
        decision: dict,
        exec_result: dict,
        db: Session,
        goal_id: int,
        student_id: int,
    ) -> dict:
        """构建统一的推进响应"""
        from app.services.agent_goal_service import agent_goal_service

        response = {
            "cycle_id": cycle.id,
            "cycle_uuid": cycle.cycle_uuid,
            "goal_id": goal_id,
            "status": cycle.status,
            "decision_type": cycle.decision_type,
            "decision_reason": cycle.decision_reason,
            "selected_step_id": cycle.selected_step_id,
            "selected_run_id": cycle.selected_run_id,
            "action_required": bool(cycle.action_required),
            "action_type": cycle.action_type,
            "action_payload": cycle.action_payload_json,
            "result_summary": cycle.result_summary,
            "user_message": goal.last_agent_summary or self._build_user_message(decision, exec_result),
            "goal": agent_goal_service._serialize_goal(goal) if goal else None,
            "step": None,
            "run": None,
            "reflection": None,
        }

        # 关联步骤
        if cycle.selected_step_id:
            step = db.query(AgentGoalStep).filter(
                AgentGoalStep.id == cycle.selected_step_id
            ).first()
            if step:
                response["step"] = agent_goal_service._serialize_step(step)

        # 关联 run
        if cycle.selected_run_id:
            run = db.query(AgentGoalRun).filter(
                AgentGoalRun.id == cycle.selected_run_id
            ).first()
            if run:
                response["run"] = agent_goal_service.serialize_run(run)

        # 关联 reflection
        if cycle.selected_reflection_id:
            reflection = db.query(AgentGoalReflection).filter(
                AgentGoalReflection.id == cycle.selected_reflection_id
            ).first()
            if reflection:
                response["reflection"] = agent_goal_service._serialize_reflection(reflection)

        return response

    def _mark_cycle_failed(
        self,
        db: Session,
        cycle_id: int,
        goal_id: int,
        error_message: str | None = None,
    ):
        """将推进记录标记为失败（文档 Section 12.5）"""
        try:
            cycle = db.query(AgentGoalAdvanceCycle).filter(
                AgentGoalAdvanceCycle.id == cycle_id
            ).first()
            if cycle:
                cycle.status = "failed"
                cycle.error_message = error_message
                cycle.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            logger.exception("标记 cycle 失败时出错 cycle_id=%s", cycle_id)
            try:
                db.rollback()
            except Exception:
                pass

    @staticmethod
    def _serialize_cycle(cycle: AgentGoalAdvanceCycle) -> dict:
        """序列化推进记录为字典"""
        return {
            "id": cycle.id,
            "cycle_uuid": cycle.cycle_uuid,
            "goal_id": cycle.goal_id,
            "status": cycle.status,
            "decision_type": cycle.decision_type,
            "decision_reason": cycle.decision_reason,
            "selected_step_id": cycle.selected_step_id,
            "selected_run_id": cycle.selected_run_id,
            "action_required": bool(cycle.action_required),
            "action_type": cycle.action_type,
            "action_payload": cycle.action_payload_json,
            "result_summary": cycle.result_summary,
            "error_message": cycle.error_message,
            "started_at": cycle.started_at,
            "finished_at": cycle.finished_at,
        }


agent_goal_advance_service = AgentGoalAdvanceService()
