"""CapturingLLM — 包装真实 LLM，透明记录所有 prompt/response 交互。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.agent.perception import _clean_llm_output


@dataclass
class LLMInteraction:
    """单次 LLM 交互记录。"""
    prompt: str
    raw_response: str
    cleaned_response: str
    timestamp: float = field(default_factory=time.time)


class CapturingLLM:
    """包装真实 LLM，记录所有 ainvoke 调用的 prompt 和 response。

    对外暴露与 LangChain ChatModel 相同的 ainvoke 接口，
    SlotFillingEngine 通过 _invoke_llm 无感知地使用本类。
    """

    def __init__(self, real_llm):
        self.real_llm = real_llm
        self.interactions: list[LLMInteraction] = []

    async def ainvoke(self, prompt) -> object:
        response = await self.real_llm.ainvoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        self.interactions.append(LLMInteraction(
            prompt=str(prompt),
            raw_response=raw,
            cleaned_response=_clean_llm_output(raw),
        ))
        return response

    def clear(self):
        """清空所有记录。"""
        self.interactions.clear()

    def pop_all(self) -> list[LLMInteraction]:
        """取出并清空所有交互记录。"""
        result = list(self.interactions)
        self.interactions.clear()
        return result

    def get_last(self) -> LLMInteraction | None:
        """获取最后一条交互。"""
        return self.interactions[-1] if self.interactions else None

    @property
    def call_count(self) -> int:
        return len(self.interactions)
