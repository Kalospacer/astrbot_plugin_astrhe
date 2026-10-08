"""QQ 默认目标、好友申请、权限包装与材料翻页回归。"""

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astrbot.core.agent.tool import FunctionTool
from astrbot.core.provider.func_tool_manager import FunctionToolManager

from astrhe.night.silent_event import make_silent_event
from astrhe.platform import PlatformHelper
from astrhe.qq.action_tool import QQActionTool
from astrhe.qq.client import QQClient
from astrhe.qq.friend_requests import FriendRequestManager
from astrhe.qq.rate_limit import RateLimiter
from astrhe.tools.reader_tools import ReaderTools
from astrhe.timeutil import utc_now
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage
from tests.test_night_pipeline import _build_pipeline
from tests.test_schedule_tool import _impl, _future

TZ = ZoneInfo("Asia/Shanghai")
UMO = "default:GroupMessage:20002"


def test_external_tools_use_real_permission_guard(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            mgr = FunctionToolManager()
            invoked = []

            async def handler(event):
                invoked.append(True)
                return "已调用"

            active = FunctionTool(
                name="read_external",
                description="读",
                parameters={"type": "object", "properties": {}},
                handler=handler,
            )
            inactive = FunctionTool(
                name="disabled_external",
                description="停用",
                parameters={},
                handler=handler,
            )
            inactive.active = False
            mgr.func_list = [active, inactive]

            async def permission(name, context):
                return (
                    "error: Permission denied"
                    if not context.context.event.is_admin()
                    else None
                )

            mgr._check_tool_permission = permission
            ctx.get_llm_tool_manager = lambda: mgr
            tools = _build_pipeline(s, ctx, FakeLogger())._external_proxied_tools(set())
            assert [t.name for t in tools] == ["read_external"]
            event = make_silent_event(ctx, "")
            result = await tools[0].call(
                SimpleNamespace(context=SimpleNamespace(event=event))
            )
            assert "Permission denied" in result and not invoked
        finally:
            await s.close()

    arun(check())


def test_react_and_poke_default_to_current_isolated_session(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            tool = QQActionTool(
                qq_client=QQClient(PlatformHelper(ctx, FakeLogger())),
                rate_limiter=RateLimiter(s, lambda: TZ),
            )
            event = FakeEvent(umo="default:GroupMessage:10001_20002")
            assert "已贴" in await tool.run(event, action="react", emoji="赞")
            call = next(c for c in ctx.api.calls if c[0] == "set_msg_emoji_like")
            assert call[1]["message_id"] == 1001
            assert "戳了" in await tool.run(event, action="poke", user_id="40004")
            assert (
                next(c for c in ctx.api.calls if c[0] == "send_poke")[1]["group_id"]
                == 20002
            )
            assert await s.ledger.count_actions("react", 0, umo=UMO) == 1
            cron = FakeEvent(extras={"cron_payload": {}})
            assert "message_id" in await tool.run(cron, action="react", emoji="赞")
        finally:
            await s.close()

    arun(check())


def test_doubt_and_day_expected_friend_pending_approval(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext(
                api_actions={
                    "get_doubt_friends_add_request": [
                        {"uin": 50005, "flag": "doubt-flag"}
                    ]
                }
            )
            qq = QQClient(PlatformHelper(ctx, FakeLogger()))
            friends = FriendRequestManager(s, qq, FakeLogger())
            await s.persons.set_expected_friend("50005", utc_now() + 3600, "预期")
            results = await friends.nightly_followup()
            assert any("处理可疑好友申请" in r for r in results)
            assert (
                "set_doubt_friends_add_request",
                {"flag": "doubt-flag", "approve": True},
            ) in ctx.api.calls
            await s.ledger.add_friend_request(
                user_id="60006", flag="pending-flag", comment="我是帮手", ts=utc_now()
            )
            impl = _impl(s, ctx)
            impl.friend_requests = friends
            kw = dict(
                action="create",
                run_at=_future(),
                background="背景",
                purpose="目的",
                how="做法",
                expect_friend_ids=["60006"],
            )
            assert "只有管理员" in await impl.run(FakeEvent(), **kw)
            result = await impl.run(FakeEvent(role="admin"), **kw)
            assert "定好了" in result and "补同意" in result
            assert not await s.ledger.pending_friend_requests()
            assert (
                "set_friend_add_request",
                {"flag": "pending-flag", "approve": True},
            ) in ctx.api.calls
        finally:
            await s.close()

    arun(check())


def test_search_pages_and_todo_notes(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            for i in range(65):
                await s.ledger.add_message(
                    umo=UMO,
                    platform_id="default",
                    message_type="GroupMessage",
                    session_id="20002",
                    sender_id="10001",
                    text=f"关键词-{i}",
                    ts=i + 1,
                    platform_message_id=str(1000 + i),
                )
            reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, 100))
            text = await reader._search_messages(None, keyword="关键词")
            assert "offset=50" in text
            text2 = await reader._search_messages(None, keyword="关键词", offset=50)
            assert "找到 15 条" in text2 and "关键词-0" in text2
            tid = await s.plans.add_todo(
                content="协作", visible_umos=[UMO], note="她负责蛋糕"
            )
            assert "她负责蛋糕" in await reader._read_todos(None)
            assert tid
        finally:
            await s.close()

    arun(check())
