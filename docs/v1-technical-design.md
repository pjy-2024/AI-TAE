# AI-TAE · V1 技术方案细化（骨架版）

> 版本：v0.1 ｜ 日期：2026-09-03 ｜ 关联：V1 技术方案细化
> 本文档是「任务 1」的产出：先定**契约**（目录、接口、数据结构、指标口径），再进入任务 2 写实现。

---

## 1. 本阶段目标与范围

- **做**：仓库骨架 + 模块边界 + 接口签名 + 关键设计决策文档化。
- **不做**（守住范围与红线）：不写业务逻辑、不调 LLM、不跑真实用例、不产生任何指标数字。
- 被测项目：**尚未确认**，选择标准见本文 §9 与 `samples/README.md`。

## 2. 目录结构与职责

```
src/aiae/
├── config.py      # 配置：LLM/路径，统一读环境变量（AITAE_*），密钥不入库
├── cli.py         # 命令行：selfcheck(可用) / generate / run / heal / judge
├── llm/client.py  # LLM 封装：OpenAI 兼容 chat/completions + 429/5xx 退避重试 + 用量记账
├── parser/
│   ├── openapi.py # OpenAPI/Swagger 读取 + 归一化成 Operation（收敛文档差异）
│   └── codec.py   # LLM 输出剥离/校验/落盘（可执行率第一道门禁）
├── generator/     # 编排：Operation → Prompt → LLM → 校验重试 → 落盘
├── runner/        # pytest 执行与结果收集（junitxml）
├── metrics/       # 指标口径（见 §7）
└── healer|judge|kv|rag  # V2/V3 占位
```

## 3. V1 端到端数据流

```
OpenAPI 文件(JSON/YAML)
   │ ① parser.openapi.load_spec / iter_operations
   ▼
Operation[]（method/path/参数/body/响应 的归一化结构）
   │ ② generator.build_messages：系统提示(JSON Schema) + 接口信息
   ▼
LLM（OpenAI 兼容，json_mode）──429/5xx──▶ 指数退避+抖动重试
   │ ③ 返回结构化 JSON（不是裸 Markdown）
   ▼
parser.codec.parse_llm_output   ←─ 校验失败：带错误信息限次重试(≤N)
   │ ④ validate_code(ast 静态校验) → write_test_file
   ▼
data/generated_tests/*.py（草稿，人工审阅后才入库）
   │ ⑤ runner.run_pytest（编程式调用 pytest）
   ▼
RunSummary → metrics（可执行率 / 通过率）
```

人工环节：生成的是**草稿**，人审阅后可执行/修改 —— 定位是“减少手写、加速”，不做无人值守。

## 4. 模块接口契约（先定契约，任务 2 填实现）

| 模块 | 关键符号 | 职责 | 实现时机 |
|---|---|---|---|
| `config.LLMConfig` | `from_env()` | 读取 `AITAE_LLM_*`；模型/地址与代码解耦 | ✅ 已可用 |
| `config.PathsConfig` | 默认路径 | 产物统一进 `data/`（gitignore） | ✅ 已可用 |
| `llm.LLMClient.complete()` | `messages→LLMResponse` | 单轮对话；429/5xx 重试；记录 tokens/耗时/重试次数 | ✅ 2026-09-03 |
| `parser.openapi.load_spec/iter_operations` | 文件→`Operation[]` | 解析并归一化文档差异 | ✅ 2026-09-03 |
| `parser.codec.parse_llm_output` | 文本→`GeneratedTest[]` | 剥离围栏、json 解析、结构校验 | ✅ 2026-09-03 |
| `parser.codec.validate_code` | `GeneratedTest→errors[]` | ast 静态校验（语法/函数名/危险调用初筛） | ✅ 2026-09-03 |
| `parser.codec.write_test_file` | `→Path` | 按 tag/模块组织落盘 | ✅ 2026-09-03 |
| `generator.generate_for_operations` | `→GenerationReport` | 主流程编排 + 限次重试 | ✅ 2026-09-03 |
| `runner.run_pytest` | `→RunSummary` | 执行生成用例，区分 passed/failed/errors | ✅ 2026-09-03 |
| `metrics.Metrics` | 率值计算 | 口径统一，避免“数字对不上” | ✅ 已可用 |

