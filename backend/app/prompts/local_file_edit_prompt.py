"""
本地文件修改 LLM Prompt（文档 Section 11.2）

让 LLM 按用户要求修改文件内容，输出严格 JSON。
"""

LOCAL_FILE_EDIT_SYSTEM_PROMPT = """你是一个受控文件内容修改助手。

你只能根据用户要求修改给定的文本内容。
你不能编造文件路径。
你不能输出命令。
你不能要求系统执行 shell、PowerShell、Python 或其他命令。
你不能删除用户未要求删除的大段内容。
你必须保留与修改要求无关的内容。

你必须输出严格 JSON，不要输出 Markdown，不要输出 JSON 之外的任何文字。

JSON 结构：
{
  "summary": "简短说明你改了什么",
  "modified_content": "修改后的完整文件内容"
}"""


def build_local_file_edit_prompt(file_name: str, instruction: str, original_text: str) -> list[dict]:
    """构建 LLM 文件修改 prompt（文档 Section 11.2）"""
    return [
        {"role": "system", "content": LOCAL_FILE_EDIT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"文件名：{file_name}\n"
                f"用户修改要求：{instruction}\n\n"
                "下面是原文件完整内容：\n"
                "<<<FILE_CONTENT_START>>>\n"
                f"{original_text}\n"
                "<<<FILE_CONTENT_END>>>"
            ),
        },
    ]
