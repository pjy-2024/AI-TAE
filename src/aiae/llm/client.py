"""LLM 客户端：对 OpenAI 兼容 chat/completions 的最小封装（契约先行）。

设计要点（对应项目说明书 §7 问题 2「429 怎么处理」）：
- 只重试「可安全重试」的错误：HTTP 429（限流）、5xx（服务端）、连接/超时；
  不重试 400/401/403/404/422 等「重试也白搭」的请求错误。
- 429 优先遵循响应头 Retry-After；没有则按指数退避 + 抖动（jitter）等待，
  避免大量客户端同时重试造成「重试风暴」。
- 为什么不能盲目重试：① 请求类错误重试只会重复计费/浪费配额；
  ② 无抖动会让所有失败请求在同一时刻打爆服务端。

实现说明：真实 HTTP 调用在任务 2（V1 骨架跑通）接入 openai SDK；
本文件先固定接口签名与异常语义，供上层 generator 按契约编程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiae.config import LLMConfig


class LLMError(Exception):
    """LLM 调用失败基类。"""


class LLMRetryableError(LLMError):
    """可安全重试：429 限流 / 5xx 服务端错误 / 连接与超时。"""


class LLMNonRetryableError(LLMError):
    """不可重试：请求本身错误（400/401/403/404/422 等），或超出重试上限后的最终失败。"""


@dataclass
class LLMResponse:
    """一次成功的 LLM 调用结果（含成本/延迟记账字段）。"""

    content: str  # 模型返回文本（json_mode=True 时为合法 JSON 字符串）
    usage: dict[str, int] = field(default_factory=dict)  # {"prompt_tokens":..,"completion_tokens":..}
    latency_s: float = 0.0  # 单次调用耗时
    retries: int = 0  # 实际重试次数（0 = 一次成功）


class LLMClient:
    """OpenAI 兼容 chat/completions 客户端。

    骨架阶段仅定义契约；任务 2 实现 complete()，内部策略见模块 docstring 与设计文档 §6。
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        json_mode: bool | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """发送一轮对话并返回结构化结果。

        json_mode=True 时要求模型只输出合法 JSON（provider 支持时传 response_format）。
        重试策略：429/5xx -> 指数退避 + 抖动，最多 config.max_retries 次；
        其余错误直接抛 LLMNonRetryableError。
        """
        raise NotImplementedError("任务 2（V1 跑通）实现：接入 openai SDK + 重试策略。")