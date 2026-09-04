"""UI 失败「错误签名」：把一次定位失败压成可用于 KV/RAG 的稳定指纹。

为什么需要签名：
- KV/RAG 都需要一把「钥匙」；钥匙要稳定（同样的失败 -> 同样的签名）才能命中；
- 钥匙要能区分（不同页面/不同元素的失败 -> 不同签名），否则会串经验；
- 元素顺序等无关细节要归一化（同一页面结构变化顺序不应改变指纹）。

签名组成：错误类型 | 定位器（规范化） | 页面指纹（title + 关键元素结构）。
真实指标：命中率【待实测】，签名粒度是影响命中率的关键可调项。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def _normalize(text: str) -> str:
    """规范化：去首尾空白、内部空白压缩、转小写（让同义写法收敛到同一签名）。"""
    return re.sub(r"\s+", " ", text.strip().lower())


def structure_fingerprint(elements: list[dict[str, Any]]) -> str:
    """页面关键元素结构的稳定指纹。

    每个元素取 (tag, name, id, type, placeholder) 里非空字段拼成串；
    列表按串排序后整体哈希 —— 元素在 DOM 里的出现顺序不影响指纹
    （页面结构语义相同但顺序抖动时仍能命中）。
    """
    normalized = []
    for el in elements or []:
        parts = [str(el.get(k, "")).strip() for k in ("tag", "name", "id", "type", "placeholder", "text")]
        line = "|".join(p for p in parts if p)
        if line:
            normalized.append(_normalize(line))
    normalized.sort()
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()[:16]


def make_signature(
    *,
    error_type: str,
    locator: str,
    page_title: str,
    elements: list[dict[str, Any]],
) -> str:
    """生成错误签名：error_type | normalized_locator | structure_fingerprint。"""
    raw = "|".join([
        _normalize(error_type),
        _normalize(locator),
        _normalize(page_title),          # 页面 title 也参与签名：不同页面不串经验
        structure_fingerprint(elements),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def signature_to_dict(signature: str) -> dict[str, Any]:
    """审计辅助：把签名拆回组成便于人读（不用于匹配）。"""
    return {"signature": signature, "note": "组成顺序: 错误类型 | 定位器 | 页面结构指纹"}
