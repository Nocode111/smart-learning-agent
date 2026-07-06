"""
LLM 语义路由服务 — 结合上下文、pending action、课程知识点，输出结构化 JSON 意图。

文档参考：docs/LLM语义路由Agent最终架构_详细技术实现文档.md Section 8-10
"""

import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.qwen_client import qwen_client

logger = logging.getLogger(__name__)

# ================================================================
# Pydantic 模型（文档 Section 8.3 / 8.4）
# ================================================================


class IntentRouterInput(BaseModel):
    message: str
    course_id: int
    student_id: int
    pending_action: dict | None = None
    recent_messages: list[dict] = Field(default_factory=list)
    last_topic: str | None = None
    knowledge_points: list[dict] = Field(default_factory=list)
    active_practice_session: dict | None = None
    attachments: list[dict] = Field(default_factory=list)
    memory_context_text: str | None = None


class IntentRouterResult(BaseModel):
    is_learning_related: bool
    domain: str  # learning | system_identity | small_talk | out_of_scope | ambiguous
    intent: str
    confidence: float
    refers_to_previous_message: bool = False
    resolved_action: str | None = None
    topic: str | None = None
    knowledge_point_ids: list[int] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
    tool_name: str | None = None
    tool_args: dict = Field(default_factory=dict)
    pending_action_update: dict | None = None
    answer_strategy: str = "normal"  # normal | brief_identity | boundary_response | execute_tool
    reason: str = ""
    # 附件相关字段（文档 Section 14.1）
    requires_attachment_context: bool = False
    retrieval_scope: str = "hybrid"  # attachments_only | attachments_first | course_only | hybrid
    target_attachment_ids: list[int] = Field(default_factory=list)
    attachment_reference: str | None = None

    @classmethod
    def from_rule(cls, rule_result: dict) -> "IntentRouterResult":
        """当 RuleGate 命中时，直接将规则结果转为 IntentRouterResult。"""
        return cls(
            is_learning_related=rule_result.get("is_learning_related", True),
            domain=rule_result.get("domain", "learning"),
            intent=rule_result.get("intent", "unknown"),
            confidence=rule_result.get("confidence", 1.0),
            refers_to_previous_message=rule_result.get("refers_to_previous_message", False),
            resolved_action=rule_result.get("resolved_action"),
            topic=rule_result.get("topic"),
            knowledge_point_ids=rule_result.get("knowledge_point_ids") or [],
            need_clarification=rule_result.get("need_clarification", False),
            clarification_question=rule_result.get("clarification_question"),
            tool_name=rule_result.get("tool_name", "clarify"),
            tool_args=rule_result.get("tool_args") or {},
            pending_action_update=rule_result.get("pending_action_update"),
            answer_strategy=rule_result.get("answer_strategy", "normal"),
            reason=f'[RuleGate] {rule_result.get("reason", "")}',
            requires_attachment_context=rule_result.get("requires_attachment_context", False),
            retrieval_scope=rule_result.get("retrieval_scope", "hybrid"),
            target_attachment_ids=rule_result.get("target_attachment_ids") or [],
            attachment_reference=rule_result.get("attachment_reference"),
        )


# ================================================================
# 允许值白名单（文档 Section 8.5 / 8.6 / 8.7）
# ================================================================

ALLOWED_DOMAINS = {"learning", "system_identity", "small_talk", "out_of_scope", "ambiguous"}

ALLOWED_INTENTS = {
    "qa_answer",
    "generate_exercise_document",
    "confirm_previous_action",
    "deny_previous_action",
    "clarify_exercise_count",
    "start_guided_practice",
    "continue_explanation",
    "provide_code_example",
    "provide_compare_explanation",
    "clarify_missing_info",
    "system_identity",
    "small_talk",
    "out_of_scope",
    "unknown",
    "generate_inline_practice",
    "grade_practice_answer",
    "continue_inline_practice",
    "local_file_edit_prepare",
    "local_file_edit_confirm",
    "local_file_edit_cancel",
    "create_learning_goal",
    "continue_learning_goal",
    "memory_recall",
    "memory_update",
}

ALLOWED_TOOL_NAMES = {
    "qa_answer",
    "generate_exercise_document",
    "start_guided_practice",
    "continue_explanation",
    "provide_code_example",
    "provide_compare_explanation",
    "cancel_pending_action",
    "clarify_exercise_count",
    "clarify",
    "system_identity",
    "small_talk",
    "out_of_scope",
    "generate_inline_practice",
    "grade_practice_answer",
    "continue_inline_practice",
    "local_file_edit_prepare",
    "local_file_edit_confirm",
    "local_file_edit_cancel",
    "create_learning_goal_from_chat",
    "continue_learning_goal_loop",
    "memory_recall",
    "memory_update",
}

