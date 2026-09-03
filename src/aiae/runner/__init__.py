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

# runner 自动写入的 conftest（只写一次，人工改过不覆盖）
_CONFTEST_TEMPLATE = '''"""AI-TAE 运行约定（runner 自动生成，可人工修改）。

base_url fixture：被测服务地址，来自环境变量 AITAE_TARGET_BASE_URL。
生成用例统一用签名 def test_xxx(base_url): ...，由本 fixture 提供被测服务地址。
"""
import os

import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("AITAE_TARGET_BASE_URL", "http://127.0.0.1:8000")
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