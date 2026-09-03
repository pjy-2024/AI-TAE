"""LLM 调用封装：统一入口、429/5xx 退避重试、成本记账（用量记录）。

骨架阶段只定义接口与异常层次；实现细节见 client.py 与 docs/v1-technical-design.md §6。
"""

from aiae.llm.client import (
    LLMClient,
    LLMError,
    LLMNonRetryableError,
    LLMResponse,
    LLMRetryableError,
)

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMRetryableError",
    "LLMNonRetryableError",
    "LLMResponse",
]