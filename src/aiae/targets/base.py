"""被测项目适配器：AI-TAE 与被测项目之间的「适配契约」。

目标（面试可讲）：框架代码不含任何被测项目硬编码。被测特定面全部收敛到
TargetAdapter / ResourceAdapter 里——换被测项目 = 写一个适配器类并把
AITAE_TARGET 指向它（conftest 与生成用例的 fixture 契约由适配器驱动）。

适配契约涵盖被测特定能力：
1. 认证形态 auth_mode：
   - "password"：被测有「注册用户 + 账号密码登录换 token」（todo_app 形态）。
     conftest 生成 registered_user / fresh_user / auth_headers fixtures；
     generator 对登录 / 需认证接口给出对应 fixture 用法指令（文案钩子见下）；
   - "none"：被测无认证、纯开放 API。conftest 只提供 base_url，不注册任何
     登录/鉴权 fixtures；generator 不给鉴权/登录指令 —— 验证框架可退化；
   - 其它形态（如 "apikey"）：预留，按需扩展（auth_mode + 模板渲染 + 适配器实现）。
2. 资源语义 resource：被测有没有「当前用户已存在资源 id」（如 todo 的 {todo_id}），
   有则提供创建/取回 id 的能力（供 {id} 类接口用例与 V2 签名）；无资源语义 = None。
3. 默认地址 default_base_url（可被 AITAE_TARGET_BASE_URL 覆盖）。
4. 接口文档 openapi_relpath：cli generate 的缺省 OpenAPI 输入（相对项目根）。
5. 展示名 display_name：报告 / 日志用（空则退回 name）。

Prompt 指令钩子（login_instruction / auth_instruction / resource_id_instruction）：
generator 只负责「按 OpenAPI 特征识别接口类型」，被测特定的「fixture 怎么用」
文案一律从适配器取 —— 换被测项目不用改核心，只改适配器。
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
    display_name: str = ""        # 报告 / 日志展示名（空则退回 name）
    auth_mode: str = "password"   # "password"（注册+登录换 token）| "none"（无认证）
    auth_role: str = "user"       # password 模式 registered_user 用的角色（被测若 admin 可通吃则设 admin）
    default_base_url: str = "http://127.0.0.1:8000"
    openapi_relpath: str = ""     # 相对项目根的 OpenAPI 文件（cli generate 缺省输入）
    resource: ResourceAdapter | None = None

    # ---- 认证（auth_mode="password" 必须实现；"none" 不会走到）----

    def register_user(self, base_url: str, *, role: str) -> dict[str, Any]:
        """注册一个随机用户并返回登录凭据 {"username","password",...}。

        auth_mode="none" 的适配器无需实现；password 模式必须覆写。
        """
        raise NotImplementedError(
            f"{self.name} 适配器未实现 register_user（auth_mode={self.auth_mode}；"
            "password 形态必须覆写，none 形态不会被调用）"
        )

    def login_token(self, base_url: str, username: str, password: str) -> str:
        """用凭据登录，返回 token 字符串。auth_mode="none" 的适配器无需实现。"""
        raise NotImplementedError(
            f"{self.name} 适配器未实现 login_token（auth_mode={self.auth_mode}；"
            "password 形态必须覆写，none 形态不会被调用）"
        )

    def build_auth_headers(self, token: str) -> dict[str, str]:
        """把登录 token 包装成请求头（password 形态默认 Bearer；apikey 等项目覆写）。"""
        return {"Authorization": f"Bearer {token}"}

    # ---- Prompt 指令钩子（generator 从适配器取「接口怎么测」文案，核心不写被测假设）----

    def login_instruction(self) -> str:
        """登录 / 获取令牌类接口的用例生成指令（password 形态通用：fresh_user）。"""
        return (
            "该接口是登录/获取令牌类（表单请求体）。请让用例函数签名包含 fresh_user 参数"
            "（pytest fixture，每次新建的已注册用户 dict，含 username/password），"
            "用 fresh_user['username'] 与 fresh_user['password'] 作为表单值，"
            "不要用写死的账号。"
        )

    def auth_instruction(self) -> str:
        """普通需认证接口的用例生成指令（password 形态通用：auth_headers）。"""
        return (
            "鉴权要求：该接口需要登录认证。请让用例函数签名包含 auth_headers 参数"
            "（pytest fixture，已是登录后的请求头 dict），并在每个请求传 headers=auth_headers。"
            "不要自己实现注册或登录。"
        )

    def resource_id_instruction(self, id_params: list[str]) -> str:
        """操作「当前用户已存在资源」（path 形参是资源 id）接口的用例生成指令。

        仅当 self.resource 非 None 时会被 generator 调用。
        """
        assert self.resource is not None, "resource_id_instruction 仅在有 resource 能力时调用"
        fixture = self.resource.fixture_name
        ids = ", ".join(str(n) for n in id_params)
        return (
            "鉴权要求：该接口需要登录认证，且操作的是当前用户已存在的资源"
            f"（path 形参 {{{ids}}} 是资源 id）。请让用例函数签名包含 auth_headers 与 {fixture}"
            " 两个参数（pytest fixture：auth_headers 是登录后的请求头；"
            f"{self.resource.describe_for_prompt()}）。请求传 headers=auth_headers，"
            f"并把资源 id 位置用 {fixture} 传入，不要用写死的 id。"
        )


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
