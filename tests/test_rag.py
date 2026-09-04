"""rag 单元测试：案例入库 + 相似检索（本地哈希 embedding，离线；chromadb 落 tmp）。"""

from __future__ import annotations

from aiae.rag import RAGStore


def test_add_and_count(tmp_path):
    rag = RAGStore(tmp_path / "rag")
    rag.add_case("c1", signature="sig-1", description="登录页 username 输入框定位失败", fix="name=username -> name=user_name")
    rag.add_case("c2", signature="sig-2", description="注册页 email 输入框定位失败", fix="name=email -> name=mail")
    assert rag.count() == 2


def test_search_finds_similar_case(tmp_path):
    rag = RAGStore(tmp_path / "rag")
    rag.add_case("c1", signature="sig-1", description="登录页 username 输入框定位失败 input name username", fix="name=username -> name=user_name")
    rag.add_case("c2", signature="sig-2", description="注册页 email 输入框定位失败 input name email", fix="name=email -> name=mail")
    hits = rag.search("登录页 username 输入框 找不到 input[name=username]", top_k=2)
    assert hits, "应有检索结果"
    assert hits[0]["doc_id"] == "c1"          # 与 c1 共享更多字符片段 -> 应排第一
    assert hits[0]["fix"].startswith("name=")


def test_search_empty_returns_empty_list(tmp_path):
    rag = RAGStore(tmp_path / "rag")
    assert rag.search("任何查询") == []


def test_upsert_same_id_overwrites(tmp_path):
    rag = RAGStore(tmp_path / "rag")
    rag.add_case("c1", signature="s", description="旧描述", fix="旧修复")
    rag.add_case("c1", signature="s", description="新描述", fix="新修复")
    assert rag.count() == 1
    hits = rag.search("新描述", top_k=1)
    assert hits and hits[0]["fix"] == "新修复"
