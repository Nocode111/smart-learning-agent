"""
RuleGate 规则门服务 — 高置信度规则预判，不是主判断器。

职责（文档 Section 11）：
1. 明确的确认/否定短语 + pending action
2. 明确的安全边界
3. 明确的命令式练习题生成
4. LLM 失败时的兜底

推荐顺序：RuleGate 高置信命中 → 直接执行；未命中 → LLMIntentRouter
"""

import re

from app.services.agent_memory_semantics_service import agent_memory_semantics_service


class AgentRuleGateService:
    """
    高置信度规则预判器。

    只处理"几乎不可能错"的场景，其余返回 None 交由 LLM 处理。
    这也作为 LLM 失败时的兜底。
    """

    # ── 确认/否定短语（文档 Section 11.3） ─────────────────────

    @staticmethod
    def is_affirmative(message: str) -> bool:
        normalized = (message or "").strip().lower().replace(" ", "")
        affirmative_words = [
            "需要", "要", "好的", "好", "可以", "行",
            "来", "来吧", "生成吧", "出吧", "给我出",
            "嗯", "嗯嗯", "开始吧", "继续", "是的", "对",
            "确认", "没问题", "ok", "yes", "好呀",
        ]
        return normalized in affirmative_words

    @staticmethod
    def is_negative(message: str) -> bool:
        normalized = (message or "").strip().lower().replace(" ", "")
        negative_words = [
            "不需要", "不用", "不要", "先不用", "算了", "暂时不用",
            "否", "不", "取消", "no", "不必",
        ]
        return normalized in negative_words

    # ── 练习题生成关键词 ──────────────────────────────────────

    @staticmethod
    def _has_exercise_keywords(message: str) -> bool:
        exercise_kw = ["练习题", "习题", "题目", "试题", "专项练习"]
        generate_kw = ["生成", "出", "帮我出", "整理", "做一份"]
        return any(k in message for k in exercise_kw) and any(k in message for k in generate_kw)

    # ── 系统身份关键词 ────────────────────────────────────────

    @staticmethod
    def _has_system_identity_keywords(message: str) -> bool:
        identity_kw = [
            "你是什么模型", "你是谁", "你能做什么", "你叫什么",
            "你是什么", "什么模型", "什么大模型",
            "你的能力", "你有哪些功能", "你可以做什么",
        ]
        return any(k in message for k in identity_kw)

    @staticmethod
    def _has_memory_recall_keywords(message: str) -> bool:
        return agent_memory_semantics_service.is_memory_recall_question(message)

    @staticmethod
    def _extract_memory_update_name(message: str) -> str | None:
        return agent_memory_semantics_service.extract_name_update(message)

    # ── 问候关键词 ────────────────────────────────────────────

    @staticmethod
    def _has_small_talk_keywords(message: str) -> bool:
        small_talk_kw = ["你好", "嗨", "hello", "hi", "在吗", "早上好", "晚上好"]
        normalized = (message or "").strip().lower()
        return normalized in small_talk_kw

    # ── 非学习请求关键词 ──────────────────────────────────────

    @staticmethod
    def _has_out_of_scope_keywords(message: str) -> bool:
        out_of_scope_kw = [
            "情书", "写诗", "写歌", "写小说", "写故事",
            "天气预报", "天气", "股票", "彩票",
            "帮我写作业", "代写", "替考",
        ]
        return any(k in message for k in out_of_scope_kw)

    # ── 学习目标创建关键词（文档 Section 10.1） ──────────────────

    @staticmethod
    def _has_learning_goal_keywords(message: str) -> bool:
        goal_words = ["学习计划", "复习计划", "学习目标", "帮我规划", "制定计划", "安排学习", "学习路线"]
        exam_words = ["期末", "考试", "考", "分", "及格", "通过", "掌握", "天", "周", "个月"]
        return any(w in message for w in goal_words) and any(w in message for w in exam_words)

    @staticmethod
    def _extract_target_score(message: str) -> int | None:
        """从消息中提取目标分数"""
        import re
        # 匹配 "XX分" 模式
        match = re.search(r'(\d+)\s*分', message)
        if match:
            score = int(match.group(1))
            if 0 <= score <= 100:
                return score
        # 关键词映射
        if any(k in message for k in ["及格", "过线"]):
            return 60
        if any(k in message for k in ["优秀", "高分"]):
            return 85
        return None

    @staticmethod
    def _extract_duration_days(message: str) -> int | None:
        """从消息中提取学习周期天数"""
        import re
        # 匹配 "30天" "三十天" "两周" "一个月" 等
        match = re.search(r'(\d+)\s*天', message)
        if match:
            return int(match.group(1))
        match = re.search(r'(\d+)\s*周', message)
        if match:
            return int(match.group(1)) * 7
        match = re.search(r'(\d+)\s*个?月', message)
        if match:
            return int(match.group(1)) * 30
        if "两周" in message:
            return 14
        if "一个月" in message:
            return 30
        return None

    @staticmethod
    def _extract_course_name_hint(message: str) -> str | None:
        """从消息中简单提取课程名提示"""
        import re
        # 匹配 "XX课程" 或 "XX课"
        match = re.search(r'[一-龥]+(?:课程|课)', message)
        if match:
            name = match.group(0)
            # 去掉 "课程"/"课" 后缀
            for suffix in ["课程", "课"]:
                if name.endswith(suffix):
                    return name[:-len(suffix)]
            return name
        return None

    # ── 本地文件修改关键词（文档 Section 13.4） ──────────────────

    # ── 继续推进目标关键词（文档 Section 20.1） ──────────────────

    @staticmethod
    def _has_continue_goal_keywords(message: str) -> bool:
        continue_words = ["继续推进", "帮我推进", "推进目标", "继续执行", "开始推进", "继续我的目标"]
        goal_words = ["目标", "计划", "学习计划", "期末", "复习"]
        has_continue = any(w in message for w in continue_words)
        has_goal = any(w in message for w in goal_words)
        return has_continue and has_goal

    @staticmethod
    def _extract_goal_title_hint(message: str) -> str | None:
        """从消息提取目标标题提示"""
        # 尝试匹配 "数据结构期末目标" 等模式
        patterns = [
            r'继续推进(?:我?的?)?(.+?)(?:目标|计划)',
            r'推进(.+?)(?:目标|计划)',
            r'(?:帮我)?(?:继续)?推进(.+?)(?:的)?(?:目标|计划|学习)',
        ]
        import re
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                hint = match.group(1).strip()
                if hint and len(hint) > 1:
                    return hint
        return None

    # ── 本地文件修改关键词（文档 Section 13.4） ──────────────────

    @staticmethod
    def _has_local_file_edit_keywords(message: str) -> bool:
        """检测是否包含本地文件修改相关关键词"""
        modify_words = ["修改", "改一下", "替换", "补充", "删除这一段", "新增", "改写"]
        file_words = ["文件", "文档", "md", "txt", "py", "笔记"]
        has_modify = any(k in message for k in modify_words)
        has_file = any(k in message for k in file_words)
        return has_modify and has_file

    @staticmethod
    def _extract_windows_path(message: str) -> str | None:
        """从消息中提取 Windows 绝对路径"""
        import re
        # 匹配 D:\xxx\file.md 或 C:\xxx\file.py 等
        match = re.search(r'[A-Za-z]:\\[^\s]+\.\w+', message)
        if match:
            return match.group(0)
        return None

    def _try_local_file_edit(self, message: str, context: dict) -> dict | None:
        """
        低置信度规则：识别明显本地文件修改请求，协助 LLM Router。

        只处理明显场景：路径 + 修改动词都存在。
        复杂语义交给 LLM Router。
        """
        file_path = self._extract_windows_path(message)

        if not file_path:
            return None

        # 有 Windows 绝对路径，再检查是否有修改意图
        modify_words = ["修改", "改一下", "替换", "补充", "删除这一段", "新增", "改写", "改成"]
        has_modify = any(k in message for k in modify_words)

        if not has_modify:
            return None

        # 提取修改要求（去掉路径部分）
        instruction = message.replace(file_path, "").strip()
        if not instruction:
            return None

        return {
            "is_learning_related": True,
            "domain": "learning",
            "intent": "local_file_edit_prepare",
            "confidence": 0.85,
            "refers_to_previous_message": False,
            "resolved_action": "local_file_edit_prepare",
            "topic": None,
            "knowledge_point_ids": [],
            "need_clarification": False,
            "clarification_question": None,
            "tool_name": "local_file_edit_prepare",
            "tool_args": {
                "file_path": file_path,
                "instruction": instruction,
            },
            "pending_action_update": None,
            "answer_strategy": "execute_tool",
            "reason": "用户明确要求修改本地文件并提供了路径",
            "source": "rule_gate",
        }

    # ================================================================
    # 主入口（文档 Section 11.3）
    # ================================================================

    def try_resolve(self, message: str, context: dict) -> dict | None:
        """
        尝试用高置信规则解析。

        返回 dict 包含路由信息，或 None 表示无法解析（交给 LLM）。
        """
        message = (message or "").strip()
        pending_action = context.get("pending_action")
        active_practice_session = context.get("active_practice_session")

        # ── 规则 0（最高优先）：active practice session + 作答语句 ──
        if active_practice_session or (pending_action and pending_action.get("type") == "inline_practice_waiting_answer"):
            # 取消练习
            if self._is_cancel_practice(message):
                return {
                    "is_learning_related": True,
                    "domain": "learning",
                    "intent": "cancel_pending_action",
                    "confidence": 1.0,
                    "refers_to_previous_message": True,
                    "resolved_action": "cancel_pending_action",
                    "topic": None,
                    "knowledge_point_ids": [],
                    "need_clarification": False,
                    "clarification_question": None,
                    "tool_name": "cancel_pending_action",
                    "tool_args": {
                        "session_id": active_practice_session.get("session_id") if active_practice_session else pending_action.get("session_id"),
                    },
                    "pending_action_update": None,
                    "answer_strategy": "execute_tool",
                    "reason": "用户取消当前对话式练习",
                    "source": "rule_gate",
                }

            # 作答语句识别
            answer_parsed = self._parse_practice_answer(message)
            if answer_parsed:
                session_id = active_practice_session.get("session_id") if active_practice_session else pending_action.get("session_id")
                return {
                    "is_learning_related": True,
                    "domain": "learning",
                    "intent": "grade_practice_answer",
                    "confidence": 1.0,
                    "refers_to_previous_message": True,
                    "resolved_action": "grade_practice_answer",
                    "topic": active_practice_session.get("topic") if active_practice_session else pending_action.get("topic"),
                    "knowledge_point_ids": active_practice_session.get("knowledge_point_ids") if active_practice_session else (pending_action.get("knowledge_point_ids") or []),
                    "need_clarification": False,
                    "clarification_question": None,
                    "tool_name": "grade_practice_answer",
                    "tool_args": {
                        "session_id": session_id,
                        "question_no": answer_parsed.get("question_no"),
                        "submitted_answer": answer_parsed.get("submitted_answer"),
                    },
                    "pending_action_update": None,
                    "answer_strategy": "execute_tool",
                    "reason": "用户提交当前对话式练习答案",
                    "source": "rule_gate",
                }

        # ── 规则：明确不要文档 → inline practice ──
        if self._is_inline_practice_request(message):
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "generate_inline_practice",
                "confidence": 0.98,
                "refers_to_previous_message": False,
                "resolved_action": "generate_inline_practice",
                "topic": self._extract_topic(message),
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "generate_inline_practice",
                "tool_args": {
                    "question_count": self.extract_question_count(message, default=5),
                    "delivery_mode": "inline",
                    "include_answer_on_display": False,
                    "include_explanation_on_display": False,
                    "grading_mode": "interactive",
                },
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "用户明确要求文字出题、不要文档",
                "source": "rule_gate",
            }

        if (
            pending_action
            and pending_action.get("type") == "clarify_exercise_count"
            and self.has_question_count(message)
        ):
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "generate_exercise_document",
                "confidence": 1.0,
                "refers_to_previous_message": True,
                "resolved_action": "generate_exercise_document",
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "generate_exercise_document",
                "tool_args": {
                    "topic": pending_action.get("topic"),
                    "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                    "question_count": self.extract_question_count(message),
                    **(pending_action.get("payload") or {}),
                },
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "用户补充了练习题数量",
                "source": "rule_gate",
            }

        # ── 规则 1：确认语 + pending_action ──
        if pending_action and self.is_affirmative(message):
            confirm_action = pending_action.get("confirm_action") or pending_action.get("confirm_intent")
            if pending_action.get("type") == "local_file_edit_confirmation":
                confirm_action = "local_file_edit_confirm"
            tool_args = {
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                **(pending_action.get("payload") or {}),
            }
            if pending_action.get("operation_uuid"):
                tool_args["operation_uuid"] = pending_action.get("operation_uuid")
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "confirm_previous_action",
                "confidence": 1.0,
                "refers_to_previous_message": True,
                "resolved_action": confirm_action,
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": confirm_action or "clarify",
                "tool_args": tool_args,
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": f"用户确认 pending_action[{pending_action.get('type')}]",
                "source": "rule_gate",
            }

        # ── 规则 2：否定语 + pending_action ──
        if pending_action and self.is_negative(message):
            negative_action = pending_action.get("negative_action") or pending_action.get("negative_intent") or "cancel_pending_action"
            if pending_action.get("type") == "local_file_edit_confirmation":
                negative_action = "local_file_edit_cancel"
            tool_args = {
                **(pending_action.get("payload") or {}),
            }
            if pending_action.get("operation_uuid"):
                tool_args["operation_uuid"] = pending_action.get("operation_uuid")
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "deny_previous_action",
                "confidence": 1.0,
                "refers_to_previous_message": True,
                "resolved_action": negative_action,
                "topic": None,
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": negative_action,
                "tool_args": tool_args,
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": f"用户取消 pending_action[{pending_action.get('type')}]",
                "source": "rule_gate",
            }

        # ── 规则 2.5：pending_action 为 clarify_learning_goal_course 时，用户回答课程名 ──
        if pending_action and pending_action.get("type") == "clarify_learning_goal_course":
            # 用户回复课程名，重新调用 create_learning_goal_from_chat
            original_tool_args = (pending_action.get("payload") or {}).get("tool_args") or {}
            merged_args = {**original_tool_args, "course_name": message}
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "create_learning_goal",
                "confidence": 0.95,
                "refers_to_previous_message": True,
                "resolved_action": "create_learning_goal_from_chat",
                "topic": None,
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "create_learning_goal_from_chat",
                "tool_args": merged_args,
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "用户补充了课程名称，继续创建学习目标",
                "source": "rule_gate",
            }

        # ── 规则 2.6：高置信学习目标创建关键词 ──
        if self._has_learning_goal_keywords(message):
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "create_learning_goal",
                "confidence": 0.9,
                "refers_to_previous_message": False,
                "resolved_action": "create_learning_goal_from_chat",
                "topic": self._extract_topic(message),
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "create_learning_goal_from_chat",
                "tool_args": {
                    "goal_text": message,
                    "target_score": self._extract_target_score(message),
                    "duration_days": self._extract_duration_days(message),
                    "course_name": self._extract_course_name_hint(message),
                    "target_topics": [],
                    "need_diagnostic": "auto",
                    "auto_generate_plan": True,
                    "auto_advance_first_step": False,
                },
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "用户明确要求创建学习计划或学习目标",
                "source": "rule_gate",
            }

        # ── 规则 2.7：高置信继续推进目标关键词 ──
        if self._has_continue_goal_keywords(message):
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "continue_learning_goal",
                "confidence": 0.9,
                "refers_to_previous_message": False,
                "resolved_action": "continue_learning_goal_loop",
                "topic": None,
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "continue_learning_goal_loop",
                "tool_args": {
                    "goal_id": None,
                    "goal_title_hint": self._extract_goal_title_hint(message),
                    "max_iterations": 3,
                    "auto_select_latest_goal": True,
                },
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "用户明确要求继续推进学习目标",
                "source": "rule_gate",
            }

        update_name = self._extract_memory_update_name(message)
        if update_name:
            return {
                "is_learning_related": False,
                "domain": "system_identity",
                "intent": "memory_update",
                "confidence": 0.98,
                "refers_to_previous_message": False,
                "resolved_action": "memory_update",
                "topic": None,
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "memory_update",
                "tool_args": {
                    "memory_type": "profile",
                    "memory_key": "name",
                    "value": update_name,
                },
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "用户明确更新自己的名字",
                "source": "rule_gate",
            }

        # ── 规则 3：明确的练习题生成命令 ──
        if self._has_exercise_keywords(message):
            return None  # 交给 LLM 更准确地提取参数（count、topic 等）

        # ── 规则 4：系统身份问题 ──
        if self._has_memory_recall_keywords(message):
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "memory_recall",
                "confidence": 0.98,
                "refers_to_previous_message": True,
                "resolved_action": "memory_recall",
                "topic": context.get("last_topic"),
                "knowledge_point_ids": context.get("last_knowledge_point_ids") or [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "memory_recall",
                "tool_args": {},
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "用户询问系统是否记得历史信息",
                "source": "rule_gate",
            }

        # ── 规则 4：系统身份问题 ──
        if self._has_system_identity_keywords(message):
            return {
                "is_learning_related": False,
                "domain": "system_identity",
                "intent": "system_identity",
                "confidence": 0.95,
                "refers_to_previous_message": False,
                "resolved_action": None,
                "topic": None,
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "system_identity",
                "tool_args": {},
                "pending_action_update": None,
                "answer_strategy": "brief_identity",
                "reason": "用户询问系统身份",
                "source": "rule_gate",
            }

        # ── 规则 5：普通问候 ──
        if self._has_small_talk_keywords(message):
            return {
                "is_learning_related": False,
                "domain": "small_talk",
                "intent": "small_talk",
                "confidence": 0.9,
                "refers_to_previous_message": False,
                "resolved_action": None,
                "topic": None,
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "small_talk",
                "tool_args": {},
                "pending_action_update": None,
                "answer_strategy": "brief_identity",
                "reason": "用户问候",
                "source": "rule_gate",
            }

        # ── 规则 6：明确的非学习请求 ──
        if self._has_out_of_scope_keywords(message):
            return {
                "is_learning_related": False,
                "domain": "out_of_scope",
                "intent": "out_of_scope",
                "confidence": 0.9,
                "refers_to_previous_message": False,
                "resolved_action": None,
                "topic": None,
                "knowledge_point_ids": [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_name": "out_of_scope",
                "tool_args": {"message": "该请求与学习辅助场景无关"},
                "pending_action_update": None,
                "answer_strategy": "boundary_response",
                "reason": "非学习请求",
                "source": "rule_gate",
            }

        # ── 规则 7：本地文件修改请求（文档 Section 13.4） ──
        local_file_result = self._try_local_file_edit(message, context)
        if local_file_result:
            return local_file_result

        # ── 无法解析，交给 LLM ──
        return None

    # ================================================================
    # LLM 失败时的兜底（文档 Section 11.4）
    # ================================================================

    def fallback_resolve(self, message: str, context: dict) -> dict:
        """
        LLM 失败后的兜底解析，至少保证系统不崩溃。
        比 try_resolve 更宽松的规则。
        """
        message = (message or "").strip()
        pending_action = context.get("pending_action")

        if (
            pending_action
            and pending_action.get("type") == "clarify_exercise_count"
            and self.has_question_count(message)
        ):
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "generate_exercise_document",
                "confidence": 0.9,
                "tool_name": "generate_exercise_document",
                "refers_to_previous_message": True,
                "resolved_action": "generate_exercise_document",
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_args": {
                    "topic": pending_action.get("topic"),
                    "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                    "question_count": self.extract_question_count(message),
                    **(pending_action.get("payload") or {}),
                },
                "pending_action_update": None,
                "answer_strategy": "execute_tool",
                "reason": "fallback: 用户补充了练习题数量",
                "source": "rule_gate_fallback",
            }

        # 有 pending_action + 任何短确认语 → 确认
        if pending_action and len(message) <= 10 and self.is_affirmative(message):
            confirm_action = pending_action.get("confirm_action") or pending_action.get("confirm_intent")
            if pending_action.get("type") == "local_file_edit_confirmation":
                confirm_action = "local_file_edit_confirm"
            tool_args = {
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                **(pending_action.get("payload") or {}),
            }
            if pending_action.get("operation_uuid"):
                tool_args["operation_uuid"] = pending_action.get("operation_uuid")
            return {
                "is_learning_related": True,
                "domain": "learning",
                "intent": "confirm_previous_action",
                "confidence": 0.8,
                "tool_name": confirm_action or "clarify",
                "refers_to_previous_message": True,
                "resolved_action": confirm_action,
                "topic": pending_action.get("topic"),
                "knowledge_point_ids": pending_action.get("knowledge_point_ids") or [],
                "need_clarification": False,
                "clarification_question": None,
                "tool_args": tool_args,
                "answer_strategy": "execute_tool",
                "reason": "fallback: 短确认语+pending_action",
                "source": "rule_gate_fallback",
            }

        # 兜底：澄清
        return {
            "is_learning_related": False,
            "domain": "ambiguous",
            "intent": "unknown",
            "confidence": 0.0,
            "tool_name": "clarify",
            "tool_args": {"original_message": message},
            "answer_strategy": "clarify",
            "reason": "fallback: 无法理解，需要澄清",
            "source": "rule_gate_fallback",
        }

    # ── 提取题目数量 ──────────────────────────────────────────

    @classmethod
    def has_question_count(cls, message: str) -> bool:
        return cls.extract_question_count(message, default=0) > 0

    @staticmethod
    def extract_question_count(message: str, default: int = 5) -> int:
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


    # ── 对话式练习相关辅助方法 ──────────────────────────────────

    @staticmethod
    def _is_cancel_practice(message: str) -> bool:
        """检测用户是否要取消练习"""
        cancel_kw = ["不做了", "取消练习", "先不练了", "不练了", "停止练习"]
        return any(k in message for k in cancel_kw)

    @staticmethod
    def _is_inline_practice_request(message: str) -> bool:
        """检测用户是否明确要求文字出题（不要文档）（文档 Section 14.2）"""
        has_exercise = any(k in message for k in ["题", "练习", "出"])
        no_document = any(k in message for k in [
            "不要文档", "不用文档", "不用出文档", "不要生成文档",
            "文字发", "直接发", "聊天里", "不用生成文件",
            "我答完", "你批改", "你判断", "帮我判断",
            "看我是否理解", "只需要用文字",
        ])
        return has_exercise and no_document

    @staticmethod
    def _parse_practice_answer(message: str) -> dict | None:
        """高置信解析练习作答语句（文档 Section 14.1）"""
        message = (message or "").strip()
        if not message:
            return None

        # 检测作答模式
        question_no = None
        submitted_answer = None

        # 匹配"第N题选X"模式
        for pattern in [r"第?\s*(\d+)\s*[题道]\s*[选]?\s*([A-Da-d])", r"第?\s*([一二两三四五六七八九十])\s*[题道]\s*[选]?\s*([A-Da-d])"]:
            match = re.search(pattern, message)
            if match:
                num_str = match.group(1)
                if num_str.isdigit():
                    question_no = int(num_str)
                else:
                    chinese_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                                   "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                    question_no = chinese_map.get(num_str)
                submitted_answer = match.group(2).upper()
                break

        # 匹配"选X"模式（无题号，但整体很简单）
        if not question_no and not submitted_answer:
            for pattern in [r"选\s*([A-Da-d])", r"我选\s*([A-Da-d])"]:
                match = re.search(pattern, message)
                if match:
                    submitted_answer = match.group(1).upper()
                    break

        # 纯 A/B/C/D
        if not submitted_answer and len(message) <= 2:
            match = re.match(r"^\s*([A-Da-d])\s*$", message)
            if match:
                submitted_answer = match.group(1).upper()

        if not submitted_answer:
            return None

        return {
            "question_no": question_no,
            "submitted_answer": submitted_answer,
        }

    @staticmethod
    def _extract_topic(message: str) -> str | None:
        """简单提取主题关键词"""
        # 尝试从"关于X"或"X的题"中提取
        for pattern in [r'关于\s*[《]?(\S+?)[》]?\s*[的]?', r'[《](\S+?)[》]']:
            match = re.search(pattern, message)
            if match:
                return match.group(1)
        return None


agent_rule_gate_service = AgentRuleGateService()
