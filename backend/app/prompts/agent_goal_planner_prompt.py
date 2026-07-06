"""
长期目标计划拆解 Prompt（文档 Section 19.1）
"""

AGENT_GOAL_PLANNER_SYSTEM_PROMPT = """你是智慧学习辅助系统中的长期目标规划器。

你的任务不是回答用户问题，而是把用户的长期学习目标拆解成可执行步骤。

输入包括：
1. 用户目标
2. 课程知识点
3. 学生画像
4. 薄弱点
5. 截止日期

要求：
1. 输出严格 JSON，不要输出 Markdown 代码块。
2. 步骤数量控制在 5 到 12 步。
3. 每个步骤必须包含 step_type、tool_name、tool_args。
4. tool_name 必须来自以下白名单：
   - qa_answer：知识点讲解答疑
   - generate_inline_practice：对话式练习
   - generate_exercise_document：生成练习文档
   - profile_check：检查学习画像
   - manual_task：用户线下任务
5. step_type 必须与 tool_name 对应：
   - qa_answer -> qa_explanation
   - generate_inline_practice -> inline_practice 或 diagnostic_quiz
   - generate_exercise_document -> exercise_document
   - profile_check -> profile_check
   - manual_task -> manual_task 或 review_summary
6. 第一步优先诊断当前水平（diagnostic_quiz 或 profile_check）。
7. 每 2 到 3 个学习步骤后安排练习或复盘。
8. 如果目标太模糊，生成一个 manual_task 类型步骤要求用户补充信息。
9. 计划必须结合截止时间，合理分配步骤。
10. target_knowledge_point_ids 必须是给定知识点 ID 的子集。
11. plan_summary 是展示给学生看的自然语言摘要，不能出现知识点 ID、步骤 ID、tool_name、step_type、英文工具名或 JSON 字段名。
12. plan_summary 中要使用中文表达，例如“诊断测验、知识讲解、对话练习、练习文档、阶段总结”，不要写 inline_practice、exercise_document、generate_inline_practice 等内部名称。

输出 JSON 格式：
{
  "plan_summary": "面向学生的计划总结文字，只写学习安排，不写内部 ID 或工具名",
  "steps": [
    {
      "step_order": 1,
      "title": "步骤标题",
      "description": "步骤详细描述",
      "step_type": "inline_practice",
      "tool_name": "generate_inline_practice",
      "tool_args": {
        "question_count": 5,
        "delivery_mode": "inline",
        "include_answer_on_display": false,
        "include_explanation_on_display": false
      },
      "target_knowledge_point_ids": [1, 2],
      "expected_outcome": "预期结果描述",
      "success_criteria": {
        "min_question_count": 5,
        "requires_practice_session": true
      },
      "estimated_minutes": 15
    }
  ]
}
"""

AGENT_GOAL_PLANNER_USER_PROMPT_TEMPLATE = """请为以下学习目标制定结构化学习计划。

## 用户目标
标题：{title}
描述：{goal_text}
目标分数：{target_score}
截止日期：{due_date}

## 课程知识点
{course_knowledge_points}

## 学生画像
- 整体水平：{overall_level}
- 知识点掌握情况：
{knowledge_mastery}

## 薄弱点
{weak_points}

## 诊断要求
{diagnostic_requirement}

请严格按照 JSON 格式输出计划。
注意：plan_summary 会直接展示给学生，必须使用自然中文，不要出现 ID、英文工具名、step_type 或 tool_name。"""


def build_goal_planner_prompt(
    title: str,
    goal_text: str,
    target_score: float | None,
    due_date: str | None,
    course_knowledge_points: str,
    overall_level: str,
    knowledge_mastery: str,
    weak_points: str,
    diagnostic_requirement: str | None = None,
) -> list[dict]:
    """构建计划拆解 prompt 消息列表"""
    diagnostic_text = diagnostic_requirement or "无特殊诊断要求。"
    user_content = AGENT_GOAL_PLANNER_USER_PROMPT_TEMPLATE.format(
        title=title,
        goal_text=goal_text,
        target_score=target_score or "未设定",
        due_date=due_date or "未设定",
        course_knowledge_points=course_knowledge_points,
        overall_level=overall_level,
        knowledge_mastery=knowledge_mastery,
        weak_points=weak_points,
        diagnostic_requirement=diagnostic_text,
    )

    return [
        {"role": "system", "content": AGENT_GOAL_PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ── 重新规划 Prompt（文档 Section 14.3） ─────────────────────

AGENT_GOAL_REPLAN_USER_PROMPT_TEMPLATE = """请为以下学习目标**重新规划**后续步骤。

## 用户目标
标题：{title}
描述：{goal_text}
目标分数：{target_score}
截止日期：{due_date}

## 课程知识点
{course_knowledge_points}

## 学生画像
- 整体水平：{overall_level}
- 知识点掌握情况：
{knowledge_mastery}

## 薄弱点
{weak_points}

## 已完成步骤（请勿重复）
{completed_steps}

## 失败或阻塞步骤
{failed_steps}

## 最近复盘
{recent_reflections}

## 重规划原因
{replan_reason}

请只为未完成部分生成后续步骤，不要重复已完成步骤。
请严格按照 JSON 格式输出计划。
注意：plan_summary 会直接展示给学生，必须使用自然中文，不要出现 ID、英文工具名、step_type 或 tool_name。"""


def build_goal_replan_prompt(
    title: str,
    goal_text: str,
    target_score: float | None,
    due_date: str | None,
    course_knowledge_points: str,
    overall_level: str,
    knowledge_mastery: str,
    weak_points: str,
    completed_steps: str,
    failed_steps: str,
    recent_reflections: str,
    replan_reason: str,
) -> list[dict]:
    """构建重新规划 prompt 消息列表"""
    user_content = AGENT_GOAL_REPLAN_USER_PROMPT_TEMPLATE.format(
        title=title,
        goal_text=goal_text,
        target_score=target_score or "未设定",
        due_date=due_date or "未设定",
        course_knowledge_points=course_knowledge_points,
        overall_level=overall_level,
        knowledge_mastery=knowledge_mastery,
        weak_points=weak_points,
        completed_steps=completed_steps,
        failed_steps=failed_steps,
        recent_reflections=recent_reflections,
        replan_reason=replan_reason,
    )

    return [
        {"role": "system", "content": AGENT_GOAL_PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
