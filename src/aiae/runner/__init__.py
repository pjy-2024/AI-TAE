"""pytest 执行与结果收集：跑「已生成的用例」，产出通过/失败/错误统计。

为什么用 pytest 而不是自己写执行器：pytest 生态成熟、报告标准（junitxml），
且 V2 需要的 fixture/hook 机制是现成的 —— 面试讲「站在生态上，不自造轮子」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunSummary:
    """一次 pytest 运行的结果汇总。"""

    total: int = 0
    passed: int = 0
    failed: int = 0  # 断言失败（执行了但结果不符，疑似真问题）
    errors: int = 0  # 用例本身报错（import 错误/异常），属「不可执行」口径
    skipped: int = 0
    durations_s: dict[str, float] = field(default_factory=dict)  # test nodeid -> 耗时


def run_pytest(generated_dir: Path, *, junit_xml: Path | None = None) -> RunSummary:
    """编程式调用 pytest 收集结果（pytest.main + junitxml 解析，或插件钩子）。"""
    raise NotImplementedError("任务 2 实现。")