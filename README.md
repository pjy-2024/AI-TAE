# AI 智能测试辅助引擎（AI-TAE）

> 状态：**骨架阶段 v0.1**（目录与接口契约已建，业务代码未开始）
> 项目说明书与上下文交接：`AI-TAE-项目说明书与上下文交接.md` ｜ V1 技术方案：[docs/v1-technical-design.md](docs/v1-technical-design.md)

把 LLM 嵌入真实测试工作流的引擎，分三步落地：

- **V1** 接口文档（OpenAPI/Swagger）→ 自动生成可执行 pytest 用例 → 统计可执行率/通过率
- **V2** UI 用例失败自愈：先查本地 KV 缓存 → 未命中查 RAG 知识库 → 仍无解才问 LLM → 人工确认后应用
- **V3** LLM-as-Judge 区分「真 Bug / Flaky / 用例问题」，用 golden 人工标注评测一致率

> ⚠️ **真实数字纪律**：本仓库一切指标以【待实测】占位。未实测前不填任何数字，拒绝编造/包装。

## 快速开始（骨架阶段）

```bash
# 1) 安装（可选：骨架冒烟测试只用标准库，不装依赖也能跑）
pip install -e ".[dev]"

# 2) 环境自检（唯一可用的命令）
python -m aiae.cli selfcheck

# 3) 冒烟测试
pytest -q
```

## 目录结构

```
04-AI智能测试辅助引擎-AITAE/
├── docs/
│   └── v1-technical-design.md   # V1 技术方案细化（数据流/接口契约/429/指标口径）
├── src/aiae/                    # 主包（src 布局，后续业务代码都在这）
│   ├── config.py                # 配置（环境变量，密钥不入库）
│   ├── cli.py                   # 命令行入口（selfcheck 可用）
│   ├── llm/                     # LLM 调用封装（429 退避重试）—— 契约先行
│   ├── parser/                  # OpenAPI 解析 + LLM 输出校验落盘
│   ├── generator/               # 用例生成编排（V1 主流程）
│   ├── runner/                  # pytest 执行与结果收集
│   ├── metrics/                 # 指标口径定义（可执行率/通过率）
│   ├── healer/ judge/ kv/ rag/  # V2/V3 占位
├── tests/                       # 自身单元测试（冒烟）
├── samples/                     # 被测项目选择说明 + 样例 OpenAPI（待确认）
├── scripts/                     # 一键脚本（后续）
├── data/                        # 运行产物（gitignore，不入库）
└── pyproject.toml
```

## Roadmap 与当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 任务 1 | 确认被测开源小项目 + 细化 V1 技术方案 | 骨架已建；**被测项目待你确认** |
| 任务 2 | V1：OpenAPI → 生成 → Parser → pytest 执行 → 指标 | 未开始（初试后集中做） |
| 任务 3 | V2：自愈 + KV/RAG | 未开始 |
| 任务 4 | V3：judge + golden | 未开始（视时间） |

时间盒提醒：考研初试（约 2026-12）前只做轻量工作，大代码留到初试后集中冲刺。

## 证据链清单（做完勾选，全部真实）

- [ ] 选定 1 个真实开源小项目（被测对象）
- [ ] V1：可执行率 / 通过率【待实测】
- [ ] V2：≥5 个真实 UI 改动 case + 自愈成功率/耗时【待实测】
- [ ] V2：缓存命中率【待实测】
- [ ] V3：judge 与 golden 一致率【待实测】
- [ ] 公网部署 URL / 可运行演示
- [ ] README：架构图 + 截图 + 快速开始
- [ ] 演示视频（2–3 分钟）
- [ ] git commit 历史真实连续
- [ ] （可选）开源到 GitHub 收集真实反馈