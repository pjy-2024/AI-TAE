"""被测项目适配器：AI-TAE 与被测项目之间的「适配契约」。

目标（面试可讲）：框架代码不含任何被测项目硬编码。被测特定面全部收敛到
TargetAdapter / ResourceAdapter 里——换被测项目 = 写一个适配器类并把
AITAE_TARGET 指向它（conftest 与生成用例的 fixture 契约由适配器驱动）。

适配契约涵盖三块被测特定能力：
1. 认证：怎么注册用户（payload 模板）、注册的默认/可用角色、怎么登录拿 token；
2. 资源语义：被测有没有「当前用户已存在资源 id」（如 todo 的 {todo_id}），
   有则提供创建/取回 id 的能力（供 {id} 类接口用例与 V2 签名）；
3. 默认地址：default_base_url（可被 AITAE_TARGET_BASE_URL 覆盖）。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class ResourceAdapter(ABC):
    """「当前用户已创建资源」适配：为 {xxx_id} 类接口提供真实资源 id。"""

    fixture_name: str = "created_resource_id"  # conftest 注册的 fixture 名（与生成用例签名一致）

    @abstractmethod
    def create_id(self, base_url: str, headers: dict[str, str], seed: str) -> int:
        """创建一个属于当前用户的资源并返回其 id。seed 用于标记唯一性（如标题前缀）。"""

    def describe_for_prompt(self) -> str:
        """给生成器 Prompt 的说明（LLM 据此知道怎么用该 fixture）。"""
        return f"pytest fixture {self.fixture_name}（已为当前用户创建好的资源 id）"


class TargetAdapter(ABC):
    """被测项目适配器基类：定义 AI-TAE 需要的被测特定行为。"""

    name: str = ""
    auth_role: str = "user"        # registered_user 使用的角色（被测若 admin 可通吃则设 admin）
    default_base_url: str = "http://127.0.0.1:8000"
    resource: ResourceAdapter | None = None

    @abstractmethod
    def register_user(self, base_url: str, *, role: str) -> dict[str, Any]:
        """注册一个随机用户并返回登录凭据 {"username","password",...}。"""

    @abstractmethod
    def login_token(self, base_url: str, username: str, password: str) -> str:
        """用凭据登录，返回 access token。"""


def _default_target_name() -> str:
    return os.getenv("AITAE_TARGET", "todo_app")


def get_adapter(name: str | None = None) -> TargetAdapter:
    """按 AITAE_TARGET（缺省 todo_app）返回适配器实例。conftest 运行时调用。"""
    target = name or _default_target_name()
    try:
        return _REGISTRY[target]()
    except KeyError:
        raise ValueError(f"未注册的被测项目适配器: {target!r}（AITAE_TARGET 可选: {sorted(_REGISTRY)}）")


def register_adapter(cls: type[TargetAdapter]) -> type[TargetAdapter]:
    """注册适配器（换被测项目时在 targets 包内 import 即自动注册）。"""
    _REGISTRY[cls.name] = cls
    return cls


_REGISTRY: dict[str, type[TargetAdapter]] = {}
