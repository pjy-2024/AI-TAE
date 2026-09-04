"""todo_app（manojnd9/todo_app）被测项目适配器。

从旧 conftest 硬编码迁移而来：注册 payload / 登录表单 / admin 角色 / 资源创建
全部收敛在此。换被测项目参考本文件写新适配器，不改框架。
"""

from __future__ import annotations

import uuid
from typing import Any

import requests

from aiae.targets.base import ResourceAdapter, TargetAdapter, register_adapter


class TodoResourceAdapter(ResourceAdapter):
    """todo_app 的待办资源：创建接口返回 201+null（无对象），需从列表按唯一 title 取回 id。"""

    fixture_name = "created_todo_id"

    def create_id(self, base_url: str, headers: dict[str, str], seed: str) -> int:
        title = f"{seed}"
        resp = requests.post(
            f"{base_url}/todos/todo",
            json={
                "title": title,
                "description": f"{seed}-desc",
                "priority": 1,
            },
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        listing = requests.get(f"{base_url}/todos/", headers=headers, timeout=10)
        listing.raise_for_status()
        todos = listing.json() or []
        matches = [t for t in todos if t.get("title") == title]
        if not matches:
            raise AssertionError(f"创建后未在列表中找到待办: {title}")
        return matches[0]["id"]


@register_adapter
class TodoAppAdapter(TargetAdapter):
    """todo_app：password 认证（注册接口任意给 role，admin 可通吃普通+admin 接口）；登录走 OAuth2 密码表单。"""

    name = "todo_app"
    display_name = "todo_app"
    auth_mode = "password"
    auth_role = "admin"
    default_base_url = "http://127.0.0.1:8010"
    openapi_relpath = "samples/openapi/todo_app-openapi.json"
    resource: ResourceAdapter = TodoResourceAdapter()

    # ---- Prompt 指令钩子：保持 2026-09-03「定稿 Prompt」逐字一致（回归稳定性：todo 端到端 19/19）----

    def login_instruction(self) -> str:
        """登录 / 获取令牌类（todo：POST /auth/token 表单）-> fresh_user（每次新建，防共享污染）。"""
        return (
            "该接口是登录/获取令牌类（表单请求体）。请让用例函数签名包含 fresh_user 参数"
            "（pytest fixture，每次新建的已注册用户 dict，含 username/password），"
            "用 fresh_user['username'] 与 fresh_user['password'] 作为表单值，"
            "不要用写死的账号。"
        )

    def auth_instruction(self) -> str:
        """普通需认证接口（todo：读自己/建待办等）-> auth_headers。"""
        return (
            "鉴权要求：该接口需要登录认证。请让用例函数签名包含 auth_headers 参数"
            "（pytest fixture，已是登录后的请求头 dict），并在每个请求传 headers=auth_headers。"
            "不要自己实现注册或登录。"
        )

    def resource_id_instruction(self, id_params: list[str]) -> str:
        """资源 id 类接口（todo：{todo_id}）-> auth_headers + created_todo_id。"""
        ids = ", ".join(str(n) for n in id_params)
        return (
            "鉴权要求：该接口需要登录认证，且操作的是当前用户已存在的资源"
            f"（path 形参 {{{ids}}} 是资源 id）。请让用例函数签名包含 auth_headers 与 created_todo_id"
            " 两个参数（pytest fixture：auth_headers 是登录后的请求头；created_todo_id"
            " 已为当前用户创建好一条待办、返回其 id）。请求传 headers=auth_headers，"
            "并把资源 id 位置用 created_todo_id 传入，不要用写死的 id。"
        )

    # ---- 认证实现（password 形态）----

    def build_payload(self, username: str, password: str, role: str) -> dict[str, str]:
        """注册请求体模板（CreateUserRequest 全字段必填）。"""
        return {
            "username": username,
            "email": f"{username}@test.local",
            "first_name": "AI",
            "last_name": "TAE",
            "password": password,
            "role": role,
            "phone_number": "13800000000",
        }

    def register_user(self, base_url: str, *, role: str) -> dict[str, Any]:
        username = "aiae_" + uuid.uuid4().hex[:12]
        password = "Aiae_pass_" + uuid.uuid4().hex[:8]
        payload = self.build_payload(username, password, role)
        resp = requests.post(f"{base_url}/auth", json=payload, timeout=10)
        resp.raise_for_status()  # 注册失败直接暴露（预期 201）
        return {"username": username, "password": password, "email": payload["email"]}

    def login_token(self, base_url: str, username: str, password: str) -> str:
        resp = requests.post(
            f"{base_url}/auth/token",
            data={"username": username, "password": password},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
