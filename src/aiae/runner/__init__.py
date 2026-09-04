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
# conftest 模板：通用骨架，运行时 import 被测项目适配器（aiae.targets）。
# 框架代码不再含被测项目硬编码 —— 换被测项目换 AITAE_TARGET 指向的适配器即可。
_CONFTEST_TEMPLATE = '''"""AI-TAE 运行约定（runner 自动生成，可人工修改）。

fixtures 由被测项目适配器驱动（src/aiae/targets/，AITAE_TARGET 选择）：
- 框架不含被测项目硬编码；换被测项目 = 换适配器，本文件无需改。
- base_url   : 被测服务地址（AITAE_TARGET_BASE_URL，缺省取适配器默认端口）
- registered_user : session 级用户（角色取适配器 auth_role）
- fresh_user : function 级随机普通用户（登录类用例用，自包含防共享污染）
- auth_headers : registered_user 登录后的 Authorization 头（需认证接口用）
- <资源 fixture> : 按适配器 resource 能力动态注册（如 {todo_id} 接口用）

生成用例签名约定（与 generator 的 Prompt 配套）：
- 开放接口   : def test_xxx(base_url)
- 需认证接口 : def test_xxx(base_url, auth_headers)
- 登录类接口 : def test_xxx(base_url, fresh_user)
- 资源 id 接口 : def test_xxx(base_url, auth_headers, <资源 fixture>)
"""
import os
import uuid

import pytest
import requests

from aiae.targets import get_adapter

ADAPTER = get_adapter()  # AITAE_TARGET，缺省 todo_app


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("AITAE_TARGET_BASE_URL") or ADAPTER.default_base_url


@pytest.fixture(scope="session")
def registered_user(base_url) -> dict:
    """session 级用户：角色取适配器 auth_role（todo_app 为 admin，可通吃普通+admin 接口）。"""
    return ADAPTER.register_user(base_url, role=ADAPTER.auth_role)


@pytest.fixture
def fresh_user(base_url) -> dict:
    """function 级随机普通用户：登录类用例用（每次新建，不受其他用例改状态影响）。"""
    return ADAPTER.register_user(base_url, role="user")


@pytest.fixture(scope="session")
def auth_headers(base_url, registered_user) -> dict:
    """用 registered_user 登录，返回带 Bearer token 的请求头。"""
    token = ADAPTER.login_token(base_url, registered_user["username"], registered_user["password"])
    return {"Authorization": f"Bearer {token}"}


# 资源级 fixture：仅当被测适配器声明了 resource 能力时注册（fixture 名取适配器声明）
if ADAPTER.resource is not None:
    _RESOURCE = ADAPTER.resource

    @pytest.fixture
    def _resource_id(base_url, auth_headers) -> int:
        return _RESOURCE.create_id(base_url, auth_headers, seed=f"seed-{uuid.uuid4().hex[:6]}")

    globals()[_RESOURCE.fixture_name] = _resource_id
'''


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
    """子进程执行 pytest（可被测试 monkeypatch 替换）。

    显式注入 PYTHONPATH=项目 src：conftest 需 import aiae.targets（适配器），
    而 pytest --rootdir 指向生成目录时不会加载项目 pyproject 的 pythonpath 配置。
    """
    import os

    from pathlib import Path as _Path
    src_dir = str(_Path(PathsConfig().project_root) / "src")
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=cwd,
        env=env,
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