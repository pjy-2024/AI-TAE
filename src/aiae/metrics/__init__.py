"""质量指标与口径定义（V1 的第一个真实数字从这里来）。

先定口径再写实现，避免「数字对不上」：
- generated_count   : LLM 成功返回且通过结构校验、成功落盘的用例数（分母）
- executable_count  : 能被 pytest 正常收集并执行（无 import/语法错误）的用例数
- passed_count      : 首轮运行断言通过的用例数
- failed_count      : 执行了但断言失败（疑似真问题，待人工确认）
- error_count       : 用例本身报错（不可执行类）

两种口径都要保留（面试被追问「通过率多少」时先说明分母）：
- 可执行率 = executable / generated  —— 衡量「LLM 产出能不能跑」（生成质量）
- 通过率   = passed / executable     —— 衡量「跑起来的用例对不对」（运行质量）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Metrics:
    """质量指标（真实数字一律【待实测】；本类的单元测试数字只是公式样例）。"""

    generated_count: int = 0
    executable_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    llm_calls: int = 0  # LLM 实际调用次数（含重试，用于成本分析）
    llm_cost_usd: float = 0.0  # 按 token 用量 x 单价估算（真实记账后填）

    @property
    def executable_rate(self) -> float:
        """可执行率 = 可执行数 / 生成数（生成质量）。"""
        return self.executable_count / self.generated_count if self.generated_count else 0.0

    @property
    def pass_rate(self) -> float:
        """通过率 = 通过数 / 可执行数（运行质量）。"""
        return self.passed_count / self.executable_count if self.executable_count else 0.0

    @property
    def error_rate(self) -> float:
        """错误率 = 用例自身报错数 / 可执行数。"""
        return self.error_count / self.executable_count if self.executable_count else 0.0