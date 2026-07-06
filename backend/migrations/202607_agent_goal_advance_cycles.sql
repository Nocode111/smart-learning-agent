-- ============================================================
-- 目标执行闭环增强阶段 数据库迁移（文档 Section 8）
-- 版本：v1.0
-- 日期：2026-07-02
-- 依赖：202607_agent_goal_execution_loop.sql 已执行
-- 数据库：MySQL 8.0+
-- 安全：可重复执行，已存在的表/列会被跳过
-- ============================================================

DELIMITER $$

-- 辅助存储过程：安全创建表（如表已存在则跳过）
DROP PROCEDURE IF EXISTS safe_create_table$$
CREATE PROCEDURE safe_create_table(
    IN tbl_name VARCHAR(128),
    IN tbl_def TEXT
)
BEGIN
    DECLARE tbl_count INT DEFAULT 0;
    SELECT COUNT(*) INTO tbl_count
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = tbl_name;

    IF tbl_count = 0 THEN
        SET @sql = tbl_def;
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('[OK] Created table ', tbl_name) AS result;
    ELSE
        SELECT CONCAT('[SKIP] Table ', tbl_name, ' already exists') AS result;
    END IF;
END$$

-- 辅助存储过程：安全添加列（如列已存在则跳过）
DROP PROCEDURE IF EXISTS safe_add_column$$
CREATE PROCEDURE safe_add_column(
    IN tbl_name VARCHAR(128),
    IN col_name VARCHAR(128),
    IN col_def VARCHAR(512)
)
BEGIN
    DECLARE col_count INT DEFAULT 0;
    SELECT COUNT(*) INTO col_count
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = tbl_name
      AND COLUMN_NAME = col_name;

    IF col_count = 0 THEN
        SET @sql = CONCAT('ALTER TABLE ', tbl_name, ' ADD COLUMN ', col_name, ' ', col_def);
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('[OK] Added ', col_name, ' to ', tbl_name) AS result;
    ELSE
        SELECT CONCAT('[SKIP] ', col_name, ' already exists in ', tbl_name) AS result;
    END IF;
END$$

-- 辅助存储过程：安全创建索引（如索引已存在则跳过）
DROP PROCEDURE IF EXISTS safe_create_index$$
CREATE PROCEDURE safe_create_index(
    IN idx_name VARCHAR(128),
    IN tbl_name VARCHAR(128),
    IN idx_cols VARCHAR(512)
)
BEGIN
    DECLARE idx_count INT DEFAULT 0;
    SELECT COUNT(*) INTO idx_count
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = tbl_name
      AND INDEX_NAME = idx_name;

    IF idx_count = 0 THEN
        SET @sql = CONCAT('CREATE INDEX ', idx_name, ' ON ', tbl_name, ' (', idx_cols, ')');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('[OK] Created index ', idx_name, ' on ', tbl_name) AS result;
    ELSE
        SELECT CONCAT('[SKIP] Index ', idx_name, ' already exists on ', tbl_name) AS result;
    END IF;
END$$

DELIMITER ;

-- ============================================================
-- 8.1 新建 agent_goal_advance_cycles 表
-- ============================================================
CALL safe_create_table('agent_goal_advance_cycles', '
CREATE TABLE agent_goal_advance_cycles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    goal_id BIGINT NOT NULL,
    student_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,

    cycle_uuid VARCHAR(64) NOT NULL UNIQUE,
    trigger_type VARCHAR(32) NOT NULL DEFAULT ''user_click'',
    status VARCHAR(32) NOT NULL DEFAULT ''running'',

    decision_type VARCHAR(64) NULL,
    decision_reason TEXT NULL,

    selected_step_id BIGINT NULL,
    selected_run_id BIGINT NULL,
    selected_reflection_id BIGINT NULL,

    action_required TINYINT NOT NULL DEFAULT 0,
    action_type VARCHAR(64) NULL,
    action_payload_json JSON NULL,

    before_snapshot_json JSON NULL,
    after_snapshot_json JSON NULL,
    agent_trace_json JSON NULL,

    result_summary TEXT NULL,
    error_message TEXT NULL,

    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_goal_advance_goal (goal_id),
    INDEX idx_goal_advance_student_course (student_id, course_id),
    INDEX idx_goal_advance_status (status),
    INDEX idx_goal_advance_decision (decision_type),
    INDEX idx_goal_advance_started_at (started_at)
)');

-- ============================================================
-- 8.2 agent_learning_goals 增量字段（可选缓存字段）
-- ============================================================
CALL safe_add_column('agent_learning_goals', 'last_advance_cycle_id', 'BIGINT NULL AFTER metadata_json');
CALL safe_add_column('agent_learning_goals', 'next_action_type', 'VARCHAR(64) NULL AFTER last_advance_cycle_id');
CALL safe_add_column('agent_learning_goals', 'next_action_payload_json', 'JSON NULL AFTER next_action_type');
CALL safe_add_column('agent_learning_goals', 'last_agent_summary', 'TEXT NULL AFTER next_action_payload_json');

-- ============================================================
-- 清理存储过程（可选，注释掉则保留以备后续使用）
-- ============================================================
-- DROP PROCEDURE IF EXISTS safe_create_table;
-- DROP PROCEDURE IF EXISTS safe_add_column;
-- DROP PROCEDURE IF EXISTS safe_create_index;

SELECT '========================================' AS '';
SELECT '  目标执行闭环增强 迁移完成！' AS '';
SELECT '========================================' AS '';
