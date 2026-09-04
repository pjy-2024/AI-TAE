"""被测项目适配层：AI-TAE 与被测项目的解耦边界（见 base.py docstring）。"""

from aiae.targets.base import ResourceAdapter, TargetAdapter, get_adapter, register_adapter

# import 触发注册（AITAE_TARGET 选择；换被测项目 = 在此加 import 即可）
from aiae.targets import todo_app  # noqa: F401
from aiae.targets import fastapi_crud_todo  # noqa: F401

__all__ = ["ResourceAdapter", "TargetAdapter", "get_adapter", "register_adapter"]
