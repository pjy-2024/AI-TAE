"""pytest 执行与结果收集：跑「已生成的用例」，产出通过/失败/错误统计。

为什么用 pytest 而不是自己写执行器：pytest 生态成熟、报告标准（junitxml），
且 V2 需要的 fixture/hook 机制是现成的 —— 面试讲「站在生态上，不自造轮子」。

关键设计：
1. 子进程隔离执行（.venv python -m pytest），不用 pytest.main ——
   在自身 pytest 会话里嵌套调用会抢插件/缓存/捕获，不可靠；
2. 结果收集用 junitxml（--junitxml）标准报告解析，落盘可审计；
3. 运行前确保 generated_dir/conftest.py 存在（提供 base_url fixture）——
   否则生成用例签名 def test_x(base_url) 会收集期 fixture not found，
   可执行率假性为 0。conftest 已存在（可能人工改过）则不覆盖。

口径注意（面试可讲）：pytest 的 <failure> = 测试函数内抛出的异常
（含 AssertionError、连不上被测服务），<error> = import/收集/fixture 级错误。
所以「服务没起导致连不上」会计入 failed 而非 error —— 该口径边界待端到端
用真实数据校验后再决定是否调整。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from aiae.config import PathsConfig

# runner 自动写入的 conftest（只写一次，人工改过不覆盖）。
# 注意：conftest 是「运行约定」，模板升级后旧自动生成的 conftest 需删除才会按新模板重建。
_CONFTEST_TEMPLATE = '''"""AI-TAE 运行约定（runner 自动生成，可人工修改）。

fixtures（按被测项目角色/资源语义设计；换被测项目需人工调整本文件）：
- base_url        : 被测服务地址（AITAE_TARGET_BASE_URL）
- registered_user : session 级用户（注册 role="admin"：被测项目 admin 接口要求 role=admin，
                     而普通接口只校验登录不校验角色，故 admin 可通吃；若被测项目角色语义更严，
                     应拆普通/管理员两类 fixture 并让 Prompt 区分）
- fresh_user      : function 级随机普通用户（登录类用例用；每次新建，避免被「改密码」等
                     改状态用例污染共享的 registered_user）
- auth_headers    : registered_user 的 Authorization 头（需认证接口用）
- created_todo_id : function 级已创建的待办 id（path 含 {todo_id} 的接口用；每次新建，
                     避免 read/update/delete 共用一条造成的执行顺序耦合）

