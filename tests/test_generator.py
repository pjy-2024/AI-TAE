"""generator 单元测试：编排 + 语义层限次重试 + 报告统计（fake LLM，不联网不烧钱）。

这里的数字只是测试断言，与项目真实指标无关；真实指标一律【待实测】。
"""

from __future__ import annotations

import json

from aiae.generator import (
    GenerationReport,
    build_messages,
    generate_for_operations,
)
from aiae.llm.client import LLMNonRetryableError, LLMResponse
from aiae.parser.openapi import Operation

GOOD_CODE = (
    "def test_create_todo(base_url):\n"
    '    resp = requests.post(f"{base_url}/todos", json={"title": "x"})\n'
    "    assert resp.status_code == 201\n"
)


def _good_json(name="test_create_todo", code=GOOD_CODE):
    return json.dumps({"tests": [{"name": name, "description": "d", "method": "POST", "path": "/todos", "code": code}]})


def _op(**kw):
    base = dict(
        method="POST",
        path="/todos",
        operation_id="create_todo",
        summary="Create todo",
        tags=["todos"],
        parameters=[],
        request_body=None,
        responses={"201": {"description": "created", "content": {}}},
    )
    base.update(kw)
    return Operation(**base)


class FakeLLM:
    """按剧本表演 complete()：每次调用弹出下一个 outcome（LLMResponse 或 Exception）。

    记录每次调用的 (messages, kwargs)，供断言「错误是否回传、json_mode 是否生效」。
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _resp(content):
    return LLMResponse(content=content, usage={}, latency_s=0.0, retries=0)


# ---------------------------------------------------------------- build_messages

def test_build_messages_structure_and_content():
    messages = build_messages(_op(), {"title": "todo_app", "version": "0.1.0"})
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "pytest" in messages[0]["content"]           # 系统提示含角色与约束
    assert '"tests"' in messages[0]["content"]          # 含 JSON Schema 示例
    user = messages[1]["content"]
    assert "todo_app" in user                            # spec_summary 透传
    assert "POST" in user and "/todos" in user           # 接口信息透传
    assert "create_todo" in user


def test_build_messages_trims_non_2xx_response_schema():
    op = _op(
        responses={
            "200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}},
            "422": {
                "description": "Validation Error",
                "content": {"application/json": {"schema": {"type": "object", "properties": {"detail": {}}}}},
            },
        }
    )
    messages = build_messages(op, {})
    user = messages[1]["content"]
    assert '"description": "ok"' in user                # 2xx 保留
    assert "detail" not in user                         # 4xx schema 已精简（只留 description）
    assert "Validation Error" in user


# ---------------------------------------------------------------- generate_for_operations

def test_generate_success_single(tmp_path):
    fake = FakeLLM([_resp(_good_json())])
    report = generate_for_operations([_op()], out_dir=tmp_path, client=fake)
    assert isinstance(report, GenerationReport)
    assert report.requested == 1
    assert report.succeeded == 1
    assert report.failed == []
    assert report.retry_counts == [0]                   # 一次成功，无重试
    files = list(tmp_path.glob("*.py"))
    assert len(files) == 1
    assert files[0].name == "test_create_todo.py"       # 一 operation 一文件
    # fake 收到的调用带 json_mode=True
    assert fake.calls[0][1]["json_mode"] is True


def test_generate_retries_on_structure_error_with_feedback(tmp_path):
    fake = FakeLLM([_resp("这不是 JSON"), _resp(_good_json())])
    report = generate_for_operations([_op()], out_dir=tmp_path, client=fake)
    assert report.succeeded == 1
    assert report.retry_counts == [1]                   # 第一次结构失败 -> 改写一次成功
    # 第二次调用的对话末尾应带「结构校验失败」的精确错误
    second_messages = fake.calls[1][0]
    assert second_messages[-1]["role"] == "user"
    assert "结构校验失败" in second_messages[-1]["content"]
    assert second_messages[-2]["role"] == "assistant"   # 模型坏输出也在上下文里


def test_generate_retries_on_code_error_with_feedback(tmp_path):
    bad_code = "def test_wrong_name(base_url):\n    pass\n"  # 函数名与 name 不一致 -> ast 校验失败
    bad_json = json.dumps({"tests": [{"name": "test_create_todo", "code": bad_code}]})
    fake = FakeLLM([_resp(bad_json), _resp(_good_json())])
    report = generate_for_operations([_op()], out_dir=tmp_path, client=fake)
    assert report.succeeded == 1
    assert report.retry_counts == [1]
    second = fake.calls[1][0]
    assert "代码静态校验失败" in second[-1]["content"]
    assert "test_wrong_name" in second[-1]["content"]   # 精确到函数名不一致


def test_generate_exhausts_retries(tmp_path):
    fake = FakeLLM([_resp("坏输出")] * 3)                # 首次 + 2 次改写全失败
    report = generate_for_operations([_op()], out_dir=tmp_path, client=fake)
    assert report.succeeded == 0
    assert report.retry_counts == []
    assert len(report.failed) == 1
    assert "create_todo" in report.failed[0]
    assert "重试 2 次后仍失败" in report.failed[0]
    assert list(tmp_path.glob("*.py")) == []            # 失败不落盘


def test_generate_llm_error_recorded_and_batch_continues(tmp_path):
    # 两个 operation：第一个 LLM 调用直接失败（如未配 key），第二个成功 -> 批处理不中断
    op_a = _op(operation_id="op_a", path="/a")
    op_b = _op(operation_id="op_b", path="/b")
    fake = FakeLLM([LLMNonRetryableError("未配置 API_KEY"), _resp(_good_json())])
    report = generate_for_operations([op_a, op_b], out_dir=tmp_path, client=fake)
    assert report.requested == 2
    assert report.succeeded == 1
    assert len(report.failed) == 1
    assert "op_a" in report.failed[0]
    assert "LLM 调用失败" in report.failed[0]
    assert report.retry_counts == [0]                   # 只有 op_b 成功


def test_generate_multiple_tests_multiple_files(tmp_path):
    # 一个 operation 返回两条合法用例 -> succeeded=2，逐条独立文件（避免同文件覆盖丢数据）
    code2 = (
        GOOD_CODE
        .replace("def test_create_todo(", "def test_create_todo_missing_title(", 1)
        .replace("assert resp.status_code == 201", "assert resp.status_code == 422")
    )
    two = json.dumps(
        {
            "tests": [
                {"name": "test_create_todo", "code": GOOD_CODE},
                {"name": "test_create_todo_missing_title", "code": code2},
            ]
        }
    )
    fake = FakeLLM([_resp(two)])
    report = generate_for_operations([_op()], out_dir=tmp_path, client=fake)
    assert report.succeeded == 2
    files = sorted(p.name for p in tmp_path.glob("*.py"))
    assert files == ["test_create_todo.py", "test_create_todo_missing_title.py"]
    texts = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.glob("*.py")}
    assert "def test_create_todo(" in texts["test_create_todo.py"]
    assert "def test_create_todo_missing_title(" in texts["test_create_todo_missing_title.py"]


def test_generate_empty_operations(tmp_path):
    fake = FakeLLM([])
    report = generate_for_operations([], out_dir=tmp_path, client=fake)
    assert report.requested == 0
    assert report.succeeded == 0
    assert report.failed == []
    assert report.retry_counts == []