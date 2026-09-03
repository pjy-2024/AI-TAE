"""parser.codec 单元测试：LLM 输出 -> 结构化 -> ast 静态校验 -> 落盘。

这里的数字只是测试断言（函数个数、错误条数等），与项目真实指标无关；
真实指标一律【待实测】。
"""

from __future__ import annotations

import ast
import json

import pytest

from aiae.parser.codec import (
    GENERATED_TESTS_JSON_EXAMPLE,
    GeneratedTest,
    parse_llm_output,
    validate_code,
    write_test_file,
)

OK_CODE = (
    'def test_create_todo(base_url):\n'
    '    resp = requests.post(f"{base_url}/todos", json={"title": "x"})\n'
    '    assert resp.status_code == 201\n'
)


def _test(name="test_create_todo", code=OK_CODE, **kw):
    return GeneratedTest(name=name, code=code, **kw)


# ---------------------------------------------------------------- parse_llm_output

def test_parse_clean_json():
    text = json.dumps(
        {
            "tests": [
                {
                    "name": "test_create_todo",
                    "description": "正常创建一条待办，返回 201",
                    "method": "POST",
                    "path": "/todos",
                    "code": OK_CODE,
                }
            ]
        }
    )
    tests = parse_llm_output(text)
    assert len(tests) == 1
    t = tests[0]
    assert t.name == "test_create_todo"
    assert t.method == "POST"
    assert t.path == "/todos"
    assert "def test_create_todo" in t.code


def test_parse_json_fence_and_chatter():
    # 模型常见行为：开头废话 + ```json 围栏 + 结尾客套
    noisy = (
        "好的，以下是生成的用例：\n"
        "```json\n"
        + json.dumps({"tests": [{"name": "test_ok", "code": OK_CODE}]})
        + "\n```\n请查收"
    )
    tests = parse_llm_output(noisy)
    assert [t.name for t in tests] == ["test_ok"]


def test_parse_braces_fallback():
    # 围栏剥不掉时（无围栏但有前言），截取首尾花括号兜底
    text = "这是结果 " + json.dumps({"tests": [{"name": "test_ok", "code": OK_CODE}]}) + " 以上"
    tests = parse_llm_output(text)
    assert tests[0].name == "test_ok"


def test_parse_example_constant_is_valid():
    # 骨架里的 Prompt 示例本身必须能被本解析器消费（自洽性冒烟）
    tests = parse_llm_output(GENERATED_TESTS_JSON_EXAMPLE)
    assert tests[0].name == "test_create_todo"


def test_parse_rejects_non_json():
    with pytest.raises(ValueError, match="合法 JSON"):
        parse_llm_output("抱歉，我没法生成代码。")


def test_parse_rejects_missing_tests_key():
    with pytest.raises(ValueError, match="tests 数组"):
        parse_llm_output(json.dumps({"foo": "bar"}))


def test_parse_rejects_empty_tests():
    with pytest.raises(ValueError, match="空"):
        parse_llm_output(json.dumps({"tests": []}))


def test_parse_rejects_item_missing_name():
    text = json.dumps({"tests": [{"code": OK_CODE}]})
    with pytest.raises(ValueError, match=r"tests\[0\].*name"):
        parse_llm_output(text)


def test_parse_rejects_name_without_test_prefix():
    text = json.dumps({"tests": [{"name": "create_todo", "code": OK_CODE}]})
    with pytest.raises(ValueError, match="test_"):
        parse_llm_output(text)


def test_parse_rejects_non_string_metadata():
    text = json.dumps({"tests": [{"name": "test_ok", "code": OK_CODE, "method": 123}]})
    with pytest.raises(ValueError, match="method 必须是字符串"):
        parse_llm_output(text)


# ---------------------------------------------------------------- validate_code

def test_validate_ok_single_test_function():
    assert validate_code(_test()) == []


def test_validate_allows_helper_function():
    # 非 test_ 的 helper 允许存在；只要求恰好一个 test_ 函数
    code = (
        "def _build_payload():\n"
        "    return {'title': 'x'}\n\n"
        "def test_create_todo(base_url):\n"
        '    resp = requests.post(f"{base_url}/todos", json=_build_payload())\n'
        "    assert resp.status_code == 201\n"
    )
    assert validate_code(_test(code=code)) == []


def test_validate_syntax_error():
    errors = validate_code(_test(code="def test_ok(:\n    pass"))
    assert any("语法错误" in e for e in errors)


def test_validate_no_test_function():
    errors = validate_code(_test(code="def helper():\n    return 1\n"))
    assert any("test_" in e for e in errors)


def test_validate_multiple_test_functions():
    code = "def test_a(base_url):\n    pass\n\ndef test_b(base_url):\n    pass\n"
    errors = validate_code(_test(name="test_a", code=code))
    assert any("恰好一个" in e for e in errors)


def test_validate_name_mismatch():
    errors = validate_code(_test(name="test_a", code="def test_b(base_url):\n    pass\n"))
    assert any("不一致" in e for e in errors)


# ---------------------------------------------------------------- write_test_file

def test_write_file_default_naming_and_header(tmp_path):
    t = _test(method="POST", path="/todos", description="正常创建待办")
    target = write_test_file(t, tmp_path)
    assert target.name == "test_create_todo.py"
    text = target.read_text(encoding="utf-8")
    assert "import requests" in text                # 统一文件头
    assert "method=POST" in text and "path=/todos" in text  # 元数据注释
    assert "def test_create_todo" in text           # 源码正文
    # 落盘文件本身仍可通过静态校验（端到端自洽）
    assert validate_code(t) == []
    ast.parse(text)


def test_write_file_module_name_prefix_and_sanitize(tmp_path):
    t = _test()
    target = write_test_file(t, tmp_path, module_name="auth")
    assert target.name == "test_auth.py"            # 不带 test_ 自动补前缀
    target2 = write_test_file(t, tmp_path, module_name="../evil")
    assert target2.parent == tmp_path               # 路径注入被清洗，不会逃出 out_dir
    assert target2.name == "test_evil.py"


def test_write_file_flattens_description_newlines(tmp_path):
    t = _test(description="第一行\n第二行")
    target = write_test_file(t, tmp_path)
    # 换行被压成空格，注释结构不被破坏
    text = target.read_text(encoding="utf-8")
    assert "第一行 第二行" in text
    assert "第一行\n第二行" not in text


def test_write_file_overwrite_idempotent(tmp_path):
    # 重复生成同一接口 -> 覆盖而不是追加（避免同名函数堆积）
    t1 = _test(name="test_a", code=OK_CODE)
    t2 = _test(name="test_a", code="def test_a(base_url):\n    assert True\n")
    p1 = write_test_file(t1, tmp_path)
    p2 = write_test_file(t2, tmp_path)
    assert p1 == p2
    files = list(tmp_path.glob("*.py"))
    assert len(files) == 1
    assert "assert True" in p2.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 端到端小链路

def test_end_to_end_example_to_file(tmp_path):
    """真实链路：LLM 文本 -> 结构化 -> 静态校验 -> 落盘。"""
    tests = parse_llm_output(GENERATED_TESTS_JSON_EXAMPLE)
    assert len(tests) == 1
    t = tests[0]
    assert validate_code(t) == []
    target = write_test_file(t, tmp_path)
    assert target.exists()
    ast.parse(target.read_text(encoding="utf-8"))