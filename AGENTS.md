# AGENTS.md — AI-TAE 项目协作指引

> 本文件是给「进入该项目的 AI 助手」看的自动指引。项目对话的助手会先读本文件，
> 因此**本人无需再把上下文文档整篇粘贴一遍**。

## 这是什么项目

AI 智能测试辅助引擎：V1 接口用例自动生成（OpenAPI → pytest）→ V2 UI 失败自愈（KV + RAG + LLM）
→ V3 judge + golden 评测。当前：骨架 v0.1 + C 盘独立环境 + 被测项目已选定跑通，业务代码未开始。

## 进入项目后请先读这些文件（全部上下文都在仓库里）

- docs/progress-2026-09-03.md —— 阶段进度与交接（最新，优先读）
- AI-TAE-项目说明书与上下文交接.md —— 项目总纲（版本规划 / 面试 / 红线）
- docs/v1-technical-design.md —— V1 技术方案（接口契约 / 数据流 / 指标口径）
- samples/README.md —— 被测项目记录与固定 commit
- AGENTS.md —— 本文件

## 硬性规则（必须遵守）

1. 用中文沟通；代码注释与 README 以中文为主（本人可读性优先）。
2. 真实数字纪律：一切指标先以【待实测】占位，禁止编造任何数字、成果、commit 历史。
3. 时间盒：考研初试（约 2026-12）前只做轻量工作；V1 大代码留到初试后集中做。
   任何「顺手多做」的需求先说明成本，再决定是否做。
4. 被测项目：manojnd9/todo_app，固定 commit f3cf7eeb...，快照在 data/targets/todo_app（gitignore 不入库）；
   依赖按其 lock 时代版本运行，不要追最新（详见 progress 文档「依赖漂移」）。
5. 环境：C 盘独立 Python 3.12（C:\Users\彭井艺\AppData\Local\Programs\Python\python312），
   项目 venv 在根目录 .venv；安装依赖用清华镜像 https://pypi.tuna.tsinghua.edu.cn/simple。
6. 密钥不入库：.env 已被 gitignore。
7. 沙箱账户无法写 .git（保护 commit 真实性）→ commit / push 由本人执行，助手只需改工作区文件并提示提交。

## 代码布局

- src/aiae：主包（parser / generator / runner / metrics / llm / healer / judge / kv / rag）
- tests：自身单元测试；samples：被测记录与 OpenAPI；data：运行产物（gitignore，不入库）
- 生成 / 执行的产物一律进 data/，人工审阅确认后才入库

## 常用命令（在项目 .venv 内）

- aiae selfcheck
- python -m pytest -q
- 被测项目启动与验证见 samples/README.md