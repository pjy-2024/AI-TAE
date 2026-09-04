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
    """todo_app：注册接口任意给 role（admin 可通吃普通+admin 接口）；登录走 OAuth2 密码表单。"""

    name = "todo_app"
    auth_role = "admin"
    default_base_url = "http://127.0.0.1:8010"
    resource: ResourceAdapter = TodoResourceAdapter()

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
