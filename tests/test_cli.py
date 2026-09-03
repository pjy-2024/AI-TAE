"""cli 单元测试：参数接线 + 输出（monkeypatch fake LLM / run_pytest，不联网）。

这里的数字只是测试样例（如可执行率 7/8=87.5%），验证输出格式与口径计算，
与项目真实指标无关 —— 真实指标一律【待实测】。
"""

from __future__ import annotations

import json

from aiae.cli import main
from aiae.config import LLMConfig
from aiae.llm.client import LLMResponse
from aiae.runner import RunSummary

GOOD_CODE = (
    "def test_create_x(base_url):\n"
    '    resp = requests.post(f"{base_url}/x", json={"a": 1})\n'
    "    assert resp.status_code == 200\n"
)


def _good_json():
    return json.dumps({"tests": [{"name": "test_create_x", "code": GOOD_CODE}]})


def _write_mini_spec(path):
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "mini", "version": "1.0.0"},
        "paths": {
            "/x": {
                "post": {
                    "operationId": "create_x",
                    "summary": "Create x",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


class FakeLLM:
    """fake LLMClient：构造接受 config，complete 恒返回合法用例 JSON。"""

    def __init__(self, config):
        self.config = config

    def complete(self, messages, **kwargs):
        return LLMResponse(content=_good_json())


# ---------------------------------------------------------------- generate

def test_generate_without_key_returns_1(monkeypatch, capsys):
    monkeypatch.setattr(
        "aiae.cli.LLMConfig.from_env", staticmethod(lambda: LLMConfig(api_key=""))
    )
    rc = main(["generate", "--openapi", "samples/openapi/todo_app-openapi.json"])
    assert rc == 1
    assert "AITAE_LLM_API_KEY" in capsys.readouterr().out


def test_generate_missing_openapi_returns_1(capsys):
    rc = main(["generate", "--openapi", "不存在的文件.json"])
    assert rc == 1
    assert "不存在" in capsys.readouterr().out


def test_generate_success_with_fake_llm(tmp_path, monkeypatch, capsys):
    spec = _write_mini_spec(tmp_path / "spec.json")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        "aiae.cli.LLMConfig.from_env",
        staticmethod(lambda: LLMConfig(api_key="sk-test-fake")),
    )
    monkeypatch.setattr("aiae.cli.LLMClient", FakeLLM)

    rc = main(["generate", "--openapi", str(spec), "--out-dir", str(out_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "succeeded = 1" in out
    files = list(out_dir.glob("test_*.py"))
    assert len(files) == 1
    assert "def test_create_x" in files[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------- run

def test_run_prints_metrics_with_documented_denominator(tmp_path, monkeypatch, capsys):
    # 样例：收集 8（passed 6 / failed 1 / errors 1）-> 可执行=7，通过率=6/7
    monkeypatch.setattr(
        "aiae.cli.run_pytest",
        lambda *a, **kw: RunSummary(total=8, passed=6, failed=1, errors=1),
    )
    rc = main(["run", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "可执行率" in out and "87.5%" in out          # 7/8
    assert "通过率" in out and "85.7%" in out            # 6/7（分母=可执行）
    assert "口径" in out                                 # 报数先报口径


def test_run_empty_dir_reports_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "aiae.cli.run_pytest", lambda *a, **kw: RunSummary(total=0)
    )
    rc = main(["run", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "没有收集到用例" in out


def test_run_missing_dir_returns_1(capsys):
    rc = main(["run", "--dir", "不存在的用例目录"])
    assert rc == 1
    assert "请先执行 aiae generate" in capsys.readouterr().out


# ---------------------------------------------------------------- 占位命令

def test_placeholder_commands_return_1(capsys):
    assert main(["heal"]) == 1
    assert "尚未实现" in capsys.readouterr().out
    assert main(["judge"]) == 1