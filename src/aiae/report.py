"""HTML 运行报告：把 data/ 下的真实产物渲染成单文件报告（base64 内嵌图，自包含）。

定位（面试可讲）：工具本质是 CLI，展示层「按需生成」——不引前端框架、不起 web 服务；
run/heal 成功后自动重生成 = 事件驱动，报告永远是最新的，Edge 打开即看。

数据源：
- V1 最近一次 run：data/runs/latest.xml（junit，若存在）
- V2 自愈记录：data/v2_experiments/batch-heal-summary.json（若存在；否则显示占位）
- 里程碑图：docs/images/v1-pass-rate-trend.png / v2-llm-calls.png（真实数字绘制，base64 内嵌）
"""

from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from aiae.config import PathsConfig
from aiae.targets import get_adapter


def _b64img(p: Path) -> str:
    return base64.b64encode(Path(p).read_bytes()).decode()


def _read_v1(latest_xml: Path) -> dict[str, Any]:
    if not latest_xml.exists():
        return {"available": False}
    root = ET.parse(str(latest_xml)).getroot()
    cases = []
    for tc in root.iter("testcase"):
        name = tc.get("name", "?")
        status = ("error" if tc.find("error") is not None
                  else "failed" if tc.find("failure") is not None
                  else "skipped" if tc.find("skipped") is not None else "passed")
        cases.append({"name": name, "status": status, "time": tc.get("time", "")})
    total = len(cases)
    passed = sum(1 for c in cases if c["status"] == "passed")
    failed = sum(1 for c in cases if c["status"] == "failed")
    errors = sum(1 for c in cases if c["status"] == "errors" or c["status"] == "error")
    return {"available": True, "total": total, "passed": passed, "failed": failed,
            "errors": errors, "cases": sorted(cases, key=lambda c: c["name"])}


def _read_v2(summary_path: Path) -> dict[str, Any]:
    if not summary_path.exists():
        return {"available": False}
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    healed = sum(1 for r in rows if r.get("outcome") in ("kv_hit", "healed"))
    kv = data.get("kv_stats", {})
    total = kv.get("hits", 0) + kv.get("misses", 0)
    return {
        "available": True, "rows": rows, "healed": healed, "total": len(rows),
        "kv_hits": kv.get("hits", 0), "kv_total": total,
        "rag_count": data.get("rag_count", 0),
    }


