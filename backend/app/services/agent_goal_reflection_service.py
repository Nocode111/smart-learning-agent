"""
长期目标执行复盘服务（文档 Section 11 + 执行闭环增强 Section 9.3）

职责：
1. 对每一步执行结果做质量评估
2. 决定是否完成步骤
3. 决定是否需要补救步骤
4. 更新目标整体进度
5. 刷新步骤复盘（用户完成练习后）
6. 应用复盘动作落地

本阶段策略（文档 Section 11.4）：
- 优先使用规则复盘（确定性、快速）
- 对 review_summary 类型调用 LLM 复盘
- LLM 复盘失败降级为规则复盘
- 练习完成后可刷新复盘
"""

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun, AgentGoalReflection

logger = logging.getLogger(__name__)


class AgentGoalReflectionService:
    """执行复盘服务"""

    # ── 主入口 ────────────────────────────────────────────────

    def reflect_step(
        self,
        db: Session,
        goal: AgentLearningGoal,
        step: AgentGoalStep,
        run: AgentGoalRun,
        student_id: int,
        course_id: int,
        tool_result: dict,
    ) -> dict:
        """
        对步骤执行结果进行复盘。

        返回复盘字典。
        """
        step_type = step.step_type

        # 根据步骤类型选择复盘策略
        if step_type == "review_summary":
            # 必须调用 LLM 复盘
            try:
                return self._llm_reflection(
                    db, goal, step, run, student_id, course_id, tool_result
                )
            except Exception:
                logger.warning("LLM 复盘失败，降级为规则复盘 step_id=%s", step.id)
                return self._rule_based_reflection(
                    db, goal, step, run, student_id, course_id, tool_result
                )
        else:
            # 规则复盘
            return self._rule_based_reflection(
                db, goal, step, run, student_id, course_id, tool_result
            )

    # ── 刷新步骤复盘（文档 Section 9.3） ───────────────────────

    def refresh_step_reflection(
        self,
        db: Session,
        goal: AgentLearningGoal,
        step: AgentGoalStep,
        student_id: int,
        force_llm: bool = False,
    ) -> dict:
        """
        刷新某步骤的复盘（用于用户完成练习后）。

        找到最近的 run，重新生成复盘。
        """
        latest_run = (
            db.query(AgentGoalRun)
            .filter(
                AgentGoalRun.goal_id == goal.id,
                AgentGoalRun.step_id == step.id,
            )
            .order_by(desc(AgentGoalRun.started_at))
            .first()
        )

        if not latest_run:
            raise ValueError("该步骤还没有执行记录")

        tool_result = latest_run.tool_result_json or {}

        # 如果有练习结果，合并到 tool_result
        if step.output_type == "practice_session" and step.output_ref_json:
            session_id = step.output_ref_json.get("practice_session_id")
            if session_id:
                try:
                    from app.models.agent_practice import AgentPracticeSession
                    session = db.query(AgentPracticeSession).filter(
                        AgentPracticeSession.id == session_id
                    ).first()
                    if session:
                        practice_summary = {
                            "question_count": session.question_count,
                            "answered_count": session.answered_count,
                            "correct_count": session.correct_count,
                            "accuracy": round(session.correct_count / max(session.question_count, 1), 2),
                        }
                        tool_result["practice_summary"] = practice_summary
                except Exception:
                    logger.debug("获取练习 session 失败", exc_info=True)

        # 强制 LLM 复盘还是走规则
        if force_llm:
            try:
                return self._llm_reflection(
                    db, goal, step, latest_run, student_id, goal.course_id, tool_result
                )
            except Exception:
                logger.warning("强制 LLM 复盘失败，降级为规则复盘 step_id=%s", step.id)

        # 使用规则复盘（含练习结果）
        return self._rule_based_reflection(
            db, goal, step, latest_run, student_id, goal.course_id, tool_result
        )

    # ── 规则复盘（文档 Section 11.4，增强版） ──────────────────

    def _rule_based_reflection(
        self,
        db: Session,
        goal: AgentLearningGoal,
        step: AgentGoalStep,
        run: AgentGoalRun,
        student_id: int,
        course_id: int,
        tool_result: dict,
    ) -> dict:
        """
        基于规则的复盘。

        规则：
        1. 工具执行成功 -> is_success = true
        2. 练习 session 创建成功，题目数量满足要求 -> 成功
        3. 练习文档生成成功，document_id 存在 -> 成功
        4. 答疑生成成功，qa_id 存在 -> 成功
        5. 练习完成 -> 根据正确率判断是否通过质量门禁
        """
        is_error = tool_result.get("is_error", False)
        is_success = not is_error and tool_result.get("success", False) if isinstance(tool_result, dict) else False

        step_type = step.step_type
        quality_score = 0.5
        summary = ""
        issues = []
        next_action = "continue"

        # 检查练习结果（如有）
        practice_summary = tool_result.get("practice_summary", {})

        if is_error:
            # 执行失败
            is_success = False
            quality_score = 0.0
            summary = f"步骤执行失败：{tool_result.get('error', '未知错误')}"
            issues = [{"type": "execution_error", "message": tool_result.get("error", "未知错误")}]

            if step.retry_count <= (step.max_retries or 1):
                next_action = "retry_step"
            else:
                next_action = "blocked_need_user"

        elif step_type == "profile_check":
            profile = tool_result.get("profile", {})
            weak_count = len(profile.get("weak_points", []))
            is_success = True
            quality_score = 0.8
            summary = f"画像检查完成。整体水平：{profile.get('overall_level', '未知')}，发现 {weak_count} 个薄弱点。"
            if weak_count == 0:
                quality_score = 0.95
                summary += " 无明显薄弱点，基础扎实。"

        elif step_type == "qa_explanation":
            qa_id = tool_result.get("qa_id")
            answer = tool_result.get("answer", "")
            is_success = bool(qa_id) and len(answer) > 50
            quality_score = 0.75 if is_success else 0.0
            summary = "知识讲解答疑已生成。" if is_success else "答疑生成失败。"
            if not is_success:
                next_action = "retry_step"

        elif step_type in ("inline_practice", "diagnostic_quiz"):
            qc = tool_result.get("question_count", 0)
            min_qc = (step.success_criteria_json or {}).get("min_question_count", 3)

            if practice_summary:
                # 用户已完成练习，根据正确率判断
                accuracy = practice_summary.get("accuracy", 0)
                correct = practice_summary.get("correct_count", 0)
                total = practice_summary.get("question_count", qc)
                is_success = accuracy >= 0.6
                quality_score = accuracy
                summary = f"练习完成：{correct}/{total} 正确，正确率 {accuracy:.0%}。"

                if accuracy < 0.6:
                    next_action = "insert_remedial_step"
                    issues = [{
                        "type": "low_accuracy",
                        "message": f"练习正确率 {accuracy:.0%} 低于 60%，建议补充学习",
                    }]
                elif accuracy >= 0.85:
                    quality_score = min(accuracy + 0.1, 1.0)
                    summary += " 表现优秀！"
            else:
                # 练习已生成但未完成
                is_success = qc >= min_qc
                quality_score = min(qc / max(min_qc, 1) * 0.7, 1.0)
                summary = f"已生成 {qc} 道练习题，等待用户作答。" if is_success else f"练习生成不完整（期望 {min_qc} 题，实际 {qc} 题）。"

                if not is_success:
                    issues = [{
                        "type": "insufficient_questions",
                        "message": f"题目数量不足：期望 {min_qc}，实际 {qc}",
                    }]
                    next_action = "retry_step"

        elif step_type == "exercise_document":
            doc_id = tool_result.get("document_id")
            is_success = bool(doc_id)
            quality_score = 0.8 if is_success else 0.0
            summary = "练习文档已生成。" if is_success else "文档生成失败。"
            if step.user_action_status == "completed":
                summary = "练习文档已阅读/完成。"
                quality_score = 0.85

        elif step_type == "recommendation_sync":
            plans = tool_result.get("plans", [])
            is_success = len(plans) > 0
            quality_score = min(len(plans) * 0.3, 1.0)
            summary = f"已生成 {len(plans)} 个推荐方案。" if is_success else "未生成推荐方案。"
            if not is_success:
                issues = [{"type": "no_recommendation", "message": "未能生成推荐方案"}]

        elif step_type == "review_summary":
            summary_text = tool_result.get("summary", "")
            is_success = bool(summary_text and len(summary_text) > 50)
            quality_score = 0.7 if is_success else 0.3
            summary = "阶段总结已生成。"

        elif step_type == "manual_task":
            is_success = True
            quality_score = 0.7
            summary = f"线下任务已完成：{tool_result.get('result_summary', '已标记完成')}"

        else:
            is_success = not is_error
            quality_score = 0.6 if is_success else 0.0
            summary = "步骤已执行。"

        # 写入数据库
        reflection = AgentGoalReflection(
            goal_id=goal.id,
            step_id=step.id,
            run_id=run.id,
            student_id=student_id,
            course_id=course_id,
            reflection_type="step_after_run",
            is_success=1 if is_success else 0,
            quality_score=quality_score,
            summary=summary,
            issues_json=issues,
            next_action=next_action,
            raw_llm_json={"method": "rule_based"},
            applied_action_status="pending",
        )
        db.add(reflection)
        db.flush()

        # 更新 step 的 reflection_json
        step.reflection_json = {
            "is_success": is_success,
            "quality_score": quality_score,
            "summary": summary,
            "next_action": next_action,
        }

        logger.info(
            "规则复盘完成 step_id=%s is_success=%s quality=%.2f next_action=%s",
            step.id, is_success, quality_score, next_action,
        )

        return {
            "id": reflection.id,
            "is_success": is_success,
            "quality_score": quality_score,
            "summary": summary,
            "issues": issues,
            "next_action": next_action,
            "suggested_new_steps": [],
        }

    # ── LLM 复盘（文档 Section 11） ────────────────────────────

    def _llm_reflection(
        self,
        db: Session,
        goal: AgentLearningGoal,
        step: AgentGoalStep,
        run: AgentGoalRun,
        student_id: int,
        course_id: int,
        tool_result: dict,
    ) -> dict:
        """调用 LLM 进行深度复盘"""
        from app.prompts.agent_goal_reflection_prompt import build_goal_reflection_prompt
        from app.services.qwen_client import qwen_client
        from app.services.profile_service import profile_service

        # 获取画像
        try:
            profile = profile_service.get_profile_for_agent(db, student_id, course_id)
            profile_before = json.dumps(profile, ensure_ascii=False, indent=2)
        except Exception:
            profile_before = "暂无数据"

        # 合并练习结果
        practice_result = "暂无"
        if tool_result.get("practice_summary"):
            practice_result = json.dumps(tool_result["practice_summary"], ensure_ascii=False, indent=2)

        # 构建 prompt
        messages = build_goal_reflection_prompt(
            goal_title=goal.title,
            goal_text=goal.goal_text,
            target_score=float(goal.target_score) if goal.target_score else None,
            progress_percent=float(goal.progress_percent),
            step_order=step.step_order,
            step_title=step.title,
            step_description=step.description,
            step_type=step.step_type,
            expected_outcome=step.expected_outcome,
            run_status=run.status,
            tool_name=run.tool_name,
            tool_result_text=json.dumps(tool_result, ensure_ascii=False, indent=2),
            profile_before=profile_before,
            profile_after="（执行后画像待更新）",
            practice_result=practice_result,
        )

        # 调用 LLM
        llm_output = qwen_client.chat(messages=messages, temperature=0.2)

        # 解析 JSON
        parsed = self._parse_reflection_json(llm_output)

        is_success = parsed.get("is_success", False)
        quality_score = parsed.get("quality_score", 0.5)
        summary = parsed.get("summary", "")
        issues = parsed.get("issues", [])
        next_action = parsed.get("next_action", "continue")
        suggested_new_steps = parsed.get("suggested_new_steps", [])

        # 处理根据复盘结果需要插入补救步骤
        if next_action == "insert_remedial_step" and suggested_new_steps:
            # 防重复：检查是否已有来自同一步骤的补救步骤
            existing_remedial = (
                db.query(AgentGoalStep)
                .filter(
                    AgentGoalStep.goal_id == goal.id,
                    AgentGoalStep.metadata_json.contains({"source": "reflection_remedial", "source_step_id": step.id}),
                )
                .first()
            )
            if not existing_remedial:
                self._insert_remedial_steps(db, goal, step, suggested_new_steps)

        # 处理需要重新规划
        if next_action == "replan_needed":
            goal.planning_status = "replan_needed"
            db.commit()

        # 写入数据库
        reflection = AgentGoalReflection(
            goal_id=goal.id,
            step_id=step.id,
            run_id=run.id,
            student_id=student_id,
            course_id=course_id,
            reflection_type="step_after_run",
            is_success=1 if is_success else 0,
            quality_score=quality_score,
            summary=summary,
            issues_json=issues,
            next_action=next_action,
            suggested_new_steps_json=suggested_new_steps,
            raw_llm_json=parsed,
            applied_action_status="applied" if next_action == "continue" else "pending",
        )
        db.add(reflection)
        db.flush()

        # 更新 step 的 reflection_json
        step.reflection_json = {
            "is_success": is_success,
            "quality_score": quality_score,
            "summary": summary,
            "next_action": next_action,
        }

        logger.info(
            "LLM复盘完成 step_id=%s is_success=%s quality=%.2f next_action=%s",
            step.id, is_success, quality_score, next_action,
        )

        return {
            "id": reflection.id,
            "is_success": is_success,
            "quality_score": quality_score,
            "summary": summary,
            "issues": issues,
            "next_action": next_action,
            "suggested_new_steps": suggested_new_steps,
        }

    # ── 应用复盘动作（文档 Section 9.3.1） ────────────────────

    def apply_reflection_action(
        self,
        db: Session,
        goal: AgentLearningGoal,
        step: AgentGoalStep,
        reflection: AgentGoalReflection,
    ) -> dict:
        """
        将复盘动作落地。

        规则：
        - continue → 标记 applied
        - retry_step → step.status = failed_retryable
        - insert_remedial_step → 插入补救步骤
        - replan_needed → goal.planning_status = replan_needed
        - blocked_need_user → step.status = blocked
        - complete_goal → goal.status = completed
        """
        next_action = reflection.next_action

        if not next_action:
            reflection.applied_action_status = "applied"
            reflection.applied_action_message = "无动作需要应用"
            db.commit()
            return {"applied": True, "message": "无动作需要应用"}

        try:
            if next_action == "continue":
                reflection.applied_action_status = "applied"
                reflection.applied_action_message = "继续后续步骤"

            elif next_action == "retry_step":
                step.status = "failed_retryable"
                reflection.applied_action_status = "applied"
                reflection.applied_action_message = "步骤已标记为可重试"

            elif next_action == "insert_remedial_step":
                suggested = reflection.suggested_new_steps_json or []
                if suggested:
                    self._insert_remedial_steps(db, goal, step, suggested)
                    reflection.applied_action_status = "applied"
                    reflection.applied_action_message = f"已插入 {len(suggested)} 个补救步骤"
                else:
                    reflection.applied_action_status = "skipped"
                    reflection.applied_action_message = "无补救步骤内容，跳过"

            elif next_action == "replan_needed":
                goal.planning_status = "replan_needed"
                reflection.applied_action_status = "applied"
                reflection.applied_action_message = "目标已标记为需重新规划"

            elif next_action == "blocked_need_user":
                step.status = "blocked"
                step.needs_user_action = 1
                reflection.applied_action_status = "applied"
                reflection.applied_action_message = "步骤已标记为需用户介入"

            elif next_action == "complete_goal":
                goal.status = "completed"
                goal.progress_percent = 100
                goal.completed_at = datetime.utcnow()
                reflection.applied_action_status = "applied"
                reflection.applied_action_message = "目标已完成"

            else:
                reflection.applied_action_status = "skipped"
                reflection.applied_action_message = f"未知动作类型: {next_action}"

            db.commit()
            logger.info("复盘动作已应用 reflection_id=%s action=%s", reflection.id, next_action)

            return {
                "applied": reflection.applied_action_status == "applied",
                "action": next_action,
                "message": reflection.applied_action_message,
            }

        except Exception:
            db.rollback()
            logger.exception("应用复盘动作失败 reflection_id=%s", reflection.id)
            return {"applied": False, "action": next_action, "message": "应用失败"}

    # ── JSON 解析 ─────────────────────────────────────────────

    def _parse_reflection_json(self, llm_output: str) -> dict:
        """解析 LLM 输出的复盘 JSON"""
        llm_output = (llm_output or "").strip()

        parsed = None
        try:
            parsed = json.loads(llm_output)
        except json.JSONDecodeError:
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(llm_output[start:end + 1])
                except json.JSONDecodeError:
                    pass

        if not parsed or not isinstance(parsed, dict):
            logger.warning("LLM 复盘输出无法解析为 JSON，使用规则复盘降级")
            raise ValueError("LLM 复盘 JSON 解析失败")

        return parsed

    # ── 插入补救步骤（文档 Section 11.2 & 15） ──────────────────

    def _insert_remedial_steps(
        self,
        db: Session,
        goal: AgentLearningGoal,
        current_step: AgentGoalStep,
        suggested_steps: list[dict],
    ):
        """
        在目标计划中插入补救步骤。

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

        for ss in suggested_steps[:3]:
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
                },
            )
            db.add(step)
            next_order += 1

        db.flush()
        logger.info("已插入 %s 个补救步骤 goal_id=%s", len(suggested_steps[:3]), goal.id)


agent_goal_reflection_service = AgentGoalReflectionService()
