import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.services.agent_conversation_service import agent_conversation_service
from app.services.agent_memory_service import agent_memory_service
from app.services.agent_reply_action_detector import agent_reply_action_detector
from app.services.exercise_agent_service import exercise_agent_service
from app.services.qa_agent_service import get_qa_agent_service


class AgentRouterService:
    # ================================================================
    # 上下文意图 → Handler 路由表
    # ================================================================
    @property
    def contextual_handlers(self):
        return {
            "cancel_pending_action": self.handle_cancel_pending_action,
            "clarify_exercise_count": self.handle_clarify_exercise_count,
            "generate_exercise_document": self.handle_contextual_generate_exercise,
            "start_guided_practice": self.handle_start_guided_practice,
            "continue_explanation": self.handle_continue_explanation,
            "provide_code_example": self.handle_provide_code_example,
            "provide_compare_explanation": self.handle_provide_compare_explanation,
        }

    # ================================================================
    # 主入口
    # ================================================================

    def chat(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation_id: int | None = None,
    ) -> dict:
        message = (message or "").strip()

        # 1. 获取或创建会话
        conversation = agent_conversation_service.get_or_create_conversation(
            db=db,
            student_id=student_id,
            course_id=course_id,
            conversation_id=conversation_id,
            first_message=message,
        )

        # 2. 读取最近上下文
        recent_messages = agent_conversation_service.get_recent_messages(
            db=db,
            conversation_id=conversation.id,
            limit=10,
        )
        context = agent_memory_service.build_context(conversation, recent_messages)

        # 3. 保存用户消息
        agent_conversation_service.add_message(
            db=db,
            conversation=conversation,
            role="user",
            content=message,
            message_type="text",
        )

        # 4. 先判断是否有上下文待确认动作（pending_action 或上条 assistant 邀请）
        contextual_intent = agent_memory_service.resolve_contextual_intent(message, context)

        if contextual_intent:
            # 路由到对应的上下文 handler
            intent = contextual_intent.get("intent")
            handler = self.contextual_handlers.get(intent)
            if handler:
                result = handler(
                    db=db,
                    student_id=student_id,
                    course_id=course_id,
                    message=message,
                    conversation=conversation,
                    contextual_intent=contextual_intent,
                )
            else:
                # 未知上下文意图，兜底走普通答疑
                result = self.handle_qa(
                    db=db,
                    student_id=student_id,
                    course_id=course_id,
                    message=message,
                    conversation=conversation,
                )
        else:
            # 5. 检查是否为无上下文的确认语/否定语（Section 23.5）
            if agent_memory_service.is_affirmative(message) or agent_memory_service.is_negative(message):
                result = self.handle_bare_affirmative(message)
            else:
                # 6. 常规意图识别
                intent = self.detect_intent(message)
                if intent == "generate_exercise_document":
                    result = self.handle_generate_exercise(
                        db=db,
                        student_id=student_id,
                        course_id=course_id,
                        message=message,
                        conversation=conversation,
                    )
                else:
                    result = self.handle_qa(
                        db=db,
                        student_id=student_id,
                        course_id=course_id,
                        message=message,
                        conversation=conversation,
                    )

        # 7. 后处理：分析 assistant 回复，自动生成 derived_pending_action
        derived_pending_action = None
        if not result.get("skip_reply_action_detection"):
            derived_pending_action = agent_reply_action_detector.detect(
                assistant_text=result.get("text") or "",
                last_topic=conversation.last_topic,
                knowledge_point_ids=result.get("related_knowledge_point_ids") or conversation.last_knowledge_point_ids or [],
            )

            if derived_pending_action:
                agent_conversation_service.update_memory(
                    db=db,
                    conversation=conversation,
                    last_topic=derived_pending_action.get("topic"),
                    last_knowledge_point_ids=derived_pending_action.get("knowledge_point_ids") or [],
                    pending_action=derived_pending_action,
                )

        # 8. 附加 conversation_id
        result["conversation_id"] = conversation.id

        # 9. 保存 AI 消息（含 derived_pending_action）
        agent_conversation_service.add_message(
            db=db,
            conversation=conversation,
            role="assistant",
            content=result.get("text"),
            message_type=result.get("type", "answer"),
            intent=result.get("intent"),
            qa_id=result.get("qa_id"),
            document_id=result.get("document", {}).get("id") if result.get("document") else None,
            related_knowledge_point_ids=result.get("related_knowledge_point_ids"),
            agent_steps=result.get("agent_steps"),
            retrieved_chunks=result.get("retrieved_chunks"),
            metadata={
                "document": result.get("document"),
                "derived_pending_action": derived_pending_action,
            },
        )

        db.commit()
        return result

    # ========== 意图识别 ==========

    def detect_intent(self, message: str) -> str:
        exercise_keywords = ["练习题", "习题", "题目", "试题", "专项练习"]
        generate_keywords = ["生成", "出", "帮我出", "整理", "做一份"]
        document_keywords = ["文档", "markdown", "md"]

        has_exercise = any(keyword in message for keyword in exercise_keywords)
        has_generate = any(keyword in message for keyword in generate_keywords)
        has_document = any(keyword.lower() in message.lower() for keyword in document_keywords)

        if has_exercise and (has_generate or has_document):
            return "generate_exercise_document"

        return "qa_answer"

    # ========== 无上下文确认语处理 ==========

    def handle_bare_affirmative(self, message: str) -> dict:
        """用户输入确认/否定语，但没有上下文可参考时，引导澄清"""
        if agent_memory_service.is_negative(message):
            return {
                "intent": "cancel_pending_action",
                "type": "answer",
                "text": "好的，有需要随时问我。",
                "qa_id": None,
                "document": None,
                "agent_steps": [],
                "retrieved_chunks": [],
                "skip_reply_action_detection": True,
            }

        return {
            "intent": "clarify_ambiguous_need",
            "type": "clarification",
            "text": "你是指需要讲解、需要练习题，还是需要继续某个知识点？请说得具体一点，我好帮你。",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "需要澄清",
                    "detail": "用户输入确认语但无上下文，等待用户补充具体需求",
                    "status": "need_user_input",
                }
            ],
            "retrieved_chunks": [],
            "skip_reply_action_detection": True,
        }

    # ================================================================
    # 上下文意图 Handler
    # ================================================================

    def handle_cancel_pending_action(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation,
        contextual_intent: dict,
    ) -> dict:
        agent_conversation_service.update_memory(
            db=db,
            conversation=conversation,
            clear_pending=True,
        )
        return {
            "intent": "cancel_pending_action",
            "type": "answer",
            "text": "好的，那我们先不继续这个操作。你可以继续问我刚才这个知识点的问题。",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "取消待确认任务",
                    "detail": "用户取消当前待确认动作",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "skip_reply_action_detection": True,
        }

    def handle_clarify_exercise_count(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation,
        contextual_intent: dict,
    ) -> dict:
        pending_action = contextual_intent.get("pending_action") or {}
        topic = contextual_intent.get("topic") or pending_action.get("topic") or "相关知识点"
        knowledge_point_ids = contextual_intent.get("knowledge_point_ids") or pending_action.get("knowledge_point_ids") or []

        new_pending = {
            "type": "clarify_exercise_count",
            "topic": topic,
            "knowledge_point_ids": knowledge_point_ids,
            "include_answer": True,
            "include_explanation": True,
            "created_at": datetime.utcnow().isoformat(),
        }
        agent_conversation_service.update_memory(
            db=db,
            conversation=conversation,
            pending_action=new_pending,
        )
        return {
            "intent": "clarify_exercise_count",
            "type": "clarification",
            "text": f"好的，我会基于刚才的“{topic}”来出题。你想生成几道？是否需要答案和解析？",
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "读取上下文",
                    "detail": f"识别到上一轮话题：{topic}；待确认动作：生成练习题",
                    "status": "done",
                },
                {
                    "title": "等待补充参数",
                    "detail": "需要用户补充题目数量",
                    "status": "need_user_input",
                },
            ],
            "retrieved_chunks": [],
            "skip_reply_action_detection": True,
        }

    def handle_contextual_generate_exercise(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation,
        contextual_intent: dict,
    ) -> dict:
        knowledge_point_ids = contextual_intent.get("knowledge_point_ids") or []
        knowledge_point_id = knowledge_point_ids[0] if knowledge_point_ids else None
        result = self.handle_generate_exercise(
            db=db,
            student_id=student_id,
            course_id=course_id,
            message=message,
            conversation=conversation,
            fallback_knowledge_point_id=knowledge_point_id,
        )
        agent_conversation_service.update_memory(
            db=db,
            conversation=conversation,
            clear_pending=True,
        )
        return result

    def handle_start_guided_practice(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation,
        contextual_intent: dict,
    ) -> dict:
        topic = contextual_intent.get("topic") or "刚才这个知识点"

        agent_conversation_service.update_memory(
            db=db,
            conversation=conversation,
            clear_pending=True,
        )

        return {
            "intent": "start_guided_practice",
            "type": "answer",
            "text": (
                f"好的，我们就基于“{topic}”做一个小练习。\n\n"
                "第 1 题：请你判断下面这个场景更像栈还是队列，并说一句理由：\n\n"
                "浏览器连续打开 A 页面、B 页面、C 页面，然后点击“返回”时，"
                "会先回到哪个页面？"
            ),
            "qa_id": None,
            "document": None,
            "agent_steps": [
                {
                    "title": "读取上下文",
                    "detail": f"用户确认开始小练习；练习话题：{topic}",
                    "status": "done",
                }
            ],
            "retrieved_chunks": [],
            "skip_reply_action_detection": True,
        }

    def handle_continue_explanation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation,
        contextual_intent: dict,
    ) -> dict:
        topic = contextual_intent.get("topic") or "刚才的问题"
        # 清掉 pending，避免循环
        agent_conversation_service.update_memory(
            db=db,
            conversation=conversation,
            clear_pending=True,
        )
        question = f"请继续解释：{topic}。要求比上一轮更详细、更深入。"
        return self.handle_qa(
            db=db,
            student_id=student_id,
            course_id=course_id,
            message=question,
            conversation=conversation,
        )

    def handle_provide_code_example(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation,
        contextual_intent: dict,
    ) -> dict:
        topic = contextual_intent.get("topic") or "刚才的问题"
        agent_conversation_service.update_memory(
            db=db,
            conversation=conversation,
            clear_pending=True,
        )
        question = f"请用代码示例解释：{topic}。给出可运行的代码并逐行解释。"
        return self.handle_qa(
            db=db,
            student_id=student_id,
            course_id=course_id,
            message=question,
            conversation=conversation,
        )

    def handle_provide_compare_explanation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation,
        contextual_intent: dict,
    ) -> dict:
        topic = contextual_intent.get("topic") or "刚才的问题"
        agent_conversation_service.update_memory(
            db=db,
            conversation=conversation,
            clear_pending=True,
        )
        question = f"请用对比方式解释：{topic}。从多个维度对比并给出结论。"
        return self.handle_qa(
            db=db,
            student_id=student_id,
            course_id=course_id,
            message=question,
            conversation=conversation,
        )

    # ========== 普通答疑 ==========

    def handle_qa(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation=None,
    ) -> dict:
        qa_service = get_qa_agent_service()
        result = qa_service.ask(
            db=db,
            student_id=student_id,
            course_id=course_id,
            question=message,
        )

        related_ids = result.get("related_knowledge_point_ids", [])
        point_names = self.get_knowledge_point_names(db, related_ids)
        topic = "、".join(point_names) if point_names else self.extract_topic_from_message(message)

        answer_text = result["answer"]

        # 匹配到知识点时，追问是否要生成练习题
        if related_ids:
            answer_text += f"\n\n需要我基于“{topic}”给你出几道练习题吗？"
            if conversation:
                agent_conversation_service.update_memory(
                    db=db,
                    conversation=conversation,
                    last_topic=topic,
                    last_knowledge_point_ids=related_ids,
                    pending_action={
                        "type": "confirm_generate_exercise",
                        "topic": topic,
                        "knowledge_point_ids": related_ids,
                        "confirm_intent": "clarify_exercise_count",
                        "negative_intent": "cancel_pending_action",
                        "default_question_count": 5,
                        "default_include_answer": True,
                        "default_include_explanation": True,
                        "created_at": datetime.utcnow().isoformat(),
                    },
                )
        else:
            if conversation:
                agent_conversation_service.update_memory(
                    db=db,
                    conversation=conversation,
                    last_topic=topic,
                    last_knowledge_point_ids=[],
                    clear_pending=True,
                )

        return {
            "intent": "qa_answer",
            "type": "answer",
            "text": answer_text,
            "qa_id": result["qa_id"],
            "document": None,
            "agent_steps": result.get("agent_steps", []),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            "related_knowledge_point_ids": related_ids,
        }

    # ========== 练习题生成 ==========

    def handle_generate_exercise(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        message: str,
        conversation=None,
        fallback_knowledge_point_id: int | None = None,
    ) -> dict:
        question_count = self.extract_question_count(message)
        point = self.match_knowledge_point(db, course_id, message)

        # 本轮未匹配时，从上下文恢复
        if not point and fallback_knowledge_point_id:
            point = (
                db.query(KnowledgePoint)
                .filter(
                    KnowledgePoint.id == fallback_knowledge_point_id,
                    KnowledgePoint.course_id == course_id,
                )
                .first()
            )

        if not point:
            return {
                "intent": "generate_exercise_document",
                "type": "clarification",
                "text": "我需要知道你想生成哪个知识点的练习题，例如：生成5道有关栈的练习题。",
                "qa_id": None,
                "document": None,
                "agent_steps": [
                    {
                        "title": "需要补充信息",
                        "detail": "未识别到明确知识点",
                        "status": "need_user_input",
                    }
                ],
                "retrieved_chunks": [],
            }

        include_answer = self.extract_include_answer(message)
        include_explanation = self.extract_include_explanation(message)

        # 没有答案时也不应输出解析
        if not include_answer:
            include_explanation = False

        doc, steps = exercise_agent_service.generate(
            db=db,
            user_id=student_id,
            course_id=course_id,
            prompt=message,
            question_count=question_count,
            knowledge_point_id=point.id,
            difficulty="adaptive",
            include_answer=include_answer,
            include_explanation=include_explanation,
        )

        # 更新会话记忆
        if conversation:
            agent_conversation_service.update_memory(
                db=db,
                conversation=conversation,
                last_topic=point.name,
                last_knowledge_point_ids=[point.id],
                clear_pending=True,
            )

        return {
            "intent": "generate_exercise_document",
            "type": "document",
            "text": f"已生成《{doc.file_name}》。",
            "qa_id": None,
            "document": {
                "id": doc.id,
                "title": doc.title,
                "file_name": doc.file_name,
                "preview_content": doc.preview_content,
                "download_url": f"/api/exercise-generation/{doc.id}/download",
            },
            "agent_steps": steps,
            "retrieved_chunks": [],
        }

    # ========== 参数抽取 ==========

    def extract_question_count(self, message: str, default: int = 5) -> int:
        match = re.search(r"(\d+)\s*[道个题]", message)
        if match:
            return max(1, min(int(match.group(1)), 20))

        chinese_map = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        for word, count in chinese_map.items():
            if f"{word}道" in message or f"{word}个" in message or f"{word}题" in message:
                return count

        return default

    def match_knowledge_point(self, db: Session, course_id: int, message: str):
        points = db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id).all()
        for point in points:
            if point.name in message:
                return point
        return None

    def extract_include_answer(self, message: str) -> bool:
        negative_patterns = ["不要答案", "不带答案", "不需要答案", "隐藏答案", "只要题目"]
        return not any(pattern in message for pattern in negative_patterns)

    def extract_include_explanation(self, message: str) -> bool:
        negative_patterns = ["不要解析", "不带解析", "不需要解析", "无解析"]
        if any(pattern in message for pattern in negative_patterns):
            return False
        return True

    # ========== 工具方法 ==========

    def get_knowledge_point_names(self, db: Session, knowledge_point_ids: list[int]) -> list[str]:
        if not knowledge_point_ids:
            return []
        points = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(knowledge_point_ids)).all()
        return [point.name for point in points]

    def extract_topic_from_message(self, message: str) -> str:
        """从消息中提取话题关键词（简单 fallback）"""
        common_terms = [
            "栈", "队列", "链表", "数组", "树", "二叉树", "图", "排序",
            "查找", "递归", "哈希", "堆", "串", "字符串", "时间复杂度",
            "空间复杂度", "动态规划", "贪心", "回溯", "分治",
        ]
        for term in common_terms:
            if term in message:
                return term
        return message[:20] if len(message) > 20 else message


agent_router_service = AgentRouterService()
