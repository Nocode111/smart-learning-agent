"""
长期目标 API 路由（文档 Section 8 + 执行闭环增强 Section 8）

前缀：/api/agent/goals
"""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models.user import User
from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun, AgentGoalReflection
from app.schemas.agent_goal import (
    AgentGoalAdvanceCycleResponse,
    AgentGoalAdvanceRequest,
    AgentGoalAdvanceResponse,
    AgentGoalCreateRequest,
    AgentGoalDetailResponse,
    AgentGoalInsertRemedialStepRequest,
    AgentGoalPlanGenerateResponse,
    AgentGoalPlanResponse,
    AgentGoalRefreshReflectionRequest,
    AgentGoalReplanRequest,
    AgentGoalResponse,
    AgentGoalRunDetailResponse,
    AgentGoalRunListItem,
    AgentGoalRunResponse,
    AgentGoalStatusResponse,
    AgentGoalStepCompleteRequest,
    AgentGoalStepResponse,
    AgentGoalUserActionCompleteRequest,
    AgentGoalUserActionHeartbeatRequest,
    AgentGoalUserActionResponse,
    AgentGoalUserActionStartRequest,
    GoalPracticeAnswerRequest,
    GoalPracticeSessionResponse,
    AgentGoalLoopRunRequest,
    AgentGoalLoopRunResponse,
)
from app.security import get_current_user
from app.services.course_permission_service import course_permission_service
from app.services.agent_goal_service import agent_goal_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _trigger_user_action_auto_advance_background(
    goal_id: int,
    step_id: int,
    student_id: int,
    course_id: int,
    action_uuid: str,
):
    """后台触发用户动作完成后的自动推进，避免前端等待 LLM / 文档生成超时。"""
    from app.models.agent_goal_user_action import AgentGoalUserAction
    from app.services.agent_goal_user_action_service import agent_goal_user_action_service

    db = SessionLocal()
    try:
        action = db.query(AgentGoalUserAction).filter(
            AgentGoalUserAction.action_uuid == action_uuid,
            AgentGoalUserAction.goal_id == goal_id,
            AgentGoalUserAction.step_id == step_id,
            AgentGoalUserAction.student_id == student_id,
        ).first()
        if not action:
            logger.warning("后台自动推进找不到用户动作 action_uuid=%s", action_uuid)
            return

        agent_goal_user_action_service.maybe_trigger_auto_advance(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=student_id,
            course_id=course_id,
            action=action,
        )
    except Exception:
        logger.exception("后台自动推进失败 goal_id=%s step_id=%s action_uuid=%s", goal_id, step_id, action_uuid)
    finally:
        db.close()


# ── 权限辅助函数 ──────────────────────────────────────────────

def _get_goal_and_check(db: Session, goal_id: int, current_user: User):
    """获取目标并校验用户+课程权限，返回 goal"""
    goal = agent_goal_service._get_goal_for_user(db, goal_id, current_user.id)
    course_permission_service.require_view_course(db, current_user, goal.course_id)
    return goal


def _get_goal_practice_session_or_repair(
    db: Session,
    goal_id: int,
    session_id: int,
    current_user: User,
):
    """
    获取目标练习 session。

    兼容历史数据：早期目标执行记录可能只在 agent_goal_runs.practice_session_id
    里记录了 session，但没有回填 agent_practice_sessions.goal_id。
    如果 run 能证明 session 属于当前目标，则自动补齐关联字段。
    """
    from app.models.agent_practice import AgentPracticeSession

    session = db.query(AgentPracticeSession).filter(
        AgentPracticeSession.id == session_id,
        AgentPracticeSession.student_id == current_user.id,
    ).first()
    if not session:
        raise ValueError("练习会话不存在")

    if session.goal_id == goal_id:
        return session

    run = db.query(AgentGoalRun).filter(
        AgentGoalRun.goal_id == goal_id,
        AgentGoalRun.practice_session_id == session_id,
        AgentGoalRun.student_id == current_user.id,
    ).first()
    if not run:
        raise ValueError("练习会话不存在或不属于该目标")

    session.goal_id = goal_id
    session.goal_step_id = session.goal_step_id or run.step_id
    session.goal_run_id = session.goal_run_id or run.id

    step = db.query(AgentGoalStep).filter(
        AgentGoalStep.id == run.step_id,
        AgentGoalStep.goal_id == goal_id,
        AgentGoalStep.student_id == current_user.id,
    ).first()
    if step:
        step.output_type = step.output_type or "practice_session"
        step.output_ref_json = step.output_ref_json or {
            "practice_session_id": session.id,
            "question_count": session.question_count,
        }
        if session.status == "active" and (session.answered_count or 0) < (session.question_count or 0):
            step.status = "waiting_user_action"
            step.needs_user_action = 1
            step.user_action_type = "answer_practice"
            step.user_action_status = "pending"

    run.output_type = run.output_type or "practice_session"
    run.output_ref_json = run.output_ref_json or {
        "practice_session_id": session.id,
        "question_count": session.question_count,
    }
    run.user_action_required = 1
    run.user_action_status = run.user_action_status or "pending"

    db.flush()
    return session


