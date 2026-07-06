"""
长期目标步骤执行服务（文档 Section 10 + 执行闭环增强 Section 9.2）

职责：
1. 找到下一个待执行步骤
2. 创建 run 记录
3. 标记 step 为 running
4. 根据 step_type 调用对应工具
5. 保存工具结果
6. 调用复盘服务
7. 应用复盘动作
8. 更新 step 和 goal 进度
9. waiting_user_action 状态流管理
10. 质量门禁评估
"""

import json
import logging
import uuid

from sqlalchemy.orm import Session

import app.models  # noqa: F401  # ensure FK target tables are registered
from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun
from app.utils.time_utils import now_shanghai

logger = logging.getLogger(__name__)

# 步骤执行后状态映射（文档 Section 9.2.1）
_STEP_POST_STATUS: dict[str, str] = {
    "profile_check": "completed",
    "qa_explanation": "waiting_user_action",
    "inline_practice": "waiting_user_action",
    "diagnostic_quiz": "waiting_user_action",
    "exercise_document": "waiting_user_action",
    "recommendation_sync": "completed",
    "review_summary": "waiting_user_action",
    "manual_task": "waiting_user_action",
}


class AgentGoalStepRunnerService:
    """步骤执行服务"""

    # ── 选择下一步（文档 Section 10.1） ────────────────────────

    @staticmethod
    def _find_next_step(db: Session, goal_id: int) -> AgentGoalStep | None:
        """选择下一个待执行步骤"""
        return (
            db.query(AgentGoalStep)
            .filter(
                AgentGoalStep.goal_id == goal_id,
                AgentGoalStep.status.in_(["pending", "failed_retryable"]),
            )
            .order_by(AgentGoalStep.step_order)
            .first()
        )

    # ── 确保目标专用 Agent 对话（文档 Section 9.2.2） ─────────

    @staticmethod
    def _ensure_goal_conversation(
        db: Session,
        goal: AgentLearningGoal,
        student_id: int,
        course_id: int,
    ) -> int:
        """获取或创建目标专用的 Agent 对话"""
        if goal.conversation_id:
            return goal.conversation_id

        from app.models.agent_conversation import AgentConversation
        from app.models.course import Course

        course = db.query(Course).filter(Course.id == course_id).first()
        course_name = course.name if course else f"课程{course_id}"

        conv = AgentConversation(
            student_id=student_id,
            course_id=course_id,
            title=f"📌 学习目标：{goal.title[:50]}",
            status="active",
        )
        db.add(conv)
        db.flush()

        goal.conversation_id = conv.id
        db.commit()

        logger.info("为目标创建专用对话 goal_id=%s conversation_id=%s", goal.id, conv.id)
        return conv.id

    # ── 主入口：执行下一步（文档 Section 10） ──────────────────

    def run_next_step(
        self,
        db: Session,
        goal_id: int,
        student_id: int,
        course_id: int,
    ) -> dict:
        """
        执行下一个待执行步骤。

        流程:
        1. 找到下一个 pending/failed_retryable 步骤
        2. 创建 run 记录
        3. 标记 step 为 running
        4. 根据 step_type 调用对应工具
        5. 保存工具结果
        6. 根据 step_type 决定执行后状态（waiting_user_action / completed）
        7. 调用复盘服务
        8. 应用复盘动作
        9. 更新 step 和 goal 进度
        """
        from app.services.agent_goal_service import agent_goal_service

        # 1. 校验目标
        goal = agent_goal_service._get_goal_for_user(db, goal_id, student_id)
        if goal.status not in ("active", "paused"):
            raise ValueError(f"当前目标状态为 {goal.status}，无法执行步骤")

        if goal.planning_status not in ("planned", "replan_needed"):
            raise ValueError("请先生成学习计划")

        # 2. 查找下一步
        step = self._find_next_step(db, goal_id)
        if not step:
            # 检查是否所有步骤都已完成
            all_done = agent_goal_service.check_goal_completion(db, goal_id)
            if all_done:
                return {
                    "run_id": 0,
                    "run_uuid": "",
                    "goal_id": goal_id,
                    "step_id": 0,
                    "status": "goal_completed",
                    "text": "恭喜！所有学习步骤已完成，目标达成！",
                    "agent_steps": [],
                    "reflection": None,
                }
            raise ValueError("当前没有可执行的步骤，所有步骤已完成或最终失败")

        # 3. 如果是 manual_task，不允许自动执行
        if step.step_type == "manual_task":
            step.status = "blocked"
            db.commit()
            raise ValueError(
                f"「{step.title}」是线下任务，请手动完成后再标记。"
            )

        # 4. 创建 run 记录
        run_uuid_str = f"goal_run_{uuid.uuid4().hex[:16]}"
        run = AgentGoalRun(
            goal_id=goal_id,
            step_id=step.id,
            student_id=student_id,
            course_id=course_id,
            run_uuid=run_uuid_str,
            status="running",
            tool_name=step.tool_name,
            tool_args_json=step.tool_args_json,
            started_at=now_shanghai(),
        )
        db.add(run)
        db.flush()

        # 5. 标记 step 为 running
        step.status = "running"
        step.started_at = now_shanghai()
        step.last_run_id = run.id
        db.commit()

        logger.info("开始执行步骤 step_id=%s goal_id=%s step_type=%s", step.id, goal_id, step.step_type)

        # 6. 执行工具
        agent_steps = []
        tool_result = {}
        error_msg = None
        output_message_id = None
        qa_id = None
        practice_session_id = None
        generated_document_id = None

        # 保存 ID 以备异常处理使用（文档 Section 6.3）
        _run_id = run.id
        _step_id = step.id

        try:
            tool_result, agent_steps, extras = self._execute_step(
                db=db,
                step=step,
                student_id=student_id,
                course_id=course_id,
                run=run,
                goal=goal,
            )
            output_message_id = extras.get("output_message_id")
            qa_id = extras.get("qa_id")
            practice_session_id = extras.get("practice_session_id")
            generated_document_id = extras.get("generated_document_id")

            # 更新 run 为 completed
            run.status = "completed"
            run.tool_result_json = tool_result
            run.agent_steps_json = agent_steps
            run.output_message_id = output_message_id
            run.qa_id = qa_id
            run.practice_session_id = practice_session_id
            run.generated_document_id = generated_document_id
            run.finished_at = now_shanghai()

        except Exception as exc:
            error_msg = str(exc)
            logger.warning("步骤执行失败 step_id=%s: %s", _step_id, error_msg)

            # 先回滚，避免 PendingRollbackError（文档 Section 6.3）
            db.rollback()

            # 重新查询，避免访问过期对象
            run = db.query(AgentGoalRun).filter(AgentGoalRun.id == _run_id).first()
            step = db.query(AgentGoalStep).filter(AgentGoalStep.id == _step_id).first()

            # 处理失败（文档 Section 10.3）
            if run:
                run.status = "failed"
                run.error_message = error_msg
                run.finished_at = now_shanghai()

            if step:
                step.retry_count = (step.retry_count or 0) + 1
                step.last_error = error_msg

                if step.retry_count <= (step.max_retries or 1):
                    step.status = "failed_retryable"
                else:
                    step.status = "failed_final"

            db.commit()

            # 仍然尝试做复盘（记录失败情况）
            self._run_reflection(
                db=db,
                goal=goal,
                step=step,
                run=run,
                student_id=student_id,
                course_id=course_id,
                agent_steps=agent_steps,
                tool_result={"error": error_msg, "is_error": True},
            )

            return {
                "run_id": _run_id,
                "run_uuid": run_uuid_str,
                "goal_id": goal_id,
                "step_id": _step_id,
                "status": "failed",
                "text": f"步骤执行失败：{error_msg}",
                "agent_steps": agent_steps,
                "reflection": None,
            }

        # 7. 根据 step_type 决定执行后状态（文档 Section 9.2.1）
        post_status = _STEP_POST_STATUS.get(step.step_type, "completed")
        step.status = post_status
        if post_status == "completed":
            step.completed_at = now_shanghai()
        db.commit()

        # 8. 复盘
        reflection = self._run_reflection(
            db=db,
            goal=goal,
            step=step,
            run=run,
            student_id=student_id,
            course_id=course_id,
            agent_steps=agent_steps,
            tool_result=tool_result,
        )

        # 9. 应用复盘动作（文档 Section 9.3.1）
        if reflection:
            self._apply_reflection_to_step(db, goal, step, reflection)

        # 10. 更新进度
        progress = agent_goal_service.recalculate_progress(db, goal_id)
        goal.progress_percent = progress
        db.commit()

        # 11. 检查目标是否可完成
        agent_goal_service.check_goal_completion(db, goal_id)

        # 12. 构建返回结果
        text = self._build_result_text(step, tool_result, reflection)

        return {
            "run_id": run.id,
            "run_uuid": run_uuid_str,
            "goal_id": goal_id,
            "step_id": step.id,
            "status": post_status,
            "text": text,
            "agent_steps": agent_steps,
            "reflection": reflection,
        }

    # ── step_type 分发执行（文档 Section 10.2） ────────────────

    def _execute_step(
        self,
        db: Session,
        step: AgentGoalStep,
        student_id: int,
        course_id: int,
        run: AgentGoalRun,
        goal: AgentLearningGoal,
    ) -> tuple[dict, list[dict], dict]:
        """
        根据 step_type 分发执行逻辑。

        返回：(tool_result, agent_steps, extras)
        """
        step_type = step.step_type
        tool_args = step.tool_args_json or {}
        agent_steps = []
        extras = {}

        if step_type == "profile_check":
            return self._exec_profile_check(db, student_id, course_id, agent_steps)

        elif step_type == "qa_explanation":
            return self._exec_qa_explanation(
                db, student_id, course_id, step, tool_args, agent_steps, run
            )

        elif step_type in ("inline_practice", "diagnostic_quiz"):
            return self._exec_inline_practice(
                db, student_id, course_id, step, tool_args, agent_steps, run, goal
            )

        elif step_type == "exercise_document":
            return self._exec_exercise_document(
                db, student_id, course_id, step, tool_args, agent_steps, run
            )

        elif step_type == "recommendation_sync":
            return self._exec_recommendation_sync(
                db, student_id, course_id, step, tool_args, agent_steps
            )

        elif step_type == "review_summary":
            return self._exec_review_summary(
                db, student_id, course_id, step, tool_args, agent_steps, run
            )

        else:
            raise ValueError(f"不支持的步骤类型: {step_type}")

    # ── profile_check ─────────────────────────────────────────

    def _exec_profile_check(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        agent_steps: list,
    ) -> tuple[dict, list[dict], dict]:
        """执行画像检查"""
        from app.services.profile_service import profile_service

        profile = profile_service.get_profile_for_agent(db, student_id, course_id)
        agent_steps.append({
            "title": "检查学习画像",
            "detail": f"整体水平：{profile.get('overall_level', '未知')}，"
                      f"薄弱点数量：{len(profile.get('weak_points', []))}",
            "status": "done",
        })

        return (
            {"profile": profile, "success": True},
            agent_steps,
            {},
        )

    # ── qa_explanation ────────────────────────────────────────

    def _exec_qa_explanation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        step: AgentGoalStep,
        tool_args: dict,
        agent_steps: list,
        run: AgentGoalRun,
    ) -> tuple[dict, list[dict], dict]:
        """执行知识讲解答疑（文档 Section 12.2 改造）"""
        from app.services.qa_agent_service import get_qa_agent_service

        question = tool_args.get("question") or step.title
        kp_ids = step.target_knowledge_point_ids or []

        agent_steps.append({
            "title": "生成知识讲解",
            "detail": f"针对知识点 {kp_ids} 生成讲解",
            "status": "done",
        })

        qa_service = get_qa_agent_service()
        result = qa_service.ask(
            db=db,
            student_id=student_id,
            course_id=course_id,
            question=question,
        )

        agent_steps.append({
            "title": "讲解生成完成",
            "detail": f"已生成回答，关联知识点 {result.get('related_knowledge_point_ids', [])}",
            "status": "done",
        })

        qa_id = result.get("qa_id")

        # 文档 Section 12.2：讲解生成后标记为 waiting_user_action，用户必须阅读
        step.needs_user_action = 1
        step.user_action_type = "read_explanation"
        step.user_action_status = "pending"
        step.output_type = "qa"
        step.output_ref_json = {
            "qa_id": qa_id,
            "run_id": run.id,
        }

        run.output_type = "qa"
        run.output_ref_json = {
            "qa_id": qa_id,
        }
        run.user_action_required = 1
        run.user_action_status = "pending"

        db.commit()

        return (
            {"qa_id": qa_id, "answer": result.get("answer"), "success": True},
            agent_steps,
            {"qa_id": qa_id},
        )

    # ── inline_practice / diagnostic_quiz ──────────────────────

    def _exec_inline_practice(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        step: AgentGoalStep,
        tool_args: dict,
        agent_steps: list,
        run: AgentGoalRun,
        goal: AgentLearningGoal,
    ) -> tuple[dict, list[dict], dict]:
        """
        执行对话式练习（文档 Section 9.2.2 改造）

        改造点：
        1. 使用目标专用 conversation 替代 conversation_id=0
        2. PracticeSession 写入 goal_id / goal_step_id / goal_run_id
        3. Step 进入 waiting_user_action 状态
        """
        from app.services.agent_practice_session_service import agent_practice_session_service

        kp_ids = step.target_knowledge_point_ids or []
        question_count = tool_args.get("question_count", 5)
        topic = step.title

        agent_steps.append({
            "title": "创建练习",
            "detail": f"生成 {question_count} 道对话式练习题",
            "status": "done",
        })

        # 确保目标专用对话
        conversation_id = self._ensure_goal_conversation(db, goal, student_id, course_id)

        session, questions, practice_agent_steps = (
            agent_practice_session_service.create_inline_practice(
                db=db,
                conversation_id=conversation_id,
                student_id=student_id,
                course_id=course_id,
                topic=topic,
                knowledge_point_ids=kp_ids,
                question_count=question_count,
                difficulty=tool_args.get("difficulty", "adaptive"),
                include_answer_on_display=tool_args.get("include_answer_on_display", False),
                include_explanation_on_display=tool_args.get("include_explanation_on_display", False),
            )
        )

        # 关联 practice session 到 goal/step/run（文档 Section 10.2）
        session.goal_id = goal.id
        session.goal_step_id = step.id
        session.goal_run_id = run.id
        db.commit()

        # 更新 step（文档 Section 9.2.2）
        step.needs_user_action = 1
        step.user_action_type = "answer_practice"
        step.user_action_status = "pending"
        step.output_type = "practice_session"
        step.output_ref_json = {
            "practice_session_id": session.id,
            "question_count": len(questions),
        }

        # 更新 run
        run.output_type = "practice_session"
        run.output_ref_json = step.output_ref_json
        run.user_action_required = 1
        run.user_action_status = "pending"

        db.commit()

        agent_steps.extend(practice_agent_steps)
        agent_steps.append({
            "title": "练习已就绪",
            "detail": f"已创建 {len(questions)} 道题目，请在目标页完成练习",
            "status": "done",
        })

        return (
            {
                "practice_session_id": session.id,
                "question_count": len(questions),
                "success": True,
            },
            agent_steps,
            {"practice_session_id": session.id},
        )

    # ── exercise_document ──────────────────────────────────────

    def _exec_exercise_document(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        step: AgentGoalStep,
        tool_args: dict,
        agent_steps: list,
        run: AgentGoalRun,
    ) -> tuple[dict, list[dict], dict]:
        """
        生成练习文档（文档 Section 9.2.3 改造）

        文档生成后标记为 waiting_user_action，用户需要阅读 / 完成文档。
        """
        from app.services.exercise_agent_service import exercise_agent_service

        kp_ids = step.target_knowledge_point_ids or []
        main_kp_id = kp_ids[0] if kp_ids else None
        question_count = tool_args.get("question_count", 5)

        agent_steps.append({
            "title": "生成练习文档",
            "detail": f"为知识点 {kp_ids} 生成 {question_count} 道练习题文档",
            "status": "done",
        })

        doc, doc_agent_steps = exercise_agent_service.generate(
            db=db,
            user_id=student_id,
            course_id=course_id,
            prompt=step.title,
            question_count=question_count,
            knowledge_point_id=main_kp_id,
            difficulty=tool_args.get("difficulty", "adaptive"),
            include_answer=tool_args.get("include_answer", True),
            include_explanation=tool_args.get("include_explanation", True),
        )

        agent_steps.extend(doc_agent_steps)
        agent_steps.append({
            "title": "文档已生成",
            "detail": "已生成练习文档",
            "status": "done",
        })

        # 文档步骤：标记为 waiting_user_action，用户需标记已阅读/已完成
        step.needs_user_action = 1
        step.user_action_type = "read_document"
        step.user_action_status = "pending"
        step.output_type = "document"
        step.output_ref_json = {"document_id": doc.id}

        run.output_type = "document"
        run.output_ref_json = step.output_ref_json
        run.user_action_required = 1
        run.user_action_status = "pending"

        db.commit()

        return (
            {"document_id": doc.id, "success": True},
            agent_steps,
            {"generated_document_id": doc.id},
        )

    # ── recommendation_sync ────────────────────────────────────

    def _exec_recommendation_sync(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        step: AgentGoalStep,
        tool_args: dict,
        agent_steps: list,
    ) -> tuple[dict, list[dict], dict]:
        """同步推荐任务"""
        from app.services.recommendation_service import recommendation_service

        kp_ids = step.target_knowledge_point_ids or []

        agent_steps.append({
            "title": "生成推荐方案",
            "detail": f"为薄弱知识点 {kp_ids} 生成推荐计划",
            "status": "done",
        })

        plans = []
        for kp_id in kp_ids:
            plan = recommendation_service.generate_for_weak_point(
                db=db,
                student_id=student_id,
                course_id=course_id,
                knowledge_point_id=kp_id,
            )
            if plan:
                plans.append({"plan_id": plan.id, "title": plan.title})

        agent_steps.append({
            "title": "推荐方案已生成",
            "detail": f"已生成 {len(plans)} 个推荐方案",
            "status": "done",
        })

        return (
            {"plans": plans, "success": True},
            agent_steps,
            {},
        )

    # ── review_summary ─────────────────────────────────────────

    def _exec_review_summary(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        step: AgentGoalStep,
        tool_args: dict,
        agent_steps: list,
        run: AgentGoalRun,
    ) -> tuple[dict, list[dict], dict]:
        """生成阶段总结（调用 LLM）（文档 Section 12.3 改造）"""
        from app.services.qwen_client import qwen_client
        from app.services.profile_service import profile_service

        goal = db.query(AgentLearningGoal).filter(
            AgentLearningGoal.id == step.goal_id
        ).first()

        profile = profile_service.get_profile_for_agent(db, student_id, course_id)

        # 获取已完成步骤
        completed_steps = (
            db.query(AgentGoalStep)
            .filter(
                AgentGoalStep.goal_id == step.goal_id,
                AgentGoalStep.status.in_(["completed", "waiting_user_action"]),
            )
            .order_by(AgentGoalStep.step_order)
            .all()
        )

        agent_steps.append({
            "title": "生成阶段总结",
            "detail": f"汇总 {len(completed_steps)} 个已完成步骤的情况",
            "status": "done",
        })

        summary_prompt = f"""请根据以下信息生成学习阶段总结：

目标：{goal.title if goal else step.goal_id}
整体画像水平：{profile.get('overall_level', '未知')}

已完成步骤：
{chr(10).join(f'- {s.title}: {s.result_summary or "已完成"}' for s in completed_steps)}

当前步骤：{step.title}

请生成一段 200-500 字的阶段总结，包括：
1. 已完成内容回顾
2. 当前掌握情况
3. 下一步建议"""

        messages = [
            {"role": "system", "content": "你是一位学习辅导专家，请根据学生的学习数据生成阶段总结。"},
            {"role": "user", "content": summary_prompt},
        ]

        summary = qwen_client.chat(messages=messages, temperature=0.5)

        agent_steps.append({
            "title": "总结生成完成",
            "detail": summary[:100] + ("..." if len(summary) > 100 else ""),
            "status": "done",
        })

        # 文档 Section 12.3：总结生成后标记为 waiting_user_action，用户必须阅读
        step.needs_user_action = 1
        step.user_action_type = "read_summary"
        step.user_action_status = "pending"
        step.output_type = "summary"
        step.output_ref_json = {"summary": summary[:200]}

        run.output_type = "summary"
        run.output_ref_json = step.output_ref_json
        run.user_action_required = 1
        run.user_action_status = "pending"

        db.commit()

        return (
            {"summary": summary, "success": True},
            agent_steps,
            {},
        )

    # ── 手动完成步骤（文档 Section 8.6） ───────────────────────

    def complete_manual_step(
        self,
        db: Session,
        goal_id: int,
        step_id: int,
        student_id: int,
        course_id: int,
        result_summary: str,
    ) -> dict:
        """手动完成线下任务步骤"""
        from app.services.agent_goal_service import agent_goal_service

        goal = agent_goal_service._get_goal_for_user(db, goal_id, student_id)

        step = db.query(AgentGoalStep).filter(
            AgentGoalStep.id == step_id,
            AgentGoalStep.goal_id == goal_id,
            AgentGoalStep.student_id == student_id,
        ).first()

        if not step:
            raise ValueError("步骤不存在")

        if step.status not in ("pending", "blocked", "failed_retryable", "waiting_user_action"):
            raise ValueError(f"步骤当前状态为 {step.status}，不能手动完成")

        if step.step_type in ("qa_explanation", "review_summary", "exercise_document", "inline_practice", "diagnostic_quiz"):
            raise ValueError("该步骤需要通过阅读或练习入口完成，不能使用普通标记完成")

        # 创建 run 记录
        run_uuid_str = f"goal_run_{uuid.uuid4().hex[:16]}"
        run = AgentGoalRun(
            goal_id=goal_id,
            step_id=step.id,
            student_id=student_id,
            course_id=course_id,
            run_uuid=run_uuid_str,
            status="completed",
            tool_name="manual_task",
            tool_args_json={"result_summary": result_summary},
            tool_result_json={"result_summary": result_summary, "success": True},
            agent_steps_json=[{
                "title": "手动完成",
                "detail": result_summary,
                "status": "done",
            }],
            started_at=now_shanghai(),
            finished_at=now_shanghai(),
        )
        db.add(run)
        db.flush()

        step.status = "completed"
        step.result_summary = result_summary
        step.completed_at = now_shanghai()
        step.last_run_id = run.id
        step.needs_user_action = 0
        step.user_action_status = "completed"

        # 复盘
        self._run_reflection(
            db=db,
            goal=goal,
            step=step,
            run=run,
            student_id=student_id,
            course_id=course_id,
            agent_steps=[],
            tool_result={"result_summary": result_summary, "manual": True},
        )

        # 更新进度
        progress = agent_goal_service.recalculate_progress(db, goal_id)
        goal.progress_percent = progress
        db.commit()

        agent_goal_service.check_goal_completion(db, goal_id)

        return {
            "step_id": step.id,
            "status": "completed",
            "message": f"步骤「{step.title}」已标记完成",
        }

    # ── 质量门禁（文档 Section 9.2.4 & 13） ───────────────────

    @staticmethod
    def evaluate_quality_gate(
        step: AgentGoalStep,
        tool_result: dict,
        practice_summary: dict | None = None,
    ) -> dict:
        """
        评估步骤是否通过质量门禁。

        返回：{"passed": bool, "score": float, "reason": str}
        """
        gate_config = step.quality_gate_json or {}
        step_type = step.step_type

        # 默认门禁配置
        default_gates = {
            "profile_check": {"type": "profile_exists", "rule": "profile_exists"},
            "qa_explanation": {"type": "qa_complete", "rule": "qa_id_and_length", "min_length": 50},
            "inline_practice": {"type": "practice_session", "rule": "session_created", "min_questions": 3},
            "diagnostic_quiz": {"type": "diagnostic_accuracy", "rule": "min_accuracy", "min_accuracy": 0.6},
            "exercise_document": {"type": "document_exists", "rule": "document_id"},
            "recommendation_sync": {"type": "plan_count", "rule": "min_plans", "min_plans": 1},
            "review_summary": {"type": "summary_length", "rule": "min_length", "min_length": 100},
            "manual_task": {"type": "manual_complete", "rule": "result_summary"},
        }

        gate = gate_config if gate_config else default_gates.get(step_type, {})
        gate_type = gate.get("type", "unknown")

        if gate_type in ("profile_exists",):
            profile = tool_result.get("profile", {})
            passed = bool(profile)

        elif gate_type in ("qa_complete", "qa_id_and_length"):
            qa_id = tool_result.get("qa_id")
            answer = tool_result.get("answer", "")
            min_len = gate.get("min_length", 50)
            passed = bool(qa_id) and len(answer) >= min_len

        elif gate_type in ("practice_session", "session_created"):
            session_id = tool_result.get("practice_session_id")
            qc = tool_result.get("question_count", 0)
            min_q = gate.get("min_questions", 3)
            passed = bool(session_id) and qc >= min_q
            score = min(qc / max(min_q, 1), 1.0)

        elif gate_type in ("diagnostic_accuracy",):
            if practice_summary:
                accuracy = practice_summary.get("accuracy", 0)
                min_acc = gate.get("min_accuracy", 0.6)
                passed = accuracy >= min_acc
                score = accuracy
            else:
                passed = True  # 还没有练习结果时先通过

        elif gate_type in ("document_exists",):
            doc_id = tool_result.get("document_id")
            passed = bool(doc_id)

        elif gate_type in ("plan_count",):
            plans = tool_result.get("plans", [])
            min_plans = gate.get("min_plans", 1)
            passed = len(plans) >= min_plans

        elif gate_type in ("summary_length",):
            summary = tool_result.get("summary", "")
            min_len = gate.get("min_length", 100)
            passed = len(summary) >= min_len

        elif gate_type in ("manual_complete",):
            result_text = tool_result.get("result_summary", "")
            passed = bool(result_text and len(result_text) > 0)

        else:
            passed = True

        score = locals().get("score", 1.0 if passed else 0.0)

        return {
            "passed": passed,
            "score": round(score, 2),
            "reason": "门禁通过" if passed else f"未通过质量门禁 {gate_type}",
        }

    # ── 复盘调用 ──────────────────────────────────────────────

    def _run_reflection(
        self,
        db: Session,
        goal: AgentLearningGoal,
        step: AgentGoalStep,
        run: AgentGoalRun,
        student_id: int,
        course_id: int,
        agent_steps: list,
        tool_result: dict,
    ) -> dict | None:
        """调用复盘服务"""
        try:
            from app.services.agent_goal_reflection_service import agent_goal_reflection_service

            reflection = agent_goal_reflection_service.reflect_step(
                db=db,
                goal=goal,
                step=step,
                run=run,
                student_id=student_id,
                course_id=course_id,
                tool_result=tool_result,
            )
            return reflection
        except Exception:
            logger.exception("复盘失败 step_id=%s", step.id)
            return None

    # ── 应用复盘动作到步骤（文档 Section 9.3.1） ──────────────

    def _apply_reflection_to_step(
        self,
        db: Session,
        goal: AgentLearningGoal,
        step: AgentGoalStep,
        reflection: dict,
    ):
        """
        根据复盘结果调整步骤和目标状态。

        规则（文档 Section 9.3.1）：
        - continue → 不做额外动作
        - retry_step → step.status = failed_retryable
        - insert_remedial_step → 调用 _insert_remedial_from_reflection
        - replan_needed → goal.planning_status = replan_needed
        - blocked_need_user → step.status = blocked
        - complete_goal → goal.status = completed
        """
        next_action = reflection.get("next_action", "continue")
        is_success = reflection.get("is_success", True)

        if next_action == "continue":
            # 如果质量分很低但不是失败，不影响已完成状态
            pass

        elif next_action == "retry_step":
            # 步骤需要重试
            if step.status == "completed" or step.status == "waiting_user_action":
                step.status = "failed_retryable"
                logger.info("复盘要求重试 step_id=%s", step.id)

        elif next_action == "insert_remedial_step":
            # 插入补救步骤（防重复）
            suggested = reflection.get("suggested_new_steps", [])
            if suggested:
                self._insert_remedial_from_reflection(db, goal, step, reflection, suggested)

        elif next_action == "replan_needed":
            # 目标需要重新规划
            goal.planning_status = "replan_needed"
            db.commit()
            logger.info("复盘触发重规划 goal_id=%s", goal.id)

        elif next_action == "blocked_need_user":
            # 需要用户补充信息
            if step.status == "completed":
                step.status = "blocked"
                step.needs_user_action = 1
                db.commit()
                logger.info("复盘标记步骤需要用户介入 step_id=%s", step.id)

        elif next_action == "complete_goal":
            # 标记目标完成
            goal.status = "completed"
            goal.progress_percent = 100
            goal.completed_at = now_shanghai()
            db.commit()
            logger.info("复盘触发目标完成 goal_id=%s", goal.id)

    # ── 从复盘插入补救步骤（文档 Section 15） ──────────────────

    def _insert_remedial_from_reflection(
        self,
        db: Session,
        goal: AgentLearningGoal,
        current_step: AgentGoalStep,
        reflection: dict,
        suggested_steps: list[dict],
    ):
        """
        根据复盘结果自动插入补救步骤。

        防重复：每个原始 step 最多自动插入一次补救步骤。
        """
        # 检查是否已有同 source_step_id 的补救步骤
        existing = (
            db.query(AgentGoalStep)
            .filter(
                AgentGoalStep.goal_id == goal.id,
                AgentGoalStep.metadata_json.contains({"source": "reflection_remedial", "source_step_id": current_step.id}),
            )
            .first()
        )
        if existing:
            logger.info("已有来自 step_id=%s 的补救步骤 step_id=%s，跳过重复插入", current_step.id, existing.id)
            return

        # 找到当前最大 step_order
        max_order = (
            db.query(AgentGoalStep.step_order)
            .filter(AgentGoalStep.goal_id == goal.id)
            .order_by(AgentGoalStep.step_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else current_step.step_order + 1

        for ss in suggested_steps[:3]:  # 最多插入 3 个补救步骤
            step = AgentGoalStep(
                goal_id=goal.id,
                student_id=goal.student_id,
                course_id=goal.course_id,
                step_order=next_order,
                title=ss.get("title", "补救步骤"),
                description=ss.get("description", ""),
                step_type=ss.get("step_type", "qa_explanation"),
                tool_name=ss.get("tool_name", "qa_answer"),
                tool_args_json=ss.get("tool_args", {}),
                expected_outcome=ss.get("expected_outcome", ""),
                status="pending",
                metadata_json={
                    "source": "reflection_remedial",
                    "source_step_id": current_step.id,
                    "source_reflection_id": reflection.get("id"),
                },
            )
            db.add(step)
            next_order += 1

        db.flush()
        logger.info("已自动插入 %s 个补救步骤 goal_id=%s", len(suggested_steps[:3]), goal.id)

    # ── 构建结果文本 ──────────────────────────────────────────

    @staticmethod
    def _build_result_text(step: AgentGoalStep, tool_result: dict, reflection: dict | None) -> str:
        """构建展示给用户的结果文本"""
        parts = [f"已完成步骤：{step.title}"]

        if step.step_type == "profile_check" and tool_result.get("profile"):
            p = tool_result["profile"]
            parts.append(f"当前学习水平：{p.get('overall_level', '未知')}")
            weak_count = len(p.get("weak_points", []))
            if weak_count > 0:
                parts.append(f"发现 {weak_count} 个薄弱点")

        elif step.step_type == "qa_explanation" and tool_result.get("answer"):
            answer = tool_result["answer"]
            parts.append(answer[:500] + ("..." if len(answer) > 500 else ""))

        elif step.step_type in ("inline_practice", "diagnostic_quiz"):
            qc = tool_result.get("question_count", 0)
            parts.append(f"已生成 {qc} 道练习题，请在目标页完成练习")

        elif step.step_type == "exercise_document":
            parts.append("已生成练习文档，请阅读后标记完成")

        elif step.step_type == "recommendation_sync":
            plans = tool_result.get("plans", [])
            parts.append(f"已生成 {len(plans)} 个推荐方案")

        elif step.step_type == "review_summary":
            summary = tool_result.get("summary", "")
            parts.append(summary)

        if reflection and reflection.get("summary"):
            parts.append(f"\n复盘：{reflection['summary']}")

        return "\n".join(parts)


agent_goal_step_runner_service = AgentGoalStepRunnerService()
