-- ============================================================
-- 智能答疑对话附件系统 — 数据库迁移
-- 文档：docs/智能答疑对话附件系统方案_详细技术实现文档.md Section 6
-- 执行方式：mysql -u root -p smart_learning < backend/migrations/202607_agent_attachments.sql
-- ============================================================

-- 附件主表
CREATE TABLE IF NOT EXISTS agent_attachments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  conversation_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,

  upload_message_id BIGINT NULL,

  title VARCHAR(255) NOT NULL,
  original_file_name VARCHAR(255) NOT NULL,
  stored_file_name VARCHAR(255) NOT NULL,
  file_ext VARCHAR(32) NOT NULL,
  file_path VARCHAR(512) NOT NULL,
  file_size BIGINT NOT NULL DEFAULT 0,
  mime_type VARCHAR(128),

  attachment_type VARCHAR(32) NOT NULL DEFAULT 'document',

  content LONGTEXT,
  content_hash VARCHAR(64),

  extract_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  extract_error TEXT,

  index_status VARCHAR(32) NOT NULL DEFAULT 'none',
  index_error TEXT,
  chunk_count INT NOT NULL DEFAULT 0,

  status VARCHAR(32) NOT NULL DEFAULT 'active',

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  INDEX idx_agent_attachment_conversation (conversation_id),
  INDEX idx_agent_attachment_student_course (student_id, course_id),
  INDEX idx_agent_attachment_course (course_id),
  INDEX idx_agent_attachment_status (status),
  INDEX idx_agent_attachment_index_status (index_status),
  INDEX idx_agent_attachment_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 附件文本切片表
CREATE TABLE IF NOT EXISTS agent_attachment_chunks (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  attachment_id BIGINT NOT NULL,
  conversation_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,

  chunk_index INT NOT NULL,
  vector_id VARCHAR(128) NOT NULL,
  content LONGTEXT NOT NULL,
  char_count INT NOT NULL DEFAULT 0,
  metadata_json JSON,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE KEY uk_agent_attachment_chunk (attachment_id, chunk_index),
  UNIQUE KEY uk_agent_attachment_vector (vector_id),
  INDEX idx_agent_attachment_chunk_attachment (attachment_id),
  INDEX idx_agent_attachment_chunk_conversation (conversation_id),
  INDEX idx_agent_attachment_chunk_student_course (student_id, course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 消息与附件关系表
CREATE TABLE IF NOT EXISTS agent_message_attachments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  message_id BIGINT NOT NULL,
  attachment_id BIGINT NOT NULL,
  relation_type VARCHAR(32) NOT NULL DEFAULT 'referenced',

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE KEY uk_agent_message_attachment (message_id, attachment_id, relation_type),
  INDEX idx_agent_msg_attach_message (message_id),
  INDEX idx_agent_msg_attach_attachment (attachment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
