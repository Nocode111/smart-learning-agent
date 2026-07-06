-- 学生自建课程接入现有课程主链路：数据库迁移脚本
-- 文档：docs/学生自建课程接入现有课程主链路_详细技术实现文档.md Section 4

-- ================================================================
-- 4.1 courses 表字段改造
-- ================================================================
ALTER TABLE courses
  ADD COLUMN course_type VARCHAR(32) NOT NULL DEFAULT 'teacher' COMMENT 'teacher/student',
  ADD COLUMN owner_id BIGINT NULL COMMENT '课程创建者，教师课程为教师ID，学生课程为学生ID',
  ADD COLUMN visibility VARCHAR(32) NOT NULL DEFAULT 'public' COMMENT 'public/private',
  ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'manual' COMMENT 'manual/ai/import',
  ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'active/archived/deleted',
  ADD INDEX idx_courses_type_owner (course_type, owner_id),
  ADD INDEX idx_courses_visibility (visibility),
  ADD INDEX idx_courses_status (status);

-- 数据迁移：将历史课程标记为 teacher/public/active
UPDATE courses
SET
  course_type = 'teacher',
  owner_id = teacher_id,
  visibility = 'public',
  source = 'manual',
  status = 'active'
WHERE course_type IS NULL OR course_type = '';

-- ================================================================
-- 4.2 learning_resources 表增强
-- ================================================================
ALTER TABLE learning_resources
  ADD COLUMN owner_id BIGINT NULL COMMENT '资源创建者',
  ADD COLUMN file_name VARCHAR(255) NULL COMMENT '原始文件名',
  ADD COLUMN file_path VARCHAR(512) NULL COMMENT '后端保存路径',
  ADD COLUMN file_size BIGINT NULL COMMENT '文件大小，字节',
  ADD COLUMN mime_type VARCHAR(128) NULL COMMENT '文件 MIME 类型',
  ADD COLUMN index_status VARCHAR(32) NOT NULL DEFAULT 'none' COMMENT 'none/pending/indexed/failed',
  ADD COLUMN index_error TEXT NULL,
  ADD INDEX idx_resource_owner_id (owner_id),
  ADD INDEX idx_resource_index_status (index_status);

-- 兼容迁移：将 indexed 字段同步到 index_status
UPDATE learning_resources
SET index_status = CASE WHEN indexed = 1 THEN 'indexed' ELSE 'none' END
WHERE index_status IS NULL OR index_status = '';

-- ================================================================
-- 4.3 knowledge_points 表可选增强
-- ================================================================
ALTER TABLE knowledge_points
  ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'manual' COMMENT 'manual/ai/import',
  ADD INDEX idx_knowledge_points_source (source);
