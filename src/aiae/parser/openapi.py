"""OpenAPI/Swagger 规范读取与归一化。

为什么单独做「归一化」：真实接口文档差异很大（Swagger 2.0 vs OpenAPI 3.x、
参数内联 vs $ref、requestBody 两种写法）。生成器只认本项目自己的 Operation 结构，
解析差异全部收敛在这一层 —— 换被测项目时生成逻辑不用改。

面试可讲：防腐层思想，把「外部格式差异」隔离在单一模块。
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

# 可生成用例的 HTTP 方法；path 对象上的其余键（parameters/summary/description 等）不是 operation
HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options", "trace"})


@dataclass
class Operation:
    """一条可生成用例的 HTTP 操作（归一化后）。

    归一化收敛点（目标：generator 只认本结构，不感知外部文档差异）：
    1. path 级 parameters 已合并进 operation（OpenAPI 允许写在 path 对象上）；
    2. schema 里的 $ref 已递归解析成真实结构 —— 生成器要直接读字段，
       不能留一个指向 components 的指针让它自己猜；
    3. request_body / responses 保留 media_type —— json 与 form 的请求构造方式不同；
    4. security 取 operation 级（缺省回退文档顶层）并原样保留，
       生成器据此判断「这接口要不要先登录拿 token」。
    """

    method: str  # GET/POST/PUT/DELETE...（统一大写）
    path: str  # 模板路径，如 /todos/todo/{todo_id}（{x} 占位符保留，由生成器填值）
    operation_id: str = ""  # 用于命名用例；缺失时由 method+path 兜底生成
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None  # {"required": bool, "content": {media_type: {"schema": {...}}}}
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)  # status -> {description, content}
    security: list[dict[str, Any]] = field(default_factory=list)  # 非空 = 该接口需要认证


# ---------------------------------------------------------------- 读取

def load_spec(path: str | Path) -> dict[str, Any]:
    """读取 OpenAPI 文件（按扩展名识别 JSON/YAML），并校验版本字段。

    OpenAPI 3.x（openapi 字段）与 Swagger 2.0（swagger 字段）都接受；
    2.0 由 iter_operations 桥接成 3.x 形状后走同一套归一化（见 _bridge_swagger2_to_openapi3）。
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 OpenAPI 文件: {p}（{exc}）") from exc

    suffix = p.suffix.lower()
    if suffix == ".json":
        try:
            spec = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败: {p}（第 {exc.lineno} 行: {exc.msg}）") from exc
    elif suffix in {".yaml", ".yml"}:
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML 解析失败: {p}（{exc}）") from exc
    else:
        raise ValueError(f"无法识别的 OpenAPI 文件扩展名: {suffix!r}（支持 .json/.yaml/.yml）: {p}")

    if not isinstance(spec, dict):
        raise ValueError(f"OpenAPI 文档顶层必须是对象（dict），实际是 {type(spec).__name__}: {p}")
    if not isinstance(spec.get("paths"), dict):
        raise ValueError(f"OpenAPI 文档缺少 paths 对象（或 paths 不是对象）: {p}")

    if "openapi" in spec:
        version = str(spec["openapi"])
        if not version.startswith("3."):
            raise ValueError(f"暂只支持 OpenAPI 3.x，文档声明 openapi={version}: {p}")
    elif "swagger" in spec:
        version = str(spec["swagger"])
        if not version.startswith("2."):
            raise ValueError(f"暂只支持 Swagger 2.x，文档声明 swagger={version}: {p}")
    else:
        raise ValueError(f"无法识别文档版本：既无 openapi 也无 swagger 字段: {p}")
    return spec


# ---------------------------------------------------------------- $ref 解析

