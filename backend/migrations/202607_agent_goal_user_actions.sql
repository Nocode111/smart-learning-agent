-- 学习步骤完成门控与事件触发推进阶段 — 用户动作表
-- 文档：docs/学习步骤完成门控与事件触发推进阶段_详细落地技术开发文档.md Section 7
-- 创建日期：2026-07-02

CREATE TABLE IF NOT EXISTS agent_goal_user_actions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    action_uuid VARCHAR(64) NOT NULL UNIQUE,

    goal_id BIGINT NOT NULL,
    step_id BIGINT NOT NULL,
    run_id BIGINT NULL,
    student_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,

    action_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'started',

    target_type VARCHAR(64) NULL,
    target_id BIGINT NULL,

    required_seconds INT NOT NULL DEFAULT 30,
    accumulated_seconds INT NOT NULL DEFAULT 0,

    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat_at DATETIME NULL,
    completed_at DATETIME NULL,

    metadata_json JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_goal_user_action_goal (goal_id),
    INDEX idx_goal_user_action_step (step_id),
    INDEX idx_goal_user_action_student_course (student_id, course_id),
    INDEX idx_goal_user_action_status (status),
    INDEX idx_goal_user_action_type (action_type)
);
