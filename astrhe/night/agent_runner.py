"""夜间统一流式调用：不限步数/内部工具时长，带上下文重试连续模型失败。"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
from typing import Any

from astrbot.api import logger

from .. import constants as C
from .silent_event import make_silent_event

try:
    from astrbot.core.agent.hooks import BaseAgentRunHooks
    from astrbot.core.agent.tool import ToolSet
except ImportError:  # pragma: no cover
    BaseAgentRunHooks = object
    ToolSet = None

# 子任务继承同一份运行统计，各次模型失败记录归属于本次运行。
retry_stats = contextvars.ContextVar("astrhe_retry_stats", default=None)


class NightAgentError(Exception):
    """连续模型失败达到上限，未提交的运行应终止。"""


def message_dict(message: Any) -> dict:
    return message.model_dump() if hasattr(message, "model_dump") else dict(message)


class CaptureHooks(BaseAgentRunHooks):
    """开始时保存可变上下文引用，失败时同样能拿到已完成的工具调用。"""

    def __init__(self) -> None:
        self.run_context = None
        self.messages: list = []
        self.initial_assistants = 0

    async def on_agent_begin(self, run_context: Any) -> None:
        self.run_context = run_context
        self.initial_assistants = self.assistant_count()

    def snapshot(self) -> list[dict]:
        if self.run_context is not None:
            return [message_dict(m) for m in self.run_context.messages]
        return self.messages

    def assistant_count(self) -> int:
        return sum(m.get("role") == "assistant" for m in self.snapshot())

    async def on_agent_done(self, run_context: Any, llm_response: Any) -> None:
        self.run_context = run_context
        self.messages = self.snapshot()


async def run_night_agent(
    context: Any,
    *,
    umo: str,
    provider_id: str,
    system_prompt: str,
    prompt: str | None,
    tools: list | None = None,
    contexts: list | None = None,
) -> tuple[str, list]:
    """持续保留对话与工具结果；三次连续失败抛错，取消不参与重试。"""
    current_prompt = prompt
    current_contexts = list(contexts or [])
    failures = 0
    attempt = 0
    while True:
        attempt += 1
        hooks = CaptureHooks()
        event = make_silent_event(context, umo, message="AstrHe 夜间复盘")
        tool_set = ToolSet(tools=list(tools or [])) if ToolSet is not None else None
        try:
            resp = await context.tool_loop_agent(
                event=event,
                chat_provider_id=provider_id,
                prompt=current_prompt,
                system_prompt=system_prompt,
                tools=tool_set,
                contexts=current_contexts,
                max_steps=C.UNLIMITED_STEPS,
                tool_call_timeout=C.UNLIMITED_SECONDS,
                stream=True,
                agent_hooks=hooks,
            )
            if resp is None or getattr(resp, "role", "") == "err":
                raise NightAgentError(
                    str(getattr(resp, "completion_text", "") or "模型没有返回结果")
                )
            return resp.completion_text or "", [
                m for m in hooks.snapshot() if m.get("role") != "system"
            ]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 已有成功 assistant（可能带工具调用）意味着上一段连续失败已结束。
            progressed = hooks.assistant_count() > hooks.initial_assistants
            failures = 1 if progressed else failures + 1
            detail = {
                "attempt": attempt,
                "consecutive": failures,
                "reason": f"{type(exc).__name__}: {exc}",
                "umo": umo,
            }
            logger.debug(f"[AstrHe] 夜间模型失败: {detail}")
            stats = retry_stats.get()
            if stats is not None:
                stats.setdefault("model_failures", []).append(detail)
            if failures >= C.NIGHT_MAX_CONSECUTIVE_FAILURES:
                raise NightAgentError(f"连续 {failures} 次模型请求失败：{exc}") from exc
            if hooks.run_context is not None:
                current_contexts = [
                    m for m in hooks.snapshot() if m.get("role") != "system"
                ]
                current_prompt = None
            await asyncio.sleep(C.NIGHT_RETRY_DELAY_SECONDS)


async def get_persona_prompt(context: Any, umo: str = "", persona_id: str = "") -> str:
    """读取选定人格；为空或不存在时回退 AstrBot 默认人格。"""
    manager = context.persona_manager
    persona = None
    if persona_id:
        try:
            persona = manager.get_persona_v3_by_id(persona_id)
            if inspect.isawaitable(persona):
                persona = await persona
        except Exception as exc:
            logger.warning(f"[AstrHe] 读取选定人格失败：{exc}")
    if persona is None:
        logger.warning("[AstrHe] 未选择人格或人格不存在，使用 AstrBot 默认人格")
        persona = await manager.get_default_persona_v3(umo or None)
    prompt = (
        persona.get("prompt", "")
        if isinstance(persona, dict)
        else getattr(persona, "prompt", "")
    )
    return str(prompt or "")
