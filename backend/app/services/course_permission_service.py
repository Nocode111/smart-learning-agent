"""
课程权限服务 — 统一课程访问和管理权限校验。

文档参考：docs/学生自建课程接入现有课程主链路_详细技术实现文档.md Section 7
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.user import User


class CoursePermissionService:
    """课程权限校验服务。

    核心规则：
    - admin 可查看/管理全部课程。
    - 教师课程(teacher)：公开课所有学生可见；owner/teacher 可管理。
    - 学生课程(student)：仅 owner 可查看/管理。
    """

    def can_view_course(self, user: User, course: Course) -> bool:
        """判断用户是否可以查看课程"""
        if user.role == "admin":
            return True
        if course.status != "active":
            return False
        if course.course_type == "teacher":
            return (
                course.visibility == "public"
                or course.owner_id == user.id
                or course.teacher_id == user.id
            )
        if course.course_type == "student":
            return course.owner_id == user.id
        return False

    def can_manage_course(self, user: User, course: Course) -> bool:
        """判断用户是否可以管理课程（编辑、删除、修改知识点/资源）"""
        if user.role == "admin":
            return True
        if course.course_type == "teacher":
            return user.role == "teacher" and (
                course.owner_id == user.id or course.teacher_id == user.id
            )
        if course.course_type == "student":
            return user.role == "student" and course.owner_id == user.id
        return False

    def require_view_course(self, db: Session, user: User, course_id: int) -> Course:
        """校验用户可查看课程，否则抛出 HTTPException"""
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course or not self.can_view_course(user, course):
            raise HTTPException(status_code=404, detail="课程不存在或无权访问")
        return course

    def require_manage_course(self, db: Session, user: User, course_id: int) -> Course:
        """校验用户可管理课程，否则抛出 HTTPException"""
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course or not self.can_manage_course(user, course):
            raise HTTPException(status_code=403, detail="无权管理该课程")
        return course


course_permission_service = CoursePermissionService()
