"""V2：本地 KV 缓存（diskcache）。

key = 错误签名（错误类型 + 元素特征 + 页面指纹），value = 修复策略。
诚实定位：本地嵌入式 KV；Redis 是多实例/分布式的正解，这里不硬蹭「迷你 Redis」。

为什么先查 KV：UI 失败大多重复（同页面同改法会反复遇到）。
完全命中的情况直接复用历史修复，零 LLM 调用 —— 命中率是「成本越用越低」的数据支撑。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import diskcache

from aiae.config import PathsConfig


class KVStore:
    """diskcache 封装：错误签名 -> 修复策略，带命中/未命中计数（供 healer 统计）。"""

    def __init__(self, path: str | Path | None = None):
        # 缺省 data/cache/heal_kv（gitignore，不入库）
        cache_dir = Path(path) if path is not None else Path(PathsConfig().cache_dir) / "heal_kv"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(cache_dir))
        self._hits = 0
        self._misses = 0

    def get(self, signature: str) -> Any | None:
        """按签名取历史修复策略；命中记 hits，未命中记 misses。"""
        value = self._cache.get(signature)
        if value is None:
            self._misses += 1
        else:
            self._hits += 1
        return value

    def put(self, signature: str, value: Any) -> None:
        """写入/更新某签名的修复策略。"""
        self._cache.set(signature, value)

    def stats(self) -> dict[str, int]:
        """命中/未命中计数（命中率 = hits / (hits + misses)，由调用方按口径算）。"""
        return {"hits": self._hits, "misses": self._misses}

    def close(self) -> None:
        self._cache.close()

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
