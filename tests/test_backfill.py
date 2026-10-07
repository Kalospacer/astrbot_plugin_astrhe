"""补拉合并测试：bot 消息匹配合并、撤回不被覆盖、分页锚点去重、空会话处理。"""

from __future__ import annotations

from astrhe.backfill import Backfiller
from astrhe.platform import PlatformHelper
from tests.conftest import FakeContext, FakeLogger, arun, make_storage

GROUP_UMO = "default:GroupMessage:20002"


def _msg(mid, ts, text, sender_id="10001", post_type="message", nickname="甲"):
    return {
        "message_id": mid,
        "time": ts,
        "post_type": post_type,
        "user_id": sender_id,
        "sender": {"user_id": sender_id, "nickname": nickname, "card": ""},
        "message": [{"type": "text", "data": {"text": text}}],
    }


async def _main(tmp_path):
    s = await make_storage(tmp_path)
    try:
        # 账本里已有一条 recalled 的实时消息 + 一条 bot 临时记录
        await s.ledger.add_message(
            umo=GROUP_UMO, platform_id="default", message_type="GroupMessage",
            session_id="20002", sender_id="10001", text="被撤回的话",
            ts=1700000100.0, platform_message_id="5001",
        )
        await s.ledger.mark_recalled(GROUP_UMO, "5001")
        await s.ledger.add_message(
            umo=GROUP_UMO, platform_id="default", message_type="GroupMessage",
            session_id="20002", sender_id="99999", text="晚上好呀",
            ts=1700000200.0, platform_message_id=None, is_bot=True,
        )

        # 补拉数据：含撤回消息的原文、bot 消息的正式版（同文本、60 秒内）、
        # 以及重复锚点（第二页第一条 = 第一页最后一条）
        page1 = {
            "messages": [
                _msg("5001", 1700000100, "被撤回的话"),
                _msg("5002", 1700000200, "晚上好呀", sender_id="99999",
                     post_type="message_sent"),
                _msg("5003", 1700000300, "明天见"),
            ]
        }
        page2 = {
            "messages": [
                _msg("5003", 1700000300, "明天见"),  # 锚点重复
                _msg("5000", 1699999000, "窗口外的旧消息"),
            ]
        }
        pages = [page1, page2]

        def fake_history(**params):
            return pages.pop(0) if pages else {"messages": []}

        ctx = FakeContext(api_actions={
            "get_group_msg_history": fake_history,
            "get_login_info": {"user_id": 99999},
        })
        backfiller = Backfiller(s, PlatformHelper(ctx, FakeLogger()), FakeLogger())
        n = await backfiller._backfill_session(
            umo=GROUP_UMO, action="get_group_msg_history", key="group_id",
            target="20002", window_start=1700000000.0, window_end=1700000400.0,
            self_id="99999",
        )
        assert n == 2  # 5003 新写入 + bot 合并各算一次实质写入

        all_msgs = await s.ledger.get_messages(GROUP_UMO, 0, 2e10, include_recalled=True)
        by_mid = {m["platform_message_id"]: m for m in all_msgs}
        # 撤回标记没被补拉覆盖
        assert by_mid["5001"]["recalled"] == 1
        # bot 临时记录合并上了平台 id，没有新增重复 bot 消息
        bots = [m for m in all_msgs if m["is_bot"]]
        assert len(bots) == 1 and bots[0]["platform_message_id"] == "5002"
        # 锚点去重：5003 只有一条
        assert sum(1 for m in all_msgs if m["platform_message_id"] == "5003") == 1
        # 窗口外消息不写入
        assert "5000" not in by_mid
    finally:
        await s.close()


def test_backfill_merge(tmp_path):
    arun(_main(tmp_path))


async def _main_empty(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext(api_actions={
            "get_group_msg_history": RuntimeError("NapCat 错误: 消息不存在"),
        })
        backfiller = Backfiller(s, PlatformHelper(ctx, FakeLogger()), FakeLogger())
        n = await backfiller._backfill_session(
            umo=GROUP_UMO, action="get_group_msg_history", key="group_id",
            target="20002", window_start=0, window_end=2e10, self_id="",
        )
        assert n == 0  # 「消息不存在」按空处理
    finally:
        await s.close()


def test_backfill_empty_session(tmp_path):
    arun(_main_empty(tmp_path))
