def build_exercise_prompt(
    course_name: str,
    knowledge_point_name: str,
    question_count: int,
    difficulty: str,
    profile: dict,
    retrieved_chunks: list[dict],
    include_answer: bool = True,
    include_explanation: bool = True,
) -> list[dict]:
    context = "\n\n".join(
        [
            f"资料{index + 1}：{chunk['content']}"
            for index, chunk in enumerate(retrieved_chunks)
        ]
    )

    return [
        {
            "role": "system",
            "content": (
                "你是智慧学习辅助系统中的练习题生成 Agent。"
                "你需要基于课程资料和学生画像生成高质量练习题。"
                "题目必须与指定知识点强相关，不要编造课程范围外的内容。"
                "输出必须是 Markdown 格式。"
            ),
        },
        {
            "role": "user",
            "content": f"""
请为课程《{course_name}》生成一份专项练习题文档。

【知识点】
{knowledge_point_name}

【题目数量】
{question_count}

【难度要求】
{difficulty}

【学生画像】
整体水平：{profile.get("overall_level", "未知")}
薄弱知识点：{profile.get("weak_points", [])}
知识点掌握情况：{profile.get("knowledge_mastery", [])}

【课程资料】
{context}

【生成要求】
1. 输出 Markdown。
2. 标题格式：# {course_name}：{knowledge_point_name}专项练习题
3. 题目数量必须正好是 {question_count} 道。
4. 题型尽量多样，可以包含选择题、判断题、简答题、应用题。
5. 每道题必须包含题干。
6. {"每道题必须包含答案。" if include_answer else "不要输出答案。"}
7. {"每道题必须包含解析。" if include_explanation else "不要输出解析。"}
8. 题目应覆盖概念理解、基本操作、应用场景和易错点。
9. 不要输出与 {knowledge_point_name} 无关的题目。
10. 不要输出除 Markdown 文档之外的解释性废话。
""",
        },
    ]
