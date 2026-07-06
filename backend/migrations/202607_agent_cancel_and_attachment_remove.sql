-- ============================================================
-- 智能答疑二期完整版：附件可撤销与提问可取消
-- 文档：docs/附件删除与提问取消二期完整版_详细技术实现文档.md Section 5
-- ============================================================

-- 5.1 扩展附件表
ALTER TABLE agent_attachments
  ADD COLUMN deleted_at DATETIME NULL,
  ADD COLUMN deleted_by BIGINT NULL,
  ADD COLUMN delete_reason VARCHAR(255) NULL,
  ADD COLUMN delete_error TEXT NULL,
  ADD COLUMN physical_file_deleted TINYINT NOT NULL DEFAULT 0,
  ADD COLUMN delete_message_id BIGINT NULL,
  ADD INDEX idx_agent_attachment_deleted_at (deleted_at),
  ADD INDEX idx_agent_attachment_deleted_by (deleted_by);

-- 5.2 扩展附件 chunk 表
ALTER TABLE agent_attachment_chunks
  ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'active',
  ADD COLUMN deleted_at DATETIME NULL,
  ADD INDEX idx_agent_attachment_chunk_status (status),
  ADD INDEX idx_agent_attachment_chunk_deleted_at (deleted_at);

-- 5.3 扩展 Agent 消息表
ALTER TABLE agent_messages
  ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'completed',
  ADD COLUMN task_id BIGINT NULL,
  ADD COLUMN client_request_id VARCHAR(64) NULL,
  ADD COLUMN canceled_at DATETIME NULL,
  ADD COLUMN error_message TEXT NULL,
  ADD INDEX idx_agent_msg_status (status),
  ADD INDEX idx_agent_msg_task_id (task_id),
  ADD INDEX idx_agent_msg_client_request_id (client_request_id);

-- 5.4 新增提问任务表
CREATE TABLE IF NOT EXISTS agent_chat_tasks (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  task_uuid VARCHAR(64) NOT NULL,
  client_request_id VARCHAR(64) NOT NULL,

  conversation_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,

  user_message_id BIGINT NOT NULL,
  assistant_message_id BIGINT NULL,

  request_message LONGTEXT NOT NULL,
  request_payload_json JSON,

  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  stage VARCHAR(64) NULL,
  progress_text VARCHAR(255) NULL,

  cancel_requested TINYINT NOT NULL DEFAULT 0,
  cancel_reason VARCHAR(255) NULL,
  cancel_requested_at DATETIME NULL,
  canceled_at DATETIME NULL,

  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  failed_at DATETIME NULL,
  error_message TEXT,

  result_json JSON,
  debug_json JSON,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uk_agent_chat_task_uuid (task_uuid),
  UNIQUE KEY uk_agent_chat_client_request (student_id, client_request_id),
  INDEX idx_agent_chat_task_conversation (conversation_id),
  INDEX idx_agent_chat_task_student_course (student_id, course_id),
  INDEX idx_agent_chat_task_status (status),
  INDEX idx_agent_chat_task_created_at (created_at),
  INDEX idx_agent_chat_task_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
