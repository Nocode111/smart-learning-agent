"""
长期目标计划拆解服务（文档 Section 9）

职责：
1. 读取目标、知识点、画像、薄弱点
2. 调用 LLM 生成结构化计划
3. 校验 JSON 输出
4. 规范化步骤并写入数据库
5. 更新目标状态
"""

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.agent_goal import AgentLearningGoal, AgentGoalStep
from app.models.knowledge_point import KnowledgePoint

logger = logging.getLogger(__name__)

# 白名单（文档 Section 9.3）
# 注意：recommendation_sync 暂缓，待回归测试完成后恢复
ALLOWED_GOAL_STEP_TOOLS = {
    "qa_answer",
    "generate_inline_practice",
    "generate_exercise_document",
    "profile_check",
    "manual_task",
}

# step_type -> 允许的 tool_name 映射
STEP_TYPE_TOOL_MAP = {
    "diagnostic_quiz": "generate_inline_practice",
    "qa_explanation": "qa_answer",
    "inline_practice": "generate_inline_practice",
    "exercise_document": "generate_exercise_document",
    "profile_check": "profile_check",
    "recommendation_sync": "recommendation_sync",
    "review_summary": "manual_task",
    "manual_task": "manual_task",
}

# tool_name -> step_type 反向映射
TOOL_NAME_STEP_TYPE_MAP = {v: k for k, v in STEP_TYPE_TOOL_MAP.items()}


