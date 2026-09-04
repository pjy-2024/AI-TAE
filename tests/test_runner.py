"""runner 单元 + 集成测试：junitxml 解析 / conftest 确保 / 真实子进程跑 pytest。

这里的数字只是测试样例，与项目真实指标无关；真实指标一律【待实测】。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from aiae.runner import RunSummary, _conftest_source, _ensure_conftest, _parse_junit, run_pytest
from aiae.targets import TargetAdapter


def _write_xml(tmp_path, text):
    p = tmp_path / "junit.xml"
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- junit 解析

def test_parse_junit_counts_and_durations(tmp_path):
    xml = _write_xml(
        tmp_path,
        """<?xml version="1.0" encoding="utf-8"?>
        <testsuites>
          <testsuite>
            <testcase classname="test_ok" name="test_ok" time="0.01"/>
            <testcase classname="test_fail" name="test_fail" time="0.02">
              <failure message="assert False">assertion</failure>
            </testcase>
            <testcase classname="test_error" name="test_error" time="0.0">
              <error message="boom">traceback</error>
            </testcase>
            <testcase classname="test_skip" name="test_skip" time="0.0">
              <skipped message="skipped"/>
            </testcase>
          </testsuite>
        </testsuites>""",
    )
    s = _parse_junit(xml)
    assert s.total == 4
    assert s.passed == 1
    assert s.failed == 1
    assert s.errors == 1
    assert s.skipped == 1
    assert s.durations_s["test_fail::test_fail"] == 0.02


def test_parse_junit_empty_suite(tmp_path):
    xml = _write_xml(
        tmp_path,
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite/></testsuites>',
    )
    s = _parse_junit(xml)
    assert s.total == 0 and s.passed == 0 and s.failed == 0 and s.errors == 0


# ---------------------------------------------------------------- conftest 确保

def test_ensure_conftest_writes_once_and_preserves_edits(tmp_path):
    _ensure_conftest(tmp_path)
    first = (tmp_path / "conftest.py").read_text(encoding="utf-8")
    assert "def base_url()" in first          # 模板含 base_url fixture
    assert "def registered_user(" in first     # 模板含随机用户 fixture
    assert "def auth_headers(" in first        # 模板含鉴权头 fixture
    assert "from aiae.targets import get_adapter" in first  # 适配器驱动（框架无项目硬编码）
    assert "Aiae_pass_" not in first           # todo 特定数据已移出模板
    assert "todos/todo" not in first

    # 人工改过后再次 run 不应覆盖
    (tmp_path / "conftest.py").write_text("# 人工修改", encoding="utf-8")
    _ensure_conftest(tmp_path)
    assert (tmp_path / "conftest.py").read_text(encoding="utf-8") == "# 人工修改"


# ---------------------------------------------------------------- 真实子进程集成

def _write_case(dirpath, filename, code):
    p = dirpath / filename
    p.write_text(code, encoding="utf-8")
    return p


def test_run_pytest_real_collection(tmp_path):
    """真实跑一个样例目录：过 / 断言失败 / 自身报错（import 级 error）三类齐全。"""
    _write_case(tmp_path, "test_ok.py", (
        "def test_ok(base_url):\n"
        "    assert isinstance(base_url, str) and base_url\n"
    ))
    _write_case(tmp_path, "test_fail.py", (
        "def test_fail(base_url):\n"
        "    assert False\n"
    ))
    _write_case(tmp_path, "test_error.py", (
        "import no_such_module_xyz\n"  # import 级错误 -> junitxml <error>
        "def test_never(base_url):\n"
        "    assert True\n"
    ))

    summary = run_pytest(tmp_path)
    assert isinstance(summary, RunSummary)
    assert summary.total == 3
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.errors == 1
    assert summary.skipped == 0
    # conftest 被自动写入，base_url fixture 生效（test_ok 没报 fixture not found）
    assert (tmp_path / "conftest.py").exists()
    # durations 有值（至少 test_ok 有耗时）
    assert any("test_ok" in node for node in summary.durations_s)


def test_run_pytest_skipped_counted(tmp_path):
    _write_case(tmp_path, "test_skip.py", (
        "import pytest\n"
        "@pytest.mark.skip(reason='demo')\n"
        "def test_skip(base_url):\n"
        "    assert True\n"
    ))
    summary = run_pytest(tmp_path)
    assert summary.skipped == 1
    assert summary.passed == 0


def test_run_pytest_empty_dir(tmp_path):
    summary = run_pytest(tmp_path)
    assert summary.total == 0
    assert (tmp_path / "conftest.py").exists()  # 空目录也确保 conftest（便于后续追加用例）


def test_run_pytest_junit_xml_artifact(tmp_path):
    _write_case(tmp_path, "test_ok.py", "def test_ok(base_url):\n    assert base_url\n")
    junit = tmp_path / "runs" / "latest.xml"
    summary = run_pytest(tmp_path, junit_xml=junit)
    assert summary.passed == 1
    assert junit.exists()  # junit 落盘可审计
    root = ET.parse(str(junit)).getroot()
    assert root.tag == "testsuites"


def test_run_pytest_missing_dir_raises():
    with pytest.raises(FileNotFoundError):
        run_pytest("不存在的目录xyz")


# ---------------------------------------------------------------- conftest 按 auth_mode 渲染

class _NoneAdapter(TargetAdapter):
    """无认证被测的最小适配器（测试用；不入全局注册表）。"""

    name = "none_test"
    auth_mode = "none"
    resource = None


def test_conftest_none_mode_only_base_url():
    """auth_mode=none：conftest 只给 base_url，不注册登录/鉴权/资源 fixtures（退化）。"""
    src = _conftest_source(_NoneAdapter())
    assert "def base_url()" in src
    assert "ADAPTER = get_adapter()" in src
    assert "registered_user" not in src
    assert "fresh_user" not in src
    assert "auth_headers" not in src
    assert "_RESOURCE" not in src
    assert "import uuid" not in src


def test_ensure_conftest_none_mode_writes_degraded_template(tmp_path):
    _ensure_conftest(tmp_path, adapter=_NoneAdapter())
    text = (tmp_path / "conftest.py").read_text(encoding="utf-8")
    assert "def base_url()" in text
    assert "registered_user" not in text
    assert "auth_headers" not in text


def test_ensure_conftest_password_mode_still_full(tmp_path):
    """password 形态（缺省 todo）仍注册全套 fixtures（回归保护）。"""
    _ensure_conftest(tmp_path)
    text = (tmp_path / "conftest.py").read_text(encoding="utf-8")
    assert "def base_url()" in text
    assert "def registered_user(" in text
    assert "def fresh_user(" in text
    assert "def auth_headers(" in text
