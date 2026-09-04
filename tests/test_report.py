"""report 单元测试：用临时数据生成 HTML，断言关键内容与空态。"""

from __future__ import annotations

from aiae.report import build_report


def _write_junit(tmp_path):
    xml = '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite>'
    for name, st, t in [("test_a", "passed", "0.01"), ("test_b", "passed", "0.02"), ("test_c", "failed", "0.03")]:
        extra = "<failure/>" if st == "failed" else ("<error/>" if st == "error" else "")
        xml += f'<testcase classname="" name="{name}" time="{t}">{extra}</testcase>'
    xml += '</testsuite></testsuites>'
    p = tmp_path / "latest.xml"
    p.write_text(xml, encoding="utf-8")
    return p


def _write_v2(tmp_path):
    data = {"rows": [
        {"scenario": "S1", "old_locator": "input[name=username]", "new_locator": "input[name=user_name]",
         "outcome": "kv_hit", "source": "kv", "attempts": 0}
    ], "kv_stats": {"hits": 1, "misses": 0}, "rag_count": 1}
    p = tmp_path / "summary.json"
    p.write_text(__import__("json").dumps(data), encoding="utf-8")
    return p


def test_build_report_with_data(tmp_path):
    junit = _write_junit(tmp_path)
    summary = _write_v2(tmp_path)
    out = build_report(runs_xml=junit, v2_summary=summary, out=tmp_path / "r.html")
    html = out.read_text(encoding="utf-8")
    assert "AI-TAE 运行报告" in html
    assert "2/3" in html                        # V1 passed/total
    assert "test_c" in html                     # 用例明细
    assert "S1" in html and "user_name" in html  # V2 记录
    assert "data:image/png;base64," in html     # 图已内嵌


def test_build_report_empty_state(tmp_path):
    out = build_report(runs_xml=tmp_path / "none.xml", v2_summary=tmp_path / "none.json",
                       out=tmp_path / "empty.html")
    html = out.read_text(encoding="utf-8")
    assert "尚无执行记录" in html
    assert "尚无自愈记录" in html
