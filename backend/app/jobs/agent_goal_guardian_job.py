"""
长期目标守护定时调度任务（文档 Section 11）

使用 APScheduler 每 5 分钟检查一次需要守护的目标。
每次最多扫描 20 个 due config。
每个目标内部根据 check_interval_minutes 控制实际守护频率。
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import SessionLocal
from app.services.agent_goal_guardian_service import agent_goal_guardian_service

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def run_goal_guardian_tick():
    """定时守护 tick：扫描需要守护的目标并执行"""
    db = SessionLocal()
    try:
        result = agent_goal_guardian_service.guard_due_goals(
            db=db,
            limit=20,
            trigger_type="scheduler",
        )
        db.commit()
        checked = result.get("checked_count", 0)
        if checked > 0:
            logger.info("目标守护 tick 完成: 检查了 %s 个目标", checked)
    except Exception:
        db.rollback()
        logger.exception("目标守护 tick 执行失败")
    finally:
        db.close()


def start_goal_guardian_scheduler():
    """启动目标守护调度器（文档 Section 11.1）"""
    if scheduler.running:
        logger.debug("目标守护调度器已在运行，跳过启动")
        return

    scheduler.add_job(
        run_goal_guardian_tick,
        trigger=IntervalTrigger(minutes=5),
        id="agent_goal_guardian_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Agent 目标守护调度器已启动（每 5 分钟 tick）")


def shutdown_goal_guardian_scheduler():
    """关闭目标守护调度器（文档 Section 11.1）"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Agent 目标守护调度器已关闭")
