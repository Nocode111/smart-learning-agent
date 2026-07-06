"""
对话式目标创建 Agent 服务（文档 Section 11）

职责：
1. 解析和规范化 tool_args
2. 匹配课程
3. 判断是否需要澄清
4. 读取学习画像
5. 读取课程知识点
6. 创建目标
7. 调用目标计划生成
8. 构造对话回复文本和目标卡片
"""

import logging
import re
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint

logger = logging.getLogger(__name__)


class AgentGoalChatCreationService:
    """对话式目标创建服务 — 编排 Agent 自动创建学习目标全流程"""

    # ── 主入口（文档 Section 11.3） ──────────────────────────────

    def create_from_chat(
        self,
        db: Session,
        student_id: int,
        current_course_id: int,
        user_message: str,
        tool_args: dict,
        conversation_id: int | None = None,
    ) -> dict:
        """
        从对话中创建学习目标并自动生成计划。

        返回结构：
        {
            "type": "learning_goal_created",
            "text": "...",
            "learning_goal": {...},
            "goal_plan": {...},
            "profile_summary": {...},
            "agent_steps": [...],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }
        """
        agent_steps = []

        # 1. 解析和规范化参数
        args = self.normalize_goal_args(user_message, tool_args)
        agent_steps.append({
            "title": "识别学习目标",
            "detail": self._build_goal_recognition_detail(args),
        })

        # 2. 匹配课程
        course, clarify = self.resolve_course(db, student_id, current_course_id, args.get("course_name"))
        if clarify:
            return clarify
        agent_steps.append({
            "title": "确认课程",
            "detail": f"已确认课程：{course.name}",
        })

        # 3. 读取学习画像和知识点
        from app.services.profile_service import profile_service

        profile = profile_service.get_profile_for_agent(db, student_id, course.id)
        knowledge_points = self._load_course_knowledge_points(db, course.id)
        diagnostic_required = self.should_add_diagnostic(profile, args.get("target_topics"))
        agent_steps.append({
            "title": "读取学习情况",
            "detail": self._build_profile_detail(profile, diagnostic_required),
        })

        # 4. 创建目标
        from app.services.agent_goal_service import agent_goal_service

        target_kp_ids = self._match_target_kp_ids(knowledge_points, args.get("target_topics") or [])

        try:
            goal = agent_goal_service.create_goal(
                db=db,
                student_id=student_id,
                course_id=course.id,
                title=self.build_goal_title(course, args),
                goal_text=self.build_goal_text(course, args, diagnostic_required),
                target_score=args.get("target_score"),
                target_knowledge_point_ids=target_kp_ids if target_kp_ids else None,
                due_date=self._parse_due_date(args),
            )
        except ValueError as exc:
            logger.warning("创建目标失败: %s", exc)
            return self._build_error_response(str(exc), agent_steps)

        # 写入 metadata
        self._write_goal_metadata(db, goal["id"], conversation_id, user_message, diagnostic_required)
        agent_steps.append({
            "title": "创建长期目标",
            "detail": f"已创建目标：{goal['title']}",
        })

        # 5. 生成学习计划
        from app.services.agent_goal_planner_service import agent_goal_planner_service

        try:
            # 构建诊断要求
            diagnostic_req = None
            if diagnostic_required:
                diagnostic_req = "当前学生画像不足，请将第一步安排为 5 道基础诊断测验，用于判断当前水平。"

            plan = agent_goal_planner_service.plan_goal(
                db=db,
                goal_id=goal["id"],
                student_id=student_id,
                course_id=course.id,
                diagnostic_requirement=diagnostic_req,
            )
            agent_steps.append({
                "title": "生成学习计划",
                "detail": f"已生成 {plan['step_count']} 个学习步骤",
            })
        except Exception as exc:
            logger.exception("生成计划失败 goal_id=%s", goal["id"])
            return self._build_goal_created_plan_failed_response(goal, str(exc), agent_steps)

        return self.build_success_response(goal, plan, profile, agent_steps, diagnostic_required)

    # ── 课程匹配（文档 Section 11.4） ────────────────────────────

    def resolve_course(
        self,
        db: Session,
        student_id: int,
        current_course_id: int,
        course_name: str | None,
    ) -> tuple:
        """
        匹配课程，返回 (course, None) 或 (None, clarification_response)。

        情况一：用户明确说了课程名 → 在用户可访问课程中匹配
        情况二：用户没有说课程名，但当前对话有课程 → 直接使用
        情况三：匹配到多个课程 → 返回澄清
        """
        from app.services.course_service import course_service
        from app.models.user import User

        user = db.query(User).filter(User.id == student_id).first()
        courses = course_service.get_available_courses(db, user, scope="available")

        if course_name:
            candidates = self._match_by_name(courses, course_name)
            if len(candidates) == 1:
                return candidates[0], None
            if len(candidates) > 1:
                return None, self._build_clarify_course(candidates)
            # 没匹配到
            return None, self._build_clarify_no_course(course_name)

        if current_course_id:
            course = db.query(type(courses[0])).filter(
                type(courses[0]).id == current_course_id
            ).first() if courses else None
            if not course:
                # fallback: iterate
                course = next((c for c in courses if c.id == current_course_id), None)
            if course:
                return course, None

        return None, self._build_clarify_need_course()

    @staticmethod
    def _match_by_name(courses: list, course_name: str) -> list:
        """按名称匹配课程：完全匹配 > 包含匹配 > 相似匹配"""
        name = course_name.strip()
        # 完全匹配
        exact = [c for c in courses if c.name == name]
        if exact:
            return exact
        # 包含匹配
        contains = [c for c in courses if name in c.name or c.name in name]
        if contains:
            return contains
        # 相似匹配（去掉"课程"后缀等）
        name_clean = name.replace("课程", "").replace("课", "")
        similar = [c for c in courses if name_clean in c.name or c.name in name_clean]
        return similar

    # ── 参数规范化（文档 Section 8 + 13） ────────────────────────

    def normalize_goal_args(self, user_message: str, tool_args: dict) -> dict:
        """规范化 tool_args，补充默认值"""
        args = dict(tool_args or {})

        if not args.get("goal_text"):
            args["goal_text"] = user_message

        if args.get("target_score") is None:
            # 尝试从消息提取
            extracted = self._extract_score_from_text(user_message)
            if extracted is not None:
                args["target_score"] = extracted
            else:
                # 默认值
                if any(k in user_message for k in ["及格", "过线"]):
                    args["target_score"] = 60
                else:
                    args["target_score"] = 80

        if args.get("need_diagnostic") is None:
            args["need_diagnostic"] = "auto"

        if args.get("auto_generate_plan") is None:
            args["auto_generate_plan"] = True

        if args.get("auto_advance_first_step") is None:
            args["auto_advance_first_step"] = False

        return args

    @staticmethod
    def _extract_score_from_text(text: str) -> int | None:
        """从文本中提取目标分数"""
        match = re.search(r'(\d+)\s*分', text)
        if match:
            score = int(match.group(1))
            if 0 <= score <= 100:
                return score
        return None

    @staticmethod
    def _parse_due_date(args: dict) -> date | None:
        """解析截止日期"""
        due_date_str = args.get("due_date")
        if due_date_str:
            try:
                return datetime.strptime(due_date_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

        duration_days = args.get("duration_days")
        if duration_days:
            try:
                return date.today() + timedelta(days=int(duration_days))
            except (ValueError, TypeError):
                pass

        return None

    # ── 标题生成（文档 Section 13.1） ────────────────────────────

    def build_goal_title(self, course, args: dict) -> str:
        """生成目标标题"""
        course_name = course.name
        target_score = args.get("target_score")
        exam_type = args.get("exam_type") or ""

        if target_score and exam_type:
            return f"{course_name}{exam_type}达到 {target_score} 分"
        elif target_score:
            return f"{course_name}达到 {target_score} 分学习目标"
        elif exam_type:
            return f"{course_name}{exam_type}学习目标"

        # fallback: 从 goal_text 取前 50 字符
        goal_text = args.get("goal_text") or ""
        short = goal_text[:50]
        return f"{course_name}：{short}"

    # ── goal_text 生成（文档 Section 13.2） ──────────────────────

    def build_goal_text(self, course, args: dict, diagnostic_required: bool) -> str:
        """生成结构化的 goal_text"""
        goal_text = args.get("goal_text") or ""
        target_score = args.get("target_score")
        exam_type = args.get("exam_type") or ""
        duration_days = args.get("duration_days")

        parts = [f"用户希望为{course.name}课程"]

        if exam_type:
            parts.append(f"针对{exam_type}")
        if target_score:
            parts.append(f"目标达到 {target_score} 分")
        if duration_days:
            parts.append(f"学习周期 {duration_days} 天")

        parts.append(f"制定学习计划。")

        if diagnostic_required:
            parts.append("系统判断：当前学习画像不足，计划第一步应安排基础诊断测验。")

        # 如果 goal_text 不太短，追加原始表达
        if goal_text and len(goal_text) > 10:
            parts.append(f"用户原始表达：{goal_text}")

        return "".join(parts)

    # ── 画像和知识点 ────────────────────────────────────────────

    @staticmethod
    def _load_course_knowledge_points(db: Session, course_id: int) -> list:
        """加载课程知识点"""
        return (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.course_id == course_id)
            .all()
        )

    def should_add_diagnostic(self, profile: dict, target_topics: list | None) -> bool:
        """
        判断是否需要添加诊断步骤（文档 Section 12.2）。

        画像足够条件：knowledge_mastery 数量 >= 3 且至少有 1 个 weak_point
        画像不足条件：knowledge_mastery 为空，或大部分 mastery_score 为 0，或 overall_level 为未知
        """
        mastery = profile.get("knowledge_mastery") or []
        weak = profile.get("weak_points") or []

        if not mastery:
            return True
        if len(mastery) < 3:
            return True
        if profile.get("overall_level") in ("未知", "暂无数据"):
            return True

        # 大部分 mastery_score 为 0
        zero_count = sum(1 for m in mastery if m.get("mastery_score", 0) == 0)
        if zero_count > len(mastery) / 2:
            return True

        return False

    @staticmethod
    def _match_target_kp_ids(knowledge_points: list, target_topics: list) -> list[int]:
        """匹配目标知识点 ID"""
        if not target_topics:
            return []
        ids = []
        for kp in knowledge_points:
            for topic in target_topics:
                if topic in kp.name or kp.name in topic:
                    ids.append(kp.id)
                    break
        return ids

    # ── 写入 metadata（文档 Section 22） ─────────────────────────

    @staticmethod
    def _write_goal_metadata(
        db: Session,
        goal_id: int,
        conversation_id: int | None,
        user_message: str,
        diagnostic_required: bool,
    ) -> None:
        """写入目标 metadata_json"""
        from app.models.agent_goal import AgentLearningGoal

        goal = db.query(AgentLearningGoal).filter(AgentLearningGoal.id == goal_id).first()
        if not goal:
            return

        current_meta = goal.metadata_json or {}
        current_meta.update({
            "source": "chat_agent",
            "source_conversation_id": conversation_id,
            "source_message": user_message,
            "diagnostic_required": diagnostic_required,
            "created_by_tool": "create_learning_goal_from_chat",
        })
        goal.metadata_json = current_meta
        db.commit()

    # ── 构建响应 ─────────────────────────────────────────────────

    def build_success_response(
        self,
        goal: dict,
        plan: dict,
        profile: dict,
        agent_steps: list,
        diagnostic_required: bool = False,
    ) -> dict:
        """构建成功响应（文档 Section 26.1 / 26.2）"""
        course_name = self._extract_course_name_from_goal(goal)
        profile_summary = self._build_profile_summary_text(profile)
        plan_summary = plan.get("plan_summary", "")
        step_count = plan.get("step_count", 0)

        goal_title = goal['title']
        if diagnostic_required:
            text = (
                "我已为你创建「{}」。\n\n"
                "目前你的学习画像数据还不够完整，"
                "所以我把计划第一步安排为基础诊断，用来先判断当前水平。\n\n"
                "我已经生成了 {} 个学习步骤，"
                "你可以进入学习目标页查看完整计划。"
            ).format(goal_title, step_count)
        else:
            text = (
                "我已为你创建「{}」。\n\n"
                "我查看了你在「{}」中的学习画像：{}\n\n"
                "基于你的目标，我已经生成了 {} 个学习步骤。"
            ).format(goal_title, course_name, profile_summary, step_count)
            if plan_summary:
                text += "\n整体安排是：\n{}\n\n".format(plan_summary)
            else:
                text += "\n"
            text += "你可以进入学习目标页查看完整计划，也可以从第一步开始。"

        return {
            "type": "learning_goal_created",
            "text": text,
            "qa_id": None,
            "document": None,
            "agent_steps": agent_steps,
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
            "learning_goal": {
                "id": goal["id"],
                "title": goal["title"],
                "course_id": goal["course_id"],
                "progress_percent": goal.get("progress_percent", 0),
                "status": goal.get("status"),
            },
            "goal_plan": {
                "step_count": step_count,
                "plan_summary": plan_summary,
                "planning_status": plan.get("planning_status", "planned"),
            },
        }

    def _build_goal_created_plan_failed_response(
        self,
        goal: dict,
        error: str,
        agent_steps: list,
    ) -> dict:
        """构建"目标已创建但计划失败"响应（文档 Section 26.4）"""
        return {
            "type": "learning_goal_created",
            "text": "我已经创建了学习目标「{}」，但生成学习计划时失败了。\n你可以进入学习目标页重新生成计划。".format(goal["title"]),
            "qa_id": None,
            "document": None,
            "agent_steps": agent_steps + [{
                "title": "生成学习计划",
                "detail": f"计划生成失败：{error}",
                "status": "failed",
            }],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
            "learning_goal": {
                "id": goal["id"],
                "title": goal["title"],
                "course_id": goal["course_id"],
                "progress_percent": goal.get("progress_percent", 0),
                "status": goal.get("status"),
            },
            "goal_plan": {
                "planning_status": "failed",
                "step_count": 0,
                "plan_summary": None,
            },
        }

    # ── 澄清响应 ─────────────────────────────────────────────────

    def _build_clarify_course(self, candidates: list) -> dict:
        """多个候选课程时返回澄清"""
        course_list = "、".join(c.name for c in candidates)
        return {
            "type": "clarification",
            "text": f"可以，我需要先确认是哪门课程。我找到多个可能的课程：{course_list}。你想为哪一门创建学习目标？",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {"title": "识别学习目标", "detail": "检测到目标创建意图", "status": "done"},
                {"title": "确认课程", "detail": f"匹配到多个课程：{course_list}，需用户确认", "status": "need_user_input"},
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": {
                "type": "clarify_learning_goal_course",
                "assistant_question": f"你想为哪一门创建学习目标？",
                "payload": {
                    "original_message": "",
                    "tool_args": {},
                    "candidate_courses": [{"id": c.id, "name": c.name} for c in candidates],
                },
            },
            "skip_reply_action_detection": True,
        }

    def _build_clarify_no_course(self, course_name: str) -> dict:
        """未找到匹配课程"""
        return {
            "type": "clarification",
            "text": "我没有找到「{}」这门课程。你可以先添加课程，或者选择当前已有课程后再让我制定计划。".format(course_name),
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {"title": "识别学习目标", "detail": "检测到目标创建意图", "status": "done"},
                {"title": "确认课程", "detail": f"未找到课程：{course_name}", "status": "failed"},
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    def _build_clarify_need_course(self) -> dict:
        """没有课程信息，需要用户明确"""
        return {
            "type": "clarification",
            "text": "可以，我需要先确认是哪门课程。你想为哪门课制定学习计划？",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {"title": "识别学习目标", "detail": "检测到目标创建意图", "status": "done"},
                {"title": "确认课程", "detail": "无法确定课程，需用户补充", "status": "need_user_input"},
            ],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": {
                "type": "clarify_learning_goal_course",
                "assistant_question": "你想为哪门课程制定学习计划？",
                "payload": {
                    "original_message": "",
                    "tool_args": {},
                    "candidate_courses": [],
                },
                "confirm_intent": "create_learning_goal",
                "confirm_action": "create_learning_goal_from_chat",
            },
            "skip_reply_action_detection": True,
        }

    def _build_error_response(self, error: str, agent_steps: list) -> dict:
        """构建通用错误响应"""
        return {
            "type": "clarification",
            "text": f"创建学习目标时出现了问题：{error}。请稍后重试。",
            "qa_id": None,
            "document": None,
            "agent_steps": agent_steps + [{
                "title": "处理失败",
                "detail": error,
                "status": "failed",
            }],
            "retrieved_chunks": [],
            "related_knowledge_point_ids": [],
            "pending_action_update": None,
            "skip_reply_action_detection": True,
        }

    # ── 辅助文本构建 ─────────────────────────────────────────────

    @staticmethod
    def _build_goal_recognition_detail(args: dict) -> str:
        """构建目标识别描述"""
        parts = []
        if args.get("exam_type"):
            parts.append(f"识别为{args['exam_type']}")
        if args.get("target_score"):
            parts.append(f"目标 {args['target_score']} 分")
        if args.get("duration_days"):
            parts.append(f"周期 {args['duration_days']} 天")
        if args.get("course_name"):
            parts.append(f"课程：{args['course_name']}")
        detail = "识别到用户希望创建学习目标"
        if parts:
            detail += "：" + "，".join(parts)
        return detail

    @staticmethod
    def _build_profile_summary_text(profile: dict) -> str:
        """构建画像摘要文本"""
        overall = profile.get("overall_level", "暂无数据")
        mastery_count = len(profile.get("knowledge_mastery") or [])
        weak_count = len(profile.get("weak_points") or [])

        parts = ["整体水平为「{}」".format(overall)]
        if mastery_count > 0:
            parts.append(f"已覆盖 {mastery_count} 个知识点")
        if weak_count > 0:
            parts.append(f"有 {weak_count} 个薄弱点需要加强")
        else:
            parts.append("暂无薄弱点数据")

        return "，".join(parts)

    @staticmethod
    def _build_profile_detail(profile: dict, diagnostic_required: bool) -> str:
        """构建画像读取详情"""
        overall = profile.get("overall_level", "未知")
        mastery_count = len(profile.get("knowledge_mastery") or [])
        detail = "已读取学习画像：整体水平「{}」，覆盖 {} 个知识点".format(overall, mastery_count)
        if diagnostic_required:
            detail += "（画像不足，建议先诊断）"
        return detail

    @staticmethod
    def _extract_course_name_from_goal(goal: dict) -> str:
        """从 goal 中提取课程名（通过 course_id）"""
        # goal 里只有 course_id，课程名需要从 title 推导
        title = goal.get("title", "")
        # title 格式如 "数据结构期末达到 60 分" -> "数据结构"
        match = re.match(r'^([^：:]+)', title)
        if match:
            return match.group(1)
        return "该课程"


# ── 单例 ──────────────────────────────────────────────────────

agent_goal_chat_creation_service = AgentGoalChatCreationService()
