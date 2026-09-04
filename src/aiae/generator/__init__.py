"""用例生成编排（V1 主流程）：Operation -> Prompt -> LLM -> 校验重试 -> 落盘。

刻意不引 LangChain：手写 pipeline 每一环都可控、可讲、可测。
LLM 在这里只做「草案生成」，质量门禁（语法/结构/可执行）由本地代码保证。

两层重试语义不同（面试易混，先分清）：
- llm/client 的重试 = HTTP 层：429/5xx 网络退避，重试「这次请求」；
- 本模块的重试 = 语义层：LLM 输出不合格 -> 把精确错误追加进对话让模型「看着错改」，
  重试「这次生成」。语义层严格限次（_GENERATION_RETRY_LIMIT），防重复计费。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aiae.config import LLMConfig
from aiae.llm.client import LLMClient, LLMError
from aiae.parser.codec import (
    GENERATED_TESTS_JSON_EXAMPLE,
    GeneratedTest,
    parse_llm_output,
    validate_code,
    write_test_file,
)
from aiae.parser.openapi import Operation
from aiae.targets import TargetAdapter, get_adapter

# 单个 operation 的「LLM 产出不合格 -> 带错误信息改写」上限（首次 + 最多 2 次改写）
_GENERATION_RETRY_LIMIT = 2


@dataclass
class GenerationReport:
    """一次批量生成的结果（用于统计与日志）。"""

    requested: int = 0  # 请求生成的 operation 数
    succeeded: int = 0  # 校验通过并成功落盘数
    failed: list[str] = field(default_factory=list)  # operation_id -> 失败原因（含重试耗尽）
    retry_counts: list[int] = field(default_factory=list)  # 每次生成的 LLM 重试次数


# ---------------------------------------------------------------- Prompt 构造

_SYSTEM_PROMPT = f"""你是一名资深接口测试工程师。根据给定的 OpenAPI 接口信息，编写可直接运行的 pytest 用例草稿（requests 风格）。

硬性要求：
1. 只输出一个 JSON 对象（不要 Markdown 围栏、不要任何解释文字），结构严格如下：
{GENERATED_TESTS_JSON_EXAMPLE}
2. tests 数组通常 1 条；如需多场景，每条都必须是独立的 test_ 函数。
3. code 字段规则：
   - 恰好一个以 test_ 开头的函数，签名形如 def test_xxx(base_url):
   - 使用 requests 库；不要写 import（文件头由落盘层统一提供）
   - 请求路径写 f"{{base_url}}/实际路径"（base_url 是 pytest fixture，不含结尾斜杠）
   - JSON 请求体用 requests.post(url, json=...)；表单请求体用 requests.post(url, data=...)
   - 用 assert 断言状态码，必要时断言响应体关键字段
   - 若请求会创建/修改数据，业务字段（用户名、邮箱、标题等）用随机唯一值，
     例如 username=f"u{{uuid.uuid4().hex[:8]}}"、title=f"t-{{uuid.uuid4().hex[:6]}}"，
     保证用例重复执行不冲突（文件头已 import uuid）