class AgentGoalPlannerService:
    """计划拆解服务"""

    # ── 主入口 ────────────────────────────────────────────────

    def plan_goal(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        course_id: int,
        diagnostic_requirement: str | None = None,
    ) -> dict:
        """
        为目标生成学习计划。

        流程:
        1. 校验 goal 属于当前用户
        2. 校验 goal 状态允许规划
        3. 设置 planning_status = planning
        4. 构建上下文并调用 LLM
        5. 校验 JSON 输出
        6. 删除旧的未执行步骤
        7. 写入新步骤
        8. 更新 goal 状态
        """
        from app.services.agent_goal_service import agent_goal_service

        goal = agent_goal_service._get_goal_for_user(db, goal_id, student_id)

        if goal.planning_status == "planning":
            raise ValueError("计划正在生成中，请稍后再试")

        if goal.status == "completed":
            raise ValueError("已完成的目标无法重新生成计划")

        if goal.status == "canceled":
            raise ValueError("已取消的目标无法生成计划")

        # 标记为规划中
        goal.planning_status = "planning"
        db.commit()
        logger.info("开始生成计划 goal_id=%s", goal_id)

        try:
            # 构建上下文
            context = self._build_planning_context(db, goal, student_id, course_id)

            # 调用 LLM
            from app.prompts.agent_goal_planner_prompt import build_goal_planner_prompt
            from app.services.qwen_client import qwen_client

            messages = build_goal_planner_prompt(
                title=goal.title,
                goal_text=goal.goal_text,
                target_score=float(goal.target_score) if goal.target_score else None,
                due_date=str(goal.due_date) if goal.due_date else None,
                course_knowledge_points=context["course_knowledge_points"],
                overall_level=context["overall_level"],
                knowledge_mastery=context["knowledge_mastery"],
                weak_points=context["weak_points"],
                diagnostic_requirement=diagnostic_requirement,
            )

            llm_output = qwen_client.chat(messages=messages, temperature=0.3)

            # 解析 JSON
            parsed = self._parse_plan_json(llm_output)

            plan_summary = parsed.get("plan_summary", "")
            steps_data = parsed.get("steps", [])

            if not steps_data:
                raise ValueError("LLM 没有生成任何步骤，请重试。")

            if len(steps_data) < 3:
                raise ValueError(f"生成的步骤太少（{len(steps_data)} 步），至少需要 3 步。请重试。")

            if len(steps_data) > 15:
                raise ValueError(f"生成的步骤太多（{len(steps_data)} 步），最多 15 步。请重试。")

            # 校验每个步骤
            valid_kp_ids = {kp.id for kp in context["knowledge_points"]}
            for i, sd in enumerate(steps_data):
                self._validate_step(sd, i + 1, valid_kp_ids)

            # 删除旧的未执行步骤（pending/running/failed_retryable），保留已完成的
            db.query(AgentGoalStep).filter(
                AgentGoalStep.goal_id == goal_id,
                AgentGoalStep.status.in_(
                    ["pending", "running", "failed_retryable", "blocked"]
                ),
            ).delete(synchronize_session=False)
            db.flush()

            # 写入新步骤
            new_steps = []
            for sd in steps_data:
                step = AgentGoalStep(
                    goal_id=goal_id,
                    student_id=student_id,
                    course_id=course_id,
                    step_order=sd["step_order"],
                    title=sd["title"],
                    description=sd.get("description"),
                    step_type=sd["step_type"],
                    tool_name=sd.get("tool_name"),
                    tool_args_json=sd.get("tool_args"),
                    expected_outcome=sd.get("expected_outcome"),
                    success_criteria_json=sd.get("success_criteria"),
                    target_knowledge_point_ids=sd.get("target_knowledge_point_ids"),
                    estimated_minutes=sd.get("estimated_minutes"),
                    status="pending",
                )
                db.add(step)
                new_steps.append(step)

            db.flush()

            # 更新 goal 状态
            goal.planning_status = "planned"
            goal.plan_summary = plan_summary
            goal.plan_json = parsed
            if goal.status == "draft":
                goal.status = "active"
                goal.activated_at = datetime.utcnow()
            db.commit()

            logger.info(
                "计划生成成功 goal_id=%s step_count=%s",
                goal_id,
                len(new_steps),
            )

            return {
                "goal_id": goal_id,
                "planning_status": "planned",
                "step_count": len(new_steps),
                "plan_summary": plan_summary,
                "message": f"学习计划已生成，共 {len(new_steps)} 个步骤。",
            }

        except ValueError:
            db.rollback()
            # 标记规划失败
            goal = db.query(AgentLearningGoal).filter(
                AgentLearningGoal.id == goal_id
            ).first()
            if goal:
                goal.planning_status = "failed"
                db.commit()
            raise
        except Exception:
            db.rollback()
            goal = db.query(AgentLearningGoal).filter(
                AgentLearningGoal.id == goal_id
            ).first()
            if goal:
                goal.planning_status = "failed"
                db.commit()
            logger.exception("计划生成异常 goal_id=%s", goal_id)
            raise ValueError("计划生成失败，请稍后重试。")

    # ── 上下文构建 ────────────────────────────────────────────

    def _build_planning_context(
        self,
        db: Session,
        goal: AgentLearningGoal,
        student_id: int,
        course_id: int,
    ) -> dict:
        """构建计划生成的上下文"""
        from app.services.profile_service import profile_service

        # 课程知识点
        knowledge_points = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.course_id == course_id)
            .all()
        )

        if knowledge_points:
            course_kp_text = "\n".join(
                f"- ID={kp.id}: {kp.name}" for kp in knowledge_points
            )
        else:
            course_kp_text = "（暂无知识点数据）"

        # 画像
        try:
            profile = profile_service.get_profile_for_agent(db, student_id, course_id)
            overall_level = profile.get("overall_level", "暂无数据")
            knowledge_mastery = json.dumps(
                profile.get("knowledge_mastery", []),
                ensure_ascii=False,
                indent=2,
            )
            weak_points = json.dumps(
                profile.get("weak_points", []),
                ensure_ascii=False,
                indent=2,
            )
        except Exception:
            overall_level = "暂无数据"
            knowledge_mastery = "暂无数据"
            weak_points = "暂无数据"

        return {
            "knowledge_points": knowledge_points,
            "course_knowledge_points": course_kp_text,
            "overall_level": overall_level,
            "knowledge_mastery": knowledge_mastery,
            "weak_points": weak_points,
        }

    # ── JSON 解析 ─────────────────────────────────────────────

    def _parse_plan_json(self, llm_output: str) -> dict:
        """解析 LLM 输出的 JSON（文档 Section 9.1）"""
        llm_output = (llm_output or "").strip()

        parsed = None
        try:
            parsed = json.loads(llm_output)
        except json.JSONDecodeError:
            # 尝试截取 { 到 }
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(llm_output[start:end + 1])
                except json.JSONDecodeError:
                    pass

        if not parsed or not isinstance(parsed, dict):
            raise ValueError("LLM 输出无法解析为 JSON，请重试。")

        return parsed

    # ── 步骤校验 ──────────────────────────────────────────────

    def _validate_step(
        self,
        step: dict,
        index: int,
        valid_kp_ids: set[int],
    ):
        """校验单个步骤的合法性（文档 Section 9.2）"""
        step_type = step.get("step_type", "")
        tool_name = step.get("tool_name", "")
        title = step.get("title", "")

        if not step_type:
            raise ValueError(f"第 {index} 步缺少 step_type")

        if not tool_name:
            raise ValueError(f"第 {index} 步缺少 tool_name")

        if not title:
            raise ValueError(f"第 {index} 步缺少 title")

        # 白名单校验
        if tool_name not in ALLOWED_GOAL_STEP_TOOLS:
            raise ValueError(
                f"第 {index} 步的 tool_name '{tool_name}' 不在白名单中。"
                f" 允许的工具：{', '.join(sorted(ALLOWED_GOAL_STEP_TOOLS))}"
            )

        # step_type 与 tool_name 一致性
        expected_step_type = TOOL_NAME_STEP_TYPE_MAP.get(tool_name)
        if expected_step_type and step_type != expected_step_type:
            # manual_task 可以对应 review_summary 或 manual_task
            if tool_name == "manual_task" and step_type in ("manual_task", "review_summary"):
                pass
            else:
                logger.warning(
                    "步骤 %s step_type='%s' 与 tool_name='%s' 不匹配，继续使用",
                    index, step_type, tool_name,
                )

        # 知识点校验
        kp_ids = step.get("target_knowledge_point_ids", [])
        if kp_ids:
            invalid_ids = set(kp_ids) - valid_kp_ids
            if invalid_ids:
                logger.warning(
                    "步骤 %s 包含无效知识点 ID: %s，将被忽略",
                    index, invalid_ids,
                )

        # step_order 校验
        step_order = step.get("step_order")
        if not isinstance(step_order, int) or step_order < 1:
            raise ValueError(f"第 {index} 步的 step_order 必须是正整数")


    # ── 重新规划（文档 Section 14） ──────────────────────────

    def replan_goal(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        course_id: int,
        reason: str | None = None,
        preserve_completed_steps: bool = True,
    ) -> dict:
        """
        重新规划目标（文档 Section 14.2）。

        策略：
        1. 保留 completed/skipped 步骤。
        2. 未完成步骤标记为 skipped（不物理删除）。
        3. 新步骤从当前最大 step_order + 1 开始追加。
        """
        from app.services.agent_goal_service import agent_goal_service

        goal = agent_goal_service._get_goal_for_user(db, goal_id, student_id)

        if goal.status in ("completed", "canceled"):
            raise ValueError(f"目标状态为 {goal.status}，不能重新规划")

        # 标记为规划中
        goal.planning_status = "planning"
        db.commit()
        logger.info("开始重新规划 goal_id=%s reason=%s", goal_id, reason)

        try:
            # 构建重规划上下文
            context = self._build_planning_context(db, goal, student_id, course_id)
            replan_context = self._build_replan_context(db, goal, reason)

            # 调用 LLM
            from app.prompts.agent_goal_planner_prompt import build_goal_replan_prompt
            from app.services.qwen_client import qwen_client

            messages = build_goal_replan_prompt(
                title=goal.title,
                goal_text=goal.goal_text,
                target_score=float(goal.target_score) if goal.target_score else None,
                due_date=str(goal.due_date) if goal.due_date else None,
                course_knowledge_points=context["course_knowledge_points"],
                overall_level=context["overall_level"],
                knowledge_mastery=context["knowledge_mastery"],
                weak_points=context["weak_points"],
                completed_steps=replan_context["completed_steps_text"],
                failed_steps=replan_context["failed_steps_text"],
                recent_reflections=replan_context["recent_reflections_text"],
                replan_reason=replan_context["reason_text"],
            )

            llm_output = qwen_client.chat(messages=messages, temperature=0.3)

            # 解析 JSON
            parsed = self._parse_plan_json(llm_output)

            plan_summary = parsed.get("plan_summary", "")
            steps_data = parsed.get("steps", [])

            if not steps_data:
                raise ValueError("LLM 没有生成任何步骤，请重试。")

            # 校验每个步骤
            valid_kp_ids = {kp.id for kp in context["knowledge_points"]}
            for i, sd in enumerate(steps_data):
                self._validate_step(sd, i + 1, valid_kp_ids)

            # 保留已完成步骤，标记未完成步骤为 skipped（文档 Section 14.2）
            if preserve_completed_steps:
                existing_steps = db.query(AgentGoalStep).filter(
                    AgentGoalStep.goal_id == goal_id
                ).all()

                current_max_order = 0
                for es in existing_steps:
                    if es.step_order > current_max_order:
                        current_max_order = es.step_order
                    if es.status not in ("completed", "skipped"):
                        es.status = "skipped"
                        es.result_summary = es.result_summary or "因重新规划跳过"
                db.flush()
            else:
                # 不保留，全部删除（除 completed）
                db.query(AgentGoalStep).filter(
                    AgentGoalStep.goal_id == goal_id,
                    AgentGoalStep.status.in_(
                        ["pending", "running", "failed_retryable", "blocked", "waiting_user_action"]
                    ),
                ).delete(synchronize_session=False)
                db.flush()

                current_max_order = (
                    db.query(AgentGoalStep.step_order)
                    .filter(AgentGoalStep.goal_id == goal_id)
                    .order_by(AgentGoalStep.step_order.desc())
                    .first()
                )
                current_max_order = current_max_order[0] if current_max_order else 0

            # 写入新步骤（追加）
            next_order = current_max_order + 1
            new_steps = []
            for sd in steps_data:
                step = AgentGoalStep(
                    goal_id=goal_id,
                    student_id=student_id,
                    course_id=course_id,
                    step_order=next_order,
                    title=sd.get("title", ""),
                    description=sd.get("description"),
                    step_type=sd["step_type"],
                    tool_name=sd.get("tool_name"),
                    tool_args_json=sd.get("tool_args"),
                    expected_outcome=sd.get("expected_outcome"),
                    success_criteria_json=sd.get("success_criteria"),
                    target_knowledge_point_ids=sd.get("target_knowledge_point_ids"),
                    estimated_minutes=sd.get("estimated_minutes"),
                    status="pending",
                    metadata_json={
                        "source": "replan",
                        "replan_reason": reason,
                    },
                )
                db.add(step)
                new_steps.append(step)
                next_order += 1

            db.flush()

            # 更新 goal 状态
            goal.planning_status = "planned"
            goal.plan_summary = plan_summary
            goal.plan_json = parsed
            if goal.status == "draft":
                goal.status = "active"
                goal.activated_at = datetime.utcnow()
            db.commit()

            # 刷新进度
            progress = agent_goal_service.recalculate_progress(db, goal_id)
            goal.progress_percent = progress
            db.commit()

            logger.info(
                "重新规划成功 goal_id=%s new_step_count=%s",
                goal_id,
                len(new_steps),
            )

            return {
                "goal_id": goal_id,
                "planning_status": "planned",
                "step_count": len(new_steps),
                "plan_summary": plan_summary,
                "message": f"目标已重新规划，新增 {len(new_steps)} 个步骤。",
            }

        except ValueError:
            db.rollback()
            goal = db.query(AgentLearningGoal).filter(
                AgentLearningGoal.id == goal_id
            ).first()
            if goal:
                goal.planning_status = "failed"
                db.commit()
            raise
        except Exception:
            db.rollback()
            goal = db.query(AgentLearningGoal).filter(
                AgentLearningGoal.id == goal_id
            ).first()
            if goal:
                goal.planning_status = "failed"
                db.commit()
            logger.exception("重新规划异常 goal_id=%s", goal_id)
            raise ValueError("重新规划失败，请稍后重试。")

    # ── 重规划上下文构建 ──────────────────────────────────────

    def _build_replan_context(self, db: Session, goal, reason: str | None) -> dict:
        """构建重新规划的上下文信息"""
        # 已完成步骤
        completed_steps = (
            db.query(AgentGoalStep)
            .filter(
                AgentGoalStep.goal_id == goal.id,
                AgentGoalStep.status == "completed",
            )
            .order_by(AgentGoalStep.step_order)
            .all()
        )

        # 失败/阻塞步骤
        failed_steps = (
            db.query(AgentGoalStep)
            .filter(
                AgentGoalStep.goal_id == goal.id,
                AgentGoalStep.status.in_(["failed_retryable", "failed_final", "blocked", "waiting_user_action"]),
            )
            .order_by(AgentGoalStep.step_order)
            .all()
        )

        # 最近复盘
        recent_reflections = (
            db.query(AgentGoalReflection)
            .filter(AgentGoalReflection.goal_id == goal.id)
            .order_by(desc(AgentGoalReflection.created_at))
            .limit(5)
            .all()
        )

        completed_steps_text = "\n".join(
            f"- 步骤 {s.step_order}: {s.title}（{s.status}） → {s.result_summary or '无总结'}"
            for s in completed_steps
        ) if completed_steps else "（无已完成步骤）"

        failed_steps_text = "\n".join(
            f"- 步骤 {s.step_order}: {s.title}（{s.status}） → {s.last_error or s.result_summary or '无详情'}"
            for s in failed_steps
        ) if failed_steps else "（无失败步骤）"

        recent_reflections_text = "\n".join(
            f"- 复盘 {r.id}: 成功={bool(r.is_success)} 质量={r.quality_score} → {r.summary or '无总结'} next_action={r.next_action}"
            for r in recent_reflections
        ) if recent_reflections else "（无近期复盘）"

        return {
            "completed_steps_text": completed_steps_text,
            "failed_steps_text": failed_steps_text,
            "recent_reflections_text": recent_reflections_text,
            "reason_text": reason or "用户手动触发重新规划",
        }


agent_goal_planner_service = AgentGoalPlannerService()