# ================================================================
# System Prompt（文档 Section 9.1）
# ================================================================

ROUTER_SYSTEM_PROMPT = """你是一个智慧学习辅助系统中的"意图路由器"，不是最终答疑老师。

你的任务是根据：
1. 用户当前输入
2. 最近几轮对话
3. 当前 pending_action
4. 当前课程知识点

判断用户真实意图，并输出严格 JSON。

你不能直接回答用户问题。
你不能编造工具。
你不能输出 Markdown。
你不能输出 JSON 之外的任何文本。

系统支持的工具只有：
- qa_answer
- generate_exercise_document
- start_guided_practice
- continue_explanation
- provide_code_example
- provide_compare_explanation
- cancel_pending_action
- clarify_exercise_count
- clarify
- system_identity
- small_talk
- out_of_scope
- generate_inline_practice
- grade_practice_answer
- continue_inline_practice
- local_file_edit_prepare
- local_file_edit_confirm
- local_file_edit_cancel
- create_learning_goal_from_chat
- continue_learning_goal_loop
- memory_recall
- memory_update

判断原则：
1. 如果用户输入是"需要 / 可以 / 好的 / 行 / 来吧 / 开始吧"等短回复，并且 pending_action 存在，应优先理解为对 pending_action 的确认。
2. 如果用户输入是"不需要 / 不用 / 不要 / 算了"等短回复，并且 pending_action 存在，应理解为取消 pending_action。
3. 如果 pending_action.type 是 confirm_generate_exercise，用户确认后 tool_name 应为 clarify_exercise_count，用于追问题目数量。
4. 如果 pending_action.type 是 clarify_exercise_count，用户补充了"3道/五题"等数量后 tool_name 应为 generate_exercise_document。
5. 如果没有 pending_action，但上一条 assistant 消息明确提出了问题或邀请，应结合上一条 assistant 消息理解短回复。
6. 如果用户问题与学习、课程、知识点、题目、解释、代码示例、复习相关，domain 为 learning。
7. 如果用户问"你是什么模型 / 你是谁 / 你能做什么"，domain 为 system_identity。
8. 如果用户只是问候，domain 为 small_talk。
9. 如果用户请求与学习无关，例如写情书、娱乐八卦、无关生活任务，domain 为 out_of_scope。
10. 如果信息不足，不要硬猜，使用 clarify 工具。
11. confidence 低于 0.65 时，优先澄清。
12. 如果用户要求"不要文档 / 不用文档 / 直接文字发给我 / 我答完你批改 / 看我是否理解"，应选择 generate_inline_practice，不要选择 generate_exercise_document。
13. 如果用户输入类似"第一题选 A / 第 2 题 B / 我选 C"，并且当前存在 active inline practice session，应选择 grade_practice_answer。
14. generate_exercise_document 只用于用户明确要"文档 / Markdown / 下载 / 整理成文件"的场景。
15. 对话式练习生成后，即使用户要求"不带答案解析"，系统内部仍要保存答案解析，只是不展示给用户。
16. 如果用户说"这个文档""刚上传的文件""这个 PDF""附件""根据资料里内容""总结文档""根据文档回答"等，应判断是否引用当前会话附件。如果可以从附件标题或上传顺序判断目标附件，请给出 target_attachment_ids（附件 ID 列表）。如果无法确定但明显需要附件，请设置 requires_attachment_context = true，retrieval_scope = "attachments_first"。如果当前会话没有附件，使用 course_only。
17. 如果用户没有明显指向附件，retrieval_scope 应为 "hybrid"。
18. 如果当前 active_practice_session 为 null，但当前会话附件不为空，用户说"这几道题是否正确""帮我看这些题""我上传的题"等，应选择 qa_answer，并设置 requires_attachment_context = true，retrieval_scope = "attachments_first"，不要选择 continue_inline_practice 或 grade_practice_answer。
19. 如果用户明确要求修改电脑上的某个本地文件，并提供了文件路径和修改要求，应选择 local_file_edit_prepare。
20. local_file_edit_prepare 必须提取 tool_args.file_path 和 tool_args.instruction。
21. 如果用户只是询问"能不能修改文件"，不要选择 local_file_edit_prepare，应走 qa_answer 或 clarify。
22. 如果用户提供了修改要求但没有文件路径，应使用 clarify，要求用户提供允许目录内的完整文件路径。
23. 任何本地文件修改都不能直接完成写入，只能生成预览，必须等待用户确认。
24. 如果用户要求执行命令、删除文件、移动文件、修改系统文件，应拒绝或澄清，不要选择文件修改工具。
25. 如果用户表达"制定学习计划 / 创建学习目标 / 期末目标 / 多少天掌握 / 目标考多少分 / 帮我规划学习路线"，应优先选择 create_learning_goal_from_chat。
26. 如果用户只是问某个知识点怎么理解，不要选择 create_learning_goal_from_chat。
27. create_learning_goal_from_chat 必须尽量提取 course_name、goal_text、target_score、due_date、duration_days、target_topics。
28. 如果无法确定课程，但当前对话已有 course_id，可以先使用当前课程；如果用户明确说的是另一门课，则填 course_name。
29. 如果用户目标太模糊，应设置 need_clarification=true，tool_name=clarify。
30. 如果用户表达"继续推进目标 / 帮我推进目标 / 继续执行学习计划 / 继续我的目标 / 开始推进 / 继续数据结构期末目标"，应优先选择 continue_learning_goal_loop。
31. continue_learning_goal_loop 需要尽量提取 goal_id（如果用户提到了具体目标）或 goal_title_hint（目标标题关键词），如果没有明确目标 id，设置 auto_select_latest_goal=true。
32. 如果当前课程下没有 active 目标，应提示用户先创建目标。
33. 如果用户只是问目标进展或查看目标状态，不要选择 continue_learning_goal_loop，应走 qa_answer。
34. continue_learning_goal_loop 的 max_iterations 默认为 3。
35. 如果用户问"你还记得我叫什么吗""你还记得我刚刚问了什么知识点吗""我刚才问了什么"等回忆类问题，tool_name 应为 memory_recall，不要因为信息看起来不足而澄清。
36. 如果用户表达"我改名字了 / 我换名字了 / 以后叫我 / 我不叫X了我叫Y / 我现在叫Y / 我是Y"等更新用户画像或偏好的请求，tool_name 应为 memory_update，不要使用 memory_recall。

必须输出以下 JSON 结构（不要输出任何其他内容）：
{
  "is_learning_related": true,
  "domain": "learning",
  "intent": "qa_answer",
  "confidence": 0.0,
  "refers_to_previous_message": false,
  "resolved_action": null,
  "topic": null,
  "knowledge_point_ids": [],
  "need_clarification": false,
  "clarification_question": null,
  "tool_name": "qa_answer",
  "tool_args": {},
  "pending_action_update": null,
  "answer_strategy": "normal",
  "reason": "简短说明判断依据",
  "requires_attachment_context": false,
  "retrieval_scope": "hybrid",
  "target_attachment_ids": [],
  "attachment_reference": null
}"""


