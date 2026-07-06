-- 鏅烘収瀛︿範杈呭姪绯荤粺 鏁版嵁搴撳垵濮嬪寲鑴氭湰

CREATE DATABASE IF NOT EXISTS smart_learning DEFAULT CHARSET=utf8mb4;
USE smart_learning;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  name VARCHAR(64) NOT NULL,
  role VARCHAR(32) NOT NULL COMMENT 'student/teacher/admin',
  grade VARCHAR(32),
  major VARCHAR(64),
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS courses (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL,
  description TEXT,
  teacher_id BIGINT,
  course_type VARCHAR(32) NOT NULL DEFAULT 'teacher' COMMENT 'teacher/student',
  owner_id BIGINT NULL COMMENT '课程创建者',
  visibility VARCHAR(32) NOT NULL DEFAULT 'public' COMMENT 'public/private',
  source VARCHAR(32) NOT NULL DEFAULT 'manual' COMMENT 'manual/ai/import',
  status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'active/archived/deleted',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_courses_type_owner (course_type, owner_id),
  INDEX idx_courses_visibility (visibility),
  INDEX idx_courses_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 鐭ヨ瘑鐐硅〃
CREATE TABLE IF NOT EXISTS knowledge_points (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  course_id BIGINT NOT NULL,
  parent_id BIGINT,
  name VARCHAR(128) NOT NULL,
  description TEXT,
  difficulty INT NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  source VARCHAR(32) NOT NULL DEFAULT 'manual' COMMENT 'manual/ai/import',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_course_id (course_id),
  INDEX idx_parent_id (parent_id),
  INDEX idx_knowledge_points_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS learning_resources (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  course_id BIGINT NOT NULL,
  knowledge_point_id BIGINT,
  title VARCHAR(255) NOT NULL,
  resource_type VARCHAR(32) NOT NULL COMMENT 'text/pdf/video/link',
  content LONGTEXT,
  file_url VARCHAR(512),
  owner_id BIGINT NULL COMMENT '资源创建者',
  file_name VARCHAR(255) NULL COMMENT '原始文件名',
  file_path VARCHAR(512) NULL COMMENT '后端保存路径',
  file_size BIGINT NULL COMMENT '文件大小，字节',
  mime_type VARCHAR(128) NULL COMMENT '文件 MIME 类型',
  indexed TINYINT NOT NULL DEFAULT 0,
  index_status VARCHAR(32) NOT NULL DEFAULT 'none' COMMENT 'none/pending/indexed/failed',
  index_error TEXT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_resource_course_id (course_id),
  INDEX idx_resource_knowledge_point_id (knowledge_point_id),
  INDEX idx_resource_owner_id (owner_id),
  INDEX idx_resource_index_status (index_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS questions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  course_id BIGINT NOT NULL,
  knowledge_point_id BIGINT NOT NULL,
  question_type VARCHAR(32) NOT NULL COMMENT 'single/multiple/judge/short',
  stem TEXT NOT NULL,
  options_json JSON,
  answer TEXT NOT NULL,
  explanation TEXT,
  difficulty INT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_question_course_id (course_id),
  INDEX idx_question_knowledge_point_id (knowledge_point_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS question_attempts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  question_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  knowledge_point_id BIGINT NOT NULL,
  submitted_answer TEXT,
  is_correct TINYINT NOT NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_attempt_student_id (student_id),
  INDEX idx_attempt_question_id (question_id),
  INDEX idx_attempt_knowledge_point_id (knowledge_point_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS learning_behaviors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  course_id BIGINT,
  knowledge_point_id BIGINT,
  behavior_type VARCHAR(64) NOT NULL COMMENT 'ask_question/qa_feedback/answer_question/view_resource/complete_task/generate_exercise',
  content TEXT,
  result VARCHAR(64),
  duration_seconds INT,
  source VARCHAR(64),
  created_at DATETIME NOT NULL,
  INDEX idx_behavior_student_id (student_id),
  INDEX idx_behavior_course_point (course_id, knowledge_point_id),
  INDEX idx_behavior_type (behavior_type),
  INDEX idx_behavior_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS qa_records (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  question TEXT NOT NULL,
  answer LONGTEXT NOT NULL,
  related_knowledge_points JSON,
  retrieved_chunks JSON,
  resolved TINYINT,
  feedback_comment TEXT,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_qa_student_id (student_id),
  INDEX idx_qa_course_id (course_id),
  INDEX idx_qa_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS student_profiles (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  overall_level VARCHAR(64),
  weak_points_json JSON,
  preference_json JSON,
  active_summary_json JSON,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uk_student_course (student_id, course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS student_knowledge_mastery (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  knowledge_point_id BIGINT NOT NULL,
  mastery_score DECIMAL(5,2) NOT NULL DEFAULT 0,
  correct_count INT NOT NULL DEFAULT 0,
  wrong_count INT NOT NULL DEFAULT 0,
  ask_count INT NOT NULL DEFAULT 0,
  unresolved_count INT NOT NULL DEFAULT 0,
  resource_view_count INT NOT NULL DEFAULT 0,
  completed_task_count INT NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uk_student_point (student_id, knowledge_point_id),
  INDEX idx_mastery_student_course (student_id, course_id),
  INDEX idx_mastery_score (mastery_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recommendation_plans (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  title VARCHAR(255) NOT NULL,
  reason TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_plan_student_id (student_id),
  INDEX idx_plan_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recommendation_tasks (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  plan_id BIGINT NOT NULL,
  task_type VARCHAR(32) NOT NULL COMMENT 'resource/practice/qa/review',
  title VARCHAR(255) NOT NULL,
  target_id BIGINT,
  estimated_minutes INT,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  completed_at DATETIME,
  created_at DATETIME NOT NULL,
  INDEX idx_task_plan_id (plan_id),
  INDEX idx_task_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS generated_exercise_documents (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  knowledge_point_id BIGINT,
  title VARCHAR(255) NOT NULL,
  prompt TEXT NOT NULL,
  question_count INT NOT NULL,
  difficulty VARCHAR(32),
  file_name VARCHAR(255) NOT NULL,
  file_path VARCHAR(512) NOT NULL,
  preview_content LONGTEXT,
  agent_steps_json JSON,
  status VARCHAR(32) NOT NULL DEFAULT 'completed',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_user_id (user_id),
  INDEX idx_course_id (course_id),
  INDEX idx_knowledge_point_id (knowledge_point_id),
  INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Agent 会话表：保存一段 Agent 会话的整体状态
CREATE TABLE IF NOT EXISTS agent_conversations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  title VARCHAR(255),
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  last_topic VARCHAR(255),
  last_knowledge_point_ids JSON,
  pending_action_json JSON,
  context_summary_json JSON,
  message_count INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_agent_conv_student_course (student_id, course_id),
  INDEX idx_agent_conv_status (status),
  INDEX idx_agent_conv_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Agent 消息表：保存每一轮用户消息和 AI 消息
CREATE TABLE IF NOT EXISTS agent_messages (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  role VARCHAR(32) NOT NULL COMMENT 'user/assistant/system',
  message_type VARCHAR(32) NOT NULL DEFAULT 'text' COMMENT 'text/answer/document/clarification/error',
  content LONGTEXT,
  intent VARCHAR(64),
  qa_id BIGINT,
  document_id BIGINT,
  related_knowledge_point_ids JSON,
  agent_steps_json JSON,
  retrieved_chunks_json JSON,
  metadata_json JSON,
  created_at DATETIME NOT NULL,
  INDEX idx_agent_msg_conversation_id (conversation_id),
  INDEX idx_agent_msg_student_course (student_id, course_id),
  INDEX idx_agent_msg_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Agent 练习 Session 表：保存一次对话式练习的整体状态
CREATE TABLE IF NOT EXISTS agent_practice_sessions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  topic VARCHAR(255),
  knowledge_point_ids JSON,
  source_message_id BIGINT,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  delivery_mode VARCHAR(32) NOT NULL DEFAULT 'inline',
  grading_mode VARCHAR(32) NOT NULL DEFAULT 'interactive',
  question_count INT NOT NULL DEFAULT 0,
  answered_count INT NOT NULL DEFAULT 0,
  correct_count INT NOT NULL DEFAULT 0,
  current_question_no INT,
  include_answer_on_display TINYINT NOT NULL DEFAULT 0,
  include_explanation_on_display TINYINT NOT NULL DEFAULT 0,
  metadata_json JSON,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  completed_at DATETIME,
  INDEX idx_agent_practice_session_conversation (conversation_id),
  INDEX idx_agent_practice_session_student_course (student_id, course_id),
  INDEX idx_agent_practice_session_status (status),
  INDEX idx_agent_practice_session_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Agent 练习题目表：保存一次练习中的每一道题
CREATE TABLE IF NOT EXISTS agent_practice_questions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  session_id BIGINT NOT NULL,
  conversation_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  knowledge_point_id BIGINT,
  question_no INT NOT NULL,
  question_type VARCHAR(32) NOT NULL DEFAULT 'single_choice',
  stem TEXT NOT NULL,
  options_json JSON,
  correct_answer TEXT NOT NULL,
  explanation TEXT,
  difficulty VARCHAR(32) NOT NULL DEFAULT 'adaptive',
  source VARCHAR(32) NOT NULL DEFAULT 'llm',
  status VARCHAR(32) NOT NULL DEFAULT 'unanswered',
  raw_llm_json JSON,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uk_practice_question_session_no (session_id, question_no),
  INDEX idx_practice_question_session (session_id),
  INDEX idx_practice_question_conversation (conversation_id),
  INDEX idx_practice_question_kp (knowledge_point_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Agent 练习作答表：保存学生对练习题的回答记录
CREATE TABLE IF NOT EXISTS agent_practice_attempts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  session_id BIGINT NOT NULL,
  question_id BIGINT NOT NULL,
  conversation_id BIGINT NOT NULL,
  student_id BIGINT NOT NULL,
  course_id BIGINT NOT NULL,
  question_no INT NOT NULL,
  submitted_answer TEXT NOT NULL,
  normalized_answer TEXT,
  is_correct TINYINT NOT NULL DEFAULT 0,
  grading_method VARCHAR(32) NOT NULL DEFAULT 'rule',
  feedback_text TEXT,
  llm_grading_json JSON,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_practice_attempt_session (session_id),
  INDEX idx_practice_attempt_question (question_id),
  INDEX idx_practice_attempt_student_course (student_id, course_id),
  INDEX idx_practice_attempt_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Agent 对话附件表：用户在智能答疑会话中上传的文件
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

-- Agent 附件文本切片表：保存附件文本切片，用于调试和重建索引
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

-- Agent 消息附件关系表：记录某条消息关联了哪些附件
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

-- ============================================================
-- 二期：附件删除与提问取消（文档 Section 5）
-- ============================================================

-- 提问任务表
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

-- ============================================================
-- Agent 长期记忆基础表
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
