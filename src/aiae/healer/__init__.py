"""V2：UI 失败自愈编排。

流程：失败捕获 -> 错误签名 -> ① KV 缓存查（完全命中，零 LLM）-> ② RAG 查（相似案例）
-> ③ LLM 看新页面结构给修复建议 -> ④ 人工确认 -> ⑤ 应用/重跑验证 -> ⑥ 经验写回 KV+RAG。

安全护栏（面试重点）：
- 只对「元素定位失败」自愈（调用方只在 error_type=locator_not_found 时才调 heal）；
- 修复默认人工确认（confirm 可注入；CLI 场景走交互 y/n）；
- LLM 建议必须在真实页面上 try_locate 验证通过才算数，验证失败带错误回传限次重写；
- 写回前记录 diff/建议，命中率与自愈成功率口径见 metrics / docs。

为什么 KV 命中还要再验证一次：历史修复可能已被再次改版作废（KV 命中但过时），
验证失败则继续走下坡（LLM 重新给建议），不让过期经验直接生效。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from aiae.healer.signature import make_signature
from aiae.healer.ui import UISession
from aiae.kv import KVStore
from aiae.llm.client import LLMClient, LLMError, LLMResponse
from aiae.rag import RAGStore

# 语义层重试上限：LLM 建议验证失败 -> 带错误回传重写（与 generator 同思路，限次防烧钱）
_LLM_RETRY_LIMIT = 2


@dataclass
class HealResult:
    """一次自愈的结果（用于统计与日志）。"""

    outcome: str  # kv_hit | healed | rejected | failed
    signature: str = ""
    new_locator: str = ""  # 修复后的定位器（kv_hit/healed 时有）
    source: str = ""       # 修复来源：kv / llm / rag+llm
    attempts: int = 0      # LLM 建议尝试次数
    message: str = ""


_SYSTEM_PROMPT = (
    "你是一名资深 UI 测试工程师。网页改版导致测试脚本的元素定位失败。"
    "给你：失败的旧定位器、页面标题、改版后页面的关键元素结构（tag/name/id/type/文本），"
    "以及可能的相似历史案例。"
    "请找出旧定位器对应的元素在新页面里改成了什么，输出修复后的 CSS 选择器。"
    "硬性要求：只输出一个 JSON 对象（不要 Markdown 围栏/解释），结构为 "
    '{"new_locator": "修复后的选择器", "reasoning": "一句话理由"}。'
    "new_locator 必须是能在新页面上定位到目标元素的 CSS 选择器。"
)


def _failure_query_text(failure: dict[str, Any]) -> str:
    """把失败信息转成 RAG 检索用的文本（含页面结构摘要）。"""
    structure = failure.get("structure") or []
    lines = [f"{e.get('tag')} name={e.get('name')} id={e.get('id')} type={e.get('type')} text={e.get('text')}"
             for e in structure if isinstance(e, dict)]
    return (
        f"页面[{failure.get('page_title', '')}] {failure.get('error_type', '')} "
        f"旧定位器 {failure.get('locator', '')}\n"
        + "\n".join(lines)
    )


def _parse_new_locator(content: str) -> str:
    """从 LLM 输出解析 new_locator；失败抛 ValueError（精确错误回传重写）。"""
    data = json.loads(content)
    locator = data.get("new_locator")
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError("缺少 new_locator（非空字符串）")
    return locator.strip()


def _interactive_confirm(proposal: dict[str, Any]) -> bool:
    """CLI 人工确认：打印修复建议，读 y/n。"""
    print("\n===== 请人工确认修复建议 =====")
    print(f"  签名      : {proposal['signature'][:16]}...")
    print(f"  旧定位器  : {proposal['old_locator']}")
    print(f"  新定位器  : {proposal['new_locator']}")
    print(f"  来源      : {proposal['source']}")
    print(f"  理由      : {proposal.get('reasoning', '')}")
    answer = input("应用该修复？(y/N): ").strip().lower()
    return answer in {"y", "yes"}


class Healer:
    """KV -> RAG -> LLM -> 人工确认 -> 应用/写回 的编排器。"""

    def __init__(
        self,
        kv: KVStore,
        rag: RAGStore,
        llm: LLMClient | None = None,
        confirm: Callable[[dict[str, Any]], bool] | None = None,
    ):
        self.kv = kv
        self.rag = rag
        self.llm = llm
        self.confirm = confirm if confirm is not None else _interactive_confirm

    def heal(self, ui: UISession, failure: dict[str, Any]) -> HealResult:
        """对一次定位失败执行自愈。ui 需已打开失败所在的页面（用于验证新定位器）。"""
        signature = make_signature(
            error_type=failure.get("error_type", ""),
            locator=failure.get("locator", ""),
            page_title=failure.get("page_title", ""),
            elements=failure.get("structure") or [],
        )

        # ① KV 完全命中（历史已验证的修复）
        cached = self.kv.get(signature)
        if cached:
            old_loc = (cached or {}).get("new_locator", "")
            if old_loc and _verify_locator(ui, old_loc):
                return HealResult(outcome="kv_hit", signature=signature,
                                  new_locator=old_loc, source="kv",
                                  message="KV 命中：历史修复仍有效")

        # ② RAG 相似案例（作 LLM 上下文，本身不直接产出修复）
        similar = self.rag.search(_failure_query_text(failure), top_k=2)
        source = "rag+llm" if similar else "llm"

        if self.llm is None:
            return HealResult(outcome="failed", signature=signature,
                              message="无 LLM 客户端且 KV 未命中，无法自愈")

        # ③ LLM 建议 + 页面验证（失败带错误回传，限次重写）
        messages = _build_messages(failure, similar)
        last_reason = ""
        for attempt in range(_LLM_RETRY_LIMIT + 1):
            try:
                response: LLMResponse = self.llm.complete(messages, json_mode=True)
            except LLMError as exc:
                return HealResult(outcome="failed", signature=signature, attempts=attempt,
                                  message=f"LLM 调用失败：{exc}")
            try:
                new_locator = _parse_new_locator(response.content)
            except (ValueError, json.JSONDecodeError) as exc:
                last_reason = f"解析失败：{exc}"
                messages = _with_feedback(messages, response.content, last_reason)
                continue
            if _verify_locator(ui, new_locator):
                proposal = {
                    "signature": signature,
                    "old_locator": failure.get("locator", ""),
                    "new_locator": new_locator,
                    "source": source,
                    "reasoning": _extract_reasoning(response.content),
                }
                if not self.confirm(proposal):
                    return HealResult(outcome="rejected", signature=signature,
                                      new_locator=new_locator, source=source,
                                      attempts=attempt, message="人工拒绝应用")
                # ⑤ 写回经验
                self.kv.put(signature, {"new_locator": new_locator, "source": source})
                self.rag.add_case(
                    doc_id=signature,
                    signature=signature,
                    description=_failure_query_text(failure),
                    fix=new_locator,
                )
                return HealResult(outcome="healed", signature=signature,
                                  new_locator=new_locator, source=source,
                                  attempts=attempt, message="LLM 建议经人工确认并写回")
            last_reason = f"新定位器 {new_locator} 在页面上验证失败"
            messages = _with_feedback(messages, response.content, last_reason)

        return HealResult(outcome="failed", signature=signature,
                          attempts=_LLM_RETRY_LIMIT,
                          message=f"建议 {_LLM_RETRY_LIMIT} 次后仍失败：{last_reason}")


def _build_messages(failure: dict[str, Any], similar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """构造 LLM 消息：失败信息 + 新页面结构 +（相似案例参考）。"""
    structure = failure.get("structure") or []
    user_lines = [
        f"页面标题: {failure.get('page_title', '')}",
        f"错误类型: {failure.get('error_type', '')}",
        f"失败的旧定位器: {failure.get('locator', '')}",
        "改版后页面关键元素结构:",
        json.dumps(structure, ensure_ascii=False),
    ]
    if similar:
        user_lines.append("相似历史案例（参考，不要照抄）:")
        for case in similar:
            user_lines.append(f"- 旧问题: {case.get('doc_id', '')} -> 修复: {case.get('fix', '')}")
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def _with_feedback(messages: list[dict[str, Any]], assistant: str, feedback: str) -> list[dict[str, Any]]:
    return [
        *messages,
        {"role": "assistant", "content": assistant},
        {"role": "user", "content": f"上面的建议不合格，请重新输出完整 JSON。原因：{feedback}"},
    ]


def _extract_reasoning(content: str) -> str:
    try:
        data = json.loads(content)
        return str(data.get("reasoning", ""))
    except Exception:
        return ""


def _verify_locator(ui: UISession, locator: str) -> bool:
    """在真实页面上验证新定位器是否有效（定位失败缓存/建议都不生效）。"""
    try:
        return ui.try_locate(locator, timeout_ms=2500).ok
    except Exception:
        return False
