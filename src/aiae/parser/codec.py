"""LLM 生成结果的校验、剥离与落盘（可执行率的第一道门禁）。

为什么需要这层（对应说明书 §7 问题 1「LLM 输出不可直接执行」）：
- LLM 常「话痨」：把代码包在 ```python ... ``` 里或夹带解释文字，不能直接写盘；
- 必须校验：语法可解析、函数名以 test_ 开头、函数名与元数据一致；
- 校验失败时把「精确错误信息」回传给生成器做带上下文的限次重试，而不是无限重试。

安全提醒：这里只做静态初筛；真正执行 LLM 生成代码必须进 Docker 沙箱（说明书 §6，V2 起）。

面试可讲：生成质量靠「Schema 约束 + 本地校验」而不是赌模型自觉 —— 可执行率的第一道门禁。
"""

from __future__ import annotations

import ast
import json
import re
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


# ---------------------------------------------------------------- 文本 -> 结构化

def parse_llm_output(text: str) -> list[GeneratedTest]:
    """剥离 Markdown 围栏 -> json.loads -> 逐字段结构校验。

    失败时抛 ValueError（错误信息要足够具体，便于回传给 LLM 修正）。

    策略：对「格式噪音」宽容（围栏、前后废话），对「结构错误」严格
    （顶层必须有 tests 数组、每条必须有 name/code、name 必须以 test_ 开头）。
    """
    raw = _extract_json_text(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 输出不是合法 JSON（{exc.msg}，位置 {exc.pos}）。原文前 200 字符：{raw[:200]!r}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("tests"), list):
        raise ValueError("LLM 输出缺少 tests 数组（顶层必须是 {\"tests\": [...]}）")
    if not data["tests"]:
        raise ValueError("tests 数组为空：模型没有生成任何用例")

    parsed: list[GeneratedTest] = []
    for index, item in enumerate(data["tests"]):
        errors = _validate_item(item, index)
        if errors:
            raise ValueError("；".join(errors))
        parsed.append(
            GeneratedTest(
                name=str(item["name"]).strip(),
                description=str(item.get("description", "")).strip(),
                method=str(item.get("method", "")).strip(),
                path=str(item.get("path", "")).strip(),
                code=str(item["code"]),
            )
        )
    return parsed


def _extract_json_text(text: str) -> str:
    """从 LLM 原始输出里取出 JSON 文本：剥围栏 -> 截取首尾花括号。

    容忍：```json 围栏、围栏前的解释文字、围栏后的收尾。
    若 text 本身不是 JSON（如只有一段解释），json.loads 会在上层给出精确报错。
    """
    stripped = text.strip()
    # 1) 若被 Markdown 代码围栏包住，取第一个围栏块内容
    fence = re.search(r"```[a-zA-Z]*\s*\n(.*?)\n```", stripped, flags=re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    # 2) 若剥完仍不是以 { 开头（前面有废话），截取第一个 { 到最后一个 }
    if not stripped.startswith("{"):
        start, end = stripped.find("{"), stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            stripped = stripped[start : end + 1]
    return stripped


def _validate_item(item: Any, index: int) -> list[str]:
    """单条用例的结构校验，返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    prefix = f"tests[{index}]"
    if not isinstance(item, dict):
        return [f"{prefix} 必须是对象（dict），实际是 {type(item).__name__}"]

    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{prefix} 缺 name（非空字符串，须以 test_ 开头）")
    elif not name.strip().startswith("test_"):
        errors.append(f"{prefix} name={name!r} 必须以 test_ 开头（pytest 才能收集）")

    code = item.get("code")
    if not isinstance(code, str) or not code.strip():
        errors.append(f"{prefix} 缺 code（非空字符串，内容是 pytest 函数源码）")

    for key in ("description", "method", "path"):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"{prefix} {key} 必须是字符串，实际是 {type(value).__name__}")
    return errors


# ---------------------------------------------------------------- ast 静态校验

def validate_code(test: GeneratedTest) -> list[str]:
    """静态校验源码：ast.parse 可解析、恰好一个 test_ 开头函数、函数名 == test.name。

    返回错误列表（空列表 = 通过）。只做静态初筛，不执行代码 ——
    执行 LLM 生成代码的安全隔离（Docker 沙箱）在 V2。
    """
    errors: list[str] = []
    try:
        tree = ast.parse(test.code)
    except SyntaxError as exc:
        where = f"（行 {exc.lineno}）" if exc.lineno is not None else ""
        return [f"语法错误: {exc.msg}{where}"]

    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    test_funcs = [f for f in funcs if f.name.startswith("test_")]
    if not test_funcs:
        errors.append("未找到以 test_ 开头的函数定义（pytest 只收集 test_ 函数）")
    elif len(test_funcs) > 1:
        errors.append(f"应恰好一个 test_ 函数，实际有 {len(test_funcs)} 个: "
                      + ", ".join(f.name for f in test_funcs))
    if test_funcs and test_funcs[0].name != test.name:
        errors.append(f"函数名 {test_funcs[0].name} 与元数据 name={test.name} 不一致")
    return errors


# ---------------------------------------------------------------- 落盘

_TEST_FILE_HEADER = """# AI-TAE 自动生成（草稿）· 人工审阅确认后才入库
# method={method}  path={path}  description={description}

import requests

"""


def write_test_file(test: GeneratedTest, out_dir: Path, *, module_name: str | None = None) -> Path:
    """把单条用例写成 pytest 文件，返回文件路径。

    约定（与 generator 的 Prompt / runner 的 conftest 配套）：
    1. 文件名保证可被 pytest 收集（test_*.py）：module_name 不带 test_ 前缀会自动补；
    2. 文件头统一 import requests —— LLM 只输出函数体，import 由本层统一提供，
       消除「每个用例都忘 import」这类低级错误；
    3. 若目标文件已存在则覆盖（生成是幂等草稿，重复生成同一接口不产生重复文件）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = _safe_stem(module_name or test.name)
    if not stem.startswith("test_"):
        stem = "test_" + stem
    target = out_dir / f"{stem}.py"

    description = " ".join(test.description.split())  # 压掉换行，避免破坏注释
    header = _TEST_FILE_HEADER.format(method=test.method, path=test.path, description=description)
    body = test.code.rstrip() + "\n"
    target.write_text(header + body, encoding="utf-8")
    return target


def _safe_stem(name: str) -> str:
    """文件名清洗：去掉路径分隔与非法字符，避免 module_name 注入子目录。"""
    cleaned = re.sub(r'[^\w\-]', "_", name.strip())
    return cleaned.strip("_") or "test_generated"