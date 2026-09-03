"""命令行入口（骨架）：python -m aiae.cli，或安装后执行 aiae。

子命令规划：
  selfcheck —— 环境自检（骨架阶段唯一可用）
  generate  —— V1：OpenAPI -> 生成用例落盘（任务 2）
  run       —— V1：执行生成用例并输出指标（任务 2）
  heal      —— V2：UI 失败自愈（占位）
  judge     —— V3：真 Bug / Flaky 判定（占位）
"""

from __future__ import annotations

import argparse
import sys

from aiae.config import LLMConfig, PathsConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiae", description="AI-TAE：AI 智能测试辅助引擎")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("selfcheck", help="环境自检（骨架阶段唯一可用命令）")
    sub.add_parser("generate", help="[任务2] OpenAPI -> 生成 pytest 用例草稿")
    sub.add_parser("run", help="[任务2] 执行已生成用例并统计指标")
    sub.add_parser("heal", help="[V2] UI 失败自愈（占位）")
    sub.add_parser("judge", help="[V3] 真Bug/Flaky 判定（占位）")
    return p


def _print_config_summary() -> None:
    llm = LLMConfig.from_env()
    paths = PathsConfig()
    print("AI-TAE 自检（骨架 v0.1）")
    print(f"  LLM base_url : {llm.base_url}")
    print(f"  LLM model    : {llm.model}")
    print(f"  API Key      : {'已配置' if llm.is_configured() else '未配置（真实生成前需配置）'}")
    print(f"  项目根目录   : {paths.project_root}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "selfcheck":
        _print_config_summary()
        return 0
    print(f"[{args.command}] 尚未实现：将在对应阶段落地，见 docs/v1-technical-design.md。")
    return 1


if __name__ == "__main__":
    sys.exit(main())