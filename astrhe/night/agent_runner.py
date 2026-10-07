"""夜间 agent 运行器：统一调用 context.tool_loop_agent。

约定（2026-10-07 修订）：
- max_steps 与 tool_call_timeout 传常量极大值（不设上限，做到做完为止）；
- 一律 stream=True：AstrBot 把 provider 的 timeout 原样交给 SDK，按「两次收到
  数据之间的间隔」计算；非流式要等整段生成完才收到第一个字节，长输出会被误判
  超时。流式只要模型持续输出就不会超时；
- role == "err" 或抛异常一律视为失败，由调用方终止整晚运行；
- 每次调用各用一个新的静默事件，不共用。
"""

from __future__ import annotations

from typing import Any

from .. import constants as C
from .silent_event import make_silent_event

try:
    from astrbot.core.agent.hooks import BaseAgentRunHooks
    from astrbot.core.agent.tool import ToolSet
except Exception:  # pragma: no cover
    BaseAgentRunHooks = object  # type: ignore[assignment]
    ToolSet = None  # type: ignore[assignment]


class NightAgentError(Exception):
    """夜间 agent 模型请求失败：整晚运行应立即终止。"""


class CaptureHooks(BaseAgentRunHooks):  # type: ignore[misc]
    """捕获 run_context.messages，供「追问一次」续跑。"""

    def __init__(self) -> None:
        self.messages: list = []

    async def on_agent_done(self, run_context: Any, llm_response: Any) -> None:
        try:
            self.messages = [m.model_dump() for m in run_context.messages]
        except Exception:  # noqa: BLE001
            self.messages = []


async def run_night_agent(
    context: Any,
    *,
    umo: str,
    provider_id: str,
    system_prompt: str,
    prompt: str,
    tools: list | None = None,
    contexts: list | None = None,
) -> tuple[str, list]:
    """跑一次夜间 agent，返回 (最终文本, 上下文消息列表)。

    失败（role=="err" / 异常）抛 NightAgentError。
    """
    event = make_silent_event(context, umo, message=prompt[:50])
    hooks = CaptureHooks()
    tool_set = ToolSet(tools=list(tools or [])) if ToolSet is not None else None
    try:
        resp = await context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt=system_prompt,
            tools=tool_set,
            contexts=contexts or [],
            max_steps=C.UNLIMITED_STEPS,
            tool_call_timeout=C.UNLIMITED_SECONDS,
            stream=True,
            agent_hooks=hooks,
        )
    except NightAgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise NightAgentError(f"模型调用异常: {exc}") from exc
    if resp is None:
        raise NightAgentError("模型没有返回任何结果")
    if getattr(resp, "role", "") == "err":
        raise NightAgentError(f"模型请求失败: {getattr(resp, 'completion_text', '')}")
    return resp.completion_text or "", hooks.messages


async def get_persona_prompt(context: Any, umo: str = "") -> str:
    """取默认人格提示词；失败返回空串。"""
    try:
        persona = await context.persona_manager.get_default_persona_v3(umo or None)
        return str(getattr(persona, "prompt", "") or "")
    except Exception:  # noqa: BLE001
        return ""
