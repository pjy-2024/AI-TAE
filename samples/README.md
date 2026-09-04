# samples · 被测项目

## 已选定：manojnd9/todo_app（FastAPI 待办应用）

- 仓库：https://github.com/manojnd9/todo_app
- 固定 commit：f3cf7eeba8db2213be77a5ca3f990be1b923a726（main 分支，2025-01-31）
- 本地快照：data/targets/todo_app（已在 .gitignore，不入库）
- OpenAPI 导出：samples/openapi/todo_app-openapi.json（17 个 path）
- 技术栈：FastAPI + SQLAlchemy + Jinja2 + SQLite + JWT(python-jose) + bcrypt

## 为什么选它（面试要能讲）

1. 真实开源、仓库小、结构清晰，自带 CI（GitHub Actions：poetry + pytest）和测试，面试官 clone 即复现；
2. 自带 OpenAPI（FastAPI 自动生成 /openapi.json），是 V1「接口用例生成」的直接输入；
3. 有真实 UI 页面（注册 / 登录 / 待办增删改查，HTML+Jinja2），是 V2「UI 失败自愈」的实验场；
4. SQLite 本地可跑，无 Docker / Postgres 依赖，Windows 一条 uvicorn 就能起。

## 复现运行

完整命令见 docs/progress-2026-09-03.md 第五节，要点：

- 用 C 盘独立 Python 3.12 建独立 venv（data/targets/todo_app/.venv）
- 依赖按该项目 lock 时代固定版本安装（fastapi 0.115.6 / starlette 0.41.3 / pydantic 2.10.4 / cryptography 44.0.0），不要追最新——原因见 progress 文档「依赖漂移」教训
- 项目根写 .env.dev：DATABASE_URL=sqlite:///./todosapp.db、SECRET_KEY（随意长字符串）、ALGORITHM=HS256
- 启动：在 data/targets/todo_app 目录运行 .venv\Scripts\python.exe -m uvicorn todo_app.main:app --port 8010
- 验证：/health、/auth/login-page（200 HTML）、/openapi.json

## 已跑通的基线（2026-09-03，全部真实）

- 页面：/、/auth/login-page、/auth/register-page、/todos/todo-page → 200 HTML
- API：注册 POST /auth → 201；登录 POST /auth/token → 200（拿到 JWT）；建待办 POST /todos/todo → 201；列表 GET /todos/ → 200；当前用户 GET /users/get_user → 200
- 数据库：SQLite（todosapp.db）

## 为什么不把被测项目本体入库

避免嵌套 git 仓库、保持证据链干净：只记录 URL + 固定 commit + 快照位置。
V2 需要「故意改动 UI 制造页面漂移」时，在快照副本里改并单独留档（见 progress 文档 V2 规划）。


---

## 第二被测项目：lymanny/FastAPI-CRUD-Todo（无认证纯 CRUD）

- 仓库：https://github.com/lymanny/FastAPI-CRUD-Todo
- 固定 commit：0ccc618b60c73bbc9f7a488a213ea14e852cb776（main，2024-11-12）
- 本地快照：data/targets/fastapi_crud_todo（已在 .gitignore，不入库；无 .git）
- OpenAPI 导出：samples/openapi/fastapi_crud_todo-openapi.json（6 个 operation / 5 path）
- 技术栈：FastAPI 0.95.2 + Pydantic 1.10 + SQLAlchemy 2.0.21 + SQLite + Uvicorn 0.22.0（2023 时代 lock）

### 为什么选它（验证价值）

1. **比 todo_app 更简单 + 认证形态不同**：无注册/登录/token 的纯 API CRUD —— 专为验证
   「auth_mode=none 退化」：conftest 只给 base_url、生成用例全部按开放接口（签名只有 base_url）；
2. 有资源 id 接口（{todo_id}）但无「当前用户资源」语义（resource=None）——验证无认证项目
   的资源 id 接口由 LLM 用例自建自取，框架不引不存在的 fixture；
3. 自带 OpenAPI、一条 uvicorn 命令起、SQLite 本地可跑、无 Docker/Postgres 依赖。

### 依赖漂移处理（2026-09-04 真实踩坑，务必保留此记录）

仓库 lock 是 2023 时代（fastapi 0.95.2 / pydantic 1.10.12 / sqlalchemy 2.0.21），在 C 盘独立
Python 3.12 上出现两处不兼容，按「包名装 lock 时代兼容版本」处理（fastapi 主版本不变）：

| 问题 | 原因 | 对策 |
|---|---|---|
| pydantic 1.10.12 启动即崩 | Python 3.12 typing.ForwardRef._evaluate 新增 recursive_guard 参数，1.10.12 未适配 | 升 pydantic 1.10.21（1.10 系列最终补丁，仍 <2.0，满足 fastapi 约束） |
| 路由执行 500：anyio 无 to_thread | starlette 0.27（fastapi 0.95.2 配套）需要 anyio 3.x，pip 装成 4.15 后顶层 anyio.to_thread 失效 | 降 anyio 3.7.1（fastapi 0.95.2 lock 时代最新 3.x） |

### 复现运行（端口 8011，独立 venv）

- venv：`data/targets/fastapi_crud_todo/.venv`（C 盘独立 Python 3.12 创建）
- 启动：在 data/targets/fastapi_crud_todo 目录运行 `.venv\Scripts\python.exe -m uvicorn main:app --port 8011`
- 验证：/（200）、/openapi.json
- AI-TAE 切换目标：`$env:AITAE_TARGET="fastapi_crud_todo"`
  （注意：.env 若残留 AITAE_TARGET_BASE_URL=8010 会覆盖默认端口，需 `$env:AITAE_TARGET_BASE_URL="http://127.0.0.1:8011"`）

### 已跑通的基线（2026-09-04，全部真实）

- 页面/API：GET / → 200；POST /todos/ → 200（创建返回对象含 id）；GET /todos/ → 200 列表；
  GET /todos/{id} → 200/404；PUT /todos/{id} → 200；DELETE /todos/{id} → 200
- AI-TAE V1：6/6 草稿生成；真实 run：可执行率 100%（6/6）、通过率 66.7%（4/6），
  失败 2 例均为 LLM「自建资源后凭 REST 惯例断言 201」，被测实际返回 200（见 progress-2026-09-04）
