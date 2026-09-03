"""用例生成编排（V1 主流程）：Operation -> Prompt -> LLM -> 校验重试 -> 落盘。

刻意不引 LangChain：手写 pipeline 每一环都可控、可讲、可测。
LLM 在这里只做「草案生成」，质量门禁（语法/结构/可执行）由本地代码保证。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiae.parser.codec import GeneratedTest
from aiae.parser.openapi import Operation


@dataclass
class GenerationReport:
    """一次批量生成的结果（用于统计与日志）。"""

    requested: int = 0  # 请求生成的 operation 数
    succeeded: int = 0  # 校验通过并成功落盘数
    failed: list[str] = field(default_factory=list)  # operation_id -> 失败原因（含重试耗尽）
    retry_counts: list[int] = field(default_factory=list)  # 每次生成的 LLM 重试次数


def build_messages(
    operation: Operation,
    spec_summary: dict[str, Any],
    base_url_hint: str = "",
) -> list[dict[str, Any]]:
    """构造发给 LLM 的 messages：系统提示（输出 JSON Schema 约束）+ 用户提示（接口信息）。

    提示词模板见 docs/v1-technical-design.md §5；要求严格输出结构化 JSON。
    """
    raise NotImplementedError("任务 2 实现：提示词模板 + 接口信息序列化。")


def generate_for_operations(
    operations: list[Operation],
    *,
    out_dir: Path,
) -> GenerationReport:
    """逐个（或分批）生成 -> 校验 ->（带错误信息限次重试）-> 落盘。"""
    raise NotImplementedError("任务 2 实现：串起 llm.client + parser.codec，加限次重试。")