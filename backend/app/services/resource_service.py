import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.resource import LearningResource
from app.models.course import Course
from app.services.rag_service import rag_service

# 上传文件保存目录
UPLOAD_DIR = Path("uploads/resources")


class ResourceService:
    # ================================================================
    # 查询
    # ================================================================

    def get_resources(self, db: Session, course_id: int) -> list[LearningResource]:
        return db.query(LearningResource).filter(LearningResource.course_id == course_id).all()

    def get_resource(self, db: Session, resource_id: int) -> LearningResource | None:
        return db.query(LearningResource).filter(LearningResource.id == resource_id).first()

    # ================================================================
    # 创建
    # ================================================================

    def create_resource(
        self, db: Session,
        course_id: int, title: str, resource_type: str = "text",
        knowledge_point_id: int | None = None,
        content: str | None = None, file_url: str | None = None,
        owner_id: int | None = None,
    ) -> LearningResource:
        resource = LearningResource(
            course_id=course_id,
            knowledge_point_id=knowledge_point_id,
            title=title,
            resource_type=resource_type,
            content=content,
            file_url=file_url,
            owner_id=owner_id,
            indexed=0,
            index_status="none",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(resource)
        db.commit()
        db.refresh(resource)
        return resource

    def create_uploaded_resource(
        self,
        db: Session,
        course_id: int,
        title: str,
        owner_id: int,
        resource_type: str,
        file_name: str,
        file_path: str,
        file_size: int,
        mime_type: str,
        content: str | None = None,
        knowledge_point_id: int | None = None,
        auto_index: bool = True,
    ) -> LearningResource:
        """创建上传文件资源（文档 Section 10.4）"""
        resource = LearningResource(
            course_id=course_id,
            knowledge_point_id=knowledge_point_id,
            title=title,
            resource_type=resource_type,
            content=content,
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            owner_id=owner_id,
            indexed=0,
            index_status="none",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(resource)
        db.commit()
        db.refresh(resource)

        # 自动索引
        if auto_index and content:
            try:
                self._do_index(db, resource)
            except Exception:
                # 索引失败不阻塞资源创建
                pass

        return resource

    # ================================================================
    # 索引
    # ================================================================

    def index_resource(self, db: Session, resource_id: int) -> LearningResource:
        """索引资源（文档 Section 11.4）"""
        resource = db.query(LearningResource).filter(LearningResource.id == resource_id).first()
        if not resource:
            raise ValueError("资源不存在")
        if not resource.content:
            raise ValueError("资源内容为空，无法索引")

        return self._do_index(db, resource)

    def _do_index(self, db: Session, resource: LearningResource) -> LearningResource:
        """执行索引，更新状态"""
        # 设置 pending
        resource.index_status = "pending"
        resource.updated_at = datetime.utcnow()
        db.commit()

        # 获取课程信息用于 metadata
        course = db.query(Course).filter(Course.id == resource.course_id).first()

        try:
            # 先删除旧 chunk（文档 Section 11.3）
            rag_service.delete_resource_vectors(resource.id)

            # 执行索引
            rag_service.index_resource(
                resource_id=resource.id,
                course_id=resource.course_id,
                knowledge_point_id=resource.knowledge_point_id,
                title=resource.title,
                content=resource.content,
                course_type=course.course_type if course else "teacher",
                owner_id=resource.owner_id,
            )

            resource.indexed = 1
            resource.index_status = "indexed"
            resource.index_error = None
        except Exception as e:
            resource.indexed = 0
            resource.index_status = "failed"
            resource.index_error = str(e)

        resource.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(resource)
        return resource

    def reindex_resource(self, db: Session, resource_id: int) -> LearningResource:
        """重建索引"""
        return self.index_resource(db, resource_id)

    # ================================================================
    # 删除
    # ================================================================

    def delete_resource(self, db: Session, resource_id: int):
        """删除资源，同时清理 Chroma 向量"""
        resource = db.query(LearningResource).filter(LearningResource.id == resource_id).first()
        if not resource:
            raise ValueError("资源不存在")

        # 清理向量（文档 Section 11.3）
        try:
            rag_service.delete_resource_vectors(resource_id)
        except Exception:
            pass  # 向量清理失败不阻塞资源删除

        # 删除物理文件
        if resource.file_path and os.path.isfile(resource.file_path):
            try:
                os.remove(resource.file_path)
            except Exception:
                pass

        db.delete(resource)
        db.commit()

    def delete_resource_vectors(self, resource_id: int):
        """仅清理向量索引"""
        rag_service.delete_resource_vectors(resource_id)

    # ================================================================
    # 文件保存
    # ================================================================

    def save_upload_file(
        self,
        file_content: bytes,
        original_filename: str,
        course_id: int,
    ) -> tuple[str, str, int]:
        """
        保存上传文件，返回 (file_path, safe_name, file_size)。

        路径：uploads/resources/{course_id}/{uuid}/原文件名
        文档 Section 10.3
        """
        # 安全文件名：只保留字母、数字、点、下划线、连字符
        safe_name = "".join(c for c in original_filename if c.isalnum() or c in "._-")
        if not safe_name:
            safe_name = "uploaded_file"

        # 子目录使用 uuid 避免文件名冲突
        sub_dir = UPLOAD_DIR / str(course_id) / uuid.uuid4().hex[:12]
        sub_dir.mkdir(parents=True, exist_ok=True)

        file_path = sub_dir / safe_name

        # 写入文件
        file_path.write_bytes(file_content)

        return str(file_path), safe_name, len(file_content)


resource_service = ResourceService()
