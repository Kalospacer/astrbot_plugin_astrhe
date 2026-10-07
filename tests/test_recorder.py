"""记录器测试：普通消息、bot 回复临时记录、撤回标记、notice / request 分类。"""

from __future__ import annotations

from astrhe.recorder import Recorder
from tests.conftest import FakeEvent, FakeLogger, FakeMessageObj, arun, make_storage


def _recorder(storage, enabled=True):
    return Recorder(storage, FakeLogger(), lambda: enabled)


async def _main(tmp_path):
    s = await make_storage(tmp_path)
    try:
        rec = _recorder(s)

        # 普通群消息
        event = FakeEvent(message_obj=FakeMessageObj(text="今天天气不错"))
        await rec.record_event(event)
        msgs = await s.ledger.get_messages("default:GroupMessage:20002", 0, 2e10)
        assert len(msgs) == 1 and msgs[0]["text"] == "今天天气不错"
        assert msgs[0]["is_bot"] == 0

        # 停用时不记录
        rec_off = _recorder(s, enabled=False)
        await rec_off.record_event(FakeEvent(message_obj=FakeMessageObj(text="不该记", message_id="1002")))
        msgs = await s.ledger.get_messages("default:GroupMessage:20002", 0, 2e10)
        assert len(msgs) == 1

        # notice：戳一戳
        poke_event = FakeEvent(
            message_obj=FakeMessageObj(
                raw_message={
                    "post_type": "notice", "notice_type": "notify",
                    "sub_type": "poke", "group_id": 20002, "user_id": 10001,
                    "target_id": 99999,
                }
            )
        )
        await rec.record_event(poke_event)
        notices = await s.ledger.get_notices("default:GroupMessage:20002", 0, 2e10)
        assert notices and notices[0]["kind"] == "poke"

        # notice：撤回 → 标记消息 recalled
        recall_event = FakeEvent(
            message_obj=FakeMessageObj(
                raw_message={
                    "post_type": "notice", "notice_type": "group_recall",
                    "group_id": 20002, "user_id": 10001, "message_id": 1001,
                }
            )
        )
        await rec.record_event(recall_event)
        msgs = await s.ledger.get_messages("default:GroupMessage:20002", 0, 2e10)
        assert msgs == []  # 唯一的用户消息被标记撤回后不再出现

        # request：好友申请 → friend_requests
        req_event = FakeEvent(
            umo="default:FriendMessage:30003",
            message_obj=FakeMessageObj(
                message_type="FriendMessage", session_id="30003",
                raw_message={
                    "post_type": "request", "request_type": "friend",
                    "user_id": 30003, "flag": "flag-abc", "comment": "我是新人",
                },
            ),
        )
        await rec.record_event(req_event)
        pending = await s.ledger.pending_friend_requests()
        assert len(pending) == 1 and pending[0]["flag"] == "flag-abc"

        # after_message_sent：bot 回复临时记录（无平台 id）
        sent_event = FakeEvent()
        sent_event._result = type(
            "R", (), {"chain": [type("Plain", (), {"text": "收到啦"})()]}
        )()
        await rec.record_sent(sent_event)
        temps = await s.ledger.find_bot_temp_messages("default:GroupMessage:20002", 0)
        assert len(temps) == 1 and temps[0]["text"] == "收到啦"
        assert temps[0]["platform_message_id"] is None
    finally:
        await s.close()


def test_recorder(tmp_path):
    arun(_main(tmp_path))
