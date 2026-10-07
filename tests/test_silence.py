"""无感保证测试（硬性要求 9）：
- SilentNightEvent 的 send / send_streaming 绝不调用 context.send_message；
- 外部工具代理把 None 和 MessageEventResult 转成文字并清空结果；
- 外部工具代理超时返回文字，不终止运行；
- 全部 AstrHe 工具在各种输入下返回非空字符串；
- 夜间工具集不含黑名单工具。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astrhe.night.silent_event import make_silent_event
from astrhe.night.tool_proxy import ProxiedTool, build_night_toolset, is_blacklisted
from astrhe.tools.base import AstrHeFunctionTool
from tests.conftest import FakeContext, FakeEvent, arun

TZ = ZoneInfo("Asia/Shanghai")


async def _main_silent():
    ctx = FakeContext()
    sink = []
    event = make_silent_event(ctx, "default:GroupMessage:20002", discard_sink=sink)

    class _Chain:
        def __init__(self):
            self.chain = [SimpleNamespace(text="哈喽")]

    await event.send(_Chain())
    await event.send(_Chain())

    async def gen():
        yield _Chain()
        yield _Chain()

    await event.send_streaming(gen())
    # 绝不发送
    assert ctx.sent_messages == []
    # 内容被丢弃（测试里进了 sink）
    assert len(sink) == 4


def test_silent_event_never_sends():
    arun(_main_silent())


async def _main_proxy():
    from astrbot.core.agent.tool import FunctionTool
    from astrbot.core.message.message_event_result import MessageEventResult

    # None 结果 → 文字
    none_tool = FunctionTool(
        name="ext_none", description="d",
        parameters={"type": "object", "properties": {}},
    )

    async def run_none(event, **kw):
        return None

    none_tool.run = run_none
    event = FakeEvent()
    wrapper = SimpleNamespace(context=SimpleNamespace(event=event))
    proxy = ProxiedTool(inner=none_tool, timeout=5)
    out = await proxy.call(wrapper)
    assert isinstance(out, str) and out.strip()

    # MessageEventResult 结果 → 文字 + 清空 event result
    mer_tool = FunctionTool(
        name="ext_mer", description="d",
        parameters={"type": "object", "properties": {}},
    )

    async def run_mer(event, **kw):
        event.set_result(MessageEventResult())
        return MessageEventResult()

    mer_tool.run = run_mer
    event2 = FakeEvent()
    wrapper2 = SimpleNamespace(context=SimpleNamespace(event=event2))
    proxy2 = ProxiedTool(inner=mer_tool, timeout=5)
    out2 = await proxy2.call(wrapper2)
    assert isinstance(out2, str) and out2.strip()
    assert event2.get_result() is None  # clear_result 被调用

    # 超时 → 文字说明，不抛异常
    slow_tool = FunctionTool(
        name="ext_slow", description="d",
        parameters={"type": "object", "properties": {}},
    )

    async def run_slow(event, **kw):
        await asyncio.sleep(5)
        return "done"

    slow_tool.run = run_slow
    proxy3 = ProxiedTool(inner=slow_tool, timeout=1)
    out3 = await proxy3.call(wrapper)
    assert "超时" in out3


def test_proxy_converts_and_times_out():
    arun(_main_proxy())


def test_blacklist():
    assert is_blacklisted("send_message_to_user")
    assert is_blacklisted("send_private_msg")
    assert is_blacklisted("future_task")
    assert is_blacklisted("transfer_to_helper")
    assert is_blacklisted("astrhe_schedule")
    assert is_blacklisted("astrhe_todo_update")
    assert is_blacklisted("astrhe_qq_act")
    assert not is_blacklisted("astrhe_qq_lookup")
    assert not is_blacklisted("astrhe_read_plan")
    assert not is_blacklisted("recall_long_term_memory")
    assert not is_blacklisted("web_search")


def test_night_toolset_excludes_blacklist():
    external = [
        SimpleNamespace(name="send_message_to_user", description="", parameters={}),
        SimpleNamespace(name="web_search", description="", parameters={}),
        SimpleNamespace(name="future_task", description="", parameters={}),
    ]
    internal = [AstrHeFunctionTool(name="astrhe_read_messages", description="", fn=None)]
    tools, excluded = build_night_toolset(external, internal, {})
    names = {t.name for t in tools}
    assert "web_search" in names
    assert "astrhe_read_messages" in names
    assert "send_message_to_user" not in names
    assert "future_task" not in names
    assert set(excluded) == {"send_message_to_user", "future_task"}


async def _main_tools_nonempty(tmp_path):
    """全部 AstrHe 工具在各种输入下返回非空字符串。"""
    from tests.conftest import make_storage
    from astrhe.tools.day_tools import DayTools
    from astrhe.tools.reader_tools import ReaderTools
    from astrhe.tools.secrecy import PresentResolver

    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()

        class _QQ:
            async def call(self, action, **params):
                return []

        reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, 2e10), PresentResolver(s, _QQ()))
        day = DayTools(s, lambda: TZ)
        tools = reader.build() + [
            AstrHeFunctionTool(name="astrhe_todo_update", description="", fn=day.todo_update)
        ]
        event = FakeEvent()
        for tool in tools:
            for kwargs in ({}, {"umo": "x"}, {"keyword": "k"}, {"todo_id": 1, "status": "done"}):
                out = await tool.run(event, **kwargs)
                assert isinstance(out, str) and out.strip(), f"{tool.name} 返回了空"
    finally:
        await s.close()


def test_all_astrhe_tools_return_nonempty(tmp_path):
    arun(_main_tools_nonempty(tmp_path))