def _deref(ref: str, spec: dict[str, Any], stack: tuple[str, ...]) -> Any:
    """按 JSON Pointer 取出 spec 内目标节点，并递归展开其中的 $ref。

    取舍：
    - 只支持文档内引用（#/...）；外部文件引用（http://、相对路径等）明确报错，
      真实被测项目几乎不用，宁可报错不静默；
    - 循环引用用 stack 检测：同一 ref 出现两次即报错（防御，真实文档罕见）。
    """
    if not ref.startswith("#/"):
        raise ValueError(f"暂不支持文档外引用（只支持 #/ 开头的文档内引用）: {ref!r}")
    if ref in stack:
        raise ValueError(f"检测到 $ref 循环引用: {' -> '.join((*stack, ref))}")
    parts = [part for part in ref.split("/") if part]
    if parts and parts[0] == "#":
        parts = parts[1:]  # "#/a/b" 切分后首段是 "#"，去掉才是真正的指针路径
    node: Any = spec
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"$ref 指向的节点不存在: {ref!r}")
        node = node[part]
    return _resolve(node, spec, (*stack, ref))


def _resolve(node: Any, spec: dict[str, Any], stack: tuple[str, ...] = ()) -> Any:
    """深拷贝 node，并把沿途所有 $ref 就地替换成真实结构（递归展开）。

    注意：返回的是「展开后的新对象」，不会改动调用方传入的 spec ——
    同一个 spec 可以安全地 iter_operations 多次。
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            return _deref(ref, spec, stack)
        return {key: _resolve(value, spec, stack) for key, value in node.items()}
    if isinstance(node, list):
        return [_resolve(item, spec, stack) for item in node]
    return node


# ---------------------------------------------------------------- 归一化

def _as_list(value: Any) -> list[Any]:
    """容忍 None / 单对象 / 列表三种写法，统一成列表。"""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _normalize_parameter(raw: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单条参数归一化：解析可能的 $ref，只保留构造请求需要的字段。

    required 缺省规则：path 参数必填 True；query/header 按文档（缺省 False）。
    schema 里的 $ref 就地展开（参数 schema 也可能指向 components）。
    """
    resolved = _resolve(raw, spec)
    schema = _resolve(resolved.get("schema", {}), spec)
    loc = str(resolved.get("in", ""))
    required = resolved.get("required")
    if required is None:
        required = loc == "path"
    return {
        "name": str(resolved.get("name", "")),
        "in": loc,
        "required": bool(required),
        "description": str(resolved.get("description", "")),
        "schema": schema,
    }


