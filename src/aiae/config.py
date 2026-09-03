"""全局配置：统一从环境变量读取，密钥与地址不写死在代码里。

设计理由：
1. API Key 绝不能入库 —— .env 已被 .gitignore 排除；
2. 供应商可切换（DeepSeek / Qwen 都走 OpenAI 兼容接口）：换模型只改环境变量、
   不改代码 —— 回答面试题「换一个模型系统会崩吗」的论据之一就是「配置与模型解耦 + Schema 约束」；
3. 骨架阶段只用标准库 dataclass + os.getenv，零第三方依赖即可被测试导入。

面试可讲：配置与实现分离、密钥安全、供应商无关。
可能被追问：换供应商字段不一致怎么办？（答：只依赖 OpenAI 兼容公共子集 chat/completions。）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _project_root() -> str:
    """src/aiae/config.py 向上三级即项目根目录（含 pyproject.toml 的那一层）。"""
    here = os.path.dirname(os.path.abspath(__file__))          # .../src/aiae
    return os.path.dirname(os.path.dirname(here))              # 项目根


# 项目级 .env（已 gitignore）在读取任何 AITAE_* 前加载。
# override=False：已存在的真实环境变量优先，.env 不覆盖（便于 CI/部署注入）。
load_dotenv(Path(_project_root()) / ".env", override=False)


@dataclass(frozen=True)
class LLMConfig:
    """LLM 调用配置（OpenAI 兼容接口）。"""

    api_key: str = ""
    base_url: str = "https://api.deepseek.com"   # Qwen 换 https://dashscope.aliyuncs.com/compatible-mode/v1
    model: str = "deepseek-chat"                 # 便宜、国内可访问；评测阶段可换模型做回归
    temperature: float = 0.0                     # 生成代码用低温，追求确定性
    timeout_seconds: float = 60.0
    max_retries: int = 3                         # 429/5xx 重试上限
    json_mode: bool = True                       # 默认要求结构化 JSON 输出
    max_tokens: int | None = None                # 按需设置，控制成本

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从 AITAE_LLM_* 环境变量构造；未设置时使用内置默认值（便于骨架阶段无密钥运行）。"""
        return cls(
            api_key=os.getenv("AITAE_LLM_API_KEY", ""),
            base_url=os.getenv("AITAE_LLM_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("AITAE_LLM_MODEL", "deepseek-chat"),
            temperature=float(os.getenv("AITAE_LLM_TEMPERATURE", "0.0")),
            timeout_seconds=float(os.getenv("AITAE_LLM_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.getenv("AITAE_LLM_MAX_RETRIES", "3")),
            json_mode=_get_bool("AITAE_LLM_JSON_MODE", True),
            max_tokens=None,
        )

    def is_configured(self) -> bool:
        """是否已配置 API Key（真实调用前必须为 True）。"""
        return bool(self.api_key)


@dataclass(frozen=True)
class PathsConfig:
    """运行路径约定：所有产物集中到 data/（已 gitignore），不入库。"""

    project_root: str = field(default_factory=_project_root)
    data_dir: str = field(default_factory=lambda: os.path.join(_project_root(), "data"))
    generated_dir: str = field(default_factory=lambda: os.path.join(_project_root(), "data", "generated_tests"))
    sqlite_path: str = field(default_factory=lambda: os.path.join(_project_root(), "data", "aiae.sqlite3"))
    chroma_dir: str = field(default_factory=lambda: os.path.join(_project_root(), "data", "chroma"))
    cache_dir: str = field(default_factory=lambda: os.path.join(_project_root(), "data", "cache"))