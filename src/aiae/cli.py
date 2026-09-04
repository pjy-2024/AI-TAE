"""命令行入口：aiae generate / run / heal / selfcheck（V3 judge 占位）。

职责边界：cli 是薄壳 —— 只做「解析参数 -> 调底层函数 -> 打印结果」，
业务逻辑一律在 parser / generator / runner / metrics 里（已各自单测）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aiae.config import LLMConfig, PathsConfig
from aiae.generator import generate_for_operations
from aiae.llm.client import LLMClient
from aiae.metrics import Metrics
from aiae.healer import Healer
from aiae.healer.ui import UISession
from aiae.kv import KVStore
from aiae.parser.openapi import iter_operations, load_spec
from aiae.rag import RAGStore
from aiae.runner import run_pytest

# 相对项目根的被测 OpenAPI 缺省路径（todo_app 为当前固定被测项目）
_DEFAULT_OPENAPI = Path("samples/openapi/todo_app-openapi.json")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiae", description="AI-TAE：AI 智能测试辅助引擎")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("selfcheck", help="环境自检")
    gen = sub.add_parser("generate", help="OpenAPI -> 生成 pytest 用例草稿（需配 AITAE_LLM_API_KEY）")
    gen.add_argument("--openapi", type=str, default=str(_DEFAULT_OPENAPI),
                     help="OpenAPI 文件路径（相对项目根或绝对路径）")
    gen.add_argument("--out-dir", type=str, default=None,
                     help="用例草稿输出目录（缺省 data/generated_tests，gitignore 不入库）")
    run = sub.add_parser("run", help="执行已生成用例并统计指标")
    run.add_argument("--dir", type=str, default=None,
                     help="用例目录（缺省 data/generated_tests）")
    run.add_argument("--junit-xml", type=str, default=None,
                     help="junitxml 落盘路径（缺省 data/runs/latest.xml）")
    heal = sub.add_parser("heal", help="[V2] UI 失败自愈：失败样本 -> KV/RAG/LLM -> 人工确认 -> 应用写回")
    heal.add_argument("--sample", type=str, default="data/v2_experiments/failure-sample.json",
                      help="失败样本 JSON（相对项目根或绝对路径）")
    heal.add_argument("--auto", action="store_true",
                      help="自动确认（演示/链路验证用；缺省交互式 y/N 人工确认）")
    sub.add_parser("judge", help="[V3] 真Bug/Flaky 判定（占位）")
    return p


def _resolve_project_path(raw: str) -> Path:
    """相对路径按项目根解析（CLI 常在项目根运行，但显式化更稳）。"""
    p = Path(raw)
    if p.is_absolute():
        return p
    return Path(PathsConfig().project_root) / p


def _cmd_generate(args: argparse.Namespace) -> int:
    """OpenAPI -> 生成用例草稿。"""
    spec_path = _resolve_project_path(args.openapi)
    if not spec_path.exists():
        print(f"[generate] OpenAPI 文件不存在: {spec_path}")
        return 1

    spec = load_spec(spec_path)
    operations = list(iter_operations(spec))

    config = LLMConfig.from_env()
    if not config.is_configured():
        print("[generate] 未配置 AITAE_LLM_API_KEY：真实生成前请复制 .env.example 为 .env 并填入 key")
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else Path(PathsConfig().generated_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = spec.get("info", {}) or {}
    spec_summary = {"title": info.get("title", ""), "version": info.get("version", "")}

    print(f"[generate] OpenAPI: {spec_path}（{len(operations)} 个接口）")
    print(f"[generate] 输出目录: {out_dir}（产物在 data/，gitignore 不入库）")
    report = generate_for_operations(operations, out_dir=out_dir,
                                     spec_summary=spec_summary, client=LLMClient(config))

    print(f"  requested = {report.requested}")
    print(f"  succeeded = {report.succeeded}（落盘 {report.succeeded} 条草稿）")
    if report.failed:
        print(f"  failed    = {len(report.failed)}")
        for reason in report.failed[:10]:
            print(f"    - {reason}")
        if len(report.failed) > 10:
            print(f"    ... 其余 {len(report.failed) - 10} 条略")
    if report.retry_counts:
        avg_retry = sum(report.retry_counts) / len(report.retry_counts)
        print(f"  平均改写重试次数 = {avg_retry:.2f}（语义层限次重试）")
    print("[generate] 完成：生成的是草稿，请人工审阅后执行 `aiae run` 验证")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """执行已生成用例并统计指标（报数先报口径）。"""
    target_dir = Path(args.dir) if args.dir else Path(PathsConfig().generated_dir)
    if not target_dir.is_dir():
        print(f"[run] 用例目录不存在: {target_dir}（请先执行 aiae generate）")
        return 1

    paths = PathsConfig()
    junit = Path(args.junit_xml) if args.junit_xml else Path(paths.data_dir) / "runs" / "latest.xml"

    summary = run_pytest(target_dir, junit_xml=junit)

    # 口径（与 docs/v1-technical-design.md §7 一致）：
    #   generated  ≈ pytest 收集总数（精确值来自 generate 阶段的 report，跨命令传递待端到端决定）
    #   executable = passed + failed（能跑起来的，含断言失败）；error 属不可执行类
    generated = summary.total
    executable = summary.passed + summary.failed
    metrics = Metrics(
        generated_count=generated,
        executable_count=executable,
        passed_count=summary.passed,
        failed_count=summary.failed,
        error_count=summary.errors,
    )

    print(f"[run] 用例目录: {target_dir}（junit: {junit}）")
    print(f"  pytest 收集 = {summary.total}（passed={summary.passed} failed={summary.failed} "
          f"errors={summary.errors} skipped={summary.skipped}）")
    print("  口径：generated≈pytest 收集数；可执行 = passed + failed（error 属不可执行类）")
    print(f"  可执行率 = {executable}/{generated} = {metrics.executable_rate:.1%}")
    print(f"  通过率   = {summary.passed}/{executable} = {metrics.pass_rate:.1%}（分母=可执行）")
    if summary.errors:
        print(f"  错误率   = {summary.errors}/{executable} = {metrics.error_rate:.1%}")
    if summary.total == 0:
        print("[run] 没有收集到用例：目录可能为空，请先 aiae generate")
    return 0


def _cmd_heal(args: argparse.Namespace) -> int:
    """UI 失败自愈：读失败样本 -> 恢复页面现场 -> Healer 编排 -> 打印报告。"""
    sample_path = _resolve_project_path(args.sample)
    if not sample_path.exists():
        print(f"[heal] 失败样本不存在: {sample_path}（先用 UI 测试复现失败并落盘样本）")
        return 1
    try:
        failure = json.loads(sample_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[heal] 失败样本不是合法 JSON: {sample_path}（{exc}）")
        return 1
    # 兼容两种样本格式：扁平（Healer.heal 输入）或 {scenario, error_info:{...}} 嵌套
    if isinstance(failure.get("error_info"), dict):
        nested = failure["error_info"]
        failure = {**nested, "scenario": failure.get("scenario", "")}
    if failure.get("error_type") != "locator_not_found":
        # 安全护栏：只对「元素定位失败」自愈，防止把真 Bug 当改版修
        print(f"[heal] 错误类型 {failure.get('error_type')!r} 不是 locator_not_found，拒绝自愈（护栏：只自愈定位失败）")
        return 1
    page_url = failure.get("page_url", "")
    if not page_url:
        print("[heal] 失败样本缺 page_url，无法恢复页面现场")
        return 1

    config = LLMConfig.from_env()
    if not config.is_configured():
        print("[heal] 未配置 AITAE_LLM_API_KEY：自愈需调 LLM 兜底，请先配置 .env")
        return 1

    kv, rag = KVStore(), RAGStore()
    confirm = (lambda proposal: True) if args.auto else None  # None -> Healer 默认交互 y/N
    healer = Healer(kv=kv, rag=rag, llm=LLMClient(config), confirm=confirm)
    with UISession("") as ui:
        print(f"[heal] 打开页面现场: {page_url}")
        ui.open_url(page_url)
        result = healer.heal(ui, failure)

    print(f"  结果      : {result.outcome}")
    print(f"  新定位器  : {result.new_locator or '-'}")
    print(f"  来源      : {result.source or '-'}")
    print(f"  LLM 尝试  : {result.attempts}")
    print(f"  说明      : {result.message}")
    stats = kv.stats()
    total = stats["hits"] + stats["misses"]
    if total:
        print(f"  KV 统计   : hits={stats['hits']} misses={stats['misses']} 命中率={stats['hits'] / total:.0%}")
    return 0 if result.outcome in ("kv_hit", "healed") else 1


def _print_config_summary() -> None:
    llm = LLMConfig.from_env()
    paths = PathsConfig()
    print("AI-TAE 自检")
    print(f"  LLM base_url : {llm.base_url}")
    print(f"  LLM model    : {llm.model}")
    print(f"  API Key      : {'已配置' if llm.is_configured() else '未配置（真实生成前需配置）'}")
    print(f"  项目根目录   : {paths.project_root}")
    generated_dir = Path(paths.generated_dir)
    n_files = len(list(generated_dir.glob("test_*.py"))) if generated_dir.is_dir() else 0
    print(f"  草稿用例数   : {n_files}（{generated_dir}）")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "selfcheck":
        _print_config_summary()
        return 0
    if args.command == "generate":
        return _cmd_generate(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "heal":
        return _cmd_heal(args)
    print(f"[{args.command}] 尚未实现：将在对应阶段落地，见 docs/v1-technical-design.md。")
    return 1


if __name__ == "__main__":
    sys.exit(main())