> **实现记录（2026-09-03，任务 2 第一步）**：`parser/openapi.py` 已落地，两点对骨架契约的细化：
> 1. `Operation` 新增 `security: list` 字段（取 operation 级，缺省回退文档顶层）——生成器据此区分「要不要先登录拿 token」；
> 2. 归一化形状具体化：`request_body = {required, content: {media_type: {schema}}}`（保留 media_type：json 用 `requests.json=`、form 用 `requests.data=`，构造方式不同）；`responses = {status: {description, content: {media_type: {schema}}}}`，空 schema `{}` 表示无响应体；
> 3. Swagger 2.0 采用「桥接」而非双轨：`_bridge_swagger2_to_openapi3` 把 definitions / body+formData / 响应 schema / consumes-produces 翻译成 3.x 形状后复用同一套归一化（归一化只实现一份，避免双轨漂移）。
>
> 验证：真实样例 todo_app-openapi.json → 19 个 Operation / 17 path；全量 35 个测试通过。真实指标仍【待实测】。
>
> **实现记录（2026-09-03，任务 2 第二步）**：`parser/codec.py` 已落地，与 generator 的 Prompt / runner 的 conftest 配套的落盘约定：
> 1. 文件名保证 pytest 可收集（`test_*.py`，module_name 不带前缀自动补），并清洗路径防目录注入；
> 2. 文件头统一 `import requests` + 元数据注释 —— LLM 只输出函数体，import 由本层统一提供，消除「每用例忘 import」类低级错误；
> 3. 重复生成同一接口覆盖写（幂等草稿），不产生重复文件。
>
> 校验错误信息精确到 `tests[i]` 字段并回传 LLM 限次重试。验证：全量 56 个测试通过。
>
> **实现记录（2026-09-03，任务 2 第三步）**：`llm/client.py` 已落地，关键实现决策：
> 1. 关掉 openai SDK 自带重试（`max_retries=0`）自实现——SDK 重试不可见/不可记账/不走本决策表；
> 2. 429 优先读 `Retry-After`（秒数，HTTP-date 解析失败走退避兜底），否则指数退避 `min(cap, base*2^n)` + `uniform(0, jitter)` 抖动；
> 3. 400/401/403/404/422 等请求错误不重试（重试 = 重复计费）；`finish_reason=length`（截断）直接报不可重试错误（重试无用，应调大 max_tokens）；
> 4. `api_key` 为空用占位符构造（openai 3.x 空 key 构造期即抛），把「未配置」延迟到 `complete()` 统一报错；
> 5. 记账内建：`LLMResponse{usage, latency_s, retries}`。
>
> 环境事实：`openai>=1.30` 实际安装 3.7.0（vendored httpx2），chat/completions 与异常层次兼容可用；锁已测版本待办。验证：全量 71 个测试通过（15 个 llm mock 测试不联网）。
>
> **实现记录（2026-09-03，任务 2 第四步）**：`generator/` 已落地，契约细化与关键决策：
> 1. `generate_for_operations` 增加 keyword-only `spec_summary` / `client` 参数（client 可注入，测试用 fake；缺省从环境配置创建）；
> 2. 双层重试语义分开：HTTP 层退避在 `llm/client`，语义层（输出不合格）在 generator——把精确错误追加进对话（assistant 坏输出 + user 错误原因）让模型对照改写，限次 `_GENERATION_RETRY_LIMIT=2`；
> 3. 批处理容错：单个 operation 失败记入 `report.failed` 不中断整批；
> 4. 落盘逐条独立文件（codec 契约本意）——曾试过「一 operation 一文件」与 codec 覆盖写语义冲突导致多用例互相覆盖丢数据，测试抓出后改回逐条文件；
> 5. Prompt 精简：4xx/5xx 响应只留 description（嵌套 schema 占 token 对断言价值低），token 优化待端到端实测后再迭代。
>
> 验证：全量 80 个测试通过（9 个 generator mock 测试）。
>
> **实现记录（2026-09-03，任务 2 第五步）**：`runner/` 已落地，关键决策与踩坑：
> 1. 子进程隔离执行（`sys.executable -m pytest`），不用 `pytest.main`（自身会话嵌套会抢插件/缓存/捕获）；
> 2. 结果收集用 `--junitxml` 标准报告解析：`<failure>`=断言失败（疑似真问题）、`<error>`=import/收集/fixture 级错误（不可执行）、`<skipped>`；注意 pytest 把函数内所有异常（含连不上服务）算 failure——口径边界待端到端真实数据校验；
> 3. 运行前自动确保 `conftest.py` 提供 `base_url` fixture（没有才写，人工改过不覆盖）——否则收集期 fixture not found 会让可执行率假性为 0；
> 4. 踩坑：测试目录在项目子树之外（如系统 Temp）时 pytest 向上找 rootdir 会扫到无权限目录 → 收集失败，需显式 `--rootdir <generated_dir>`；
> 5. 踩坑：collection error 默认中断整批（一个文件 import 坏，后面的全不跑）→ 加 `--continue-on-collection-errors`，坏文件只计 error。
>
> 验证：全量 88 个测试通过（8 个 runner 测试，含真实子进程集成样例）。
>
> **实现记录（2026-09-03，任务 2 第六步）**：`cli.py` 已落地（V1 机械部分完成）：
> 1. `aiae generate [--openapi] [--out-dir]`：前置校验 `AITAE_LLM_API_KEY`（未配置友好报错，不启动整批空转）；读 OpenAPI → Operation[] → generate_for_operations → 打印 GenerationReport；
> 2. `aiae run [--dir] [--junit-xml]`：run_pytest → Metrics，报数先报口径（generated≈pytest 收集总数，精确值来自 generate 阶段 report，跨命令传递待端到端再定）；可执行=passed+failed，error 属不可执行类；
> 3. 缺省路径全部指向项目约定（OpenAPI=samples/openapi/todo_app-openapi.json、产物=data/generated_tests、junit=data/runs/latest.xml），均可用参数覆盖。
>
> 验证：全量 95 个测试通过（7 个 cli 测试）。cli 三命令已真实冒烟（selfcheck / 无 key generate / 无目录 run）。
## 5. LLM 输出的结构化约束（为什么不用裸 Markdown）

