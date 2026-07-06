"""
AI 课程知识点大纲生成服务。

文档参考：docs/学生自建课程接入现有课程主链路_详细技术实现文档.md Section 9
"""

import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.services.qwen_client import qwen_client


class CourseOutlineService:
    """AI 自动生成课程知识点大纲"""

    SYSTEM_PROMPT = (
        "你是一个课程知识点大纲生成器。\n"
        "请根据课程名称、课程描述和学习目标，生成适合学生自学的知识点大纲。\n"
        "只能输出 JSON，不要输出 Markdown 或解释。\n"
        "JSON 格式：\n"
        '{\n'
        '  "knowledge_points": [\n'
        '    {\n'
        '      "name": "知识点名称",\n'
        '      "description": "一句话说明",\n'
        '      "difficulty": 1,\n'
        '      "sort_order": 1\n'
        '    }\n'
        '  ]\n'
        '}\n'
        "要求：\n"
        "1. 生成 8 到 15 个知识点。\n"
        "2. 名称简洁。\n"
        "3. difficulty 为 1 到 5。\n"
        "4. sort_order 从 1 开始。"
    )

    def generate_outline(
        self,
        db: Session,
        course_id: int,
        learning_goal: str | None = None,
        overwrite_existing: bool = False,
    ) -> list[KnowledgePoint]:
        """
        为指定课程生成知识点大纲。

        参数：
        - course_id: 课程 ID
        - learning_goal: 学习目标（可选）
        - overwrite_existing: 是否覆盖已有知识点（文档 Section 9.5）
        """
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise ValueError("课程不存在")

        # 构建用户提示
        user_prompt = f"课程名称：{course.name}\n课程描述：{course.description or '无'}\n学习目标：{learning_goal or '无'}"

        # 调用千问生成大纲
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response_text = qwen_client.chat(messages, temperature=0.3)
        except Exception as e:
            raise RuntimeError(f"AI 大纲生成失败：{type(e).__name__}")

        # JSON 解析与兜底（文档 Section 9.3）
        data = self._parse_json_response(response_text)
        if not data:
            raise RuntimeError("AI 返回的内容无法解析为 JSON，请重试")

        knowledge_points_data = data.get("knowledge_points", [])
        if not isinstance(knowledge_points_data, list) or not knowledge_points_data:
            raise RuntimeError("AI 未生成有效的知识点列表")

        # 限制数量（文档 Section 9.3）
        if len(knowledge_points_data) > 20:
            knowledge_points_data = knowledge_points_data[:20]

        # 名称去重
        seen_names = set()
        unique_points = []
        for item in knowledge_points_data:
            name = (item.get("name") or "").strip()
            if name and name not in seen_names:
                seen_names.add(name)
                unique_points.append(item)

        if not unique_points:
            raise RuntimeError("AI 生成的知识点全部无效")

        # 覆盖模式：先删除已有知识点
        if overwrite_existing:
            db.query(KnowledgePoint).filter(
                KnowledgePoint.course_id == course_id,
                KnowledgePoint.source == "ai",
            ).delete()
            db.flush()

        # 写入知识点到数据库（文档 Section 9.4）
        created_points = []
        for index, item in enumerate(unique_points):
            point = KnowledgePoint(
                course_id=course_id,
                name=item["name"].strip(),
                description=item.get("description"),
                difficulty=max(1, min(5, int(item.get("difficulty", 1)))),
                sort_order=item.get("sort_order", index + 1),
                source="ai",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(point)
            created_points.append(point)

        db.commit()
        for p in created_points:
            db.refresh(p)

        return created_points

    def _parse_json_response(self, text: str) -> dict | None:
        """JSON 解析与兜底（文档 Section 9.3）"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 兜底：截取第一个 { 到最后一个 }
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None


course_outline_service = CourseOutlineService()
