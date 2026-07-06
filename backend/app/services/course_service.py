from datetime import datetime
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.user import User


class CourseService:
    # ================================================================
    # 查询
    # ================================================================

    def get_available_courses(
        self,
        db: Session,
        user: User,
        scope: str = "available",
        course_type: str | None = None,
    ) -> list[Course]:
        """
        按角色和 scope 返回课程列表。

        scope:
          - available: 学生默认 → 教师公开课程 + 自己的学生课程
          - teacher: 仅教师课程
          - mine: 教师默认 → 自己创建的教师课程；学生 → 自己的学生课程
          - all: admin → 全部 active 课程

        course_type 可选过滤：teacher / student
        """
        query = db.query(Course).filter(Course.status == "active")

        if user.role == "admin":
            # admin 可看所有 active 课程，course_type 可选过滤
            if course_type:
                query = query.filter(Course.course_type == course_type)
            return query.order_by(Course.created_at.desc()).all()

        if user.role == "teacher":
            if scope == "mine" or scope == "teacher":
                # 教师只能看到自己创建的教师课程
                query = query.filter(
                    Course.course_type == "teacher",
                    Course.owner_id == user.id,
                )
            elif scope == "available":
                query = query.filter(Course.course_type == "teacher")
            else:
                query = query.filter(
                    Course.course_type == "teacher",
                    Course.owner_id == user.id,
                )
            if course_type:
                query = query.filter(Course.course_type == course_type)
            return query.order_by(Course.created_at.desc()).all()

        # student
        if scope == "mine":
            # 学生自己的课程
            query = query.filter(
                Course.course_type == "student",
                Course.owner_id == user.id,
            )
        elif scope == "teacher":
            query = query.filter(Course.course_type == "teacher", Course.visibility == "public")
        else:
            # available: 教师公开课程 + 自己的学生课程
            query = query.filter(
                (
                    (Course.course_type == "teacher") & (Course.visibility == "public")
                ) | (
                    (Course.course_type == "student") & (Course.owner_id == user.id)
                )
            )

        if course_type:
            query = query.filter(Course.course_type == course_type)
        return query.order_by(Course.created_at.desc()).all()

    def get_course(self, db: Session, course_id: int) -> Course | None:
        return db.query(Course).filter(Course.id == course_id).first()

    # ================================================================
    # 创建
    # ================================================================

    def create_teacher_course(
        self,
        db: Session,
        user: User,
        name: str,
        description: str | None = None,
    ) -> Course:
        """教师创建课程（文档 Section 8.2）"""
        course = Course(
            name=name,
            description=description,
            teacher_id=user.id,
            course_type="teacher",
            owner_id=user.id,
            visibility="public",
            source="manual",
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        return course

    def create_student_course(
        self,
        db: Session,
        user: User,
        name: str,
        description: str | None = None,
        learning_goal: str | None = None,
        auto_generate_outline: bool = True,
    ) -> Course:
        """学生创建自建课程（文档 Section 8.3）"""
        course = Course(
            name=name,
            description=description,
            teacher_id=None,
            course_type="student",
            owner_id=user.id,
            visibility="private",
            source="manual",
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(course)
        db.commit()
        db.refresh(course)

        # 自动生成知识点大纲
        if auto_generate_outline:
            try:
                from app.services.course_outline_service import course_outline_service
                course_outline_service.generate_outline(
                    db=db,
                    course_id=course.id,
                    learning_goal=learning_goal,
                )
            except Exception:
                # AI 生成失败不阻塞课程创建（文档 Section 9.3）
                pass

        return course

    # ================================================================
    # 更新
    # ================================================================

    def update_course(
        self,
        db: Session,
        course_id: int,
        name: str | None = None,
        description: str | None = None,
    ) -> Course:
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise ValueError("课程不存在")
        if name is not None:
            course.name = name
        if description is not None:
            course.description = description
        course.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(course)
        return course

    # ================================================================
    # 软删除（文档 Section 8.5）
    # ================================================================

    def soft_delete_course(self, db: Session, course_id: int) -> Course:
        """软删除课程，不物理删除（保留历史数据）"""
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise ValueError("课程不存在")
        course.status = "deleted"
        course.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(course)
        return course


course_service = CourseService()
