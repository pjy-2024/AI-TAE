"""OpenAPI/Swagger 规范读取与归一化。

为什么单独做「归一化」：真实接口文档差异很大（Swagger 2.0 vs OpenAPI 3.x、
参数内联 vs $ref、requestBody 两种写法）。生成器只认本项目自己的 Operation 结构，
解析差异全部收敛在这一层 —— 换被测项目时生成逻辑不用改。

面试可讲：防腐层思想，把「外部格式差异」隔离在单一模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Operation:
    """一条可生成用例的 HTTP 操作（归一化后）。"""

    method: str  # GET/POST/PUT/DELETE...
    path: str  # 如 /api/todos
    operation_id: str = ""  # 用于命名用例
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None  # 归一化后的 body schema
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)  # status -> {description, schema}


def load_spec(path: str | Path) -> dict[str, Any]:
    """读取 OpenAPI 文件（按扩展名识别 JSON/YAML），并校验 openapi/swagger 版本字段。"""
    raise NotImplementedError("任务 2 实现：yaml.safe_load / json.load + 版本校验。")


def iter_operations(spec: dict[str, Any]) -> Iterator[Operation]:
    """把 spec.paths 展开成 Operation 列表（处理 $ref、请求体、参数归一化）。"""
    raise NotImplementedError("任务 2 实现：遍历 paths -> 过滤 http methods -> 归一化。")