def build_report(
    *,
    runs_xml: Path | None = None,
    v2_summary: Path | None = None,
    out: Path | None = None,
) -> Path:
    """生成 HTML 报告，返回输出路径。缺省读 data/ 下最新产物。"""
    adapter = get_adapter()
    target_display = adapter.display_name or adapter.name
    data_dir = Path(PathsConfig().data_dir)
    latest_xml = Path(runs_xml) if runs_xml else data_dir / "runs" / "latest.xml"
    summary = Path(v2_summary) if v2_summary else data_dir / "v2_experiments" / "batch-heal-summary.json"
    out_path = Path(out) if out else data_dir / "reports" / "latest.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    v1 = _read_v1(latest_xml)
    v2 = _read_v2(summary)
    trend_png = _b64img(Path(PathsConfig().project_root) / "docs/images/v1-pass-rate-trend.png")
    cost_png = _b64img(Path(PathsConfig().project_root) / "docs/images/v2-llm-calls.png")

    # 卡片显示值（先算成安全变量，避免 f-string 索引缺失键）
    v1_count_disp = str(v1["total"]) if v1["available"] else "-"
    v1_pass_disp = f"{v1['passed']}/{v1['total']}" if v1["available"] else "-"
    v2_heal_disp = f"{v2['healed']}/{v2['total']}" if v2["available"] else "-"
    v2_kv_disp = f"{v2['kv_hits']}/{v2['kv_total']}" if v2["available"] else "-"

    # ---- V1 区块 ----
    if v1["available"]:
        v1_pct = f"{v1['passed']}/{v1['total']}"
        case_rows = "".join(
            f"<tr><td><code>{c['name']}</code></td><td><span class='pill p-{c['status']}'>{c['status']}</span></td>"
            f"<td>{c['time']}s</td></tr>" for c in v1["cases"])
        v1_section = f"""<h2>V1 · 最近一次真实执行（{v1_pct} 通过）</h2>
        <table><tr><th>用例</th><th>结果</th><th>耗时</th></tr>{case_rows}</table>"""
    else:
        v1_pct = "-"
        v1_section = "<h2>V1 · 最近一次执行</h2><p style='color:#889'>尚无执行记录：先 <code>aiae generate</code> + <code>aiae run</code>，本报告将自动更新。</p>"

    # ---- V2 区块 ----
    if v2["available"]:
        row_html = "".join(
            f"<tr><td>{r['scenario']}</td><td><code>{r['old_locator']}</code></td>"
            f"<td><code>{r['new_locator']}</code></td><td>{r['outcome']}</td><td>{r['source']}</td></tr>"
            for r in v2["rows"])
        kv_pct = f"{v2['kv_hits'] / v2['kv_total']:.0%}" if v2["kv_total"] else "-"
        v2_section = f"""<h2>V2 · UI 失败自愈记录（{v2["healed"]}/{v2["total"]} 成功）</h2>
        <table><tr><th>场景</th><th>旧定位器</th><th>修复后</th><th>结果</th><th>来源</th></tr>{row_html}</table>
        <p style="font-size:12px;color:#889;margin-top:8px">RAG 案例库 {v2["rag_count"]} 条；KV hits={v2["kv_hits"]} 查询={v2["kv_total"]}（命中率 {kv_pct}）。</p>
        <img src="data:image/png;base64,{cost_png}" alt="V2 LLM 调用下降">"""
    else:
        v2_section = ("<h2>V2 · UI 失败自愈记录</h2>"
                      "<p style='color:#889'>尚无自愈记录：制造 UI 失败后跑 <code>aiae heal</code>，本报告将自动更新。</p>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>AI-TAE 运行报告</title><style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:"Microsoft YaHei",sans-serif; background:#f4f6f9; color:#223; padding:24px; }}
.wrap {{ max-width:960px; margin:0 auto; }}
h1 {{ font-size:22px; margin-bottom:4px; }} .sub {{ color:#667; font-size:13px; margin-bottom:18px; }}
.badge {{ display:inline-block; background:#1E8449; color:#fff; border-radius:10px; padding:2px 10px; font-size:12px; }}
.cards {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:20px; }}
.card {{ flex:1 1 180px; background:#fff; border-radius:10px; padding:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.card .num {{ font-size:26px; font-weight:bold; color:#1F3864; }} .card .lbl {{ font-size:13px; color:#667; margin-top:4px; }}
.card .note {{ font-size:11px; color:#999; margin-top:6px; }}
section {{ background:#fff; border-radius:10px; padding:18px; margin-bottom:18px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
h2 {{ font-size:16px; margin-bottom:12px; border-left:4px solid #4C78A8; padding-left:8px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }} th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #eef1f5; }}
th {{ color:#667; font-weight:normal; background:#fafbfd; }} code {{ background:#f0f2f5; padding:1px 5px; border-radius:4px; font-size:12px; }}
img {{ max-width:100%; border-radius:8px; margin-top:10px; }}
.foot {{ color:#889; font-size:12px; line-height:1.8; }}
.pill {{ display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px; }}
.p-passed {{ background:#e9f7ef; color:#1e8449; }} .p-failed {{ background:#fdecea; color:#c0392b; }}
.p-error {{ background:#fef3e2; color:#b9770e; }} .p-skipped {{ background:#eee; color:#666; }}
</style></head><body><div class="wrap">
<h1>AI-TAE 运行报告 <span class="badge">自动生成</span></h1>
<div class="sub">AI 智能测试辅助引擎 · 数据自动读取 data/ 最新产物 · 生成时间见文件修改时间 · 被测项目 {target_display}</div>
<div class="cards">
  <div class="card"><div class="num">{v1_count_disp}</div><div class="lbl">V1 接口数</div><div class="note">最近一次 run</div></div>
  <div class="card"><div class="num">{v1_pass_disp}</div><div class="lbl">V1 通过</div><div class="note">passed/total</div></div>
  <div class="card"><div class="num">{v2_heal_disp}</div><div class="lbl">V2 自愈成功</div><div class="note">场景级</div></div>
  <div class="card"><div class="num">{v2_kv_disp}</div><div class="lbl">V2 KV 命中</div><div class="note">累计查询</div></div>
</div>
<section><h2>V1 · 里程碑（三轮迭代至定稿，2026-09-03）</h2>
<img src="data:image/png;base64,{trend_png}" alt="V1 通过率趋势"></section>
<section>{v1_section}</section>
<section>{v2_section}</section>
<section><h2>V2 · 自愈流程（通俗版）</h2>
<p style="font-size:13px;color:#445;line-height:1.9">定位失败 → <b>① 错误签名</b> → <b>② KV</b>（见过？直接抄）→ <b>③ RAG</b>（相似案例）→ <b>④ LLM</b>（看新页面给修复）→ <b>⑤ 人工确认</b> → <b>⑥ 写回经验</b>（越用越快）</p></section>
<div class="foot">数据来源：data/runs/latest.xml（junit）、data/v2_experiments/batch-heal-summary.json、docs/images（真实数字绘制）。真实数字纪律：一切可回溯产物，未编造。</div>
</div></body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path
