-- 长期目标驱动 Agent 数据库迁移（文档 Section 6）
-- 创建 4 张表：agent_learning_goals, agent_goal_steps, agent_goal_runs, agent_goal_reflections

-- 6.1 长期学习目标主表
CREATE TABLE IF NOT EXISTS agent_learning_goals (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  conversation_id BIGINT NULL,

  title VARCHAR(255) NOT NULL,
  goal_text TEXT NOT NULL,
  target_score DECIMAL(5,2) NULL,
  current_score DECIMAL(5,2) NULL,
  progress_percent DECIMAL(5,2) NOT NULL DEFAULT 0,

  target_knowledge_point_ids JSON,
  weak_knowledge_point_ids JSON,

  start_date DATE NULL,
  due_date DATE NULL,

  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  planning_status VARCHAR(32) NOT NULL DEFAULT 'none',

  plan_summary TEXT,
  plan_json JSON,
  metadata_json JSON,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  activated_at DATETIME NULL,
  paused_at DATETIME NULL,
  completed_at DATETIME NULL,
  canceled_at DATETIME NULL,

  INDEX idx_agent_goal_student_course (student_id, course_id),
  INDEX idx_agent_goal_status (status),
  INDEX idx_agent_goal_due_date (due_date),
  INDEX idx_agent_goal_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6.2 目标计划步骤表
CREATE TABLE IF NOT EXISTS agent_goal_steps (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  goal_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,

  step_order INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT,

  step_type VARCHAR(64) NOT NULL,
  tool_name VARCHAR(64) NULL,
  tool_args_json JSON,

  expected_outcome TEXT,
  success_criteria_json JSON,

  target_knowledge_point_ids JSON,
  estimated_minutes INT NULL,

  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  retry_count INT NOT NULL DEFAULT 0,
  max_retries INT NOT NULL DEFAULT 1,

  last_run_id BIGINT NULL,
  last_error TEXT,
  result_summary TEXT,
  reflection_json JSON,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  completed_at DATETIME NULL,

  UNIQUE KEY uk_agent_goal_step_order (goal_id, step_order),
  INDEX idx_agent_goal_step_goal (goal_id),
  INDEX idx_agent_goal_step_student_course (student_id, course_id),
  INDEX idx_agent_goal_step_status (status),
  INDEX idx_agent_goal_step_type (step_type),
  CONSTRAINT fk_agent_goal_steps_goal
    FOREIGN KEY (goal_id) REFERENCES agent_learning_goals(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6.3 每次步骤执行记录
CREATE TABLE IF NOT EXISTS agent_goal_runs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  goal_id BIGINT NOT NULL,
  step_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  conversation_id BIGINT NULL,

  run_uuid VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'running',

  tool_name VARCHAR(64) NULL,
  tool_args_json JSON,
  tool_result_json JSON,

  agent_steps_json JSON,
  retrieved_chunks_json JSON,

  output_message_id BIGINT NULL,
  qa_id BIGINT NULL,
  practice_session_id BIGINT NULL,
  generated_document_id BIGINT NULL,

  error_message TEXT,
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE KEY uk_agent_goal_run_uuid (run_uuid),
  INDEX idx_agent_goal_run_goal (goal_id),
  INDEX idx_agent_goal_run_step (step_id),
  INDEX idx_agent_goal_run_status (status),
  INDEX idx_agent_goal_run_student_course (student_id, course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6.4 执行后复盘表
CREATE TABLE IF NOT EXISTS agent_goal_reflections (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  goal_id BIGINT NOT NULL,
  step_id BIGINT NULL,
  run_id BIGINT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,

  reflection_type VARCHAR(64) NOT NULL DEFAULT 'step_after_run',
  is_success TINYINT NOT NULL DEFAULT 0,
  quality_score DECIMAL(5,2) NULL,

  summary TEXT,
  issues_json JSON,
  next_action VARCHAR(64),
  suggested_step_patch_json JSON,
  suggested_new_steps_json JSON,

  raw_llm_json JSON,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_agent_goal_reflection_goal (goal_id),
  INDEX idx_agent_goal_reflection_step (step_id),
  INDEX idx_agent_goal_reflection_run (run_id),
  INDEX idx_agent_goal_reflection_type (reflection_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
