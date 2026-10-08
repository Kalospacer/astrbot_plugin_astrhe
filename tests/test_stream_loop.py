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
            Queue(),
            {},
            None,
            _ProviderManager(provider),
            fake.platform_manager,
            None,
            None,
            fake.persona_manager,
            None,
            None,
            fake.cron_manager,
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


def test_real_streaming_retry_keeps_tool_results_without_repeating_tool():
    async def run():
        from asyncio import Queue
        from astrbot.core.star.context import Context as RealContext
        from astrhe.night.agent_runner import run_night_agent

        calls = []

        class CountingEcho(EchoTool):
            async def run(self, event, text=""):
                calls.append(text)
                return await super().run(event, text)

        class RetryProvider(FakeStreamProvider):
            async def text_chat_stream(self, **kwargs):
                if self.rounds == 1:
                    self.rounds += 1
                    raise RuntimeError("请求暂时失败")
                if self.rounds == 2:
                    self.rounds += 1
                    history = [
                        m.model_dump() if hasattr(m, "model_dump") else m
                        for m in kwargs.get("contexts", [])
                    ]
                    assert any(m.get("role") == "tool" for m in history), history
                    assert sum(m.get("role") == "system" for m in history) <= 1
                    yield LLMResponse(
                        role="assistant",
                        result_chain=MessageChain().message("续跑完成"),
                    )
                    return
                async for value in super().text_chat_stream(**kwargs):
                    yield value

        fake = FakeContext()
        provider = RetryProvider()
        ctx = RealContext(
            Queue(),
            {},
            None,
            _ProviderManager(provider),
            fake.platform_manager,
            None,
            None,
            fake.persona_manager,
            None,
            None,
            fake.cron_manager,
        )
        text, history = await run_night_agent(
            ctx,
            umo="",
            provider_id="fake-stream",
            system_prompt="人格和规则",
            prompt="执行一次工具",
            tools=[CountingEcho()],
        )
        assert text == "续跑完成" and calls == ["夜间你好"]
        assert not any(m["role"] == "system" for m in history)
        assert not fake.sent_messages

    arun(run())


def test_reporter_json_repair_uses_real_streaming_history_and_tool_result(tmp_path):
    async def run():
        from asyncio import Queue
        from zoneinfo import ZoneInfo
        from astrbot.core.star.context import Context as RealContext
        from astrhe.night.reporter import FIX_JSON_PROMPT, Reporter
        from astrhe.timeutil import utc_now
        from tests.conftest import make_storage

        tool_calls = []

        class CountingEcho(EchoTool):
            async def run(self, event, text=""):
                tool_calls.append(text)
                return await super().run(event, text)

        class JsonRepairProvider(FakeStreamProvider):
            async def text_chat_stream(self, **kwargs):
                if self.rounds == 0:
                    async for response in super().text_chat_stream(**kwargs):
                        yield response
                    return
                self.rounds += 1
                if self.rounds == 2:
                    text = "蛋糕已准备好，但这次先输出了散文。"
                else:
                    assert self.rounds == 3
                    history = [
                        m.model_dump() if hasattr(m, "model_dump") else m
                        for m in kwargs.get("contexts", [])
                    ]
                    assert any(m["role"] == "tool" for m in history)
                    assert "echo: 夜间你好" in str(history)
                    assert "先输出了散文" in str(history)
                    assert FIX_JSON_PROMPT in str(history) + str(kwargs.get("prompt"))
                    text = '{"summary":"蛋糕已准备好","big_events":[]}'
                yield LLMResponse(
                    role="assistant",
                    result_chain=MessageChain().message(text),
                )

        fake = FakeContext()
        provider = JsonRepairProvider()
        ctx = RealContext(
            Queue(), {}, None, _ProviderManager(provider), fake.platform_manager,
            None, None, fake.persona_manager, None, None, fake.cron_manager,
        )
        storage = await make_storage(tmp_path)
        try:
            now = utc_now()
            run_id = await storage.runs.start_run(plan_date="2026-10-08")
            umo = "default:GroupMessage:20002"
            await storage.ledger.add_message(
                umo=umo, platform_id="default", message_type="GroupMessage",
                session_id="20002", sender_id="10001", text="蛋糕已经准备好了",
                ts=now - 1, platform_message_id="5010",
            )
            reporter = Reporter(
                storage, ctx, "fake-stream", "测试人格", ZoneInfo("Asia/Shanghai"),
                [CountingEcho()], self_id="99999",
            )
            result = await reporter.report_session(run_id, umo, now - 10, now + 1)
            assert result["parse_ok"] and result["report"]["summary"] == "蛋糕已准备好"
            assert provider.rounds == 3 and tool_calls == ["夜间你好"]
            assert not fake.sent_messages
        finally:
            await storage.close()

    arun(run())
