"""AstrHe 工具基类：所有插件内 FunctionTool 子类共用。

- 统一 run(self, event, **kwargs) 入口，分发到 async 处理函数；
- 保证始终返回非空字符串（硬性要求：防止执行器触发 event.send）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

try:
    from astrbot.api import FunctionTool
except Exception:  # pragma: no cover
    FunctionTool = None  # type: ignore[assignment]


def tool_base_class():
    return FunctionTool if FunctionTool is not None else object


@dataclass
class AstrHeFunctionTool(tool_base_class()):  # type: ignore[misc]
    """通用 AstrHe 工具：fn 签名为 async (event, **kwargs) -> str。"""

    fn: Callable[..., Awaitable[str]] | None = None
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def run(self, event: Any, **kwargs: Any) -> str:
        if self.fn is None:
            return "这个工具还没有实现"
        try:
            result = await self.fn(event, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 工具绝不抛出，避免执行器走发送路径
            return f"工具执行失败: {exc}"
        if not isinstance(result, str) or not result.strip():
            return "工具已执行，无文字结果"
        return result
