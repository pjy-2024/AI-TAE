"""fastapi_crud_todo（lymanny/FastAPI-CRUD-Todo）被测项目适配器。

第二被测项目：无认证的纯 API CRUD。
与 todo_app 的差异就是验证点：
- 无注册/登录/token —— auth_mode="none"，conftest 不注册登录/鉴权 fixtures；
- 资源语义与认证解耦（方案 B，2026-09-04）：无认证项目同样可由框架创建资源
  （resource fixture，不需登录头）——LLM 不自建资源，从根上消灭「自建子请求
  凭惯例断言 201」这类错误；id 类接口用例直接用 created_todo_id fixture。
- 固定 commit 0ccc618b60c73bbc9f7a488a213ea14e852cb776（2024-11-12）。

依赖漂移处理（真实踩坑，见 samples/README / progress 对应日期）：
仓库锁 fastapi 0.95.2 / pydantic 1.10.12 / sqlalchemy 2.0.21（2023 时代）；
在 Python 3.12 上 pydantic 1.10.12 与 typing.ForwardRef 不兼容 -> 升 1.10.21（仍 <2.0）；
anyio 被装成 4.x 导致 starlette 0.27 的 anyio.to_thread 失效 -> 降到 3.7.1（lock 时代）。
"""

from __future__ import annotations

import uuid

import requests

from aiae.targets.base import ResourceAdapter, TargetAdapter, register_adapter


class FastAPICrudTodoResourceAdapter(ResourceAdapter):
    """fastapi_crud_todo 的待办资源：无认证，POST /todos/ 直接返回 200 + 对象（含 id）。

    与 todo_app（创建返回 201+null，需从列表取回）不同：本被测创建响应即含 id，
    直接取回即可。headers 参数在无认证形态下传 {}（无登录头）。
    """

    fixture_name = "created_todo_id"

    def create_id(self, base_url: str, headers: dict[str, str], seed: str) -> int:
        resp = requests.post(
            f"{base_url}/todos/",
            json={"title": f"seed-{seed}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "id" not in data:
            raise AssertionError(f"创建后响应中没有 id: {data!r}")
        return int(data["id"])


@register_adapter
class FastAPICrudTodoAdapter(TargetAdapter):
    """fastapi_crud_todo：无认证纯 CRUD（SQLite + FastAPI 0.95 / Pydantic 1.10 / SQLAlchemy 2.0）。"""

    name = "fastapi_crud_todo"
    display_name = "FastAPI CRUD Todo（无认证）"
    auth_mode = "none"                    # 无认证：conftest 不注册登录/鉴权 fixtures
    default_base_url = "http://127.0.0.1:8011"
    openapi_relpath = "samples/openapi/fastapi_crud_todo-openapi.json"
    resource: ResourceAdapter = FastAPICrudTodoResourceAdapter()

    def resource_id_instruction(self, id_params: list[str]) -> str:
        """资源 id 类接口（无认证形态）：用框架创建好的 fixture，不让 LLM 自建。

        与 password 形态不同：没有 auth_headers，只有 base_url + created_todo_id。
        """
        ids = ", ".join(str(n) for n in id_params)
        fixture = self.resource.fixture_name
        return (
            "该接口操作的是已存在的待办（path 形参 {" + ids + "} 是资源 id）。"
            f"请让用例函数签名包含 {fixture} 参数"
            f"（pytest fixture，已为当前被测创建好一条待办、返回其 id），"
            f"把资源 id 位置用 {fixture} 传入。"
            "不要自己先调用创建接口准备数据、不要用写死的 id。"
        )