生成用例签名约定（与 generator 的 Prompt 配套）：
- 开放接口     : def test_xxx(base_url)
- 需认证接口   : def test_xxx(base_url, auth_headers)
- 登录类接口   : def test_xxx(base_url, fresh_user)
- 资源 id 接口 : def test_xxx(base_url, auth_headers, created_todo_id)  # {todo_id} 用它
"""
import os
import uuid

import pytest
import requests


def _register_user(base_url: str, *, role: str) -> dict:
    """注册一个随机用户（用户名/密码带 uuid 后缀，重复运行不冲突），返回登录凭据。"""
    username = "aiae_" + uuid.uuid4().hex[:12]
    password = "Aiae_pass_" + uuid.uuid4().hex[:8]
    payload = {
        "username": username,
        "email": f"{username}@test.local",
        "first_name": "AI",
        "last_name": "TAE",
        "password": password,
        "role": role,
        "phone_number": "13800000000",
    }
    resp = requests.post(f"{base_url}/auth", json=payload, timeout=10)
    resp.raise_for_status()  # 注册失败直接暴露（预期 201）
    return {"username": username, "password": password, "email": payload["email"]}


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("AITAE_TARGET_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def registered_user(base_url) -> dict:
    """session 级用户：注册 role=admin，供 auth_headers 使用（整批只注册一次）。"""
    return _register_user(base_url, role="admin")


@pytest.fixture
def fresh_user(base_url) -> dict:
    """function 级随机普通用户：登录类用例用（每次新建，自包含、不受其他用例改状态影响）。"""
    return _register_user(base_url, role="user")


@pytest.fixture(scope="session")
def auth_headers(base_url, registered_user) -> dict:
    """用 registered_user 登录，返回带 Bearer token 的请求头。"""
    resp = requests.post(
        f"{base_url}/auth/token",
        data={
            "username": registered_user["username"],
            "password": registered_user["password"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def created_todo_id(base_url, auth_headers) -> int:
    """function 级：为当前用户创建一条待办，返回其 id（资源 id 类接口用例用）。

    注意：todo_app 的创建接口返回 201 + null（无响应体），拿不到对象，
    所以创建后从「当前用户待办列表」按 seed 标题前缀取回刚创建那条的 id。
    """
    seed_title = f"seed-{uuid.uuid4().hex[:6]}"
    resp = requests.post(
        f"{base_url}/todos/todo",
        json={
            "title": seed_title,
            "description": f"seed-desc-{uuid.uuid4().hex[:8]}",
            "priority": 1,
        },
        headers=auth_headers,
        timeout=10,
    )
    resp.raise_for_status()
    listing = requests.get(f"{base_url}/todos/", headers=auth_headers, timeout=10)
    listing.raise_for_status()
    todos = listing.json() or []
    matches = [t for t in todos if t.get("title") == seed_title]
    if not matches:
        raise AssertionError(f"创建后未在列表中找到 seed 待办: {seed_title}")
    return matches[0]["id"]
'''
import os
import uuid

import pytest
import requests


def _register_user(base_url: str, *, role: str) -> dict:
    """注册一个随机用户（用户名/密码带 uuid 后缀，重复运行不冲突），返回登录凭据。"""
    username = "aiae_" + uuid.uuid4().hex[:12]
    password = "Aiae_pass_" + uuid.uuid4().hex[:8]
    payload = {
        "username": username,
        "email": f"{username}@test.local",
        "first_name": "AI",
        "last_name": "TAE",
        "password": password,
        "role": role,
        "phone_number": "13800000000",
    }
    resp = requests.post(f"{base_url}/auth", json=payload, timeout=10)
    resp.raise_for_status()  # 注册失败直接暴露（预期 201）
    return {"username": username, "password": password, "email": payload["email"]}


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("AITAE_TARGET_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def registered_user(base_url) -> dict:
    """session 级用户：注册 role=admin，供 auth_headers 使用（整批只注册一次）。"""
    return _register_user(base_url, role="admin")


@pytest.fixture
def fresh_user(base_url) -> dict:
    """function 级随机普通用户：登录类用例用（每次新建，自包含、不受其他用例改状态影响）。"""
    return _register_user(base_url, role="user")


@pytest.fixture(scope="session")
def auth_headers(base_url, registered_user) -> dict:
    """用 registered_user 登录，返回带 Bearer token 的请求头。"""
    resp = requests.post(
        f"{base_url}/auth/token",
        data={
            "username": registered_user["username"],
            "password": registered_user["password"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def created_todo_id(base_url, auth_headers) -> int:
    """function 级：为当前用户创建一条待办，返回其 id（资源 id 类接口用例用）。"""
    resp = requests.post(
        f"{base_url}/todos/todo",
        json={
            "title": f"seed-{uuid.uuid4().hex[:6]}",
            "description": f"seed-desc-{uuid.uuid4().hex[:8]}",
            "priority": 1,
        },
        headers=auth_headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"] if isinstance(data, dict) else int(resp.text)



@dataclass
class RunSummary:
    """一次 pytest 运行的结果汇总。"""

    total: int = 0
    passed: int = 0
    failed: int = 0  # 断言失败（执行了但结果不符，疑似真问题）
    errors: int = 0  # 用例本身报错（import 错误/异常），属「不可执行」口径
    skipped: int = 0
    durations_s: dict[str, float] = field(default_factory=dict)  # test nodeid -> 耗时


def _ensure_conftest(generated_dir: Path) -> Path:
    """确保 base_url fixture 存在：没有才写模板，已存在（可能人工改过）不覆盖。"""
    conftest = generated_dir / "conftest.py"
    if not conftest.exists():
        conftest.write_text(_CONFTEST_TEMPLATE, encoding="utf-8")
    return conftest


def _invoke_pytest(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """子进程执行 pytest（可被测试 monkeypatch 替换）。"""
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _parse_junit(xml_path: Path) -> RunSummary:
    """解析 junitxml：<failure>=断言失败，<error>=用例自身报错，<skipped>=跳过。"""
    root = ET.parse(str(xml_path)).getroot()
    summary = RunSummary()
    for case in root.iter("testcase"):
        summary.total += 1
        classname = case.get("classname", "")
        name = case.get("name", "")
        nodeid = f"{classname}::{name}" if classname else name
        raw_time = case.get("time")
        if raw_time:
            try:
                summary.durations_s[nodeid] = float(raw_time)
            except ValueError:
                pass
        if case.find("failure") is not None:
            summary.failed += 1
        elif case.find("error") is not None:
            summary.errors += 1
        elif case.find("skipped") is not None:
            summary.skipped += 1
        else:
            summary.passed += 1
    return summary


def run_pytest(generated_dir: Path, *, junit_xml: Path | None = None) -> RunSummary:
    """编程式调用 pytest 收集结果（子进程 + junitxml 解析）。

    junit_xml 缺省写到系统临时文件（不落盘产物）；cli 层可传入 data/runs/ 下的
    路径用于审计留档。返回 RunSummary（含逐用例耗时）。
    """
    generated_dir = Path(generated_dir)
    if not generated_dir.is_dir():
        raise FileNotFoundError(f"generated_dir 不存在或不是目录: {generated_dir}")

    _ensure_conftest(generated_dir)

    own_temp = junit_xml is None
    if own_temp:
        handle = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
        xml_path = Path(handle.name)
        handle.close()
    else:
        xml_path = Path(junit_xml)
        xml_path.parent.mkdir(parents=True, exist_ok=True)

    # --rootdir 指向 generated_dir：测试目录可能在项目子树之外（如系统 Temp），
    # 若不显式指定，pytest 会向上找配置文件锚点、可能扫到无权限目录导致收集失败。
    args = [
        str(generated_dir),
        "--rootdir", str(generated_dir),
        "-q",
        "--junitxml", str(xml_path),
        "-p", "no:cacheprovider",   # 关缓存，避免污染被测目录/项目
        "--continue-on-collection-errors",  # 一个文件 import 坏了只计 error，不中断整批
        "--no-header",
    ]
    try:
        proc = _invoke_pytest(args, cwd=PathsConfig().project_root)
        if not xml_path.exists() and proc.returncode != 0:
            raise RuntimeError(f"pytest 子进程未产出 junit 且失败（rc={proc.returncode}）：{proc.stderr[-500:]}")
        return _parse_junit(xml_path)
    finally:
        if own_temp:
            xml_path.unlink(missing_ok=True)