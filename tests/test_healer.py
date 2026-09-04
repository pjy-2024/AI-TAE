"""healer 单元测试：KV 命中 / LLM 自愈 / 人工拒绝 / 建议无效重试（fake LLM+UI，不联网）。"""

from __future__ import annotations

import json

from aiae.healer import Healer, HealResult
from aiae.healer.ui import LocateResult
from aiae.kv import KVStore
from aiae.llm.client import LLMResponse
from aiae.rag import RAGStore


def _failure(locator="input[name=username]"):
    return {
        "error_type": "locator_not_found",
        "locator": locator,
        "page_title": "TodoAPP",
        "page_url": "http://127.0.0.1:8010/auth/login-page",
        "structure": [
            {"tag": "form", "id": "loginForm"},
            {"tag": "input", "name": "user_name", "type": "text"},
            {"tag": "input", "name": "password", "type": "password"},
            {"tag": "button", "text": "Login", "type": "submit"},
        ],
    }


class FakeUI:
    """页面验证替身：仅 input[name=user_name] 可定位成功。"""

    def __init__(self, ok_locators=("input[name=user_name]",)):
        self._ok = set(ok_locators)

    def try_locate(self, locator, **kw):
        return LocateResult(ok=locator in self._ok)


class FakeLLM:
    """按剧本返回 LLM 输出。"""

    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def complete(self, messages, **kw):
        self.calls.append(messages)
        c = self.contents.pop(0)
        if isinstance(c, Exception):
            raise c
        return LLMResponse(content=c)


def _healer(tmp_path, llm=None, confirm=None, kv=None, rag=None):
    kv = kv or KVStore(tmp_path / "kv")
    rag = rag or RAGStore(tmp_path / "rag")
    return Healer(kv=kv, rag=rag, llm=llm, confirm=confirm)


def test_kv_hit_skips_llm(tmp_path):
    kv = KVStore(tmp_path / "kv")
    # 预置一条已签名修复
    from aiae.healer.signature import make_signature
    sig = make_signature(error_type="locator_not_found", locator="input[name=username]",
                         page_title="TodoAPP", elements=_failure()["structure"])
    kv.put(sig, {"new_locator": "input[name=user_name]", "source": "kv"})
    llm = FakeLLM([])  # 不应被调用
    h = _healer(tmp_path, llm=llm, kv=kv, rag=RAGStore(tmp_path / "rag2"))
    result = h.heal(FakeUI(), _failure())
    assert result.outcome == "kv_hit"
    assert result.new_locator == "input[name=user_name]"
    assert llm.calls == []  # 零 LLM 调用


def test_llm_heal_and_write_back(tmp_path):
    llm = FakeLLM([json.dumps({"new_locator": "input[name=user_name]", "reasoning": "name 改了"})])
    h = _healer(tmp_path, llm=llm, confirm=lambda p: True)
    result = h.heal(FakeUI(), _failure())
    assert result.outcome == "healed"
    assert result.new_locator == "input[name=user_name]"
    assert result.source == "llm"          # RAG 无案例 -> 纯 llm
    # 写回：再 heal 一次应 KV 命中（零 LLM）
    llm2 = FakeLLM([])
    h2 = Healer(kv=h.kv, rag=h.rag, llm=llm2, confirm=lambda p: True)
    r2 = h2.heal(FakeUI(), _failure())
    assert r2.outcome == "kv_hit"
    assert llm2.calls == []


def test_rejected_does_not_write_back(tmp_path):
    llm = FakeLLM([json.dumps({"new_locator": "input[name=user_name]"})])
    h = _healer(tmp_path, llm=llm, confirm=lambda p: False)
    result = h.heal(FakeUI(), _failure())
    assert result.outcome == "rejected"
    assert h.kv.get(result.signature) is None   # 拒绝不写回


def test_llm_bad_locator_retries_then_succeeds(tmp_path):
    # 第一次给错选择器（验证失败）-> 反馈重试；第二次给对
    llm = FakeLLM([
        json.dumps({"new_locator": "input[name=wrong]"}),          # 页面上不存在
        json.dumps({"new_locator": "input[name=user_name]"}),      # 正确
    ])
    h = _healer(tmp_path, llm=llm, confirm=lambda p: True)
    result = h.heal(FakeUI(), _failure())
    assert result.outcome == "healed"
    assert result.attempts == 1
    # 第二次调用收到了「验证失败」反馈
    assert "验证失败" in llm.calls[1][-1]["content"]


def test_no_llm_and_no_kv_fails(tmp_path):
    h = _healer(tmp_path, llm=None, confirm=lambda p: True)
    result = h.heal(FakeUI(), _failure())
    assert result.outcome == "failed"
