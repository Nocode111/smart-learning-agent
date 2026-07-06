-- 目标Agent多轮自主推进循环阶段 数据库迁移
-- 文档：docs/目标Agent多轮自主推进循环阶段_详细落地技术开发文档.md Section 12

-- 12.2 目标循环运行主表
CREATE TABLE IF NOT EXISTS agent_goal_loop_runs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    loop_uuid VARCHAR(64) NOT NULL UNIQUE,

    goal_id BIGINT NOT NULL,
    student_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    conversation_id BIGINT NULL,

    trigger_type VARCHAR(32) NOT NULL DEFAULT 'user_click',
    status VARCHAR(32) NOT NULL DEFAULT 'running',

    max_iterations INT NOT NULL DEFAULT 3,
    completed_iterations INT NOT NULL DEFAULT 0,
    max_seconds INT NOT NULL DEFAULT 60,

    stop_reason VARCHAR(64) NULL,
    action_required TINYINT NOT NULL DEFAULT 0,
    action_type VARCHAR(64) NULL,
    action_payload_json JSON NULL,

    summary TEXT NULL,
    error_message TEXT NULL,
    final_goal_snapshot_json JSON NULL,

    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_goal_loop_goal (goal_id),
    INDEX idx_goal_loop_student_course (student_id, course_id),
    INDEX idx_goal_loop_status (status),
    INDEX idx_goal_loop_started_at (started_at)
);

-- 12.3 循环迭代明细表
CREATE TABLE IF NOT EXISTS agent_goal_loop_iterations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    loop_run_id BIGINT NOT NULL,
    iteration_no INT NOT NULL,

    goal_id BIGINT NOT NULL,
    advance_cycle_id BIGINT NULL,
    step_id BIGINT NULL,
    run_id BIGINT NULL,
    reflection_id BIGINT NULL,

    status VARCHAR(32) NOT NULL DEFAULT 'running',
    decision_type VARCHAR(64) NULL,
    thought_summary TEXT NULL,
    action_summary TEXT NULL,
    observation_json JSON NULL,
    evaluation_json JSON NULL,

    stop_after_iteration TINYINT NOT NULL DEFAULT 0,
    stop_reason VARCHAR(64) NULL,
    error_message TEXT NULL,

    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_loop_iter_loop (loop_run_id),
    INDEX idx_loop_iter_goal (goal_id),
    INDEX idx_loop_iter_advance (advance_cycle_id),
    INDEX idx_loop_iter_status (status)
);
