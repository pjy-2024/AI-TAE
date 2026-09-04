# AI-TAE · V3 技术方案细化（规划版）

> 版本：v0.1（2026-09-04）｜关联：项目说明书 §V3 / §7 面试深水区 / 占位模块 src/aiae/judge
> 本文档是 V3 的「规划契约」：先定目标、数据来源、判定口径、golden 方案、模块边界，
> 再进入实现 —— 与 V1 的任务 1（先定契约）同套路。

---

## 1. V3 要回答的问题（一句话）

**AI 说「这个失败是真 Bug / 偶发抖动(Flaky) / 用例本身写错了」，凭什么信它？**
V1/V2 证明了「AI 能生成、能自愈」；V3 要证明「AI 的判断可信」——用人工标注的 golden
样本算一致率，而不是自说自话。

## 2. 范围与不做（守住时间盒与红线）

- **做**：最小 judge（LLM 三分类判定）+ golden 标注（先 30–50 条）+ 一致率评测 + 误报/漏报分析。
- **不做**（明确划线）：双模型投票（成本翻倍，Roadmap）；judge 自动化接入 CI；多租户。
- 真实数字纪律：一致率【待实测】，golden 样本与标注流程先落地再谈数字。

## 3. 三类标签的定义（先写死，标注不靠感觉）

| 标签 | 含义 | 危险度 |
|---|---|---|
| `bug` | 被测软件真实缺陷：按文档/常识应正常，实际失败 | 漏判最危险 |
| `flaky` | 偶发/环境导致，重跑可能通过（超时、时序、外部依赖） | 需复跑佐证 |
| `test_issue` | 用例/测试本身问题：断言写错、数据没准备、定位器过时 | 最常见（V1 首轮 11 条失败全是此类） |

判定边界（面试可讲）：`test_issue` 与 `bug` 最易混——「用例断言 200 但服务返 401」，
若服务要求登录而用例没带 token → `test_issue`；若带了 token 仍 401 → 疑似 `bug`。

## 4. 数据来源（现实约束，诚实标注）

- **`test_issue` 样本**：现成 —— V1 真实失败记录（首轮 11 条全是用例问题）、V2 病灶自愈样本。
- **`bug` 样本**：被测 todo_app 是健康的 → 需在快照副本**故意注入真 Bug**（如改业务逻辑：建待办不校验空标题、删除返回错误状态码、登录不校验密码）制造，固定 commit 前留 diff。
- **`flaky` 样本**：最难得 —— 可用「重跑判定」辅助：同用例多次运行结果不一致 → 标 flaky 候选；不强造。

golden 最小集：30–50 条（bug ~10 + test_issue ~20 + flaky ~5 起步），SQLite 存标注。

## 5. Judge 判定设计（复用 llm/client，不引新框架）

```
失败信息（status/traceback 摘要/断言内容 + 上下文）
   │ 组织上下文（V1 接口信息 / V2 页面结构 可选）
   ▼
LLM(DeepSeek) json_mode 三分类：{label: bug|flaky|test_issue, reason, confidence}
   ▼
本地校验 label ∈ 三类 + reason 非空；非法/超时重试限次（复用 llm/client 语义层重试思路）
   ▼
与 golden 比对 → 一致率 + 混淆矩阵（误报/漏报）
```

口径（先定，报数先报分母）：
- **一致率** = judge 与 golden 一致的条数 / golden 总条数
- **漏报 bug**（最危险）= golden 标 bug 但 judge 判别的 / golden bug 总数 —— 面试主动讲这个，
  比只报一致率可信。
- **误报 bug** = golden 非 bug 但 judge 判 bug / golden 非 bug 总数。

## 6. 模块契约（占位 src/aiae/judge 待填）

| 符号 | 职责 | 实现时机 |
|---|---|---|
| `judge.make_judge_prompt` | 失败信息 → messages（约束输出 JSON 三分类） | V3 |
| `judge.parse_judge` | LLM 输出 → {label, reason, confidence}，本地校验 | V3 |
| `judge.evaluate` | 对 golden 批量判定 → 一致率/混淆矩阵 | V3 |
| `golden 存储` | SQLite：data/aiae.sqlite3（PathsConfig 已有） | V3 |
| CLI `aiae judge --golden` | 跑评测打印一致率/混淆矩阵 | V3 |

复用：`llm/client.py`（重试/记账）、metrics 口径思想、`aiae run` 的失败收集。
安全：判定是「建议」，不自动删改测试 —— judge 输出仅供人参考。

## 7. golden 标注流程（防「自己标自己评」的作弊嫌疑）

1. 规则写死（第 3 节）+ 标注模板固定字段；
2. **先盲标**：标注人不看 judge 输出先给标签；
3. **双人抽检**：自己与同学各标一份，比对不一致的讨论定稿（>10% 不一致要查规则歧义）；
4. 标注记录存 SQLite，留标注人/时间/依据（证据链）。

## 8. 任务分解（V3 最小原型，按序）

1. 制造 bug/flaky 样本 + 收集 test_issue 样本（快照注入 bug，留 diff）→ 凑 golden 30–50 条
2. judge 模块：prompt / 解析 / 本地校验 + 单测（fake LLM）
3. golden 存储 + 标注工具（CLI：逐条显示失败 → 人工选标签）
4. evaluate：一致率 + 混淆矩阵 + 单测
5. `aiae judge` CLI + 真实评测跑一轮 → 一致率【待实测→实测】
6. 面试文档 §8 V3 行 + README 证据链更新

## 9. 面试讲法

> judge 不解决「AI 会不会判」，解决「AI 判得对不对有没有证据」。
> 我用 golden 人工标注（规则先写死 + 双人抽检）算一致率，并且**单独报 bug 漏报率**
> ——漏判真 Bug 比误报可怕得多。双模型投票成本翻倍、不能证明正确，放 Roadmap。