LLM 输出**必须是 JSON**（json_mode），形如：

```json
{
  "tests": [
    {
      "name": "test_create_todo",
      "description": "正常创建一条待办，返回 201",
      "method": "POST",
      "path": "/todos",
      "code": "def test_create_todo(base_url):\n    resp = requests.post(f\"{base_url}/todos\", json={...})\n    assert resp.status_code == 201"
    }
  ]
}
```

取舍：裸 Markdown/代码块 → 剥离易错、格式漂移、无法结构化校验；JSON + Schema →
① 本地可先校验再落盘；② 失败时能把**精确错误**回传给 LLM 重试；③ 天然可审计/可统计。
要点：**“生成质量靠 Schema 约束 + 本地校验，而不是赌模型自觉”**。

## 6. 可靠性：429/5xx 重试策略

决策表：

| 情况 | 是否重试 | 策略 |
|---|---|---|
| HTTP 429（限流） | ✅ | 优先 `Retry-After` 响应头；没有则指数退避 + 抖动（jitter） |
| HTTP 5xx / 连接错误 / 超时 | ✅ | 指数退避 + 抖动 |
| HTTP 400/401/403/404/422 | ❌ | 请求本身错误，重试只会重复计费/浪费配额 |
| 超过 `max_retries` | ❌ | 抛最终错误，进失败清单 |

伪代码（任务 2 落到 `llm/client.py`）：

```
for attempt in 0..max_retries:
    try: return call()
    except Retryable as e:
        if attempt == max_retries: raise
        wait = retry_after(e) or min(cap, base * 2**attempt)
        sleep(wait + uniform(0, jitter))
```

为什么加 jitter：无抖动的重试会让所有失败请求在同一时刻打爆服务端（重试风暴）。
计费注意：请求若已计费，重试会二次计费 —— 所以只对“明确可安全重试”的错误重试，且单次生成失败的成本要记账（`llm_calls`、token 用量）成本口径可复现、可查。

## 7. 指标口径（先定口径，数字后填）

先给定义再实现，避免口径含糊：

| 指标 | 口径 | 含义 |
|---|---|---|
| `generated_count` | 分母 | LLM 成功返回且通过结构校验、成功落盘的用例数 |
| `executable_count` | | 能被 pytest 正常收集并执行（无 import/语法错误）的用例数 |
| `passed_count` | | 首轮运行断言通过的用例数 |
| `failed_count` | | 执行了但断言失败（疑似真问题，待人工确认） |
| `error_count` | | 用例本身报错（import/异常），属“不可执行”类 |
| **可执行率** | `executable / generated` | “LLM 产出能不能跑”（生成质量） |
| **通过率** | `passed / executable` | “跑起来的用例对不对”（运行质量） |

口径说明：报数前先说明口径（分母是谁），这本身就是工程严谨性的体现。
所有真实数字【待实测】；单元测试里的数字只是公式样例，与真实指标无关。

## 8. 配置清单（环境变量）

见根目录 `.env.example`：`AITAE_LLM_API_KEY / BASE_URL / MODEL / TIMEOUT_SECONDS / MAX_RETRIES / TEMPERATURE / JSON_MODE / TARGET_BASE_URL`。

## 9. 被测项目确认（待用户拍板）

选择标准与候选见 `samples/README.md`。骨架不依赖具体被测项目，可并行推进。

## 10. 与任务/里程碑对照

- 本骨架 = 任务 1 收尾（细化方案）+ 任务 2 的“地基”。
- 任务 2（V1 跑通）按 §4 表格逐模块填实现，顺序建议：`openapi → codec → llm → generator → runner → cli`。
- 规划：骨架先行；V1 完整跑通按阶段推进。