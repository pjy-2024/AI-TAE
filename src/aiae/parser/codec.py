"""LLM 生成结果的校验、剥离与落盘（可执行率的第一道门禁）。

为什么需要这层（对应说明书 §7 问题 1「LLM 输出不可直接执行」）：
- LLM 常「话痨」：把代码包在 ```python ... ``` 里或夹带解释文字，不能直接写盘；
- 必须校验：语法可解析、函数名以 test_ 开头、函数名与元数据一致；
- 校验失败时把「精确错误信息」回传给生成器做带上下文的限次重试，而不是无限重试。

安全提醒：这里只做静态初筛；真正执行 LLM 生成代码必须进 Docker 沙箱（说明书 §6，V2 起）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 写进 Prompt 的输出约束示例（json_mode 下要求模型严格按此结构输出）
GENERATED_TESTS_JSON_EXAMPLE: str = """{
  "tests": [
    {
      "name": "test_create_todo",
      "description": "正常创建一条待办，返回 201",
      "method": "POST",
      "path": "/todos",
      "code": "def test_create_todo(base_url):\\n    resp = requests.post(f\\"{base_url}/todos\\", json={'title': 'x'})\\n    assert resp.status_code == 201"
    }
  ]
}"""


@dataclass
class GeneratedTest:
    """一条通过校验、可落盘的用例。"""

    name: str  # 函数名（须以 test_ 开头）
    description: str = ""
    method: str = ""  # HTTP 方法（元数据，便于审计/报表）
    path: str = ""  # 请求路径（元数据）
    code: str = ""  # 可直接落盘的 pytest 函数源码


@dataclass
class CodecResult:
    """单条用例的校验结果。"""

    ok: bool
    test: GeneratedTest | None = None
    errors: list[str] = field(default_factory=list)  # 校验失败原因（回传给 LLM 重试用）


def parse_llm_output(text: str) -> list[GeneratedTest]:
    """剥离 Markdown 围栏 -> json.loads -> 逐字段结构校验。

    失败时抛 ValueError（错误信息要足够具体，便于回传给 LLM 修正）。
    """
    raise NotImplementedError("任务 2 实现：先 strip ``` 围栏，再 json.loads，再逐字段校验。")


def validate_code(test: GeneratedTest) -> list[str]:
    """静态校验源码：ast.parse 可解析、恰好一个 test_ 开头函数、函数名 == test.name。

    返回错误列表（空列表 = 通过）。
    """
    raise NotImplementedError("任务 2 实现：用 ast 模块做静态校验。")


def write_test_file(test: GeneratedTest, out_dir: Path, *, module_name: str | None = None) -> Path:
    """把单条用例写成 pytest 文件（统一文件头 import 与 conftest 约定），返回文件路径。"""
    raise NotImplementedError("任务 2 实现：按 tag/模块组织目录并写文件。")