# AI-TAE · V1 技术方案细化（骨架版）

> 版本：v0.1 ｜ 日期：2026-09-03 ｜ 关联：项目说明书 §5(V1)/§6(技术栈)/§10(任务)
> 本文档是「任务 1」的产出：先定**契约**（目录、接口、数据结构、指标口径），再进入任务 2 写实现。

---

## 1. 本阶段目标与范围

- **做**：仓库骨架 + 模块边界 + 接口签名 + 关键设计决策文档化。
- **不做**（守住时间盒与红线）：不写业务逻辑、不调 LLM、不跑真实用例、不产生任何指标数字。
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
| `llm.LLMClient.complete()` | `messages→LLMResponse` | 单轮对话；429/5xx 重试；记录 tokens/耗时/重试次数 | 任务 2 |
| `parser.openapi.load_spec/iter_operations` | 文件→`Operation[]` | 解析并归一化文档差异 | 任务 2 |
| `parser.codec.parse_llm_output` | 文本→`GeneratedTest[]` | 剥离围栏、json 解析、结构校验 | 任务 2 |
| `parser.codec.validate_code` | `GeneratedTest→errors[]` | ast 静态校验（语法/函数名/危险调用初筛） | 任务 2 |
| `parser.codec.write_test_file` | `→Path` | 按 tag/模块组织落盘 | 任务 2 |
| `generator.generate_for_operations` | `→GenerationReport` | 主流程编排 + 限次重试 | 任务 2 |
| `runner.run_pytest` | `→RunSummary` | 执行生成用例，区分 passed/failed/errors | 任务 2 |
| `metrics.Metrics` | 率值计算 | 口径统一，避免“数字对不上” | ✅ 已可用 |

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
面试讲：**“生成质量靠 Schema 约束 + 本地校验，而不是赌模型自觉”**。

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
计费注意：请求若已计费，重试会二次计费 —— 所以只对“明确可安全重试”的错误重试，且单次生成失败的成本要记账（`llm_calls`、token 用量）供面试问答“成本多少”。

## 7. 指标口径（先定口径，数字后填）

先给定义再实现，避免面试被追问时口径含糊：

| 指标 | 口径 | 含义 |
|---|---|---|
| `generated_count` | 分母 | LLM 成功返回且通过结构校验、成功落盘的用例数 |
| `executable_count` | | 能被 pytest 正常收集并执行（无 import/语法错误）的用例数 |
| `passed_count` | | 首轮运行断言通过的用例数 |
| `failed_count` | | 执行了但断言失败（疑似真问题，待人工确认） |
| `error_count` | | 用例本身报错（import/异常），属“不可执行”类 |
| **可执行率** | `executable / generated` | “LLM 产出能不能跑”（生成质量） |
| **通过率** | `passed / executable` | “跑起来的用例对不对”（运行质量） |

面试讲法：报数前先说明口径（分母是谁），这本身就是工程严谨性的体现。
所有真实数字【待实测】；单元测试里的数字只是公式样例，与真实指标无关。

## 8. 配置清单（环境变量）

见根目录 `.env.example`：`AITAE_LLM_API_KEY / BASE_URL / MODEL / TIMEOUT_SECONDS / MAX_RETRIES / TEMPERATURE / JSON_MODE / TARGET_BASE_URL`。

## 9. 被测项目确认（待用户拍板）

选择标准与候选见 `samples/README.md`。骨架不依赖具体被测项目，可并行推进。

## 10. 与任务/里程碑对照

- 本骨架 = 任务 1 收尾（细化方案）+ 任务 2 的“地基”。
- 任务 2（V1 跑通）按 §4 表格逐模块填实现，顺序建议：`openapi → codec → llm → generator → runner → cli`。
- 时间盒：骨架是轻量工作；V1 完整跑通留到初试后第 1 周集中做。