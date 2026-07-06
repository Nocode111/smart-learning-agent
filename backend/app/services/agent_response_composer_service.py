"""
ResponseComposer 响应组装器 — 将工具执行结果转为前端统一响应。

文档参考：docs/LLM语义路由Agent最终架构_详细技术实现文档.md Section 15
"""


class AgentResponseComposerService:
    """
    响应组装器。

    职责：
    - 接收 tool_result + intent_result，组装统一前端响应
    - 决定 pending_action_update（不直接写数据库）
    - 附加 debug_intent（开发环境）
    - 不对接数据库
    """

    def compose(
        self,
        intent_result,       # IntentRouterResult
        tool_result: dict,
        conversation_id: int,
        include_debug: bool = False,
    ) -> dict:
        """
        组装最终返回前端的响应结构。

        统一结构（文档 Section 15.2）：
        {
            "conversation_id": int,
            "intent": str,
            "type": "answer" | "clarification" | "document",
            "text": str,
            "qa_id": int | None,
            "document": dict | None,
            "agent_steps": list[dict],
            "retrieved_chunks": list[dict],
            "pending_action": dict | None,    // 可选：返回给前端做快捷按钮
            "debug_intent": dict | None,      // 可选：开发调试
        }
        """
        response = {
            "conversation_id": conversation_id,
            "intent": intent_result.intent,
            "type": tool_result.get("type", "answer"),
            "text": tool_result.get("text", ""),
            "qa_id": tool_result.get("qa_id"),
            "document": tool_result.get("document"),
            "agent_steps": tool_result.get("agent_steps") or [],
            "retrieved_chunks": tool_result.get("retrieved_chunks") or [],
            "related_knowledge_point_ids": tool_result.get("related_knowledge_point_ids") or [],
            # 附加字段
            "pending_action_update": tool_result.get("pending_action_update"),
            "skip_reply_action_detection": tool_result.get("skip_reply_action_detection", False),
            # 对话式练习字段（文档 Section 17）
            "practice_session": tool_result.get("practice_session"),
            "practice_result": tool_result.get("practice_result"),
            # 附件引用（文档 Section 17.2）
            "attachments": tool_result.get("attachments") or [],
            # 本地文件修改预览（文档 Section 16.3）
            "local_file_operation": tool_result.get("local_file_operation"),
            # 学习目标创建（对话式目标创建阶段 Section 15）
            "learning_goal": tool_result.get("learning_goal"),
            "goal_plan": tool_result.get("goal_plan"),
            # 目标多轮自主推进循环（Section 22）
            "goal_loop": tool_result.get("goal_loop"),
        }

        # 返回 pending_action 给前端（文档 Section 19.3 可选快捷按钮）
        pending_action_update = tool_result.get("pending_action_update")
        if pending_action_update:
            response["pending_action"] = {
                "type": pending_action_update.get("type"),
                "assistant_question": pending_action_update.get("assistant_question"),
                "topic": pending_action_update.get("topic"),
            }

        # 调试信息（文档 Section 19.2）
        if include_debug:
            response["debug_intent"] = {
                "domain": intent_result.domain,
                "intent": intent_result.intent,
                "tool_name": intent_result.tool_name,
                "confidence": intent_result.confidence,
                "refers_to_previous_message": intent_result.refers_to_previous_message,
                "reason": intent_result.reason,
            }

        return response


agent_response_composer_service = AgentResponseComposerService()
