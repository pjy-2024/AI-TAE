"""targets 单测：适配器接口与 todo_app 实现（不发真实请求，只测纯数据/注册表）。"""

from __future__ import annotations

import pytest

from aiae.targets import get_adapter
from aiae.targets.todo_app import TodoAppAdapter


def test_todo_adapter_build_payload_full_fields():
    a = TodoAppAdapter()
    payload = a.build_payload("u1", "p1", "user")
    # CreateUserRequest 7 个必填字段齐全
    for key in ("username", "email", "first_name", "last_name", "password", "role", "phone_number"):
        assert key in payload and payload[key]
    assert payload["username"] == "u1" and payload["role"] == "user"


def test_todo_adapter_config():
    a = TodoAppAdapter()
    assert a.name == "todo_app"
    assert a.auth_role == "admin"                     # todo admin 可通吃普通+admin 接口
    assert a.default_base_url.endswith(":8010")
    assert a.resource is not None
    assert a.resource.fixture_name == "created_todo_id"


def test_get_adapter_default_and_registry():
    assert get_adapter().name == "todo_app"           # 缺省 AITAE_TARGET=todo_app
    with pytest.raises(ValueError, match="未注册"):
        get_adapter("not_exist_project")


def test_resource_describe_for_prompt():
    a = TodoAppAdapter()
    desc = a.resource.describe_for_prompt()
    assert "created_todo_id" in desc
