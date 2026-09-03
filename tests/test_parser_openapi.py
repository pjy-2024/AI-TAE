"""parser.openapi 单元测试：load_spec / iter_operations 归一化。

输入分两类：
1. 真实样例 samples/openapi/todo_app-openapi.json —— 验证「真实文档能读通」（回归护栏）；
2. 测试内联的小 spec —— 验证归一化分支（$ref、path 级参数合并、缺 operationId 等）。

真实指标数字仍【待实测】；这里的数字（19 个 operation、17 个 path 等）
是「真实文档的结构事实」，用来做可复现断言，不是成果/性能指标。
"""

from __future__ import annotations

import json

import pytest

from aiae.parser.openapi import load_spec, iter_operations

SAMPLE = "samples/openapi/todo_app-openapi.json"


# ---------------------------------------------------------------- 工具

def _write_spec(tmp_path, data, name="spec.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


# 覆盖归一化分支的最小 OpenAPI 3 文档
MINI_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "mini", "version": "1.0.0"},
    "paths": {
        # path 级参数 + operation 级同名覆盖 + 响应 $ref
        "/items/{item_id}": {
            "parameters": [
                {"name": "item_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                {"name": "verbose", "in": "query", "schema": {"type": "boolean", "default": False}},
            ],
            "get": {
                "summary": "Get one item",
                "operationId": "get_item",
                "parameters": [
                    # 与 path 级 verbose 同名同 in，应覆盖（boolean -> string）
                    {"name": "verbose", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Item"}}
                        },
                    }
                },
            },
            # 无 operationId -> 兜底命名；body $ref
            "post": {
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Item"}}
                    },
                },
                "responses": {"201": {"description": "created"}},
            },
        },
        # 无 operationId / 无 security 的开放接口
        "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
        # 噪音节点：path item 不是 dict，应被跳过
        "not_a_path_item": "skip me",
    },
    "components": {
        "schemas": {
            "Item": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "tag": {"$ref": "#/components/schemas/Tag"}},
                "required": ["name"],
            },
            "Tag": {"type": "object", "properties": {"label": {"type": "string"}}},
        }
    },
}


# ---------------------------------------------------------------- load_spec

def test_load_spec_real_sample_json():
    spec = load_spec(SAMPLE)
    assert spec["openapi"].startswith("3.")
    assert isinstance(spec["paths"], dict)
    assert len(spec["paths"]) == 17


def test_load_spec_yaml(tmp_path):
    yaml_text = "openapi: 3.0.3\ninfo:\n  title: y\n  version: '1'\npaths: {}\n"
    p = tmp_path / "spec.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    spec = load_spec(p)
    assert spec["openapi"] == "3.0.3"


def test_load_spec_rejects_missing_paths(tmp_path):
    p = _write_spec(tmp_path, {"openapi": "3.0.3", "info": {}})
    with pytest.raises(ValueError, match="paths"):
        load_spec(p)


def test_load_spec_rejects_non_object_top(tmp_path):
    p = _write_spec(tmp_path, ["not", "a", "dict"])
    with pytest.raises(ValueError, match="顶层"):
        load_spec(p)


def test_load_spec_rejects_unknown_suffix(tmp_path):
    p = tmp_path / "spec.txt"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="扩展名"):
        load_spec(p)


def test_load_spec_accepts_swagger2(tmp_path):
    p = _write_spec(tmp_path, {"swagger": "2.0", "info": {}, "paths": {}})
    spec = load_spec(p)
    assert spec["swagger"] == "2.0"  # 桥接发生在 iter_operations，load_spec 只负责读取与版本校验


def test_load_spec_rejects_swagger_other_version(tmp_path):
    p = _write_spec(tmp_path, {"swagger": "1.2", "paths": {}})
    with pytest.raises(ValueError, match="2.x"):
        load_spec(p)


def test_load_spec_rejects_unknown_version(tmp_path):
    p = _write_spec(tmp_path, {"openapi": "2.0", "paths": {}})
    with pytest.raises(ValueError, match="3.x"):
        load_spec(p)


# ---------------------------------------------------------------- iter_operations（真实样例）

def test_iter_operations_real_sample_count():
    ops = list(iter_operations(load_spec(SAMPLE)))
    assert len(ops) == 19          # 真实文档结构事实
    assert len({op.path for op in ops}) == 17
    methods = {op.method for op in ops}
    assert {"GET", "POST", "PUT", "DELETE"} <= methods


def test_iter_operations_real_sample_path_parameter():
    ops = {op.operation_id: op for op in iter_operations(load_spec(SAMPLE))}
    op = ops["read_todo_todos_todo__todo_id__get"]
    assert op.path == "/todos/todo/{todo_id}"  # 模板占位符保留
    assert op.parameters == [
        {
            "name": "todo_id",
            "in": "path",
            "required": True,
            "description": "",
            "schema": {"type": "integer", "exclusiveMinimum": 0, "title": "Todo Id"},
        }
    ]