4. name 必须与 code 里的函数名完全一致。
5. 状态码纪律：断言的状态码一律以接口信息里 responses 声明的为准；若用例内部先调用其它接口准备数据，其状态码同样以对应接口 responses 为准。不要凭 REST 惯例假设（例如创建成功就默认断言 201）。
"""


def _op_for_prompt(operation: Operation) -> dict[str, Any]:
    """把 Operation 序列化成 Prompt 用的紧凑结构。

    取舍：成功响应（2xx）保留完整 schema（模型写断言要用）；4xx/5xx 错误响应
    只留 description —— 其嵌套校验错误 schema 很占 token，但对写用例断言价值低。
    """
    data = asdict(operation)
    responses: dict[str, Any] = {}
    for status, item in (data.get("responses") or {}).items():
        if str(status).startswith("2"):
            responses[status] = item
        else:
            responses[status] = {"description": (item or {}).get("description", "")}
    data["responses"] = responses
    return data


def _interface_instruction(operation: Operation, adapter: TargetAdapter) -> str:
    """按接口类型给 LLM 的鉴权/登录/资源指令（与 runner conftest 的 fixture 配套）。

    核心只负责「识别接口类型」（基于 OpenAPI 特征的通用规则）；被测特定的
    「fixture 怎么用」文案一律从适配器取（TargetAdapter 的 login_instruction /
    auth_instruction / resource_id_instruction 钩子）——被测假设全部收敛在 targets 层。

    优先级（互斥，按特征识别接口类型；auth_mode="none" 时全部按开放接口退化）：
    1. 登录类：password 形态 + 无 security + 表单请求体（OAuth2 password 流特征）
       -> 适配器 login_instruction（todo 用 fresh_user，每次新建防共享污染）；
    2. 资源 id 类：需认证且 path 形参以 id 结尾（如 {todo_id}）且适配器声明了 resource
       -> 适配器 resource_id_instruction（todo 用 auth_headers + created_todo_id）；
    3. 普通需认证 -> 适配器 auth_instruction（auth_headers）；
    4. 其余开放接口无附加指令。
    """
    if adapter.auth_mode == "none":
        # 无认证被测：没有登录/鉴权概念，接口全部按开放接口处理（框架可退化）
        return ""

    request_body = operation.request_body or {}
    media_types = (request_body.get("content") or {}).keys()
    form_like = any("x-www-form-urlencoded" in m or "multipart" in m for m in media_types)

    # 1) 登录类（无 security + form 请求体）-> 适配器文案（todo: fresh_user）
    if not operation.security and form_like:
        return adapter.login_instruction()
    if not operation.security:
        return ""

    # 2) 资源 id 类：需认证 + path 形参名以 id 结尾 + 适配器有资源语义
    id_params = [
        p.get("name")
        for p in operation.parameters
        if p.get("in") == "path" and str(p.get("name", "")).lower().endswith("id")
    ]
    if id_params and adapter.resource is not None:
        return adapter.resource_id_instruction(id_params)

    # 3) 普通需认证（含「有 id 形参但适配器无资源语义」的项目）
    return adapter.auth_instruction()


def build_messages(
    operation: Operation,
    spec_summary: dict[str, Any],
    base_url_hint: str = "",
    adapter: TargetAdapter | None = None,
) -> list[dict[str, Any]]:
    """构造发给 LLM 的 messages：系统提示（输出 JSON Schema 约束）+ 用户提示（接口信息）。

    提示词模板见 docs/v1-technical-design.md §5；要求严格输出结构化 JSON。
    adapter 缺省取当前 AITAE_TARGET（与 runner conftest 同一选择源）。
    """
    adapter = adapter or get_adapter()
    title = spec_summary.get("title", "被测服务")
    version = spec_summary.get("version", "")
    op_text = json.dumps(_op_for_prompt(operation), ensure_ascii=False, indent=1)

    user_lines = [f"被测服务：{title}（version={version}）"]
    if base_url_hint:
        user_lines.append(f"服务地址提示：{base_url_hint}（仅参考，测试里统一用 base_url fixture）")
    instruction = _interface_instruction(operation, adapter)
    if instruction:
        user_lines.append(instruction)
    user_lines.append("请为以下接口生成用例：")
    user_lines.append(op_text)

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def _with_feedback(
    messages: list[dict[str, Any]],
    assistant_content: str,
    feedback: str,
) -> list[dict[str, Any]]:
    """把「模型上次的坏输出 + 精确错误」追加进对话，供模型对照修正后重写。"""
    return [
        *messages,
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": f"上面的输出不合格，请修正后重新输出完整 JSON。错误原因：{feedback}"},
    ]


# ---------------------------------------------------------------- 编排

def _generate_one(
    operation: Operation,
    out_dir: Path,
    client: LLMClient,
    spec_summary: dict[str, Any],
    *,
    adapter: TargetAdapter | None = None,
) -> tuple[int, int, str | None]:
    """单个 operation：返回 (成功落盘数, 重试次数, 失败原因或 None)。

    失败原因非 None 时前两个字段无意义（由调用方记入 report.failed）。
    """
    messages = build_messages(operation, spec_summary, adapter=adapter)
    last_feedback = ""
    for attempt in range(_GENERATION_RETRY_LIMIT + 1):
        try:
            response = client.complete(messages, json_mode=True)
        except LLMError as exc:
            return 0, attempt, f"LLM 调用失败：{exc}"

        try:
            parsed = parse_llm_output(response.content)
        except ValueError as exc:
            last_feedback = f"结构校验失败：{exc}"
            messages = _with_feedback(messages, response.content, last_feedback)
            continue

        valid: list[GeneratedTest] = []
        code_errors: list[str] = []
        for test in parsed:
            errors = validate_code(test)
            if errors:
                code_errors.append(f"{test.name}: {'；'.join(errors)}")
            else:
                valid.append(test)
        if code_errors:
            last_feedback = "代码静态校验失败：" + "；".join(code_errors)
            messages = _with_feedback(messages, response.content, last_feedback)
            continue

        # 校验全过 -> 逐条落盘。文件名用「operation_id + test.name」唯一键：
        # - operation_id 全局唯一 -> 不同接口即使 LLM 起了同名 test 函数也不互相覆盖（真实踩过：19 成功只落 18 文件）；
        # - test.name 区分同一接口的多场景 -> 不互相覆盖；
        # - 同一接口同一场景重跑 = 同文件覆盖写（草稿幂等）。
        for test in valid:
            write_test_file(test, out_dir, module_name=f"{operation.operation_id}__{test.name}")
        return len(valid), attempt, None

    return 0, _GENERATION_RETRY_LIMIT, f"重试 {_GENERATION_RETRY_LIMIT} 次后仍失败：{last_feedback}"


def generate_for_operations(
    operations: list[Operation],
    *,
    out_dir: Path,
    spec_summary: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    adapter: TargetAdapter | None = None,
) -> GenerationReport:
    """逐个生成 -> 校验 ->（带错误信息限次重试）-> 落盘。

    容错：单个 operation 失败只记入 report.failed，不中断整批（批处理原则）。
    client 可注入（测试用 fake）；缺省从环境配置创建真实客户端。
    """
    if client is None:
        client = LLMClient(LLMConfig.from_env())
    spec_summary = spec_summary or {}
    out_dir = Path(out_dir)

    report = GenerationReport(requested=len(operations))
    for operation in operations:
        succeeded_count, retries, error = _generate_one(
            operation, out_dir, client, spec_summary, adapter=adapter
        )
        if error is not None:
            report.failed.append(f"{operation.operation_id}: {error}")
        else:
            report.succeeded += succeeded_count
            report.retry_counts.append(retries)
    return report