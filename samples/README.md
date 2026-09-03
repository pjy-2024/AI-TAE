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