def test_iter_operations_real_sample_json_body_resolved():
    ops = {op.operation_id: op for op in iter_operations(load_spec(SAMPLE))}
    body = ops["create_user_auth_post"].request_body
    assert body is not None and body["required"] is True
    schema = body["content"]["application/json"]["schema"]
    # $ref 已展开：直接看到字段，而不是 {"$ref": ...}
    assert "username" in schema["properties"]
    assert "password" in schema["properties"]
    assert "required" in schema


def test_iter_operations_real_sample_form_body_keeps_media_type():
    ops = {op.operation_id: op for op in iter_operations(load_spec(SAMPLE))}
    body = ops["login_for_access_token_auth_token_post"].request_body
    assert "application/x-www-form-urlencoded" in body["content"]  # json 与 form 必须可区分


def test_iter_operations_real_sample_security():
    ops = {op.operation_id: op for op in iter_operations(load_spec(SAMPLE))}
    assert ops["get_user_data_users_get_user_get"].security  # 需认证接口带 security
    assert ops["test__get"].security == []                      # 开放接口为空


def test_iter_operations_real_sample_no_content_response():
    ops = {op.operation_id: op for op in iter_operations(load_spec(SAMPLE))}
    resp = ops["todo_delete_todos_todo__todo_id__delete"].responses
    assert resp["204"]["content"] == {}  # 无响应体：保留空 content，供生成器决定是否断言 body


# ---------------------------------------------------------------- iter_operations（归一化分支）

def test_mini_merge_path_and_op_parameters():
    ops = {op.operation_id: op for op in iter_operations(MINI_SPEC)}
    get_item = ops["get_item"]
    assert len(get_item.parameters) == 2  # path 级 item_id + verbose（合并后不重复）
    verbose = next(p for p in get_item.parameters if p["name"] == "verbose")
    assert verbose["schema"]["type"] == "string"  # operation 级覆盖了 path 级 boolean


def test_mini_required_default_rule():
    ops = {op.operation_id: op for op in iter_operations(MINI_SPEC)}
    item_id = next(p for p in ops["get_item"].parameters if p["name"] == "item_id")
    verbose = next(p for p in ops["get_item"].parameters if p["name"] == "verbose")
    assert item_id["required"] is True   # path 参数缺省必填
    assert verbose["required"] is False  # query 参数缺省非必填


def test_mini_response_ref_resolved_recursively():
    ops = {op.operation_id: op for op in iter_operations(MINI_SPEC)}
    schema = ops["get_item"].responses["200"]["content"]["application/json"]["schema"]
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["tag"]["properties"]["label"]["type"] == "string"  # 嵌套 $ref 也展开


def test_mini_operation_id_fallback():
    ops = {op.operation_id: op for op in iter_operations(MINI_SPEC)}
    assert ops["get_health"].path == "/health"  # 无 operationId -> method_path 兜底


def test_mini_noise_path_item_skipped():
    ops = list(iter_operations(MINI_SPEC))
    assert len(ops) == 3  # get/post items + get health；噪音节点被跳过


def test_mini_security_inherit_and_override():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "s", "version": "1"},
        "security": [{"ApiKey": []}],
        "paths": {
            "/a": {"get": {"responses": {"200": {"description": "ok"}}}},                      # 继承顶层
            "/b": {
                "get": {
                    "security": [],                                                            # 显式覆盖为无需认证
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }
    ops = {op.path: op for op in iter_operations(spec)}
    assert ops["/a"].security == [{"ApiKey": []}]
    assert ops["/b"].security == []


def test_mini_resolve_does_not_mutate_input_spec():
    ops = list(iter_operations(MINI_SPEC))
    # 原始 spec 里仍是 $ref 指针（_resolve 必须深拷贝，不能就地改）
    assert MINI_SPEC["components"]["schemas"]["Item"]["properties"]["tag"] == {
        "$ref": "#/components/schemas/Tag"
    }
    assert len(ops) == 3  # 且同一 spec 可重复消费


def test_mini_circular_ref_raises():
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "c", "version": "1"},
        "paths": {
            "/x": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/A"}}
                            },
                        }
                    }
                }
            }
        },
        "components": {"schemas": {"A": {"properties": {"self": {"$ref": "#/components/schemas/A"}}}}},
    }
    with pytest.raises(ValueError, match="循环"):
        list(iter_operations(spec))


# ---------------------------------------------------------------- Swagger 2.0 桥接

