"""保密过滤测试：astrhe_read_plan 与 astrhe_schedule list。"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from astrhe.qq.client import QQClient
from astrhe.qq.rate_limit import RateLimiter
from astrhe.platform import PlatformHelper
from astrhe.tools.reader_tools import ReaderTools
from astrhe.tools.schedule_tool import ScheduleToolImpl
from astrhe.tools.secrecy import PresentResolver, filter_secret_text
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")
GROUP_UMO = "default:GroupMessage:20002"


def test_filter_secret_text_unit():
    text = "明天【保密:10001】给哥哥准备惊喜【/保密】，下午去取蛋糕"
    # 保密对象本人看不到
    out = filter_secret_text(text, viewer_id="10001",
                             session_umo="default:FriendMessage:10001", present_ids=set())
    assert "惊喜" not in out and "（保密内容）" in out and "取蛋糕" in out
    # 与保密对象的私聊里看不到
    out2 = filter_secret_text(text, viewer_id="40004",
                              session_umo="default:FriendMessage:10001", present_ids=set())
    assert "惊喜" not in out2
    # 保密对象在群里在场 → 群里看不到
    out3 = filter_secret_text(text, viewer_id="40004",
                              session_umo=GROUP_UMO, present_ids={"10001"})
    assert "惊喜" not in out3
    # 保密对象不在场 → 其他人能看到
    out4 = filter_secret_text(text, viewer_id="40004",
                              session_umo=GROUP_UMO, present_ids=set())
    assert "惊喜" in out4


async def _main(tmp_path):
    s = await make_storage(tmp_path)
    try:
        run_id = await s.runs.start_run(plan_date="2099-01-01", mode="auto")
        await s.plans.save_plan(
            run_id=run_id, plan_date="2099-01-01",
            full_text="公开内容。【保密:10001】秘密计划。【/保密】结尾。",
        )
        ctx = FakeContext()

        class _QQ:
            async def call(self, action, **params):
                return []

        secrecy = PresentResolver(s, _QQ())
        reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, 2e10), secrecy)

        # 找 read_plan 工具实现
        tools = {t.name: t for t in reader.build()}
        read_plan = tools["astrhe_read_plan"]

        # 保密对象在场的群（10001 发过言）
        await s.ledger.add_message(
            umo=GROUP_UMO, platform_id="default", message_type="GroupMessage",
            session_id="20002", sender_id="10001", text="hi",
            ts=__import__("time").time(), platform_message_id="1",
        )
        event = FakeEvent(umo=GROUP_UMO, sender_id="40004")
        text = await read_plan.fn(event)
        assert "秘密计划" not in text and "公开内容" not in text
        assert "管理员私聊" in text

        # 普通人的私聊同样只给本会话段落
        member_dm = FakeEvent(umo="default:FriendMessage:40004", sender_id="40004")
        assert "公开内容" not in await read_plan.fn(member_dm)

        # 管理员私聊：全文；管理员不是保密对象，保密段照常可见
        event2 = FakeEvent(
            umo="default:FriendMessage:40004", sender_id="40004", role="admin"
        )
        text2 = await read_plan.fn(event2)
        assert "公开内容" in text2 and "秘密计划" in text2

        # 管理员本人是保密对象时，全文里的保密段照样遮挡
        target = FakeEvent(
            umo="default:FriendMessage:10001", sender_id="10001", role="admin"
        )
        text3 = await read_plan.fn(target)
        assert "公开内容" in text3 and "秘密计划" not in text3

        # schedule list 的保密过滤：对 10001 保密的闹钟，10001 在场时别人也看不到
        qq = QQClient(PlatformHelper(ctx, FakeLogger()))
        impl = ScheduleToolImpl(s, ctx, qq, RateLimiter(s, lambda: TZ),
                                lambda: TZ, secrecy, lambda: ["10001"])
        await s.alarms.add_alarm(
            target_umo=GROUP_UMO, creator_id="99999", origin="night",
            run_at=4102444800.0,
            card={"purpose": "给 10001 的惊喜", "secret_from": ["10001"]},
        )
        list_text = await impl.run(FakeEvent(umo=GROUP_UMO, sender_id="40004"), action="list")
        assert "惊喜" not in list_text
        # 10001 不在场的群能看到
        list_text2 = await impl.run(
            FakeEvent(umo="default:GroupMessage:33333", sender_id="40004", role="admin"),
            action="list",
        )
        # 管理员在别的群看 list：那条闹钟目标群是 20002 且 10001 不在场 → 可见
        assert "惊喜" in list_text2 or "外部任务" in list_text2
    finally:
        await s.close()


def test_secrecy(tmp_path):
    arun(_main(tmp_path))
