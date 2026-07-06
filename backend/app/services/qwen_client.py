from openai import AsyncOpenAI, OpenAI
from app.config import settings


class QwenClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )

    def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        completion = self.client.chat.completions.create(
            model=settings.qwen_chat_model,
            messages=messages,
            temperature=temperature if temperature is not None else settings.llm_temperature,
            timeout=settings.llm_chat_timeout_seconds,
        )
        return completion.choices[0].message.content

    def embedding(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model=settings.qwen_embedding_model,
            input=text,
            timeout=settings.llm_embedding_timeout_seconds,
        )
        return response.data[0].embedding


qwen_client = QwenClient()


# ── 二期：异步客户端（文档 Section 12） ──────────────────

class AsyncQwenClient:
    """异步千问客户端，支持流式 chat 和取消（文档 Section 12.1）"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )

    async def stream_chat(self, messages: list[dict], temperature: float | None = None):
        """流式生成，每次 yield 一个 token（文档 Section 12.1）"""
        stream = await self.client.chat.completions.create(
            model=settings.qwen_chat_model,
            messages=messages,
            temperature=temperature if temperature is not None else settings.llm_temperature,
            stream=True,
            timeout=settings.llm_chat_timeout_seconds,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta

    async def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        """非流式异步生成，拼接所有 token"""
        parts = []
        async for token in self.stream_chat(messages, temperature):
            parts.append(token)
        return "".join(parts)


async_qwen_client = AsyncQwenClient()
