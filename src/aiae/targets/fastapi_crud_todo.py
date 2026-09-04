"""fastapi_crud_todo（lymanny/FastAPI-CRUD-Todo）被测项目适配器。

第二被测项目：无认证的纯 API CRUD（验证框架可退化到 auth_mode="none"）。
与 todo_app 的差异就是验证点：
- 无注册/登录/token —— auth_mode="none"，conftest 只给 base_url，
  生成用例全部按开放接口（签名只有 base_url），generator 不给任何鉴权/登录指令；
- 无「当前用户资源」语义 —— resource=None（{todo_id} 接口由 LLM 用例自建自取）；
- 固定 commit 0ccc618b60c73bbc9f7a488a213ea14e852cb776（2024-11-12）。

依赖漂移处理（真实踩坑，见 samples/README / progress 对应日期）：
仓库锁 fastapi 0.95.2 / pydantic 1.10.12 / sqlalchemy 2.0.21（2023 时代）；
在 Python 3.12 上 pydantic 1.10.12 与 typing.ForwardRef 不兼容 -> 升 1.10.21（仍 <2.0）；
anyio 被装成 4.x 导致 starlette 0.27 的 anyio.to_thread 失效 -> 降到 3.7.1（lock 时代）。
"""

from __future__ import annotations

from aiae.targets.base import TargetAdapter, register_adapter


@register_adapter
class FastAPICrudTodoAdapter(TargetAdapter):
    """fastapi_crud_todo：无认证纯 CRUD（SQLite + FastAPI 0.95 / Pydantic 1.10 / SQLAlchemy 2.0）。"""

    name = "fastapi_crud_todo"
    display_name = "FastAPI CRUD Todo（无认证）"
    auth_mode = "none"                    # 无认证：conftest 只给 base_url，不注册登录/鉴权 fixtures
    default_base_url = "http://127.0.0.1:8011"
    openapi_relpath = "samples/openapi/fastapi_crud_todo-openapi.json"
    resource = None                       # 无「当前用户资源」语义（开放 CRUD，资源 id 由用例自建自取）