# ── 8.1 创建目标 ──────────────────────────────────────────────

@router.post("")
def create_goal(
    req: AgentGoalCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建长期学习目标（文档 Section 8.1）"""
    student_id = current_user.id
    course_permission_service.require_view_course(db, current_user, req.course_id)

    try:
        result = agent_goal_service.create_goal(
            db=db,
            student_id=student_id,
            course_id=req.course_id,
            goal_text=req.goal_text,
            title=req.title,
            target_score=req.target_score,
            target_knowledge_point_ids=req.target_knowledge_point_ids,
            due_date=req.due_date,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.2 目标列表 ──────────────────────────────────────────────

@router.get("")
def list_goals(
    course_id: int | None = Query(None, alias="courseId"),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询当前用户的目标列表（文档 Section 8.2）"""
    student_id = current_user.id
    if course_id:
        course_permission_service.require_view_course(db, current_user, course_id)

    return agent_goal_service.list_goals(
        db=db,
        student_id=student_id,
        course_id=course_id,
        status=status,
    )


# ── 8.3 目标详情 ──────────────────────────────────────────────

@router.get("/{goal_id}")
def get_goal_detail(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """目标详情（含步骤和最近复盘）"""
    try:
        result = agent_goal_service.get_goal_detail(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
        )
        course_permission_service.require_view_course(db, current_user, result["goal"]["course_id"])
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.4 生成计划 ──────────────────────────────────────────────

@router.post("/{goal_id}/plan")
def generate_plan(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为目标生成结构化学习计划（文档 Section 8.4）"""
    from app.services.agent_goal_planner_service import agent_goal_planner_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_planner_service.plan_goal(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            course_id=goal.course_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.5 执行下一步 ────────────────────────────────────────────

@router.post("/{goal_id}/run-next")
def run_next_step(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行下一个待执行步骤（文档 Section 8.5）"""
    from app.services.agent_goal_step_runner_service import agent_goal_step_runner_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_step_runner_service.run_next_step(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            course_id=goal.course_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.6 手动完成步骤 ──────────────────────────────────────────

@router.post("/{goal_id}/steps/{step_id}/complete")
def complete_step_manually(
    goal_id: int,
    step_id: int,
    req: AgentGoalStepCompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动完成线下任务步骤（文档 Section 8.6）"""
    from app.services.agent_goal_step_runner_service import agent_goal_step_runner_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_step_runner_service.complete_manual_step(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            result_summary=req.result_summary,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.7 暂停/恢复/取消/完成目标 ───────────────────────────────

@router.post("/{goal_id}/pause")
def pause_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """暂停目标（文档 Section 8.7）"""
    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_service.pause_goal(db, goal_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{goal_id}/resume")
def resume_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复目标"""
    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_service.resume_goal(db, goal_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{goal_id}/cancel")
def cancel_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消目标"""
    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_service.cancel_goal(db, goal_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{goal_id}/complete")
def complete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动标记目标完成"""
    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_service.complete_goal(db, goal_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 执行闭环增强 新增端点（文档 Section 8）
# ═══════════════════════════════════════════════════════════════

# ── 8.1 步骤 run 历史 ─────────────────────────────────────────

@router.get("/{goal_id}/steps/{step_id}/runs")
def get_step_runs(
    goal_id: int,
    step_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取某步骤的所有执行历史（文档 Section 8.1）"""
    try:
        _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_service.get_step_runs(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.2 run 详情 ──────────────────────────────────────────────

@router.get("/{goal_id}/runs/{run_id}")
def get_run_detail(
    goal_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单次执行的完整详情（文档 Section 8.2）"""
    try:
        _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_service.get_run_detail(
            db=db,
            goal_id=goal_id,
            run_id=run_id,
            student_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.3 刷新步骤复盘 ──────────────────────────────────────────

@router.post("/{goal_id}/steps/{step_id}/refresh-reflection")
def refresh_step_reflection(
    goal_id: int,
    step_id: int,
    req: AgentGoalRefreshReflectionRequest = AgentGoalRefreshReflectionRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """刷新步骤复盘（文档 Section 8.3）"""
    from app.services.agent_goal_reflection_service import agent_goal_reflection_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)

        step = db.query(AgentGoalStep).filter(
            AgentGoalStep.id == step_id,
            AgentGoalStep.goal_id == goal_id,
        ).first()

        if not step:
            raise ValueError("步骤不存在")

        result = agent_goal_reflection_service.refresh_step_reflection(
            db=db,
            goal=goal,
            step=step,
            student_id=current_user.id,
            force_llm=req.force_llm,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.4 重新规划 ──────────────────────────────────────────────

@router.post("/{goal_id}/replan")
def replan_goal(
    goal_id: int,
    req: AgentGoalReplanRequest = AgentGoalReplanRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新规划目标（文档 Section 8.4）"""
    from app.services.agent_goal_planner_service import agent_goal_planner_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_planner_service.replan_goal(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            reason=req.reason,
            preserve_completed_steps=req.preserve_completed_steps,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.5 插入补救步骤 ──────────────────────────────────────────

@router.post("/{goal_id}/steps/remedial")
def insert_remedial_step(
    goal_id: int,
    req: AgentGoalInsertRemedialStepRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动插入补救步骤（文档 Section 8.5）"""
    try:
        _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_service.insert_remedial_step(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            after_step_id=req.after_step_id,
            title=req.title,
            description=req.description,
            step_type=req.step_type,
            tool_name=req.tool_name,
            tool_args=req.tool_args,
            target_knowledge_point_ids=req.target_knowledge_point_ids,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.6 获取目标练习详情 ──────────────────────────────────────

@router.get("/{goal_id}/practice-sessions/{session_id}")
def get_goal_practice_detail(
    goal_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取目标关联的练习详情（文档 Section 8.6）"""
    from app.models.agent_practice import AgentPracticeSession, AgentPracticeQuestion, AgentPracticeAttempt

    try:
        _get_goal_and_check(db, goal_id, current_user)

        session = _get_goal_practice_session_or_repair(
            db=db,
            goal_id=goal_id,
            session_id=session_id,
            current_user=current_user,
        )

        # 目标页主动进入练习，恢复过期会话
        if session.status == "expired":
            session.status = "active"
            session.updated_at = datetime.utcnow()
            db.flush()

        # 获取题目
        questions = (
            db.query(AgentPracticeQuestion)
            .filter(AgentPracticeQuestion.session_id == session_id)
            .order_by(AgentPracticeQuestion.question_no)
            .all()
        )

        # 获取作答记录
        attempts = (
            db.query(AgentPracticeAttempt)
            .filter(AgentPracticeAttempt.session_id == session_id)
            .all()
        )
        attempt_map = {a.question_no: a for a in attempts}

        questions_data = []
        for q in questions:
            attempt = attempt_map.get(q.question_no)
            # 不泄漏答案到前端（除非 include_answer_on_display 开启）
            options = q.options_json or []
            questions_data.append({
                "id": q.id,
                "question_no": q.question_no,
                "stem": q.stem,
                "options": options,
                "status": q.status,
                "submitted_answer": attempt.submitted_answer if attempt else None,
                "is_correct": bool(attempt.is_correct) if attempt else None,
                "feedback_text": attempt.feedback_text if attempt else None,
                "explanation": q.explanation if session.include_answer_on_display else None,
            })

        return {
            "session": {
                "id": session.id,
                "status": session.status,
                "topic": session.topic,
                "question_count": session.question_count,
                "answered_count": session.answered_count,
                "correct_count": session.correct_count,
                "delivery_mode": session.delivery_mode,
                "include_answer_on_display": bool(session.include_answer_on_display),
                "include_explanation_on_display": bool(session.include_explanation_on_display),
            },
            "questions": questions_data,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 8.7 提交目标练习答案 ──────────────────────────────────────

@router.post("/{goal_id}/practice-sessions/{session_id}/answer")
def submit_goal_practice_answer(
    goal_id: int,
    session_id: int,
    req: GoalPracticeAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交目标练习答案（文档 Section 8.7）"""
    from app.models.agent_practice import AgentPracticeSession, AgentPracticeQuestion, AgentPracticeAttempt
    from app.services.agent_goal_reflection_service import agent_goal_reflection_service
    from app.services.agent_goal_service import agent_goal_service as ags

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)

        session = _get_goal_practice_session_or_repair(
            db=db,
            goal_id=goal_id,
            session_id=session_id,
            current_user=current_user,
        )

        if session.status not in ("active", "expired"):
            raise ValueError(f"练习会话状态为 {session.status}，不能提交答案")

        # 目标页主动提交，恢复过期会话
        if session.status == "expired":
            session.status = "active"
            session.updated_at = datetime.utcnow()
            db.flush()

        # 获取题目
        question = db.query(AgentPracticeQuestion).filter(
            AgentPracticeQuestion.session_id == session_id,
            AgentPracticeQuestion.question_no == req.question_no,
        ).first()

        if not question:
            raise ValueError(f"题目 {req.question_no} 不存在")

        if question.status == "answered":
            raise ValueError(f"题目 {req.question_no} 已经作答")

        # 判断答案是否正确
        correct_answer = question.correct_answer.strip().upper()
        submitted = req.submitted_answer.strip().upper()
        is_correct = (submitted == correct_answer)

        # 生成反馈
        feedback = ""
        if is_correct:
            feedback = "回答正确！"
        else:
            feedback = f"回答错误。正确答案是 {question.correct_answer}。"

        if question.explanation:
            feedback += f"\n\n解析：{question.explanation}"

        # 保存 attempt
        attempt = AgentPracticeAttempt(
            session_id=session_id,
            question_id=question.id,
            conversation_id=session.conversation_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            question_no=req.question_no,
            submitted_answer=req.submitted_answer,
            normalized_answer=submitted,
            is_correct=1 if is_correct else 0,
            grading_method="rule",
            feedback_text=feedback,
        )
        db.add(attempt)

        # 更新题目状态
        question.status = "answered"
        question.updated_at = datetime.utcnow()

        # 更新 session 计数
        session.answered_count = (session.answered_count or 0) + 1
        if is_correct:
            session.correct_count = (session.correct_count or 0) + 1
        session.updated_at = datetime.utcnow()

        db.flush()

        # 检查 session 是否完成
        session_completed = session.answered_count >= session.question_count
        auto_advance_result = None
        if session_completed:
            session.status = "completed"
            session.completed_at = datetime.utcnow()

            # 更新对应 step 的 user_action_status
            if session.goal_step_id:
                step = db.query(AgentGoalStep).filter(
                    AgentGoalStep.id == session.goal_step_id,
                ).first()
                if step:
                    step.user_action_status = "completed"
                    step.result_summary = f"完成 {session.question_count} 道题，正确 {session.correct_count} 道，正确率 {session.correct_count / max(session.question_count, 1):.0%}"

                    # 质量门禁检查
                    accuracy = session.correct_count / max(session.question_count, 1)
                    if accuracy >= 0.6:
                        step.status = "completed"
                        step.completed_at = datetime.utcnow()
                    else:
                        # 不达标：步骤完成但插入补救
                        step.status = "completed"
                        step.completed_at = datetime.utcnow()

                    # 更新对应的 run
                    if session.goal_run_id:
                        run = db.query(AgentGoalRun).filter(
                            AgentGoalRun.id == session.goal_run_id,
                        ).first()
                        if run:
                            run.user_action_status = "completed"

            # 刷新复盘
            try:
                if session.goal_step_id:
                    step = db.query(AgentGoalStep).filter(
                        AgentGoalStep.id == session.goal_step_id,
                    ).first()
                    if step:
                        agent_goal_reflection_service.refresh_step_reflection(
                            db=db,
                            goal=goal,
                            step=step,
                            student_id=current_user.id,
                            force_llm=False,
                        )
            except Exception:
                logger.exception("刷新复盘失败 session_id=%s", session_id)

            # 更新目标进度
            progress = ags.recalculate_progress(db, goal_id)
            goal.progress_percent = progress

            # 检查目标完成
            ags.check_goal_completion(db, goal_id)

            # 练习完成后自动触发下一步推进（文档 Section 14）
            try:
                from app.services.agent_goal_loop_service import agent_goal_loop_service
                auto_advance_result = agent_goal_loop_service.run_goal_loop(
                    db=db,
                    goal_id=goal_id,
                    student_id=current_user.id,
                    course_id=goal.course_id,
                    max_iterations=2,
                    max_seconds=60,
                    allow_generate_plan=True,
                    allow_replan=False,
                    allow_retry=True,
                    stop_on_user_action=True,
                    trigger_type="practice_completed",
                )
            except Exception:
                logger.exception("练习完成后自动推进失败 goal_id=%s session_id=%s", goal_id, session_id)

        db.commit()

        response_data = {
            "question_no": req.question_no,
            "is_correct": is_correct,
            "feedback": feedback,
            "session_completed": session_completed,
            "session_summary": {
                "answered_count": session.answered_count,
                "question_count": session.question_count,
                "correct_count": session.correct_count,
            } if session_completed else None,
        }

        # 自动推进结果附加到响应
        if auto_advance_result:
            response_data["auto_advance_result"] = auto_advance_result

        return response_data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 目标推进闭环 新增端点（文档 Section 11）
# ═══════════════════════════════════════════════════════════════

# ── 11.1 推进目标一次 ─────────────────────────────────────────

@router.post("/{goal_id}/advance")
def advance_goal(
    goal_id: int,
    req: AgentGoalAdvanceRequest = AgentGoalAdvanceRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """推进目标一次（文档 Section 11.1）"""
    from app.services.agent_goal_advance_service import agent_goal_advance_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_advance_service.advance_once(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            allow_generate_plan=req.allow_generate_plan,
            allow_replan=req.allow_replan,
            allow_retry=req.allow_retry,
            force_step_id=req.force_step_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 11.2 获取目标推进记录列表 ──────────────────────────────────

@router.get("/{goal_id}/advance-cycles")
def list_advance_cycles(
    goal_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取目标推进记录列表（文档 Section 11.2）"""
    from app.services.agent_goal_advance_service import agent_goal_advance_service

    try:
        _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_advance_service.list_advance_cycles(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 11.3 获取单次推进详情 ──────────────────────────────────────

@router.get("/{goal_id}/advance-cycles/{cycle_id}")
def get_advance_cycle_detail(
    goal_id: int,
    cycle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单次推进详情（含快照和追踪信息）（文档 Section 11.3）"""
    from app.services.agent_goal_advance_service import agent_goal_advance_service

    try:
        _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_advance_service.get_advance_cycle_detail(
            db=db,
            goal_id=goal_id,
            cycle_id=cycle_id,
            student_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 目标多轮自主推进循环 新增端点（文档 Section 15）
# ═══════════════════════════════════════════════════════════════

# ── 15.1 运行多轮自主推进 ─────────────────────────────────

@router.post("/{goal_id}/run-loop")
def run_goal_loop(
    goal_id: int,
    req: AgentGoalLoopRunRequest = AgentGoalLoopRunRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """运行目标多轮自主推进循环（文档 Section 15.1）"""
    from app.services.agent_goal_loop_service import agent_goal_loop_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_loop_service.run_goal_loop(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            max_iterations=req.max_iterations,
            max_seconds=req.max_seconds,
            allow_generate_plan=req.allow_generate_plan,
            allow_replan=req.allow_replan,
            allow_retry=req.allow_retry,
            stop_on_user_action=req.stop_on_user_action,
            trigger_type=req.trigger_type,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 15.2 获取循环记录列表 ─────────────────────────────────

@router.get("/{goal_id}/loop-runs")
def list_loop_runs(
    goal_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取目标循环运行记录列表（文档 Section 15.2）"""
    from app.services.agent_goal_loop_service import agent_goal_loop_service

    try:
        _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_loop_service.list_loop_runs(
            db=db,
            goal_id=goal_id,
            student_id=current_user.id,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 15.3 获取循环详情 ─────────────────────────────────────

@router.get("/{goal_id}/loop-runs/{loop_run_id}")
def get_loop_run_detail(
    goal_id: int,
    loop_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单次循环运行详情（文档 Section 15.3）"""
    from app.services.agent_goal_loop_service import agent_goal_loop_service

    try:
        _get_goal_and_check(db, goal_id, current_user)
        return agent_goal_loop_service.get_loop_run_detail(
            db=db,
            goal_id=goal_id,
            loop_run_id=loop_run_id,
            student_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 用户动作门控 新增端点（文档 Section 10）
# ═══════════════════════════════════════════════════════════════

# ── 10.1 开始用户动作 ───────────────────────────────────────

@router.post("/{goal_id}/steps/{step_id}/user-actions/start")
def start_user_action(
    goal_id: int,
    step_id: int,
    req: AgentGoalUserActionStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始用户学习动作（文档 Section 10.1）"""
    from app.services.agent_goal_user_action_service import agent_goal_user_action_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_user_action_service.start_action(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            action_type=req.action_type,
            target_type=req.target_type,
            target_id=req.target_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 10.2 阅读心跳 ───────────────────────────────────────────

@router.post("/{goal_id}/steps/{step_id}/user-actions/heartbeat")
def heartbeat_user_action(
    goal_id: int,
    step_id: int,
    req: AgentGoalUserActionHeartbeatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """阅读心跳（文档 Section 10.2）"""
    from app.services.agent_goal_user_action_service import agent_goal_user_action_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_user_action_service.heartbeat(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            action_uuid=req.action_uuid,
            visible=req.visible,
            active_seconds=req.active_seconds,
            trigger_auto_advance=False,
        )
        if result.get("completed") and req.action_uuid:
            background_tasks.add_task(
                _trigger_user_action_auto_advance_background,
                goal_id,
                step_id,
                current_user.id,
                goal.course_id,
                req.action_uuid,
            )
            result["auto_advance_queued"] = True
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 10.3 手动完成用户动作 ───────────────────────────────────

@router.post("/{goal_id}/steps/{step_id}/user-actions/complete")
def complete_user_action(
    goal_id: int,
    step_id: int,
    background_tasks: BackgroundTasks,
    req: AgentGoalUserActionCompleteRequest = AgentGoalUserActionCompleteRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """手动完成用户动作（文档 Section 10.3）"""
    from app.services.agent_goal_user_action_service import agent_goal_user_action_service

    try:
        goal = _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_user_action_service.complete_action(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=current_user.id,
            course_id=goal.course_id,
            action_uuid=req.action_uuid,
            action_type=req.action_type,
            target_type=req.target_type,
            target_id=req.target_id,
            trigger_auto_advance=False,
        )
        if req.trigger_auto_advance and result.get("action_uuid"):
            background_tasks.add_task(
                _trigger_user_action_auto_advance_background,
                goal_id,
                step_id,
                current_user.id,
                goal.course_id,
                result["action_uuid"],
            )
            result["auto_advance_queued"] = True
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 10.4 查询最新动作状态 ───────────────────────────────────

@router.get("/{goal_id}/steps/{step_id}/user-actions/latest")
def get_latest_user_action(
    goal_id: int,
    step_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询步骤最新用户动作状态（文档 Section 10.4）"""
    from app.services.agent_goal_user_action_service import agent_goal_user_action_service

    try:
        _get_goal_and_check(db, goal_id, current_user)
        result = agent_goal_user_action_service.get_latest_action(
            db=db,
            goal_id=goal_id,
            step_id=step_id,
            student_id=current_user.id,
        )
        return result or {}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
