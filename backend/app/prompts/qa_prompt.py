def build_qa_prompt(
    profile: dict,
    retrieved_chunks: list[dict],
    question: str,
    conversation_context: list[dict] | None = None,
) -> list[dict]:
    # 按来源分组（文档 Section 16）
    attachment_chunks = [c for c in retrieved_chunks if c.get("metadata", {}).get("source_type") == "conversation_attachment"]
    course_chunks = [c for c in retrieved_chunks if c.get("metadata", {}).get("source_type") != "conversation_attachment"]

    context_parts = []
    if attachment_chunks:
        attachment_text = "\n\n".join(
            [f"附件资料{index + 1}（来源：{c.get('metadata', {}).get('title', '未知附件')}）: {c['content']}"
             for index, c in enumerate(attachment_chunks)]
        )
        context_parts.append(f"【当前对话附件资料】\n{attachment_text}")

    if course_chunks:
        course_text = "\n\n".join(
            [f"课程资料{index + 1}: {c['content']}" for index, c in enumerate(course_chunks)]
        )
        context_parts.append(f"【课程资料库】\n{course_text}")

    context = "\n\n".join(context_parts) if context_parts else "（无相关资料）"

    return [
        {
            "role": "system",
            "content": (
                "你是一个智慧学习辅助系统中的 AI 学习助手。"
                "你需要基于课程资料、学生画像和学生问题进行个性化答疑。"
                "回答要准确、清晰、适合学生当前水平。"
                "如果资料不足，请说明不确定，不要编造。"
                "\n\n"
                "你会收到两类资料片段：\n"
                "1. conversation_attachment：当前用户在本次对话中上传的附件。\n"
                "2. learning_resource：课程资料库中的资料。\n\n"
                "如果用户明确说「这个文档」「刚上传的文件」「附件」「PDF」「根据文档」，你必须优先依据 conversation_attachment 回答。\n"
                "如果附件资料不足以回答，请明确说明「当前附件中没有找到足够信息」，再补充课程知识或通用解释。\n"
                "不要把课程资料误说成用户刚上传的附件。\n"
                "不要把其他会话、其他用户、其他课程的附件当作当前附件。\n"
                "\n"
                "如果没有检索到任何资料，你可以基于通用学科知识回答。"
                "但需要保持谨慎，不要声称答案来自课程资料。"
                "\n\n"
                "如果你在回答末尾想邀请学生继续操作，请优先使用以下固定句式之一：\n"
                "1. 需要我继续讲解这个知识点吗？\n"
                "2. 需要我用代码示例演示一下吗？\n"
                "3. 需要我帮你做一个小练习吗？\n"
                "4. 需要我基于这个知识点给你出几道练习题吗？\n"
                "\n"
                "不要使用含糊不清的邀请，例如「要不要试试？」。"
            ),
        },
        {
            "role": "user",
            "content": f"""
【最近对话上下文】
{_format_conversation_context(conversation_context)}

【学生画像】
整体水平：{profile.get("overall_level", "未知")}
薄弱知识点：{profile.get("weak_points", [])}
当前知识点掌握情况：{profile.get("knowledge_mastery", [])}
画像与长期记忆补充：{profile.get("profile_memory_context_text", "无")}

{context}

【学生问题】
{question}

【回答要求】
1. 先直接回答问题。
2. 使用学生能理解的语言。
3. 如果学生基础薄弱，要举一个简单例子。
4. 最后给出一个下一步学习建议。
5. 不要脱离资料胡编。
6. 如果问题明确指向附件，优先基于附件内容回答。
7. 掌握度、薄弱点和整体水平以学习画像为准；长期记忆只作为偏好、近期学习事件和定性状态补充。
""",
        },
    ]


def _format_conversation_context(conversation_context: list[dict] | None) -> str:
    if not conversation_context:
        return "无"

    lines = []
    for item in conversation_context[-6:]:
        role = "学生" if item.get("role") == "user" else "AI"
        content = (item.get("content") or "").strip()
        if content:
            lines.append(f"{role}：{content[:500]}")
    return "\n".join(lines) if lines else "无"
