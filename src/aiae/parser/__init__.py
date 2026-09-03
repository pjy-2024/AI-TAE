"""输入解析与产物落盘（对应说明书 V1 的「Parser」角色）。

两件事：
1. openapi.py —— 把 OpenAPI/Swagger（JSON/YAML）归一化成内部 Operation 结构；
2. codec.py   —— 校验 LLM 输出的「用例代码 + 元数据」，剥离后写入 pytest 文件。

LLM 输出必须走「结构化 JSON + 本地校验 + 失败重试」，这是可执行率的第一道质量门禁。
"""