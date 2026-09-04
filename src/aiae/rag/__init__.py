"""V2：本地知识库 RAG（ChromaDB 嵌入式）。

存历史「错误签名 -> 修复文档/案例」，检索辅助修复。数据量小（几万条内），
本地 CPU 足够，不需要 ES/分布式向量库 —— 这是刻意取舍，面试要能讲清。

Embedding 取舍（面试可讲）：
- chromadb 默认 embedding 会下载模型（~80MB，首次联网、写用户缓存），
  这里用「本地字符 n-gram 哈希 embedding」：离线、确定、零下载，保证可复现；
- 设计成可插拔：若评测发现检索质量不足，换模型 embedding 只改 EmbeddingFn 一处。
  检索质量本身是 V2 的【待实测】项，先用轻量版跑通真实数据再决定。

为什么 KV 之外还要 RAG：KV 只解决「完全见过」的精确命中；
RAG 解决「相似但没见过」的模糊检索（比如 class 变了但 name 没变），两者互补。
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.types import EmbeddingFunction

from aiae.config import PathsConfig

_EMBED_DIM = 256


class LocalHashEmbedding(EmbeddingFunction):
    """离线本地 embedding：字符 3-gram 哈希到固定维度 + L2 归一化。

    效果：共享字符片段越多的文本，向量越接近（余弦相似度高）。
    适合「相似但不同」的模糊检索 demo；质量评测后再决定是否换模型 embedding。
    """

    def name(self) -> str:
        """chromadb 新版要求 embedding function 有名字（非 default）。"""
        return "local_hash_v1"

    def get_config(self) -> dict:
        """chromadb 新版要求 embedding function 提供可序列化配置（本实现无参数）。"""
        return {"name": self.name(), "dim": _EMBED_DIM}

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [_embed_one(text) for text in input]


def _embed_one(text: str) -> list[float]:
    vec = [0.0] * _EMBED_DIM
    normalized = " ".join(text.lower().split())
    for i in range(max(0, len(normalized) - 2)):
        gram = normalized[i : i + 3]
        h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
        vec[h % _EMBED_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class RAGStore:
    """Chromadb 封装：案例（签名/描述/修复）入库 + 相似检索。"""

    def __init__(self, path: str | Path | None = None):
        persist = Path(path) if path is not None else Path(PathsConfig().data_dir) / "chroma"
        persist.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="heal_cases",
            embedding_function=LocalHashEmbedding(),
            metadata={"hnsw:space": "cosine"},
        )

    def add_case(self, doc_id: str, *, signature: str, description: str, fix: str) -> None:
        """入库一个历史案例。description 是被检索的正文（含页面结构摘要）。"""
        self._collection.upsert(
            ids=[doc_id],
            documents=[description],
            metadatas=[{"signature": signature, "fix": fix}],
        )

    def search(self, query: str, *, top_k: int = 3) -> list[dict[str, Any]]:
        """按 query（失败描述/页面结构）检索相似案例，返回 [{doc_id, signature, fix, distance}]。"""
        if self._collection.count() == 0:
            return []
        result = self._collection.query(query_texts=[query], n_results=min(top_k, self._collection.count()))
        items: list[dict[str, Any]] = []
        ids = (result.get("ids") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        for doc_id, meta, dist in zip(ids, metas, dists):
            items.append({
                "doc_id": doc_id,
                "signature": (meta or {}).get("signature", ""),
                "fix": (meta or {}).get("fix", ""),
                "distance": float(dist),
            })
        return items

    def count(self) -> int:
        return self._collection.count()
