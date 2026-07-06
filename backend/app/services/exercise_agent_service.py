import os
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.generated_exercise_document import GeneratedExerciseDocument
from app.prompts.exercise_prompt import build_exercise_prompt
from app.services.behavior_service import behavior_service
from app.services.profile_service import profile_service
from app.services.qwen_client import qwen_client
from app.services.rag_service import rag_service


class ExerciseAgentService:
    def extract_question_count(self, prompt: str, default: int = 5) -> int:
        """从 prompt 中抽取题目数量，支持阿拉伯数字和中文数字"""
        match = re.search(r"(\d+)\s*[道个题]", prompt)
        if match:
            count = int(match.group(1))
            return max(1, min(count, 20))

        chinese_num_map = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        for word, value in chinese_num_map.items():
            if f"{word}道" in prompt or f"{word}个" in prompt:
                return value

        return default

    def resolve_knowledge_point(
        self, db: Session, course_id: int, prompt: str, knowledge_point_id: int | None
    ):
        """匹配知识点：优先使用传入的 ID，否则用名称关键词匹配"""
        if knowledge_point_id:
            point = db.query(KnowledgePoint).filter(
                KnowledgePoint.id == knowledge_point_id,
                KnowledgePoint.course_id == course_id,
            ).first()
            if point:
                return point

        points = db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id).all()
        for point in points:
            if point.name in prompt:
                return point
        return None

    def safe_filename(self, text: str) -> str:
        """安全清洗文件名"""
        return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")

    def save_markdown(self, course_name: str, point_name: str, markdown_content: str):
        """保存 Markdown 文件到 generated/exercises/ 目录"""
        output_dir = Path("generated/exercises")
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{self.safe_filename(course_name)}_{self.safe_filename(point_name)}_专项练习题_{timestamp}.md"
        file_path = output_dir / file_name

        file_path.write_text(markdown_content, encoding="utf-8")

        return file_name, str(file_path)

    def normalize_markdown(
        self,
        markdown_content: str,
        course_name: str,
        point_name: str,
        count: int,
        difficulty: str,
    ) -> str:
        """规范化 Markdown：如果模型没有生成信息头，则在前面补上"""
        if markdown_content.startswith("# ") and "## 生成信息" in markdown_content:
            return markdown_content

        header = f"""# {course_name}：{point_name}专项练习题

## 生成信息

- 课程：{course_name}
- 知识点：{point_name}
- 题目数量：{count}
- 难度：{difficulty}
- 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

"""
        return header + markdown_content

    def generate(
        self,
        db: Session,
        user_id: int,
        course_id: int,
        prompt: str,
        question_count=None,
        knowledge_point_id=None,
        difficulty="adaptive",
        include_answer: bool = True,
        include_explanation: bool = True,
    ):
        agent_steps = []

        # Step 1: 识别任务
        agent_steps.append({
            "title": "识别任务",
            "detail": "任务类型：生成练习题",
            "status": "done",
        })

        # Step 2: 抽取题目数量
        count = question_count or self.extract_question_count(prompt)
        agent_steps.append({
            "title": "抽取参数",
            "detail": f"题目数量：{count}",
            "status": "done",
        })

        # Step 3: 读取课程信息
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise ValueError("课程不存在")

        # Step 4: 匹配知识点
        point = self.resolve_knowledge_point(db, course_id, prompt, knowledge_point_id)
        if not point:
            raise ValueError("未识别到知识点，请明确说明要生成哪个知识点的练习题，例如：生成5道有关栈的练习题。")

        agent_steps.append({
            "title": "匹配知识点",
            "detail": f"知识点：{point.name}",
            "status": "done",
        })

        # Step 5: 读取学生画像
        profile = profile_service.get_profile_for_agent(db, user_id, course_id)
        agent_steps.append({
            "title": "读取学习画像",
            "detail": f"当前水平：{profile.get('overall_level', '未知')}",
            "status": "done",
        })

        # Step 6: 检索课程知识库
        try:
            chunks = rag_service.retrieve(point.name + " " + prompt, course_id)
            agent_steps.append({
                "title": "检索课程资料",
                "detail": f"检索到 {len(chunks)} 条相关资料",
                "status": "done",
            })
        except Exception as e:
            chunks = []
            agent_steps.append({
                "title": "检索课程资料",
                "detail": f"课程资料检索暂不可用，已改用课程名和知识点生成：{type(e).__name__}",
                "status": "skipped",
            })

        # Step 7: 构造 Prompt 并调用千问
        messages = build_exercise_prompt(
            course_name=course.name,
            knowledge_point_name=point.name,
            question_count=count,
            difficulty=difficulty,
            profile=profile,
            retrieved_chunks=chunks,
            include_answer=include_answer,
            include_explanation=include_explanation,
        )

        try:
            markdown_content = qwen_client.chat(messages)
        except Exception as e:
            raise ValueError(f"练习题生成失败：千问接口暂时没有返回，请检查网络/API Key，或稍后重试。错误类型：{type(e).__name__}")

        # Step 8: 规范化 Markdown
        markdown_content = self.normalize_markdown(
            markdown_content=markdown_content,
            course_name=course.name,
            point_name=point.name,
            count=count,
            difficulty=difficulty,
        )

        agent_steps.append({
            "title": "生成 Markdown",
            "detail": "已生成练习题、答案和解析",
            "status": "done",
        })

        # Step 9: 保存文件
        file_name, file_path = self.save_markdown(course.name, point.name, markdown_content)
        agent_steps.append({
            "title": "保存文件",
            "detail": f"文件名：{file_name}",
            "status": "done",
        })

        # Step 10: 保存数据库记录
        doc = GeneratedExerciseDocument(
            user_id=user_id,
            course_id=course_id,
            knowledge_point_id=point.id,
            title=f"{course.name}：{point.name}专项练习题",
            prompt=prompt,
            question_count=count,
            difficulty=difficulty,
            file_name=file_name,
            file_path=file_path,
            preview_content=markdown_content,
            agent_steps_json=agent_steps,
            status="completed",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(doc)

        # Step 11: 记录学习行为
        behavior_service.record(
            db=db,
            student_id=user_id,
            course_id=course_id,
            knowledge_point_id=point.id,
            behavior_type="generate_exercise",
            content=prompt,
            result="completed",
            source="exercise_agent",
        )

        db.commit()
        db.refresh(doc)

        return doc, agent_steps


exercise_agent_service = ExerciseAgentService()
