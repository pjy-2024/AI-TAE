"""llm/client 单元测试：重试决策表 / 退避计算 / 记账（全程 mock，不烧钱不联网）。

测试不依赖真实 API Key 与网络：注入 fake openai 对象替换 client._openai，
让 create() 按剧本抛真实 openai 异常（openai 3.x vendored 了 httpx2，用它构造响应）
或返回成功，验证重试次数、退避时长、sleep 是否被调用、记账字段。
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx2
import openai
import pytest

import aiae.llm.client as llm_client
from aiae.config import LLMConfig
from aiae.llm.client import (
    LLMClient,
    LLMNonRetryableError,
    LLMResponse,
    _backoff_seconds,
    _parse_retry_after,
)

CONFIG = LLMConfig(api_key="sk-test-fake")


def _request():
    return httpx2.Request("POST", "http://test")


def _status_error(cls, status_code, **headers):
    return cls(
        "boom",
        response=httpx2.Response(status_code, headers=headers, request=_request()),
        body=None,
    )


def _ok_response(content='{"tests": []}', finish="stop", usage=None):
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason=finish,
    )
    if usage is None:
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


class _FakeCompletions:
    """按剧本表演 create()：依次弹出 behavior（异常或成功对象），并记录每次调用参数。"""

    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _make_client(behaviors, config=CONFIG):
    client = LLMClient(config)
    client._openai = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(behaviors)))
    return client


def _fake_sleep(monkeypatch):
    """替换 time.sleep 为记录器，返回 (sleep_calls, sleep_fn)。"""
    calls = []

    def sleep_fn(seconds):
        calls.append(seconds)

    monkeypatch.setattr(llm_client.time, "sleep", sleep_fn)
    return calls


# ---------------------------------------------------------------- 纯函数：退避计算

def test_backoff_exponential_with_cap():
    assert _backoff_seconds(0, None) == 1.0
    assert _backoff_seconds(1, None) == 2.0
    assert _backoff_seconds(2, None) == 4.0
    # 封顶：不随 attempt 无限增长
    assert _backoff_seconds(10, None) == llm_client._BACKOFF_CAP_SECONDS


def test_backoff_retry_after_preferred():
    # 服务端给了 Retry-After，就听它的，不走指数退避
    assert _backoff_seconds(0, 7.5) == 7.5
    assert _backoff_seconds(3, 7.5) == 7.5


def test_parse_retry_after():
    assert _parse_retry_after("2") == 2.0
    assert _parse_retry_after("2.5") == 2.5
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") is None  # HTTP-date 兜底退避
    assert _parse_retry_after("0") is None  # 非正数视为无效


# ---------------------------------------------------------------- complete：成功路径

def test_complete_success_no_retry(monkeypatch):
    sleeps = _fake_sleep(monkeypatch)
    client = _make_client([_ok_response(content='{"tests": []}')])
    resp = client.complete([{"role": "user", "content": "hi"}])
    assert isinstance(resp, LLMResponse)
    assert resp.content == '{"tests": []}'
    assert resp.retries == 0
    assert resp.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert resp.latency_s >= 0
    assert sleeps == []  # 一次成功不该 sleep


def test_complete_passes_kwargs(monkeypatch):
    _fake_sleep(monkeypatch)
    client = _make_client([_ok_response()])
    client.complete(
        [{"role": "user", "content": "hi"}],
        temperature=0.5,
        json_mode=True,
        max_tokens=100,
    )
    kwargs = client._openai.chat.completions.calls[0]
    assert kwargs["model"] == CONFIG.model
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["temperature"] == 0.5
    assert kwargs["max_tokens"] == 100
    assert kwargs["response_format"] == {"type": "json_object"}  # json_mode 生效


def test_complete_no_json_mode_when_disabled(monkeypatch):
    _fake_sleep(monkeypatch)
    client = _make_client([_ok_response()])
    client.complete([{"role": "user", "content": "hi"}], json_mode=False)
    kwargs = client._openai.chat.completions.calls[0]
    assert "response_format" not in kwargs


def test_complete_defaults_from_config(monkeypatch):
    _fake_sleep(monkeypatch)
    client = _make_client([_ok_response()])
    client.complete([{"role": "user", "content": "hi"}])  # 不传 temperature/json_mode/max_tokens
    kwargs = client._openai.chat.completions.calls[0]
    assert kwargs["temperature"] == CONFIG.temperature
    assert kwargs["response_format"] == {"type": "json_object"}  # config.json_mode 默认 True
    assert "max_tokens" not in kwargs  # config.max_tokens 为 None 时不带


# ---------------------------------------------------------------- complete：重试决策表

def test_complete_retries_on_429_retry_after(monkeypatch):
    sleeps = _fake_sleep(monkeypatch)
    behaviors = [
        _status_error(openai.RateLimitError, 429, **{"retry-after": "2"}),
        _ok_response(content="ok"),
    ]
    client = _make_client(behaviors)
    resp = client.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert resp.retries == 1
    assert len(sleeps) == 1
    # Retry-After=2 秒 + 抖动 [0,1) -> 睡眠落在 [2, 3)
    assert 2.0 <= sleeps[0] < 3.0


def test_complete_retries_on_5xx(monkeypatch):
    sleeps = _fake_sleep(monkeypatch)
    behaviors = [_status_error(openai.InternalServerError, 500), _ok_response()]
    client = _make_client(behaviors)
    resp = client.complete([{"role": "user", "content": "hi"}])
    assert resp.retries == 1
    assert 1.0 <= sleeps[0] < 2.0  # 无 Retry-After -> base * 2^0 = 1s + jitter


def test_complete_retries_on_connection_error(monkeypatch):
    _fake_sleep(monkeypatch)
    behaviors = [
        openai.APIConnectionError(message="conn failed", request=_request()),
        _ok_response(),
    ]
    client = _make_client(behaviors)
    resp = client.complete([{"role": "user", "content": "hi"}])
    assert resp.retries == 1


def test_complete_400_raises_immediately_no_sleep(monkeypatch):
    sleeps = _fake_sleep(monkeypatch)
    behaviors = [_status_error(openai.BadRequestError, 400)]
    client = _make_client(behaviors)
    with pytest.raises(LLMNonRetryableError, match="400"):
        client.complete([{"role": "user", "content": "hi"}])
    assert sleeps == []  # 请求类错误绝不重试、绝不 sleep


def test_complete_exhausts_retries_raises_final(monkeypatch):
    sleeps = _fake_sleep(monkeypatch)
    cfg = LLMConfig(api_key="sk-test-fake", max_retries=3)
    behaviors = [_status_error(openai.RateLimitError, 429)] * 4  # 第 4 次仍失败
    client = _make_client(behaviors, config=cfg)
    with pytest.raises(LLMNonRetryableError, match="max_retries"):
        client.complete([{"role": "user", "content": "hi"}])
    assert len(sleeps) == 3  # 只退避 3 次（达到上限即抛，不再多等一次）


def test_complete_requires_api_key(monkeypatch):
    sleeps = _fake_sleep(monkeypatch)
    client = _make_client([_ok_response()], config=LLMConfig(api_key=""))
    with pytest.raises(LLMNonRetryableError, match="API_KEY"):
        client.complete([{"role": "user", "content": "hi"}])
    assert sleeps == []
    assert client._openai.chat.completions.calls == []  # 压根没发请求


def test_complete_truncated_output_raises_non_retryable(monkeypatch):
    sleeps = _fake_sleep(monkeypatch)
    client = _make_client([_ok_response(content="partial", finish="length")])
    with pytest.raises(LLMNonRetryableError, match="max_tokens"):
        client.complete([{"role": "user", "content": "hi"}])
    assert sleeps == []  # 截断重试无用 -> 直接报错


def test_complete_usage_dict_variant(monkeypatch):
    _fake_sleep(monkeypatch)
    client = _make_client([_ok_response(usage={"prompt_tokens": 1, "completion_tokens": 2})])
    resp = client.complete([{"role": "user", "content": "hi"}])
    assert resp.usage == {"prompt_tokens": 1, "completion_tokens": 2}