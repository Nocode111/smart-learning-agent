-- 对话式练习 Session 增量迁移脚本
-- 在已有数据库上执行，不会破坏现有数据

-- 表一：agent_practice_sessions
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

-- 表二：agent_practice_questions
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

-- 表三：agent_practice_attempts
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
