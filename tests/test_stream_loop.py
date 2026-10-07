"""流式循环端到端测试（修订 §11）：用假 Provider 的 text_chat_stream 跑通
一次带工具调用的流式 agent 循环，确认能拿到最终回答，且全程无真实发送。

需要 ASTRBOT_SOURCE_PATH 指向真实 AstrBot 源码。
"""
# ruff: noqa: E402

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ASTRBOT_SOURCE = os.environ.get("ASTRBOT_SOURCE_PATH")
if not ASTRBOT_SOURCE or not Path(ASTRBOT_SOURCE).is_dir():
    pytest.skip("需要 ASTRBOT_SOURCE_PATH 指向 AstrBot 源码", allow_module_level=True)
if str(ASTRBOT_SOURCE) not in sys.path:
    sys.path.insert(0, str(ASTRBOT_SOURCE))

from astrbot.core.agent.tool import FunctionTool
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.provider import Provider

from astrhe import constants as C
from astrhe.night.silent_event import make_silent_event
from tests.conftest import FakeContext, arun


class EchoTool(FunctionTool):
    """测试工具：把输入原样返回。"""

    def __init__(self):
        super().__init__(
            name="echo_tool",
            description="回声",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
        )

    async def run(self, event, text: str = "") -> str:
        return f"echo: {text}"


class FakeStreamProvider(Provider):
    """假流式 Provider：第一轮发起工具调用，第二轮给最终回答。"""

    def __init__(self):
        super().__init__(
            {"id": "fake-stream", "type": "fake", "enable": True},
            {},
        )
        self.rounds = 0

    async def text_chat(self, **kwargs) -> LLMResponse:
        raise NotImplementedError("本测试只走流式")

    async def text_chat_stream(self, **kwargs):
        self.rounds += 1
        if self.rounds == 1:
            resp = LLMResponse(
                role="assistant",
                result_chain=MessageChain().message(""),
                tools_call_args=[{"text": "夜间你好"}],
                tools_call_name=["echo_tool"],
                tools_call_ids=["call-1"],
            )
            resp.is_chunk = False
            yield resp
        else:
            yield LLMResponse(
                role="assistant",
                result_chain=MessageChain().message("工具结果收到，今晚规划完成"),
            )

    def get_current_key(self):
        return "fake-key"

    def get_models(self):
        return ["fake-model"]

    def set_key(self, key):
        pass


class _ProviderManager:
    def __init__(self, provider):
        self._provider = provider
        self.llm_tools = SimpleNamespace(func_list=[])

    async def get_provider_by_id(self, provider_id):
        return self._provider


def test_streaming_tool_loop_end_to_end():
    from astrbot.core.agent.tool import ToolSet

    async def run():
        from asyncio import Queue

        from astrbot.core.star.context import Context as RealContext

        fake = FakeContext()
        provider = FakeStreamProvider()
        # 构造真实的 Context（构造器不做校验，只用我们需要的字段）
        ctx = RealContext(
            Queue(), {}, None, _ProviderManager(provider), fake.platform_manager,
            None, None, fake.persona_manager, None, None, fake.cron_manager,
        )

        sink = []
        event = make_silent_event(ctx, "default:GroupMessage:20002", discard_sink=sink)
        resp = await ctx.tool_loop_agent(
            event=event,
            chat_provider_id="fake-stream",
            prompt="测试",
            tools=ToolSet(tools=[EchoTool()]),
            max_steps=C.UNLIMITED_STEPS,
            tool_call_timeout=C.UNLIMITED_SECONDS,
            stream=True,
        )
        return resp, sink

    resp, sink = arun(run())
    assert resp is not None and resp.role == "assistant"
    assert "规划完成" in resp.completion_text
