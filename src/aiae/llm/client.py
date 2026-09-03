"""LLM 客户端：对 OpenAI 兼容 chat/completions 的最小封装。

设计要点（对应 docs/v1-technical-design.md §6）：
- 只重试「可安全重试」的错误：429（限流）、5xx（服务端）、连接/超时；
  不重试 400/401/403/404/422 等「重试也白搭」的请求错误（重试 = 重复计费）。
- 429 优先遵循响应头 Retry-After；没有则指数退避 + 抖动（jitter），
  避免大量客户端同时重试造成「重试风暴」。
- 为什么关掉 openai SDK 自带重试（max_retries=0）自己写：SDK 重试是黑盒——
  不可见、不可记账、不走本决策表；自己实现则每次重试可见（LLMResponse.retries）
  且可单测。
- 记账内建：每次调用返回 usage / latency_s / retries，是 metrics 成本与
  「生成 100 条用例花多少钱」面试题的数据来源。

安全/透明原则：只 catch openai 自己的异常并分类；我们代码自身的 bug 不兜底，
让异常冒泡暴露，而不是被「重试」掩盖。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

import openai

from aiae.config import LLMConfig

# 指数退避参数（决策表见 docs/v1-technical-design.md §6）
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0
_JITTER_SECONDS = 1.0


class LLMError(Exception):
    """LLM 调用失败基类。"""


class LLMRetryableError(LLMError):
    """可安全重试：429 限流 / 5xx 服务端错误 / 连接与超时 / 未知 openai 错误。

    retry_after：服务端 Retry-After 指示的秒数（None = 未知，走指数退避）。
    """

    def __init__(self, message: str = "", *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMNonRetryableError(LLMError):
    """不可重试：请求本身错误（400/401/403/404/422 等），或超出重试上限后的最终失败。"""


@dataclass
class LLMResponse:
    """一次成功的 LLM 调用结果（含成本/延迟记账字段）。"""

    content: str  # 模型返回文本（json_mode=True 时为合法 JSON 字符串）
    usage: dict[str, int] = field(default_factory=dict)  # {"prompt_tokens":..,"completion_tokens":..}
    latency_s: float = 0.0  # 单次调用耗时
    retries: int = 0  # 实际重试次数（0 = 一次成功）


# ---------------------------------------------------------------- 重试时间计算

def _parse_retry_after(value: Any) -> float | None:
    """解析 Retry-After 响应头（秒数）。

    Retry-After 也可能是 HTTP-date 形式（少见），解析失败返回 None ——
    交由指数退避兜底，不让一个「看不懂的头」卡死重试。
    """
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _backoff_seconds(attempt: int, retry_after: float | None) -> float:
    """第 attempt 次重试前的等待秒数：Retry-After 优先，否则指数退避（封顶）。

    公式：min(cap, base * 2**attempt)，attempt 从 0 开始（1s, 2s, 4s, ...）。
    抖动在调用侧叠加（sleep(wait + uniform(0, jitter))）。
    """
    if retry_after is not None:
        return retry_after
    return min(_BACKOFF_CAP_SECONDS, _BACKOFF_BASE_SECONDS * (2**attempt))


# ---------------------------------------------------------------- 客户端

class LLMClient:
    """OpenAI 兼容 chat/completions 客户端（429/5xx 退避重试 + 记账）。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        # max_retries=0：关掉 SDK 隐式重试，改由 complete() 显式控制（可见/可记账/可测）
        # api_key 为空时用占位符：openai 3.x 对空 key 在构造期就抛 Missing credentials，
        # 而我们希望「未配置」延迟到 complete() 统一报错（便于无 key 阶段注入 fake 测试）。
        self._openai = openai.OpenAI(
            api_key=config.api_key or "__unset__",
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=0,
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        json_mode: bool | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """发送一轮对话并返回结构化结果。

        重试策略：LLMRetryableError -> Retry-After/指数退避 + 抖动，
        最多 config.max_retries 次；耗尽后抛 LLMNonRetryableError（最终失败）。
        """
        if not self.config.is_configured():
            raise LLMNonRetryableError("未配置 AITAE_LLM_API_KEY（写入项目 .env），无法调用 LLM")

        temperature = self.config.temperature if temperature is None else temperature
        json_mode = self.config.json_mode if json_mode is None else json_mode
        max_tokens = self.config.max_tokens if max_tokens is None else max_tokens

        retries = 0
        while True:
            try:
                response = self._call_once(
                    messages,
                    temperature=temperature,
                    json_mode=json_mode,
                    max_tokens=max_tokens,
                )
                response.retries = retries  # _call_once 不知道外层重试了几次，这里补记账
                return response
            except LLMRetryableError as exc:
                if retries >= self.config.max_retries:
                    raise LLMNonRetryableError(
                        f"LLM 调用重试 {retries} 次后仍失败（达到 max_retries="
                        f"{self.config.max_retries}）：{exc}"
                    ) from exc
                wait = _backoff_seconds(retries, exc.retry_after)
                time.sleep(wait + random.uniform(0, _JITTER_SECONDS))
                retries += 1

    def _call_once(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        json_mode: bool,
        max_tokens: int | None,
    ) -> LLMResponse:
        """真正的一次 HTTP 调用 + openai 异常分类（retries 由外层 complete 记账）。"""
        started = time.monotonic()
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "timeout": self.config.timeout_seconds,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = self._openai.chat.completions.create(**kwargs)
        except openai.RateLimitError as exc:  # HTTP 429：优先听服务端的 Retry-After
            headers = getattr(getattr(exc, "response", None), "headers", {})
            raise LLMRetryableError(
                "429 限流", retry_after=_parse_retry_after(headers.get("retry-after"))
            ) from exc
        except openai.APIStatusError as exc:
            if 500 <= exc.status_code < 600:
                raise LLMRetryableError(f"服务端错误 HTTP {exc.status_code}") from exc
            # 400/401/403/404/422...：请求本身错误，重试只会重复计费
            raise LLMNonRetryableError(
                f"请求错误 HTTP {exc.status_code}：{getattr(exc, 'message', '')}"
            ) from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise LLMRetryableError(f"连接/超时错误：{exc}") from exc
        except openai.OpenAIError as exc:
            # 其余 openai 错误（如响应解析异常）保守归可重试，max_retries 上限兜底
            raise LLMRetryableError(f"openai 库错误：{exc}") from exc

        latency = time.monotonic() - started
        try:
            choice = resp.choices[0]
            content = getattr(choice.message, "content", None) or ""
            finish_reason = getattr(choice, "finish_reason", None) or ""
        except (AttributeError, IndexError) as exc:
            raise LLMNonRetryableError(f"LLM 响应结构异常（无 choices/message）：{exc}") from exc

        if finish_reason == "length":
            # 输出被 max_tokens 截断：重试不会解决，只会重复计费 -> 直接报错提示调大
            raise LLMNonRetryableError(
                "LLM 输出因 max_tokens 截断（finish_reason=length），请调大 max_tokens 后重试"
            )

        return LLMResponse(
            content=content,
            usage=_extract_usage(getattr(resp, "usage", None)),
            latency_s=round(latency, 4),
            retries=0,  # 真实重试次数由 complete() 覆盖
        )


def _extract_usage(raw: Any) -> dict[str, int]:
    """从 openai 响应的 usage 字段提取 token 计数（兼容 dict / pydantic / 旧版属性）。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {k: int(v) for k, v in raw.items() if isinstance(v, (int, float))}
    if hasattr(raw, "model_dump"):  # pydantic 模型（新版 SDK）
        return _extract_usage(raw.model_dump())
    result: dict[str, int] = {}  # 旧版 CompletionUsage：属性访问
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(raw, key, None)
        if value is not None:
            result[key] = int(value)
    return result