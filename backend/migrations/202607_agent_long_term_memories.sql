-- ============================================================
-- Agent 长期记忆基础表 — 第三阶段
-- 执行方式：mysql -u root -p smart_learning < backend/migrations/202607_agent_long_term_memories.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_memories (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  student_id BIGINT NOT NULL,
  course_id BIGINT NULL,

  memory_type VARCHAR(32) NOT NULL,
  memory_key VARCHAR(128) NOT NULL,
  memory_value_json JSON,
  memory_text TEXT NOT NULL,

  confidence DOUBLE NOT NULL DEFAULT 0.8,
  importance DOUBLE NOT NULL DEFAULT 0.5,
  status VARCHAR(32) NOT NULL DEFAULT 'active',

  source_type VARCHAR(64),
  source_id BIGINT,
  last_used_at DATETIME NULL,
  expires_at DATETIME NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  INDEX idx_agent_memory_student_course (student_id, course_id),
  INDEX idx_agent_memory_type (memory_type),
  INDEX idx_agent_memory_key (memory_key),
  INDEX idx_agent_memory_status (status),
  INDEX idx_agent_memory_importance (importance),
  INDEX idx_agent_memory_last_used (last_used_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_memory_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  memory_id BIGINT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NULL,

  event_type VARCHAR(32) NOT NULL,
  source_message_id BIGINT NULL,
  source_task_id BIGINT NULL,
  old_value_json JSON,
  new_value_json JSON,
  reason TEXT,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_agent_memory_event_memory (memory_id),
  INDEX idx_agent_memory_event_student_course (student_id, course_id),
  INDEX idx_agent_memory_event_type (event_type),
  INDEX idx_agent_memory_event_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_memory_summaries (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  student_id BIGINT NOT NULL,
  course_id BIGINT NULL,
  conversation_id BIGINT NULL,

  summary_type VARCHAR(32) NOT NULL DEFAULT 'conversation',
  summary_text TEXT NOT NULL,
  covered_message_ids_json JSON,
  related_knowledge_point_ids_json JSON,
  status VARCHAR(32) NOT NULL DEFAULT 'active',

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  INDEX idx_agent_memory_summary_student_course (student_id, course_id),
  INDEX idx_agent_memory_summary_conversation (conversation_id),
  INDEX idx_agent_memory_summary_type (summary_type),
  INDEX idx_agent_memory_summary_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_memory_feedback (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  memory_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,

  action VARCHAR(32) NOT NULL,
  feedback_text TEXT,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_agent_memory_feedback_memory (memory_id),
  INDEX idx_agent_memory_feedback_student (student_id),
  INDEX idx_agent_memory_feedback_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
