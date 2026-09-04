"""targets 单测：适配器接口与 todo_app 实现（不发真实请求，只测纯数据/注册表）。"""

from __future__ import annotations

import pytest

from aiae.targets import TargetAdapter, get_adapter
from aiae.targets.fastapi_crud_todo import FastAPICrudTodoAdapter
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


# ---------------------------------------------------------------- 适配契约扩展（auth_mode / openapi / 指令钩子）

class FakeNoneAdapter(TargetAdapter):
    """无认证形态的最小适配器（测试用；不入全局注册表）。"""

    name = "fake_none"
    auth_mode = "none"
    resource = None


def test_todo_adapter_contract_fields():
    a = TodoAppAdapter()
    assert a.auth_mode == "password"
    assert a.display_name == "todo_app"
    assert a.openapi_relpath == "samples/openapi/todo_app-openapi.json"


def test_base_auth_methods_raise_not_implemented():
    """auth_mode=none 的适配器可以不实现注册/登录（不会被调用）。"""

    class NoAuthImpl(TargetAdapter):
        name = "x"
        auth_mode = "none"

    a = NoAuthImpl()
    with pytest.raises(NotImplementedError):
        a.register_user("http://x", role="user")
    with pytest.raises(NotImplementedError):
        a.login_token("http://x", "u", "p")


def test_build_auth_headers_default_bearer():
    a = TodoAppAdapter()
    assert a.build_auth_headers("tok123") == {"Authorization": "Bearer tok123"}


def test_todo_instruction_hooks_keep_regression_wording():
    """todo 覆写三个 Prompt 钩子，措辞与 2026-09-03 定稿一致（回归稳定性）。"""
    a = TodoAppAdapter()
    assert "fresh_user" in a.login_instruction()
    assert "auth_headers" in a.auth_instruction()
    ri = a.resource_id_instruction(["todo_id"])
    assert "created_todo_id" in ri
    assert "{todo_id}" in ri
    assert "不要用写死的 id" in ri


def test_none_adapter_contract_fields():
    a = FakeNoneAdapter()
    assert a.auth_mode == "none"
    assert a.resource is None
    assert a.name == "fake_none"


# ---------------------------------------------------------------- 第二被测项目（auth_mode="none"）

def test_fastapi_crud_todo_adapter_contract():
    """第二被测项目：无认证纯 CRUD —— 验证框架可退化（auth_mode="none"）。"""
    a = FastAPICrudTodoAdapter()
    assert a.name == "fastapi_crud_todo"
    assert a.auth_mode == "none"          # 无认证：conftest 只给 base_url
    assert a.resource is None             # 无「当前用户资源」语义
    assert a.default_base_url.endswith(":8011")
    assert a.openapi_relpath.endswith("fastapi_crud_todo-openapi.json")
    assert a.display_name


def test_get_adapter_second_project_registered():
    assert get_adapter("fastapi_crud_todo").name == "fastapi_crud_todo"
