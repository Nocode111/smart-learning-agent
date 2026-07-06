"""
对话式练习题目生成 Prompt — 让 LLM 输出严格 JSON。

文档参考：docs/对话式练习Session方案_详细技术实现文档.md Section 11
"""

INLINE_PRACTICE_SYSTEM_PROMPT = """你是智慧学习辅助系统中的练习题生成器。
你只负责生成结构化练习题 JSON。
不要输出 Markdown。
不要输出 JSON 之外的任何文字。
题目必须围绕给定课程知识点。
如果要求不展示答案和解析，也仍然必须在 JSON 内部生成 correct_answer 和 explanation，供系统批改使用。"""

INLINE_PRACTICE_USER_PROMPT_TEMPLATE = """请基于以下信息生成 {question_count} 道单选题。

课程 ID：{course_id}
练习主题：{topic}
知识点：{knowledge_point_names}
学生画像：{profile}
课程资料片段：{retrieved_chunks}

要求：
1. 只生成单选题。
2. 每题必须有 A/B/C/D 四个选项。
3. correct_answer 必须是 A/B/C/D 之一。
4. explanation 必须解释正确答案为什么正确。
5. 不要把答案直接展示给学生，但 JSON 中必须包含答案。
6. 输出必须是严格 JSON。

JSON 格式：
{{
  "questions": [
    {{
      "question_no": 1,
      "question_type": "single_choice",
      "stem": "题干",
      "options": {{
        "A": "选项 A",
        "B": "选项 B",
        "C": "选项 C",
        "D": "选项 D"
      }},
      "correct_answer": "B",
      "explanation": "解析",
      "difficulty": "基础"
    }}
  ]
}}"""


import json


def parse_json_object(text: str) -> dict:
    """解析 LLM 输出的 JSON，失败时尝试截取 { 到 } 再解析（文档 Section 11.1）"""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def validate_question(question: dict, expected_no: int) -> list[str]:
    """校验单道题结构（文档 Section 11.2），返回错误列表"""
    errors = []
    if not question.get("stem"):
        errors.append(f"第{expected_no}题 stem 为空")
    options = question.get("options") or {}
    for key in ["A", "B", "C", "D"]:
        if key not in options:
            errors.append(f"第{expected_no}题缺少选项 {key}")
    correct = question.get("correct_answer", "")
    if correct.upper() not in ["A", "B", "C", "D"]:
        errors.append(f"第{expected_no}题 correct_answer 无效: {correct}")
    return errors


def validate_questions(questions: list[dict]) -> list[str]:
    """校验全部题目，返回错误列表"""
    errors = []
    for i, q in enumerate(questions):
        expected_no = i + 1
        if q.get("question_no") != expected_no:
            errors.append(f"题目序号不连续：期望{expected_no}，实际{q.get('question_no')}")
        errors.extend(validate_question(q, expected_no))
    return errors
