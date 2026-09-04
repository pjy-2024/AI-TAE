"""被测项目适配层：AI-TAE 与被测项目的解耦边界（见 base.py docstring）。"""

from aiae.targets.base import ResourceAdapter, TargetAdapter, get_adapter, register_adapter

# import 触发注册（todo_app 为当前内置适配器；换项目在此加 import 即可）
from aiae.targets import todo_app  # noqa: F401

__all__ = ["ResourceAdapter", "TargetAdapter", "get_adapter", "register_adapter"]