def _merge_parameters(path_params: Any, op_params: Any, spec: dict[str, Any]) -> list[dict[str, Any]]:
    """合并 path 级与 operation 级参数；同名同 in 时 operation 级覆盖。

    OpenAPI 允许把公共参数写在 path 对象上、对下面所有方法生效 ——
    不合并的话同一参数会出现两次，生成器会困惑。
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in (*_as_list(path_params), *_as_list(op_params)):
        if not isinstance(raw, dict):
            continue  # 宽容跳过噪音节点
        normalized = _normalize_parameter(raw, spec)
        merged[(normalized.get("in", ""), normalized.get("name", ""))] = normalized
    return list(merged.values())


def _normalize_request_body(raw: Any, spec: dict[str, Any]) -> dict[str, Any] | None:
    """requestBody 归一化：{"required": bool, "content": {media_type: {"schema": {...}}}}。

    media_type 必须保留：application/json 用 requests.json=，而
    application/x-www-form-urlencoded 用 requests.data=，构造方式不同。
    无 content 的 requestBody 没有构造价值，归一化为 None。
    """
    if raw is None:
        return None
    body = _resolve(raw, spec)
    if not isinstance(body, dict):
        return None
    content_raw = body.get("content")
    if not isinstance(content_raw, dict) or not content_raw:
        return None
    content = {
        str(media_type): {"schema": _resolve(item.get("schema", {}), spec)}
        for media_type, item in content_raw.items()
        if isinstance(item, dict)
    }
    if not content:
        return None
    return {"required": bool(body.get("required", False)), "content": content}


def _normalize_responses(raw: Any, spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """responses 归一化：status -> {"description": str, "content": {media_type: {schema}}}。

    空 schema {} 表示「无响应体」，生成器据此决定要不要断言 body 结构；
    无 content 的响应（如 204）归一化为空 content。
    """
    result: dict[str, dict[str, Any]] = {}
    responses = _resolve(raw, spec) if isinstance(raw, dict) else {}
    if not isinstance(responses, dict):
        return result
    for status, item in responses.items():
        if not isinstance(item, dict):
            continue
        content: dict[str, dict[str, Any]] = {}
        content_raw = item.get("content")
        if isinstance(content_raw, dict):
            content = {
                str(media_type): {"schema": _resolve(sub.get("schema", {}), spec)}
                for media_type, sub in content_raw.items()
                if isinstance(sub, dict)
            }
        result[str(status)] = {"description": str(item.get("description", "")), "content": content}
    return result


def _fallback_operation_id(method: str, path: str) -> str:
    """operationId 缺失时的兜底命名：method + 路径转 snake_case。

    只做可读兜底；真实文档（如 FastAPI 自动生成）通常自带 operationId。
    """
    slug = "".join(ch if ch.isalnum() else "_" for ch in path.strip("/")).strip("_")
    return f"{method.lower()}_{slug}"


def _normalize_operation(
    method: str,
    path: str,
    op: dict[str, Any],
    path_params: Any,
    top_security: Any,
    spec: dict[str, Any],
) -> Operation:
    """把 path 下的单个 method 节点归一化成 Operation（见 Operation docstring）。"""
    parameters = _merge_parameters(path_params, op.get("parameters", []), spec)
    operation_id = str(op.get("operationId") or _fallback_operation_id(method, path))
    # security 用「键是否存在」判断：显式 [] 表示「覆盖为无需认证」，此时不回退顶层
    security = op["security"] if "security" in op else top_security
    return Operation(
        method=method.upper(),
        path=path,
        operation_id=operation_id,
        summary=str(op.get("summary", "")),
        tags=[str(t) for t in _as_list(op.get("tags"))],
        parameters=parameters,
        request_body=_normalize_request_body(op.get("requestBody"), spec),
        responses=_normalize_responses(op.get("responses", {}), spec),
        security=_resolve(security, spec) if isinstance(security, list) else [],
    )


# ---------------------------------------------------------------- Swagger 2.0 桥接

# formData 参数转 schema 时要剔除的「参数元字段」（其余键如 type/format/enum 就是 schema 字段）
_SWAGGER2_PARAM_META = frozenset({"name", "in", "required", "description", "collectionFormat"})


def _bridge_swagger2_to_openapi3(spec: dict[str, Any]) -> dict[str, Any]:
    """Swagger 2.0 -> OpenAPI 3.x 形状的最小桥接，复用同一套归一化。

    为什么桥接而不是双轨：归一化只实现一份（OpenAPI 3.x），2.0 的差异在这里
    翻译掉，iter_operations 无感知 —— 单一职责，避免两套逻辑漂移对不上。

    桥接的差异（够生成器用即可，不追求完整规范翻译）：
    1. 组件区 definitions -> components/schemas，并重写所有 $ref 前缀；
    2. 没有 requestBody：in: body / in: formData 是 parameters 里的两项 -> 转 requestBody；
    3. 响应 schema 直接挂在 response 对象上 -> 包成 content.<media>.schema；
    4. media type 由 consumes/produces 声明 -> 落到 content 的键上（缺省 json）。

    host/basePath/schemes 是「服务地址」问题，不属于接口形态，本层不处理。
    """
    out = copy.deepcopy(spec)          # 绝不改动调用方传入的 spec
    out["openapi"] = "3.0.3"           # 桥接完成后按 3.x 形状处理
    out.pop("swagger", None)

    definitions = out.pop("definitions", None)
    out["components"] = {"schemas": definitions} if isinstance(definitions, dict) else {}
    _rewrite_refs(out)                 # 先重写 $ref，后面展开时才能找到新位置

    consumes = out.get("consumes")
    produces = out.get("produces")
    for path_item in (out.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            op = path_item.get(method)
            if isinstance(op, dict):
                _bridge_operation(
                    op,
                    path_item.get("consumes") or consumes,
                    path_item.get("produces") or produces,
                )
    return out


def _rewrite_refs(node: Any) -> None:
    """就地重写 $ref：2.0 的 #/definitions/... -> #/components/schemas/..."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/definitions/"):
            node["$ref"] = "#/components/schemas/" + ref[len("#/definitions/") :]
        for value in node.values():
            _rewrite_refs(value)
    elif isinstance(node, list):
        for item in node:
            _rewrite_refs(item)


