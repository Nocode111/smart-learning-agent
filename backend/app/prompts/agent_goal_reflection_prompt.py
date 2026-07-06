"""
长期目标执行复盘 Prompt（文档 Section 19.2）
"""

AGENT_GOAL_REFLECTION_SYSTEM_PROMPT = """你是智慧学习辅助系统中的执行复盘器。

你的任务是判断目标计划中的某一步是否完成，以及是否需要重试、补救或调整计划。

请根据：
1. 目标信息
2. 当前步骤
3. 工具执行结果
4. 学生画像变化
5. 练习结果（如有）

输出严格 JSON（不要输出 Markdown 代码块）：
{
  "is_success": true,
  "quality_score": 0.0,
  "summary": "复盘总结",
  "issues": [
    {
      "type": "weak_point",
      "message": "具体问题描述"
    }
  ],
  "next_action": "continue",
  "suggested_step_patch": null,
  "suggested_new_steps": []
}

next_action 枚举：
- continue：继续执行后续步骤
- retry_step：当前步骤需要重试
- insert_remedial_step：插入补救步骤
- replan_needed：目标计划需要重新规划
- blocked_need_user：需要用户补充信息
- complete_goal：目标可以完成

判断原则：
1. 工具执行成功且结果有效 -> is_success = true, next_action = continue
2. 工具执行失败但可重试 -> is_success = false, next_action = retry_step
3. 学生明显薄弱，需要插入补救步骤 -> next_action = insert_remedial_step
4. 大量知识点仍薄弱，计划不匹配 -> next_action = replan_needed
5. 所有步骤已完成 -> next_action = complete_goal

quality_score 评分标准（0-1）：
- 0.9-1.0：高质量完成，学生表现出明显进步
- 0.7-0.89：基本完成，有小问题
- 0.5-0.69：勉强完成，存在明显不足
- 0.3-0.49：完成质量差
- 0-0.29：基本无效
"""

AGENT_GOAL_REFLECTION_USER_PROMPT_TEMPLATE = """请对以下步骤执行结果进行复盘。

## 目标信息
标题：{goal_title}
描述：{goal_text}
目标分数：{target_score}
当前进度：{progress_percent}%

## 当前步骤
序号：第 {step_order} 步
标题：{step_title}
描述：{step_description}
类型：{step_type}
预期结果：{expected_outcome}

## 工具执行结果
状态：{run_status}
工具名称：{tool_name}
{tool_result_text}

## 学生画像变化
{profile_before}
{profile_after}

## 练习结果（如有）
{practice_result}

请输出严格 JSON 格式的复盘结果。"""


def build_goal_reflection_prompt(
    goal_title: str,
    goal_text: str,
    target_score: float | None,
    progress_percent: float,
    step_order: int,
    step_title: str,
    step_description: str | None,
    step_type: str,
    expected_outcome: str | None,
    run_status: str,
    tool_name: str | None,
    tool_result_text: str,
    profile_before: str,
    profile_after: str,
    practice_result: str,
) -> list[dict]:
    """构建复盘 prompt 消息列表"""
    user_content = AGENT_GOAL_REFLECTION_USER_PROMPT_TEMPLATE.format(
        goal_title=goal_title,
        goal_text=goal_text,
        target_score=target_score or "未设定",
        progress_percent=progress_percent,
        step_order=step_order,
        step_title=step_title,
        step_description=step_description or "",
        step_type=step_type,
        expected_outcome=expected_outcome or "",
        run_status=run_status,
        tool_name=tool_name or "无",
        tool_result_text=tool_result_text,
        profile_before=profile_before,
        profile_after=profile_after,
        practice_result=practice_result,
    )

    return [
        {"role": "system", "content": AGENT_GOAL_REFLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
