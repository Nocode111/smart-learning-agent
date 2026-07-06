-- 本地文件修改操作表（文档 Section 6.1）
CREATE TABLE IF NOT EXISTS agent_local_file_operations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  operation_uuid VARCHAR(64) NOT NULL UNIQUE,

  student_id BIGINT NOT NULL,
  course_id BIGINT NULL,
  conversation_id BIGINT NULL,
  task_id BIGINT NULL,
  user_message_id BIGINT NULL,
  assistant_message_id BIGINT NULL,

  status VARCHAR(32) NOT NULL DEFAULT 'preview_ready',
  -- preview_ready | canceled | writing | applied | failed | restored

  original_path TEXT NOT NULL,
  resolved_path TEXT NOT NULL,
  workspace_root TEXT NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  file_ext VARCHAR(32) NOT NULL,
  file_size BIGINT NOT NULL DEFAULT 0,
  encoding VARCHAR(64) NOT NULL DEFAULT 'utf-8',
  newline VARCHAR(16) NULL,

  instruction TEXT NOT NULL,
  summary TEXT NULL,

  original_sha256 VARCHAR(64) NOT NULL,
  proposed_sha256 VARCHAR(64) NULL,
  applied_sha256 VARCHAR(64) NULL,

  artifact_dir TEXT NOT NULL,
  original_snapshot_path TEXT NULL,
  proposed_content_path TEXT NULL,
  diff_path TEXT NULL,
  backup_path TEXT NULL,

  error_message TEXT NULL,
  canceled_reason VARCHAR(255) NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  confirmed_at DATETIME NULL,
  applied_at DATETIME NULL,
  canceled_at DATETIME NULL,
  restored_at DATETIME NULL,

  INDEX idx_lfo_student (student_id),
  INDEX idx_lfo_conversation (conversation_id),
  INDEX idx_lfo_task (task_id),
  INDEX idx_lfo_status (status),
  INDEX idx_lfo_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 本地文件操作审计事件表（文档 Section 6.2）
CREATE TABLE IF NOT EXISTS agent_local_file_operation_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  operation_id BIGINT NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  message TEXT NULL,
  metadata_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_lfoe_operation (operation_id),
  INDEX idx_lfoe_type (event_type),
  CONSTRAINT fk_lfoe_operation
    FOREIGN KEY (operation_id)
    REFERENCES agent_local_file_operations(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
