"""冒烟测试：验证骨架可导入、配置可加载、指标口径公式正确。

注意：这里面的数字只是单元测试的「公式样例」，用来验证计算正确，
与项目真实指标无关 —— 项目真实数字一律【待实测】，禁止编造。
"""

from __future__ import annotations

import aiae
from aiae.cli import main
from aiae.config import LLMConfig, PathsConfig
from aiae.metrics import Metrics


def test_version():
    assert aiae.__version__ == "0.1.0"


def test_llm_config_from_env_defaults():
    cfg = LLMConfig.from_env()
    assert cfg.model  # 非空（默认 deepseek-chat）
    assert cfg.max_retries >= 0
    assert cfg.temperature >= 0
    assert isinstance(cfg.is_configured(), bool)


def test_paths_config_points_to_data():
    paths = PathsConfig()
    assert paths.data_dir.endswith("data")
    assert paths.generated_dir.endswith(("data", "generated_tests"))


def test_metrics_rates_formula():
    # 样例：生成 10，可执行 8，通过 6，失败 1，报错 1
    m = Metrics(generated_count=10, executable_count=8, passed_count=6, failed_count=1, error_count=1)
    assert m.executable_rate == 0.8
    assert m.pass_rate == 0.75
    assert m.error_rate == 0.125


def test_metrics_empty_rates_are_zero():
    m = Metrics()
    assert m.executable_rate == 0.0
    assert m.pass_rate == 0.0
    assert m.error_rate == 0.0


def test_cli_selfcheck_ok(capsys):
    assert main(["selfcheck"]) == 0
    out = capsys.readouterr().out
    assert "AI-TAE 自检" in out