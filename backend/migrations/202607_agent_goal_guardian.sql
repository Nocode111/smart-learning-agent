-- 长期目标守护与主动调度阶段 — 数据库迁移
-- 文档：docs/长期目标守护与主动调度阶段_详细落地技术开发文档.md Section 7
-- 创建日期：2026-07-02

-- 7.1 目标守护配置表
CREATE TABLE IF NOT EXISTS agent_goal_guardian_configs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    goal_id BIGINT NOT NULL UNIQUE,
    student_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,

    enabled TINYINT NOT NULL DEFAULT 1,
    guard_level VARCHAR(32) NOT NULL DEFAULT 'normal',

    check_interval_minutes INT NOT NULL DEFAULT 60,
    quiet_start_time TIME NULL,
    quiet_end_time TIME NULL,

    stale_action_hours INT NOT NULL DEFAULT 12,
    due_soon_days INT NOT NULL DEFAULT 3,
    progress_lag_threshold DECIMAL(5,2) NOT NULL DEFAULT 20.00,
    low_quality_threshold DECIMAL(5,2) NOT NULL DEFAULT 60.00,

    allow_auto_prepare TINYINT NOT NULL DEFAULT 1,
    allow_auto_remedial TINYINT NOT NULL DEFAULT 1,
    allow_auto_replan_suggestion TINYINT NOT NULL DEFAULT 1,
    allow_auto_replan_apply TINYINT NOT NULL DEFAULT 0,

    last_checked_at DATETIME NULL,
    next_check_at DATETIME NULL,
    last_guardian_run_id BIGINT NULL,

    metadata_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_guardian_config_student_course (student_id, course_id),
    INDEX idx_guardian_config_enabled_next (enabled, next_check_at),
    INDEX idx_guardian_config_goal (goal_id)
);

-- 7.2 目标守护执行记录表
CREATE TABLE IF NOT EXISTS agent_goal_guardian_runs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    run_uuid VARCHAR(64) NOT NULL UNIQUE,

    goal_id BIGINT NOT NULL,
    student_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,

    trigger_type VARCHAR(64) NOT NULL DEFAULT 'scheduler',
    status VARCHAR(32) NOT NULL DEFAULT 'running',

    snapshot_json JSON NULL,
    decisions_json JSON NULL,
    actions_json JSON NULL,

    risk_level VARCHAR(32) NULL,
    summary TEXT NULL,
    error_message TEXT NULL,

    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_guardian_run_goal (goal_id),
    INDEX idx_guardian_run_student_course (student_id, course_id),
    INDEX idx_guardian_run_status (status),
    INDEX idx_guardian_run_started (started_at)
);

-- 7.3 目标守护事件表（前端展示提醒）
CREATE TABLE IF NOT EXISTS agent_goal_guardian_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    goal_id BIGINT NOT NULL,
    guardian_run_id BIGINT NULL,
    student_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,

    event_type VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL DEFAULT 'info',
    title VARCHAR(255) NOT NULL,
    message TEXT NULL,

    action_type VARCHAR(64) NULL,
    action_payload_json JSON NULL,

    status VARCHAR(32) NOT NULL DEFAULT 'unread',
    read_at DATETIME NULL,
    dismissed_at DATETIME NULL,

    dedupe_key VARCHAR(128) NULL,
    metadata_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_guardian_event_goal (goal_id),
    INDEX idx_guardian_event_student_status (student_id, status),
    INDEX idx_guardian_event_type (event_type),
    INDEX idx_guardian_event_dedupe (dedupe_key)
);

-- 7.4 目标每日快照表
CREATE TABLE IF NOT EXISTS agent_goal_daily_snapshots (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    goal_id BIGINT NOT NULL,
    student_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    snapshot_date DATE NOT NULL,

    goal_status VARCHAR(32) NOT NULL,
    progress_percent DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    completed_steps INT NOT NULL DEFAULT 0,
    total_steps INT NOT NULL DEFAULT 0,
    waiting_steps INT NOT NULL DEFAULT 0,
    failed_steps INT NOT NULL DEFAULT 0,

    latest_activity_at DATETIME NULL,
    expected_progress DECIMAL(5,2) NULL,
    progress_lag DECIMAL(5,2) NULL,

    practice_count INT NOT NULL DEFAULT 0,
    avg_practice_accuracy DECIMAL(5,2) NULL,

    snapshot_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_goal_snapshot_date (goal_id, snapshot_date),
    INDEX idx_daily_snapshot_student_course (student_id, course_id),
    INDEX idx_daily_snapshot_date (snapshot_date)
);