# 仿老项目风格的 Swagger 2.0 文档：body/formData 参数、definitions、consumes/produces
SWAGGER2_SPEC = {
    "swagger": "2.0",
    "info": {"title": "legacy", "version": "1.0.0"},
    "basePath": "/api",
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "paths": {
        "/pets/{pet_id}": {
            "get": {
                "operationId": "get_pet",
                "parameters": [
                    {"name": "pet_id", "in": "path", "required": True, "type": "integer"},
                ],
                "responses": {
                    "200": {"description": "ok", "schema": {"$ref": "#/definitions/Pet"}}
                },
            }
        },
        "/pets": {
            "post": {
                "operationId": "create_pet",
                "parameters": [
                    {
                        "name": "body",
                        "in": "body",
                        "required": True,
                        "schema": {"$ref": "#/definitions/Pet"},
                    }
                ],
                "responses": {
                    "201": {"description": "created", "schema": {"$ref": "#/definitions/Pet"}}
                },
            }
        },
        # 不带 produces 的接口 -> media 缺省 application/json
        "/ping": {
            "get": {
                "operationId": "ping",
                "responses": {"200": {"description": "ok", "schema": {"type": "string"}}},
            }
        },
        "/login": {
            "post": {
                "operationId": "login",
                "consumes": ["application/x-www-form-urlencoded"],
                "parameters": [
                    {"name": "username", "in": "formData", "required": True, "type": "string"},
                    {"name": "password", "in": "formData", "required": True, "type": "string", "minLength": 6},
                    {"name": "remember", "in": "formData", "required": False, "type": "boolean", "default": False},
                ],
                "responses": {"200": {"description": "ok", "schema": {"type": "string"}}},
            }
        },
    },
    "definitions": {
        "Pet": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["name"],
        }
    },
}


def test_swagger2_load_and_bridge_count():
    ops = list(iter_operations(SWAGGER2_SPEC))
    assert len(ops) == 4  # get_pet / create_pet / ping / login
    assert {op.method for op in ops} == {"GET", "POST"}


def test_swagger2_body_param_becomes_request_body():
    ops = {op.operation_id: op for op in iter_operations(SWAGGER2_SPEC)}
    body = ops["create_pet"].request_body
    assert body is not None and body["required"] is True
    schema = body["content"]["application/json"]["schema"]
    # $ref 前缀已从 #/definitions/ 重写并展开成真实结构（不再有指针）
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["required"] == ["name"]
    assert ops["create_pet"].parameters == []  # in: body 参数已被消费掉


def test_swagger2_formdata_becomes_form_request_body():
    ops = {op.operation_id: op for op in iter_operations(SWAGGER2_SPEC)}
    body = ops["login"].request_body
    assert "application/x-www-form-urlencoded" in body["content"]
    schema = body["content"]["application/x-www-form-urlencoded"]["schema"]
    assert schema["properties"]["username"]["type"] == "string"
    assert schema["properties"]["password"]["minLength"] == 6   # 参数上的约束字段保留
    assert schema["properties"]["remember"]["default"] is False
    assert schema["required"] == ["username", "password"]       # remember 非必填不入 required
    assert ops["login"].parameters == []                        # formData 参数已被消费掉


def test_swagger2_response_schema_wrapped_in_content():
    ops = {op.operation_id: op for op in iter_operations(SWAGGER2_SPEC)}
    schema = ops["get_pet"].responses["200"]["content"]["application/json"]["schema"]
    assert schema["properties"]["id"]["type"] == "integer"
    # 无 produces 的接口：media 缺省 application/json
    assert ops["ping"].responses["200"]["content"]["application/json"]["schema"] == {"type": "string"}


def test_swagger2_path_param_type_wrapped_into_schema():
    ops = {op.operation_id: op for op in iter_operations(SWAGGER2_SPEC)}
    pet_id = next(p for p in ops["get_pet"].parameters if p["name"] == "pet_id")
    # 2.0 的 type 写在参数顶层 -> 桥接后收进 schema 子对象（3.x 形状）
    assert pet_id["schema"] == {"type": "integer"}
    assert pet_id["required"] is True


def test_swagger2_query_param_kept():
    spec = {
        "swagger": "2.0",
        "info": {"title": "q", "version": "1"},
        "paths": {
            "/search": {
                "get": {
                    "operationId": "search",
                    "parameters": [
                        {"name": "q", "in": "query", "required": True, "type": "string"},
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    ops = {op.operation_id: op for op in iter_operations(spec)}
    assert ops["search"].parameters[0]["schema"] == {"type": "string"}
    assert ops["search"].parameters[0]["required"] is True


def test_swagger2_bridge_does_not_mutate_input():
    import copy

    before = copy.deepcopy(SWAGGER2_SPEC)
    list(iter_operations(SWAGGER2_SPEC))
    assert SWAGGER2_SPEC == before  # 桥接基于深拷贝，原 spec 不变（可重复消费）
