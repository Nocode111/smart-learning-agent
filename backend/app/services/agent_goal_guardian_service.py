"""
长期目标守护服务（文档 Section 9-10）

职责：
1. 创建默认守护配置
2. 定时扫描需要守护的目标
3. 对单个目标执行守护
4. 生成目标快照
5. 执行策略判断（6 种策略）
6. 写入守护 run / event / 每日快照
7. 触发自动准备下一步
8. 插入补救步骤
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.agent_goal import AgentLearningGoal, AgentGoalStep, AgentGoalRun
from app.models.agent_goal_guardian import (
    AgentGoalGuardianConfig,
    AgentGoalGuardianRun,
    AgentGoalGuardianEvent,
    AgentGoalDailySnapshot,
)
from app.models.agent_goal_loop import AgentGoalLoopRun
from app.utils.time_utils import now_shanghai, today_shanghai

logger = logging.getLogger(__name__)

# ── 默认配置（文档 Section 18） ──────────────────────────────────

DEFAULT_GUARDIAN_CONFIG = {
    "enabled": 1,
    "guard_level": "normal",
    "check_interval_minutes": 60,
    "stale_action_hours": 12,
    "due_soon_days": 3,
    "progress_lag_threshold": 20,
    "low_quality_threshold": 60,
    "allow_auto_prepare": 1,
    "allow_auto_remedial": 1,
    "allow_auto_replan_suggestion": 1,
    "allow_auto_replan_apply": 0,
}

# ── 轻量模式配置覆盖 ─────────────────────────────────────────────

LIGHT_MODE_OVERRIDES = {
    "allow_auto_prepare": 0,
    "allow_auto_remedial": 0,
}

# ── 严格模式配置覆盖 ─────────────────────────────────────────────

STRICT_MODE_OVERRIDES = {
    "stale_action_hours": 6,
    "due_soon_days": 7,
    "progress_lag_threshold": 10,
    "low_quality_threshold": 70,
}


class AgentGoalGuardianService:
    """长期目标守护服务"""

    # ═══════════════════════════════════════════════════════════════
    # 配置管理
    # ═══════════════════════════════════════════════════════════════

    def ensure_config_for_goal(self, db: Session, goal) -> AgentGoalGuardianConfig:
        """为目标创建或获取守护配置（文档 Section 19）"""
        config = db.query(AgentGoalGuardianConfig).filter(
            AgentGoalGuardianConfig.goal_id == goal.id
        ).first()

        if config:
            return config

        config = AgentGoalGuardianConfig(
            goal_id=goal.id,
            student_id=goal.student_id,
            course_id=goal.course_id,
            **DEFAULT_GUARDIAN_CONFIG,
            next_check_at=now_shanghai() + timedelta(minutes=DEFAULT_GUARDIAN_CONFIG["check_interval_minutes"]),
        )
        db.add(config)
        db.flush()
        logger.info("为目标 %s 创建默认守护配置", goal.id)
        return config

    def list_due_goal_configs(
        self, db: Session, limit: int = 20
    ) -> list[AgentGoalGuardianConfig]:
        """查询需要守护的目标配置（next_check_at <= now 且 enabled=1）（文档 Section 11.3）"""
        now = now_shanghai()
        configs = (
            db.query(AgentGoalGuardianConfig)
            .filter(
                AgentGoalGuardianConfig.enabled == 1,
                AgentGoalGuardianConfig.next_check_at <= now,
            )
            .order_by(AgentGoalGuardianConfig.next_check_at.asc())
            .limit(limit)
            .all()
        )
        return configs

    # ═══════════════════════════════════════════════════════════════
    # 批量守护
    # ═══════════════════════════════════════════════════════════════

    def guard_due_goals(
        self, db: Session, limit: int = 20, trigger_type: str = "scheduler"
    ) -> dict:
        """扫描需要守护的目标并逐个执行（文档 Section 10.2）"""
        configs = self.list_due_goal_configs(db, limit=limit)
        results = []

        for config in configs:
            try:
                result = self.guard_goal(db, config.goal_id, trigger_type=trigger_type)
                results.append(result)
            except Exception:
                logger.exception("守护目标 %s 失败", config.goal_id)
                results.append({
                    "goal_id": config.goal_id,
                    "status": "failed",
                    "error": "守护执行异常",
                })

        return {
            "checked_count": len(results),
            "results": results,
        }

    # ═══════════════════════════════════════════════════════════════
    # 单个目标守护（核心流程 — 文档 Section 10.3）
    # ═══════════════════════════════════════════════════════════════

    def guard_goal(
        self, db: Session, goal_id: int, trigger_type: str = "scheduler"
    ) -> dict:
        """对单个目标执行一次守护检查"""
        from app.services.agent_goal_service import agent_goal_service

        # 1. 加载 goal
        goal = db.query(AgentLearningGoal).filter(
            AgentLearningGoal.id == goal_id
        ).first()
        if not goal:
            return {"goal_id": goal_id, "status": "skipped", "reason": "目标不存在"}

        # 2. 只有 active/completed 才守护
        if goal.status not in ("active", "completed"):
            return {"goal_id": goal_id, "status": "skipped", "reason": f"目标状态为 {goal.status}"}

        # 3. 加载或创建 config
        config = self.ensure_config_for_goal(db, goal)

        # 并发保护：检查是否已有 running guardian_run（文档 Section 12.1）
        running_guardian = db.query(AgentGoalGuardianRun).filter(
            AgentGoalGuardianRun.goal_id == goal_id,
            AgentGoalGuardianRun.status == "running",
        ).first()
        if running_guardian:
            return {"goal_id": goal_id, "status": "locked", "reason": "已有正在执行的守护"}

        # 4. 创建 guardian_run
        run_uuid_str = f"guardian_{uuid.uuid4().hex[:12]}"
        guardian_run = AgentGoalGuardianRun(
            run_uuid=run_uuid_str,
            goal_id=goal_id,
            student_id=goal.student_id,
            course_id=goal.course_id,
            trigger_type=trigger_type,
            status="running",
            started_at=now_shanghai(),
        )
        db.add(guardian_run)
        db.flush()

        try:
            # 5. 生成快照
            snapshot = self.build_snapshot(db, goal, config)
            guardian_run.snapshot_json = snapshot

            # 6. 策略判断
            decisions = self.evaluate_policies(db, goal, config, snapshot)
            guardian_run.decisions_json = decisions

            # 7. 执行动作
            actions = self.apply_decisions(db, goal, config, guardian_run, decisions)
            guardian_run.actions_json = actions

            # 8. 计算风险等级
            risk_level = self._compute_risk_level(decisions, snapshot)
            guardian_run.risk_level = risk_level

            # 9. 生成摘要
            guardian_run.summary = self._build_guardian_summary(decisions, actions)

            # 10. 创建每日快照
            self.create_daily_snapshot(db, goal, snapshot)

            # 11. 更新 config
            checked_at = now_shanghai()
            config.last_checked_at = checked_at
            config.next_check_at = checked_at + timedelta(minutes=int(config.check_interval_minutes or 60))
            config.last_guardian_run_id = guardian_run.id

            guardian_run.status = "completed"
            guardian_run.finished_at = now_shanghai()
            db.flush()

            events_created = len(actions.get("events_created", []))
            logger.info(
                "守护目标 %s 完成, risk=%s, events=%s, auto_prepare=%s",
                goal_id, risk_level, events_created, actions.get("auto_prepare_triggered", False),
            )

            return {
                "guardian_run_id": guardian_run.id,
                "goal_id": goal_id,
                "status": "completed",
                "risk_level": risk_level,
                "summary": guardian_run.summary,
                "events_created": events_created,
                "auto_prepare_triggered": actions.get("auto_prepare_triggered", False),
                "auto_prepare_result": actions.get("auto_prepare_result"),
            }

        except Exception as e:
            logger.exception("守护目标 %s 失败", goal_id)
            guardian_run.status = "failed"
            guardian_run.error_message = str(e)
            guardian_run.finished_at = now_shanghai()
            db.flush()
            raise

    # ═══════════════════════════════════════════════════════════════
    # 快照生成（文档 Section 9.1）
    # ═══════════════════════════════════════════════════════════════

    def build_snapshot(self, db: Session, goal, config) -> dict:
        """生成目标状态快照"""
        steps = (
            db.query(AgentGoalStep)
            .filter(AgentGoalStep.goal_id == goal.id)
            .order_by(AgentGoalStep.step_order)
            .all()
        )

        total_steps = len(steps)
        completed_steps = sum(1 for s in steps if s.status == "completed")
        pending_steps = sum(1 for s in steps if s.status == "pending")
        waiting_steps = sum(1 for s in steps if s.status == "waiting_user_action")
        failed_steps = sum(1 for s in steps if s.status in ("failed", "failed_final", "failed_retryable"))

        # 当前等待步骤
        current_step = None
        for s in steps:
            if s.status == "waiting_user_action":
                current_step = {
                    "id": s.id,
                    "order": s.step_order,
                    "title": s.title,
                    "step_type": s.step_type,
                    "status": s.status,
                    "user_action_type": s.user_action_type,
                    "user_action_status": s.user_action_status,
                }
                break

        # 最近活动时间
        latest_activity_at = None
        latest_run = (
            db.query(AgentGoalRun)
            .filter(AgentGoalRun.goal_id == goal.id)
            .order_by(desc(AgentGoalRun.started_at))
            .first()
        )
        if latest_run:
            latest_activity_at = latest_run.started_at

        hours_since_activity = None
        if latest_activity_at:
            delta = now_shanghai() - latest_activity_at
            hours_since_activity = round(delta.total_seconds() / 3600, 1)

        # 练习质量
        latest_practice_accuracy = None
        avg_practice_accuracy = None
        practice_count = 0
        try:
            from app.models.agent_practice import AgentPracticeSession
            practice_sessions = (
                db.query(AgentPracticeSession)
                .filter(
                    AgentPracticeSession.goal_id == goal.id,
                    AgentPracticeSession.status == "completed",
                )
                .order_by(desc(AgentPracticeSession.finished_at))
                .all()
            )
            practice_count = len(practice_sessions)
            if practice_sessions:
                accuracies = []
                for ps in practice_sessions:
                    if ps.question_count and ps.question_count > 0:
                        acc = ps.correct_count / ps.question_count * 100
                        accuracies.append(acc)
                if accuracies:
                    latest_practice_accuracy = round(accuracies[0], 2)
                    avg_practice_accuracy = round(sum(accuracies) / len(accuracies), 2)
        except Exception:
            logger.debug("查询练习质量失败", exc_info=True)

        # 进度与日程
        days_elapsed = None
        days_total = None
        days_left = None
        expected_progress = None
        progress_lag = None

        if goal.start_date and goal.due_date:
            days_total = (goal.due_date - goal.start_date).days
            today = today_shanghai()
            days_elapsed = (today - goal.start_date).days
            days_left = (goal.due_date - today).days
            if days_total > 0:
                expected_progress = round(min(days_elapsed / days_total * 100, 100), 2)
                current_progress = float(goal.progress_percent or 0)
                progress_lag = round(expected_progress - current_progress, 2)

        return {
            "goal": {
                "id": goal.id,
                "status": goal.status,
                "progress_percent": float(goal.progress_percent or 0),
                "due_date": str(goal.due_date) if goal.due_date else None,
                "target_score": float(goal.target_score) if goal.target_score else None,
                "current_score": float(goal.current_score) if goal.current_score else None,
            },
            "steps": {
                "total": total_steps,
                "completed": completed_steps,
                "pending": pending_steps,
                "waiting_user_action": waiting_steps,
                "failed": failed_steps,
                "current_step": current_step,
            },
            "activity": {
                "latest_activity_at": str(latest_activity_at) if latest_activity_at else None,
                "hours_since_activity": hours_since_activity,
            },
            "quality": {
                "latest_practice_accuracy": latest_practice_accuracy,
                "avg_practice_accuracy": avg_practice_accuracy,
            },
            "schedule": {
                "days_elapsed": days_elapsed,
                "days_total": days_total,
                "days_left": days_left,
                "expected_progress": expected_progress,
                "progress_lag": progress_lag,
            },
        }

    # ═══════════════════════════════════════════════════════════════
    # 策略判断（文档 Section 9.2-9.7）
    # ═══════════════════════════════════════════════════════════════

    def evaluate_policies(
        self, db: Session, goal, config, snapshot: dict
    ) -> list[dict]:
        """执行所有策略判断，返回 decisions 列表"""
        decisions = []

        # 策略六：目标完成复盘
        if goal.status == "completed":
            existing = db.query(AgentGoalGuardianEvent).filter(
                AgentGoalGuardianEvent.goal_id == goal.id,
                AgentGoalGuardianEvent.event_type == "goal_completed",
            ).first()
            if not existing:
                decisions.append({
                    "decision_type": "goal_completed",
                    "severity": "success",
                    "reason": "目标已全部完成",
                    "should_create_event": True,
                    "should_auto_prepare": False,
                    "should_insert_remedial": False,
                    "event": {
                        "event_type": "goal_completed",
                        "severity": "success",
                        "title": "目标已完成",
                        "message": self._build_completion_message(snapshot),
                    },
                })
            return decisions  # 已完成目标不做其他检查

        # 策略一：长时间未操作（文档 Section 9.2）
        stale_decision = self._evaluate_stale_action(db, goal, config, snapshot)
        if stale_decision:
            decisions.append(stale_decision)

        # 策略二：截止日期临近（文档 Section 9.3）
        due_soon_decision = self._evaluate_due_soon(db, goal, config, snapshot)
        if due_soon_decision:
            decisions.append(due_soon_decision)

        # 策略三：进度落后（文档 Section 9.4）
        progress_lag_decision = self._evaluate_progress_lag(db, goal, config, snapshot)
        if progress_lag_decision:
            decisions.append(progress_lag_decision)

        # 策略四：练习质量过低（文档 Section 9.5）
        low_quality_decision = self._evaluate_low_quality(db, goal, config, snapshot)
        if low_quality_decision:
            decisions.append(low_quality_decision)

        # 策略五：自动准备下一步（文档 Section 9.6）
        auto_prepare_decision = self._evaluate_auto_prepare(db, goal, config, snapshot)
        if auto_prepare_decision:
            decisions.append(auto_prepare_decision)

        return decisions

    def _evaluate_stale_action(self, db, goal, config, snapshot) -> dict | None:
        """策略一：检查是否长时间未操作"""
        current_step = snapshot["steps"]["current_step"]
        if not current_step:
            return None
        if current_step["user_action_status"] == "completed":
            return None

        hours_since = snapshot["activity"]["hours_since_activity"]
        if hours_since is None:
            return None

        threshold = int(config.stale_action_hours or 12)
        if hours_since < threshold:
            return None

        # 去重 key
        today_str = today_shanghai().isoformat()
        dedupe_key = f"stale_user_action:{goal.id}:{current_step['id']}:{today_str}"

        # 检查是否已存在
        existing = db.query(AgentGoalGuardianEvent).filter(
            AgentGoalGuardianEvent.dedupe_key == dedupe_key
        ).first()
        if existing:
            return None

        return {
            "decision_type": "stale_user_action",
            "severity": "warning",
            "reason": f"当前步骤等待用户操作超过 {threshold} 小时",
            "should_create_event": True,
            "should_auto_prepare": False,
            "should_insert_remedial": False,
            "event": {
                "event_type": "stale_user_action",
                "severity": "warning",
                "title": "有学习步骤等待完成",
                "message": f"你还有「{current_step['title']}」没有完成，建议今天继续学习。",
                "action_type": current_step.get("user_action_type"),
                "action_payload": {
                    "goal_id": goal.id,
                    "step_id": current_step["id"],
                },
                "dedupe_key": dedupe_key,
            },
        }

    def _evaluate_due_soon(self, db, goal, config, snapshot) -> dict | None:
        """策略二：截止日期临近"""
        schedule = snapshot["schedule"]
        days_left = schedule.get("days_left")
        if days_left is None:
            return None

        threshold = int(config.due_soon_days or 3)
        if days_left > threshold:
            return None

        progress = snapshot["goal"]["progress_percent"]
        if progress >= 100:
            return None

        today_str = today_shanghai().isoformat()
        dedupe_key = f"due_soon:{goal.id}:{today_str}"

        existing = db.query(AgentGoalGuardianEvent).filter(
            AgentGoalGuardianEvent.dedupe_key == dedupe_key
        ).first()
        if existing:
            return None

        return {
            "decision_type": "due_soon",
            "severity": "warning",
            "reason": f"距离截止还有 {days_left} 天，当前进度 {progress}%",
            "should_create_event": True,
            "should_auto_prepare": False,
            "should_insert_remedial": False,
            "event": {
                "event_type": "due_soon",
                "severity": "warning",
                "title": "目标截止日期临近",
                "message": f"距离目标截止还有 {days_left} 天，当前进度 {progress}%，建议优先完成当前待办步骤。",
                "action_type": "advance_goal",
                "action_payload": {"goal_id": goal.id},
                "dedupe_key": dedupe_key,
            },
        }

    def _evaluate_progress_lag(self, db, goal, config, snapshot) -> dict | None:
        """策略三：进度落后"""
        schedule = snapshot["schedule"]
        progress_lag = schedule.get("progress_lag")
        if progress_lag is None:
            return None

        threshold = float(config.progress_lag_threshold or 20)
        if progress_lag < threshold:
            return None

        today_str = today_shanghai().isoformat()
        dedupe_key = f"progress_lag:{goal.id}:{today_str}"

        existing = db.query(AgentGoalGuardianEvent).filter(
            AgentGoalGuardianEvent.dedupe_key == dedupe_key
        ).first()
        if existing:
            return None

        return {
            "decision_type": "progress_lag",
            "severity": "warning",
            "reason": f"期望进度 {schedule['expected_progress']}%，实际 {snapshot['goal']['progress_percent']}%，落后 {progress_lag}%",
            "should_create_event": True,
            "should_auto_prepare": False,
            "should_insert_remedial": False,
            "event": {
                "event_type": "progress_lag",
                "severity": "warning",
                "title": "学习进度落后",
                "message": f"当前进度落后于计划约 {progress_lag:.0f}%，建议今天多加一些学习时间。",
                "action_type": "advance_goal",
                "action_payload": {"goal_id": goal.id},
                "dedupe_key": dedupe_key,
            },
        }

    def _evaluate_low_quality(self, db, goal, config, snapshot) -> dict | None:
        """策略四：练习质量过低"""
        quality = snapshot["quality"]
        latest_accuracy = quality.get("latest_practice_accuracy")
        if latest_accuracy is None:
            return None

        threshold = float(config.low_quality_threshold or 60)
        if latest_accuracy >= threshold:
            return None

        # 找到最近完成的 practice session
        try:
            from app.models.agent_practice import AgentPracticeSession
            latest_session = (
                db.query(AgentPracticeSession)
                .filter(
                    AgentPracticeSession.goal_id == goal.id,
                    AgentPracticeSession.status == "completed",
                )
                .order_by(desc(AgentPracticeSession.finished_at))
                .first()
            )
            if not latest_session:
                return None

            session_id = latest_session.id
        except Exception:
            return None

        dedupe_key = f"low_quality:{goal.id}:{session_id}"
        existing = db.query(AgentGoalGuardianEvent).filter(
            AgentGoalGuardianEvent.dedupe_key == dedupe_key
        ).first()
        if existing:
            return None

        decision = {
            "decision_type": "low_quality",
            "severity": "warning",
            "reason": f"最近练习正确率 {latest_accuracy}%，低于阈值 {threshold}%",
            "should_create_event": True,
            "should_auto_prepare": False,
            "should_insert_remedial": bool(config.allow_auto_remedial),
            "event": {
                "event_type": "low_quality",
                "severity": "warning",
                "title": "练习正确率偏低",
                "message": f"最近一次练习正确率仅 {latest_accuracy:.0f}%，建议先巩固基础再继续。",
                "action_type": "practice_session",
                "action_payload": {"goal_id": goal.id, "practice_session_id": session_id},
                "dedupe_key": dedupe_key,
            },
        }

        if config.allow_auto_remedial:
            decision["remedial_step"] = {
                "step_type": "qa_explanation",
                "title": "薄弱知识点补充讲解",
                "description": f"练习正确率 {latest_accuracy:.0f}%，建议回顾相关知识点。",
            }

        return decision

    def _evaluate_auto_prepare(self, db, goal, config, snapshot) -> dict | None:
        """策略五：自动准备下一步（文档 Section 9.6）"""
        # 条件检查
        if not config.allow_auto_prepare:
            return None

        # 存在 waiting_user_action 时不自动准备
        if snapshot["steps"]["waiting_user_action"] > 0:
            return None

        # 存在 pending 或 failed_retryable 步骤
        has_pending = snapshot["steps"]["pending"] > 0
        has_failed = snapshot["steps"]["failed"] > 0
        if not has_pending and not has_failed:
            return None

        # 静默时段检查
        if config.quiet_start_time and config.quiet_end_time:
            now_time = now_shanghai().time()
            if config.quiet_start_time <= now_time <= config.quiet_end_time:
                return None

        # 并发保护：检查是否已有 running loop（文档 Section 12.2）
        running_loop = db.query(AgentGoalLoopRun).filter(
            AgentGoalLoopRun.goal_id == goal.id,
            AgentGoalLoopRun.status == "running",
        ).first()
        if running_loop:
            return None

        return {
            "decision_type": "auto_prepare",
            "severity": "info",
            "reason": "存在待执行步骤且无等待用户动作，可以自动准备下一步",
            "should_create_event": True,
            "should_auto_prepare": True,
            "should_insert_remedial": False,
            "event": {
                "event_type": "auto_prepare_started",
                "severity": "info",
                "title": "正在准备下一步学习材料",
                "message": "Agent 正在为你准备下一步学习材料，请稍候。",
            },
        }

    # ═══════════════════════════════════════════════════════════════
    # 执行决策（文档 Section 10.3 Step 7）
    # ═══════════════════════════════════════════════════════════════

    def apply_decisions(
        self,
        db: Session,
        goal,
        config,
        guardian_run: AgentGoalGuardianRun,
        decisions: list[dict],
    ) -> dict:
        """根据 decisions 执行动作"""
        events_created = []
        auto_prepare_triggered = False
        auto_prepare_result = None

        for decision in decisions:
            # 创建事件
            if decision.get("should_create_event") and decision.get("event"):
                event_data = decision["event"]
                event = self.create_event(
                    db=db,
                    goal=goal,
                    guardian_run=guardian_run,
                    event_type=event_data.get("event_type", decision["decision_type"]),
                    severity=event_data.get("severity", "info"),
                    title=event_data.get("title", ""),
                    message=event_data.get("message"),
                    action_type=event_data.get("action_type"),
                    action_payload=event_data.get("action_payload"),
                    dedupe_key=event_data.get("dedupe_key"),
                )
                if event:
                    events_created.append(event.id)

            # 自动准备下一步
            if decision.get("should_auto_prepare"):
                auto_prepare_triggered = True
                try:
                    auto_prepare_result = self._trigger_auto_prepare(db, goal)
                    # 创建完成事件
                    self.create_event(
                        db=db,
                        goal=goal,
                        guardian_run=guardian_run,
                        event_type="auto_prepare_finished",
                        severity="success" if auto_prepare_result.get("status") == "completed" else "warning",
                        title="学习材料准备完成" if auto_prepare_result.get("status") == "completed" else "自动准备未完成",
                        message=auto_prepare_result.get("summary", ""),
                        action_type=auto_prepare_result.get("action_type"),
                        action_payload=auto_prepare_result.get("action_payload"),
                    )
                except Exception:
                    logger.exception("自动准备下一步失败 goal_id=%s", goal.id)
                    self.create_event(
                        db=db,
                        goal=goal,
                        guardian_run=guardian_run,
                        event_type="auto_prepare_failed",
                        severity="danger",
                        title="自动准备失败",
                        message="Agent 尝试准备下一步学习材料时出错，请手动推进目标。",
                    )

            # 插入补救步骤
            if decision.get("should_insert_remedial") and decision.get("remedial_step"):
                try:
                    remedial = decision["remedial_step"]
                    self._insert_remedial_step(db, goal, remedial)
                    self.create_event(
                        db=db,
                        goal=goal,
                        guardian_run=guardian_run,
                        event_type="remedial_inserted",
                        severity="info",
                        title="已添加补救步骤",
                        message=f"已添加「{remedial['title']}」，建议先完成此步骤再继续。",
                    )
                except Exception:
                    logger.exception("插入补救步骤失败 goal_id=%s", goal.id)

        db.flush()
        return {
            "events_created": events_created,
            "auto_prepare_triggered": auto_prepare_triggered,
            "auto_prepare_result": auto_prepare_result,
        }

    def _trigger_auto_prepare(self, db: Session, goal) -> dict:
        """调用 run_goal_loop 自动准备下一步（文档 Section 9.6）"""
        from app.services.agent_goal_loop_service import agent_goal_loop_service

        result = agent_goal_loop_service.run_goal_loop(
            db=db,
            goal_id=goal.id,
            student_id=goal.student_id,
            course_id=goal.course_id,
            max_iterations=1,
            max_seconds=60,
            allow_generate_plan=True,
            allow_replan=False,
            allow_retry=True,
            stop_on_user_action=True,
            trigger_type="guardian",
        )

        summary = result.get("summary", "")
        action_type = None
        action_payload = None

        if result.get("action_required") and result.get("action_type"):
            action_type = result["action_type"]
            action_payload = result.get("action_payload")

        return {
            "status": result.get("status", "unknown"),
            "summary": summary,
            "stop_reason": result.get("stop_reason"),
            "action_type": action_type,
            "action_payload": action_payload,
        }

    def _insert_remedial_step(self, db: Session, goal, remedial: dict):
        """插入一个补救步骤（文档 Section 9.5）"""
        from app.models.agent_goal import AgentGoalStep
        from app.services.agent_goal_service import agent_goal_service

        max_order = (
            db.query(AgentGoalStep.step_order)
            .filter(AgentGoalStep.goal_id == goal.id)
            .order_by(AgentGoalStep.step_order.desc())
            .first()
        )
        next_order = (max_order[0] + 1) if max_order else 1

        step = AgentGoalStep(
            goal_id=goal.id,
            student_id=goal.student_id,
            course_id=goal.course_id,
            step_order=next_order,
            title=remedial.get("title", "补救学习"),
            description=remedial.get("description"),
            step_type=remedial.get("step_type", "qa_explanation"),
            tool_name=remedial.get("tool_name", "qa_answer"),
            tool_args_json=remedial.get("tool_args", {}),
            expected_outcome="补救步骤 — 巩固薄弱点",
            target_knowledge_point_ids=[],
            status="pending",
            metadata_json={
                "source": "guardian_remedial",
                "reason": remedial.get("description", ""),
            },
        )
        db.add(step)
        db.flush()

        # 更新进度
        progress = agent_goal_service.recalculate_progress(db, goal.id)
        goal.progress_percent = progress

        logger.info("守护自动插入补救步骤 goal_id=%s step_id=%s title=%s", goal.id, step.id, remedial.get("title"))
        return step

    # ═══════════════════════════════════════════════════════════════
    # 事件管理（文档 Section 10.3）
    # ═══════════════════════════════════════════════════════════════

    def create_event(
        self,
        db: Session,
        goal,
        guardian_run: AgentGoalGuardianRun | None,
        event_type: str,
        severity: str,
        title: str,
        message: str | None = None,
        action_type: str | None = None,
        action_payload: dict | None = None,
        dedupe_key: str | None = None,
    ) -> AgentGoalGuardianEvent | None:
        """创建守护事件，支持去重（文档 Section 12.3）"""
        # 去重检查
        if dedupe_key:
            existing = db.query(AgentGoalGuardianEvent).filter(
                AgentGoalGuardianEvent.dedupe_key == dedupe_key
            ).first()
            if existing:
                logger.debug("守护事件已存在，跳过 dedupe_key=%s", dedupe_key)
                return None

        event = AgentGoalGuardianEvent(
            goal_id=goal.id,
            guardian_run_id=guardian_run.id if guardian_run else None,
            student_id=goal.student_id,
            course_id=goal.course_id,
            event_type=event_type,
            severity=severity,
            title=title,
            message=message,
            action_type=action_type,
            action_payload_json=action_payload,
            status="unread",
            dedupe_key=dedupe_key,
        )
        db.add(event)
        db.flush()
        return event

    # ═══════════════════════════════════════════════════════════════
    # 每日快照（文档 Section 7.4）
    # ═══════════════════════════════════════════════════════════════

    def create_daily_snapshot(self, db: Session, goal, snapshot: dict) -> None:
        """创建或更新今日快照（幂等）"""
        today = today_shanghai()

        existing = db.query(AgentGoalDailySnapshot).filter(
            AgentGoalDailySnapshot.goal_id == goal.id,
            AgentGoalDailySnapshot.snapshot_date == today,
        ).first()

        if existing:
            # 更新现有快照
            existing.goal_status = snapshot["goal"]["status"]
            existing.progress_percent = snapshot["goal"]["progress_percent"]
            existing.completed_steps = snapshot["steps"]["completed"]
            existing.total_steps = snapshot["steps"]["total"]
            existing.waiting_steps = snapshot["steps"]["waiting_user_action"]
            existing.failed_steps = snapshot["steps"]["failed"]
            existing.latest_activity_at = (
                datetime.fromisoformat(snapshot["activity"]["latest_activity_at"])
                if snapshot["activity"]["latest_activity_at"]
                else None
            )
            existing.expected_progress = snapshot["schedule"].get("expected_progress")
            existing.progress_lag = snapshot["schedule"].get("progress_lag")
            existing.practice_count = 0  # 由查询决定
            existing.avg_practice_accuracy = snapshot["quality"].get("avg_practice_accuracy")
            existing.snapshot_json = snapshot
        else:
            new_snapshot = AgentGoalDailySnapshot(
                goal_id=goal.id,
                student_id=goal.student_id,
                course_id=goal.course_id,
                snapshot_date=today,
                goal_status=snapshot["goal"]["status"],
                progress_percent=snapshot["goal"]["progress_percent"],
                completed_steps=snapshot["steps"]["completed"],
                total_steps=snapshot["steps"]["total"],
                waiting_steps=snapshot["steps"]["waiting_user_action"],
                failed_steps=snapshot["steps"]["failed"],
                latest_activity_at=(
                    datetime.fromisoformat(snapshot["activity"]["latest_activity_at"])
                    if snapshot["activity"]["latest_activity_at"]
                    else None
                ),
                expected_progress=snapshot["schedule"].get("expected_progress"),
                progress_lag=snapshot["schedule"].get("progress_lag"),
                practice_count=0,
                avg_practice_accuracy=snapshot["quality"].get("avg_practice_accuracy"),
                snapshot_json=snapshot,
            )
            db.add(new_snapshot)
        db.flush()

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_risk_level(decisions: list[dict], snapshot: dict) -> str:
        """计算综合风险等级（文档 Section 22）"""
        severities = [d.get("severity", "info") for d in decisions]
        schedule = snapshot.get("schedule", {})

        # danger 条件
        days_left = schedule.get("days_left")
        progress = snapshot["goal"]["progress_percent"]
        progress_lag = schedule.get("progress_lag")

        if days_left is not None and days_left <= 1 and progress < 80:
            return "danger"
        if progress_lag is not None and progress_lag >= 50:
            return "danger"
        if any(d.get("decision_type") == "low_quality" for d in decisions):
            # 检查是否连续两次低质量
            if len([d for d in decisions if d.get("decision_type") == "low_quality"]) >= 2:
                return "danger"

        # warning 条件
        if "warning" in severities:
            return "warning"

        # success
        if any(d.get("decision_type") == "goal_completed" for d in decisions):
            return "success"

        return "info"

    @staticmethod
    def _build_guardian_summary(decisions: list[dict], actions: dict) -> str:
        """生成守护摘要"""
        parts = []
        decision_types = [d.get("decision_type") for d in decisions]

        if "stale_user_action" in decision_types:
            parts.append("发现等待完成的步骤，已生成提醒")
        if "due_soon" in decision_types:
            parts.append("截止日期临近")
        if "progress_lag" in decision_types:
            parts.append("进度落后于计划")
        if "low_quality" in decision_types:
            parts.append("练习正确率偏低")
        if "auto_prepare" in decision_types:
            if actions.get("auto_prepare_triggered"):
                result = actions.get("auto_prepare_result", {})
                if result.get("status") == "completed":
                    parts.append("已自动准备下一步学习材料")
                else:
                    parts.append("自动准备下一步未完成")
        if "goal_completed" in decision_types:
            parts.append("目标已完成，生成最终复盘")

        if not parts:
            parts.append("目标状态正常，无需额外操作")

        return "；".join(parts)

    @staticmethod
    def _build_completion_message(snapshot: dict) -> str:
        """生成目标完成消息"""
        total = snapshot["steps"]["total"]
        completed = snapshot["steps"]["completed"]
        avg_accuracy = snapshot["quality"].get("avg_practice_accuracy")
        parts = [f"本目标已完成，共完成 {completed}/{total} 个步骤"]
        if avg_accuracy is not None:
            parts.append(f"，练习平均正确率 {avg_accuracy:.0f}%")
        parts.append("。")
        return "".join(parts)


# ── 单例 ─────────────────────────────────────────────────────────

agent_goal_guardian_service = AgentGoalGuardianService()
