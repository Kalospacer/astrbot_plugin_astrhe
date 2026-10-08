"""夜间连续失败与上下文续跑回归。"""

import asyncio
from types import SimpleNamespace

import pytest

from astrhe import constants as C
from astrhe.night.agent_runner import (
    NightAgentError,
    get_persona_prompt,
    retry_stats,
    run_night_agent,
)
from tests.conftest import FakeContext, arun


def test_context_retry_resets_on_successful_step(monkeypatch):
    monkeypatch.setattr(C, "NIGHT_RETRY_DELAY_SECONDS", 0)

    async def check():
        ctx = FakeContext()
        calls = []
        # 一次循环成功请求后失败；续跑再成功请求后失败；两次失败；最后成功。
        progress = [True, True, False, True]

        async def loop(**kw):
            calls.append(kw)
            messages = [{"role": "system", "content": "system"}] + list(kw["contexts"])
            if kw["prompt"]:
                messages.append({"role": "user", "content": kw["prompt"]})
            rc = SimpleNamespace(messages=messages)
            hooks = kw["agent_hooks"]
            await hooks.on_agent_begin(rc)
            if progress[len(calls) - 1]:
                messages.extend(
                    [
                        {"role": "assistant", "content": "调用工具"},
                        {"role": "tool", "content": "结果"},
                    ]
                )
            if len(calls) == 4:
                return SimpleNamespace(role="assistant", completion_text="完成")
            return SimpleNamespace(role="err", completion_text="timeout")

        ctx.tool_loop_agent = loop
        stats = {}
        token = retry_stats.set(stats)
        try:
            text, _ = await run_night_agent(
                ctx, umo="", provider_id="fake", system_prompt="人格", prompt="开始"
            )
        finally:
            retry_stats.reset(token)
        assert text == "完成"
        assert [f["consecutive"] for f in stats["model_failures"]] == [1, 1, 2]
        for call in calls[1:]:
            assert call["prompt"] is None
            assert not any(m["role"] == "system" for m in call["contexts"])
            assert any(m["role"] == "tool" for m in call["contexts"])
        assert all(
            c["stream"]
            and c["max_steps"] == C.UNLIMITED_STEPS
            and c["tool_call_timeout"] == C.UNLIMITED_SECONDS
            for c in calls
        )

    arun(check())


@pytest.mark.parametrize("exception", [False, True])
def test_three_failures_and_cancellation(monkeypatch, exception):
    monkeypatch.setattr(C, "NIGHT_RETRY_DELAY_SECONDS", 0)

    async def check():
        ctx = FakeContext()
        calls = []

        async def fail(**kw):
            calls.append(kw)
            if exception:
                raise RuntimeError("服务错误")
            return SimpleNamespace(role="err", completion_text="timeout")

        ctx.tool_loop_agent = fail
        with pytest.raises(NightAgentError, match="连续 3"):
            await run_night_agent(
                ctx, umo="", provider_id="fake", system_prompt="", prompt="开始"
            )
        assert len(calls) == 3

        async def cancel(**kw):
            raise asyncio.CancelledError()

        ctx.tool_loop_agent = cancel
        with pytest.raises(asyncio.CancelledError):
            await run_night_agent(
                ctx, umo="", provider_id="fake", system_prompt="", prompt="开始"
            )

    arun(check())


def test_persona_selection_and_default_dict():
    async def check():
        ctx = FakeContext()
        assert await get_persona_prompt(ctx) == "你是测试人格。"
        assert await get_persona_prompt(ctx, persona_id="selected") == "选定的人格"
        assert await get_persona_prompt(ctx, persona_id="missing") == "你是测试人格。"

    arun(check())