def _bridge_operation(op: dict[str, Any], consumes: Any, produces: Any) -> None:
    """单个 operation 的 2.0 -> 3.x 翻译（就地修改桥接副本）。

    注意：2.0 规范不允许同一 operation 同时有 in: body 和 in: formData，
    这里按 if/elif 处理；真遇到不合规文档时 body 优先。
    """
    params = op.get("parameters")
    if isinstance(params, list):
        body_params = [p for p in params if isinstance(p, dict) and p.get("in") == "body"]
        form_params = [p for p in params if isinstance(p, dict) and p.get("in") == "formData"]
        # 其余参数（query/header/path）保留，并做 2.0 -> 3.x 的「参数内 schema」包装：
        # 2.0 的 type/format/enum 等直接写在参数顶层，3.x 要求放在 schema 子对象里。
        rest = []
        for p in params:
            if isinstance(p, dict) and p.get("in") in ("body", "formData"):
                continue
            if (
                isinstance(p, dict)
                and "schema" not in p
                and "$ref" not in p          # 2.0 参数级 $ref 暂按原样保留（已知限制）
            ):
                schema_fields = {k: v for k, v in p.items() if k not in _SWAGGER2_PARAM_META}
                if schema_fields:
                    p = {k: v for k, v in p.items() if k in _SWAGGER2_PARAM_META}
                    p["schema"] = schema_fields
            rest.append(p)
        request_body = None
        if body_params:
            media = _pick_media_type(consumes)
            request_body = {
                "required": bool(body_params[0].get("required", False)),
                "content": {media: {"schema": body_params[0].get("schema", {})}},
            }
        elif form_params:
            media = _pick_media_type(consumes, prefer_form=True)
            request_body = {
                "required": any(bool(p.get("required", False)) for p in form_params),
                "content": {media: {"schema": _form_params_to_schema(form_params)}},
            }
        if request_body is not None:
            op["requestBody"] = request_body
        op["parameters"] = rest

    responses = op.get("responses")
    if isinstance(responses, dict):
        for resp in responses.values():
            if not isinstance(resp, dict):
                continue
            schema = resp.pop("schema", None)  # 2.0 的 schema 直接挂 response 对象
            if schema is not None:
                resp["content"] = {_pick_media_type(produces): {"schema": schema}}


def _form_params_to_schema(form_params: list[dict[str, Any]]) -> dict[str, Any]:
    """formData 参数列表 -> object schema。

    2.0 的 formData 参数没有 schema 子对象，type/format/enum/minLength 等直接写在
    参数上，所以「参数去掉元字段」剩下的就是 schema 字段。
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in form_params:
        name = p.get("name")
        if not name:
            continue
        properties[str(name)] = {k: v for k, v in p.items() if k not in _SWAGGER2_PARAM_META}
        if p.get("required"):
            required.append(str(name))
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _pick_media_type(media_types: Any, *, prefer_form: bool = False) -> str:
    """从 consumes/produces 挑一个 media type；缺省按用途回退 json / form。"""
    types = media_types if isinstance(media_types, list) else []
    if prefer_form:
        for t in types:
            if isinstance(t, str) and ("x-www-form-urlencoded" in t or "multipart" in t):
                return t
        return "application/x-www-form-urlencoded"
    for t in types:
        if isinstance(t, str) and "json" in t:
            return t
    return str(types[0]) if types else "application/json"

def iter_operations(spec: dict[str, Any]) -> Iterator[Operation]:
    """把 spec.paths 展开成 Operation 列表。

    错误策略（面试可讲）：
    - 噪音节点（path item 不是 dict / 非方法键）宽容跳过；
    - 指向不存在的 $ref、循环引用、版本不符则明确报错 ——
      宁可失败暴露，不产出残缺的 Operation 让下游莫名出错。
    """
    if "swagger" in spec:
        spec = _bridge_swagger2_to_openapi3(spec)
    top_security = spec.get("security", [])
    paths = spec.get("paths")
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_params = path_item.get("parameters", [])
        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            yield _normalize_operation(method, path, op, path_params, top_security, spec)