"""绑定真实 AstrBot 源码的冒烟测试。

- 能导入插件 main.py 并完成注册（用假 Context）；
- 工具是插件模块路径下的 FunctionTool 子类；
- 真实 ToolSet 移除 future_task 后查不到；
- 所有夜间 tool_loop_agent 调用约定（stream=True / 极大 max_steps）见
  test_night_pipeline.py。
"""
# ruff: noqa: E402  # 需先把 ASTRBOT_SOURCE_PATH 插入 sys.path 才能导入真实源码

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ASTRBOT_SOURCE = os.environ.get("ASTRBOT_SOURCE_PATH")
if not ASTRBOT_SOURCE or not Path(ASTRBOT_SOURCE).is_dir():
    pytest.skip("需要 ASTRBOT_SOURCE_PATH 指向 AstrBot 源码", allow_module_level=True)
if str(ASTRBOT_SOURCE) not in sys.path:
    sys.path.insert(0, str(ASTRBOT_SOURCE))

from astrbot.core.agent.tool import FunctionTool, ToolSet

from tests.conftest import FakeContext, arun


def test_plugin_import_and_register(tmp_path, monkeypatch):
    """导入 main.py，用假 context 实例化并初始化，工具完成注册。"""
    monkeypatch.setenv("ASTRBOT_ROOT", str(tmp_path / "astrbot-root"))
    from astrbot.core.star.star_tools import StarTools

    # 数据目录指到临时目录，避免碰真实数据
    monkeypatch.setattr(
        StarTools, "get_data_dir", classmethod(lambda cls, name=None: tmp_path / "data")
    )

    import main as plugin_main

    ctx = FakeContext(config={"timezone": "Asia/Shanghai", "admins_id": ["10001"]})
    plugin = plugin_main.AstrHe(context=ctx, config={"enabled": True, "provider_id": ""})
    arun(plugin.initialize())
    arun(plugin.terminate())

    registered = {t.name: t for t in ctx.registered_tools}
    for name in (
        "astrhe_todo_update", "astrhe_read_plan", "astrhe_schedule",
        "astrhe_qq_lookup", "astrhe_qq_act",
    ):
        assert name in registered, f"缺少工具 {name}"
        tool = registered[name]
        # 是插件模块路径下的 FunctionTool 子类
        assert isinstance(tool, FunctionTool)
        assert type(tool).__module__.startswith(("astrhe", "main")) or "astrhe" in str(
            type(tool).__module__
        )


def test_toolset_remove_future_task():
    """真实 ToolSet 移除 future_task 后查不到。"""
    ts = ToolSet()
    ts.add_tool(FunctionTool(name="future_task", description="d", parameters={"type": "object", "properties": {}}))
    ts.add_tool(FunctionTool(name="web_search", description="d", parameters={"type": "object", "properties": {}}))
    assert ts.get_tool("future_task") is not None
    ts.tools = [t for t in ts.tools if t.name != "future_task"]
    assert ts.get_tool("future_task") is None
    assert ts.get_tool("web_search") is not None


def test_silent_event_streaming_with_fake_provider():
    """流式路径冒烟：SilentNightEvent 的 send_streaming 不发送任何内容。"""
    from astrhe.night.silent_event import make_silent_event

    ctx = FakeContext()

    async def run():
        event = make_silent_event(ctx, "default:GroupMessage:20002")

        async def stream():
            from astrbot.core.message.message_event_result import MessageChain

            yield MessageChain().message("第一段")
            yield MessageChain().message("第二段")

        await event.send_streaming(stream())

    arun(run())
    assert ctx.sent_messages == []
