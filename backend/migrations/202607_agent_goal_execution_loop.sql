-- ============================================================
-- 目标执行闭环增强阶段 数据库迁移（文档 Section 5）
-- 版本：v1.0
-- 日期：2026-07-01
-- 依赖：202607_agent_learning_goals.sql 已执行
-- 数据库：MySQL 8.0+
-- 安全：可重复执行，已存在的列会被跳过
-- ============================================================

DELIMITER $$

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
-- 5.1 agent_goal_steps 增量字段
-- ============================================================
CALL safe_add_column('agent_goal_steps', 'depends_on_step_ids', 'JSON NULL AFTER estimated_minutes');
CALL safe_add_column('agent_goal_steps', 'execution_mode', "VARCHAR(32) NOT NULL DEFAULT 'manual_trigger' AFTER depends_on_step_ids");
CALL safe_add_column('agent_goal_steps', 'output_type', 'VARCHAR(64) NULL AFTER execution_mode');
CALL safe_add_column('agent_goal_steps', 'output_ref_json', 'JSON NULL AFTER output_type');
CALL safe_add_column('agent_goal_steps', 'quality_gate_json', 'JSON NULL AFTER output_ref_json');
CALL safe_add_column('agent_goal_steps', 'needs_user_action', 'TINYINT NOT NULL DEFAULT 0 AFTER quality_gate_json');
CALL safe_add_column('agent_goal_steps', 'user_action_type', 'VARCHAR(64) NULL AFTER needs_user_action');
CALL safe_add_column('agent_goal_steps', 'user_action_status', 'VARCHAR(32) NULL AFTER user_action_type');
CALL safe_add_column('agent_goal_steps', 'metadata_json', 'JSON NULL AFTER reflection_json');

-- ============================================================
-- 5.2 agent_goal_runs 增量字段
-- ============================================================
CALL safe_add_column('agent_goal_runs', 'output_type', 'VARCHAR(64) NULL AFTER tool_result_json');
CALL safe_add_column('agent_goal_runs', 'output_ref_json', 'JSON NULL AFTER output_type');
CALL safe_add_column('agent_goal_runs', 'quality_gate_result_json', 'JSON NULL AFTER output_ref_json');
CALL safe_add_column('agent_goal_runs', 'user_action_required', 'TINYINT NOT NULL DEFAULT 0 AFTER quality_gate_result_json');
CALL safe_add_column('agent_goal_runs', 'user_action_status', 'VARCHAR(32) NULL AFTER user_action_required');

-- ============================================================
-- 5.3 agent_practice_sessions 增量字段 + 索引
-- ============================================================
CALL safe_add_column('agent_practice_sessions', 'goal_id', 'BIGINT NULL AFTER course_id');
CALL safe_add_column('agent_practice_sessions', 'goal_step_id', 'BIGINT NULL AFTER goal_id');
CALL safe_add_column('agent_practice_sessions', 'goal_run_id', 'BIGINT NULL AFTER goal_step_id');

CALL safe_create_index('idx_practice_goal', 'agent_practice_sessions', 'goal_id');
CALL safe_create_index('idx_practice_goal_step', 'agent_practice_sessions', 'goal_step_id');
CALL safe_create_index('idx_practice_goal_run', 'agent_practice_sessions', 'goal_run_id');

-- ============================================================
-- 5.4 agent_goal_reflections 增量字段
-- ============================================================
CALL safe_add_column('agent_goal_reflections', 'applied_action_status', 'VARCHAR(32) NULL AFTER next_action');
CALL safe_add_column('agent_goal_reflections', 'applied_action_message', 'TEXT NULL AFTER applied_action_status');

-- ============================================================
-- 清理存储过程（可选，注释掉则保留以备后续使用）
-- ============================================================
-- DROP PROCEDURE IF EXISTS safe_add_column;
-- DROP PROCEDURE IF EXISTS safe_create_index;

SELECT '========================================' AS '';
SELECT '  目标执行闭环增强 迁移完成！' AS '';
SELECT '========================================' AS '';