def _parse_json_object(text: str) -> dict:
    """解析 LLM 输出的 JSON，失败时尝试截取 { 到 } 再解析（文档 Section 10.2）"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


# ================================================================
# LLMIntentRouterService
# ================================================================


class LLMIntentRouterService:
    """
    LLM 语义路由服务。

    只负责：结合输入 + 上下文，输出结构化 IntentRouterResult。
    不操作数据库、不调用其他 Agent、不生成最终回答。
    """

    def __init__(self):
        self.temperature = 0.0  # 文档 Section 23.2
        self.timeout_seconds = 15.0  # 文档 Section 23.2
        self.recent_message_limit = 8  # 文档 Section 23.2

    # ── 公开入口 ─────────────────────────────────────────────

    def route(
        self,
        db: Session,
        message: str,
        course_id: int,
        student_id: int,
        context: dict,
    ) -> IntentRouterResult:
        """
        主入口：调用 LLM 进行语义路由。

        返回 IntentRouterResult，失败时返回 clarify fallback。
        """
        # 1. 构建输入
        knowledge_points = self._load_knowledge_points(db, course_id, context)
        router_input = IntentRouterInput(
            message=message,
            course_id=course_id,
            student_id=student_id,
            pending_action=context.get("pending_action"),
            recent_messages=self._truncate_recent_messages(
                context.get("recent_messages") or []
            ),
            last_topic=context.get("last_topic"),
            knowledge_points=knowledge_points,
            active_practice_session=context.get("active_practice_session"),
            attachments=context.get("attachments") or [],
            memory_context_text=context.get("memory_context_text"),
        )

        # 2. 构建 messages
        user_prompt = self._build_user_prompt(router_input)
        llm_messages = [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 3. 调用 LLM
        try:
            raw_response = qwen_client.chat(
                messages=llm_messages,
                temperature=self.temperature,
            )
        except Exception as exc:
            logger.warning("LLM 路由调用失败，回退到 clarify: %s", exc)
            return self._fallback_clarify(message, f"LLM调用异常: {exc}")

        # 4. 解析 JSON
        try:
            parsed = _parse_json_object(raw_response)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM 路由 JSON 解析失败，原始输出: %s", raw_response[:200])
            return self._fallback_clarify(message, f"JSON解析失败: {exc}")

        # 5. Pydantic 校验（文档 Section 10.3）
        try:
            result = IntentRouterResult.model_validate(parsed)
        except Exception as exc:
            logger.warning("Pydantic 校验失败: %s, parsed=%s", exc, parsed)
            return self._fallback_clarify(message, f"校验失败: {exc}")

        # 6. 白名单校验
        result = self._validate_and_fix(result)

        return result

    # ── User Prompt 模板（文档 Section 9.2） ──────────────────

    def _build_user_prompt(self, inp: IntentRouterInput) -> str:
        pending_json = json.dumps(inp.pending_action, ensure_ascii=False) if inp.pending_action else "null"
        recent_json = json.dumps(inp.recent_messages, ensure_ascii=False, default=str)
        kp_json = json.dumps(inp.knowledge_points, ensure_ascii=False)
        practice_json = json.dumps(inp.active_practice_session, ensure_ascii=False) if inp.active_practice_session else "null"
        attachments_json = json.dumps(inp.attachments, ensure_ascii=False) if inp.attachments else "[]"
        memory_context_text = inp.memory_context_text or "无"

        return f"""当前用户输入：
{inp.message}

