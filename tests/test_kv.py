"""kv 单元测试：KVStore 读写与命中统计（真实 diskcache，tmp 目录）。"""

from __future__ import annotations

from aiae.kv import KVStore


def test_put_get_roundtrip(tmp_path):
    with KVStore(tmp_path / "kv") as kv:
        kv.put("sig-a", {"fix": "把 name=username 改为 name=user_name", "ts": 1})
        assert kv.get("sig-a") == {"fix": "把 name=username 改为 name=user_name", "ts": 1}


def test_miss_and_hit_stats(tmp_path):
    with KVStore(tmp_path / "kv") as kv:
        assert kv.get("不存在") is None          # miss
        kv.put("sig-b", {"fix": "x"})
        assert kv.get("sig-b") == {"fix": "x"}  # hit
        stats = kv.stats()
        assert stats["hits"] == 1 and stats["misses"] == 1


def test_update_overwrites(tmp_path):
    with KVStore(tmp_path / "kv") as kv:
        kv.put("sig", {"fix": "v1"})
        kv.put("sig", {"fix": "v2"})
        assert kv.get("sig") == {"fix": "v2"}


def test_persist_across_reopen(tmp_path):
    path = tmp_path / "kv"
    with KVStore(path) as kv:
        kv.put("sig", {"fix": "persisted"})
    with KVStore(path) as kv:                     # 重新打开仍能读到（磁盘持久化）
        assert kv.get("sig") == {"fix": "persisted"}