当前 pending_action：
{pending_json}

当前 active_practice_session：
{practice_json}

当前会话附件：
{attachments_json}

最近对话：
{recent_json}

长期记忆上下文：
{memory_context_text}

当前课程知识点：
{kp_json}

最近话题：
{inp.last_topic or "无"}

如果用户说"这个文档""刚上传的文件""这个 PDF""附件""根据资料里内容"等，请判断是否引用当前会话附件。
如果可以从附件标题或上传顺序判断目标附件，请给出 target_attachment_ids。
如果无法确定但明显需要附件，请设置 retrieval_scope = "attachments_first"。
如果当前会话没有附件，请使用 retrieval_scope = "course_only"。
如果 active_practice_session 为 null，而用户是在问刚上传附件里的题目是否正确，应使用 qa_answer，不要使用 continue_inline_practice 或 grade_practice_answer。

请输出严格 JSON。"""

    # ── 知识点加载 ────────────────────────────────────────────

    def _load_knowledge_points(
        self, db: Session, course_id: int, context: dict
    ) -> list[dict]:
        """加载课程知识点（只传 id、name，不传长描述——文档 Section 23.1）"""
        from app.models.knowledge_point import KnowledgePoint

        points = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.course_id == course_id)
            .all()
        )
        return [{"id": p.id, "name": p.name} for p in points]

    # ── 截断最近消息（文档 Section 23.2） ─────────────────────

    def _truncate_recent_messages(self, recent_messages: list[dict]) -> list[dict]:
        """只保留最近 N 条消息，并精简字段"""
        truncated = recent_messages[-self.recent_message_limit :]
        return [
            {
                "role": m.get("role"),
                "type": m.get("type"),
                "content": (m.get("content") or "")[:500],  # 截断长内容
                "intent": m.get("intent"),
            }
            for m in truncated
        ]

    # ── 白名单校验与修复 ──────────────────────────────────────

    def _validate_and_fix(self, result: IntentRouterResult) -> IntentRouterResult:
        """校验并修复 LLM 输出，确保关键字段在合法范围内"""
        if result.domain not in ALLOWED_DOMAINS:
            result.domain = "ambiguous"
        if result.intent not in ALLOWED_INTENTS:
            result.intent = "unknown"
        if result.tool_name not in ALLOWED_TOOL_NAMES:
            result.tool_name = "clarify"
        result.confidence = max(0.0, min(1.0, result.confidence))
        if result.confidence < 0.65:
            result.need_clarification = True
            result.tool_name = "clarify"
            if not result.clarification_question:
                result.clarification_question = "我还不确定你想让我做什么，可以再具体说一下吗？"
        return result

    # ── Fallback ──────────────────────────────────────────────

    def _fallback_clarify(self, message: str, reason: str = "") -> IntentRouterResult:
        """LLM 调用失败或解析失败时的兜底（文档 Section 10.3）"""
        return IntentRouterResult(
            is_learning_related=False,
            domain="ambiguous",
            intent="unknown",
            confidence=0.0,
            refers_to_previous_message=False,
            need_clarification=True,
            clarification_question="我还不确定你想让我做什么，可以再具体说一下吗？",
            tool_name="clarify",
            tool_args={"original_message": message},
            answer_strategy="clarify",
            reason=f"LLM路由失败兜底: {reason}",
        )

# ── 单例 ──────────────────────────────────────────────────────

llm_intent_router_service = LLMIntentRouterService()
