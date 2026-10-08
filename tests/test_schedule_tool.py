"""astrhe_schedule 测试：目标转 UMO、校验、run_at 下限、权限、卡片渲染、
add_active_job 参数（sender_id / origin / astrhe_alarm_id）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from astrhe.qq.client import QQClient
from astrhe.qq.rate_limit import RateLimiter
from astrhe.platform import PlatformHelper
from astrhe.tools.schedule_tool import ScheduleToolImpl
from astrhe.tools.secrecy import PresentResolver
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")


def _impl(s, ctx):
    qq = QQClient(PlatformHelper(ctx, FakeLogger()))
    return ScheduleToolImpl(
        s, ctx, qq, RateLimiter(s, lambda: TZ),
        lambda: TZ, PresentResolver(s, qq),
        lambda: ["10001"],
    )


def _future(hours=3):
    # 固定在明天中午，避开深夜免打扰时段
    dt = (datetime.now(TZ) + timedelta(days=1)).replace(hour=12, minute=0)
    return dt.strftime("%Y-%m-%d %H:%M")


async def _main(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext(api_actions={
            "get_group_list": [{"group_id": 20002}, {"group_id": 33333}],
            "get_friend_list": [{"user_id": 40004}],
            "get_login_info": {"user_id": 99999},
        })
        impl = _impl(s, ctx)

        # 管理员跨会话建群闹钟
        admin_event = FakeEvent(umo="default:FriendMessage:10001",
                                sender_id="10001", role="admin")
        result = await impl.run(
            admin_event, action="create", target_type="group", target_id="20002",
            run_at=_future(), background="哥哥生日", purpose="零点送祝福",
            how="用 send_message_to_user 发生日快乐", mentions=["10001"],
            secret_from=["10001"],
        )
        assert "定好了" in result
        job_kwargs = ctx.cron_manager.added[0]
        payload = job_kwargs["payload"]
        assert payload["session"] == "default:GroupMessage:20002"  # 目标转 UMO
        assert payload["sender_id"] == "10001"  # 白天由人发起：真实发起人
        assert payload["origin"] == "tool"
        assert payload["astrhe_alarm_id"]
        assert job_kwargs["run_once"] is True
        assert job_kwargs["run_at"] is not None and job_kwargs["run_at"].tzinfo
        # 卡片渲染进 note
        note = payload["note"]
        assert "背景：哥哥生日" in note and "怎么做" in note
        assert "send_message_to_user" in note and "astrhe_schedule" in note
        assert "mention_user" in note

        # 非好友私聊：照样创建但提醒
        result2 = await impl.run(
            admin_event, action="create", target_type="private", target_id="50005",
            run_at=_future(), background="b", purpose="p", how="h",
        )
        assert "不是好友" in result2

        # 群校验：不在群里拒绝
        result3 = await impl.run(
            admin_event, action="create", target_type="group", target_id="88888",
            run_at=_future(), background="b", purpose="p", how="h",
        )
        assert "不在群" in result3

        # run_at 下限：5 分钟内拒绝
        soon = (datetime.now(TZ) + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M")
        result4 = await impl.run(
            admin_event, action="create", target_type="group", target_id="20002",
            run_at=soon, background="b", purpose="p", how="h",
        )
        assert "5 分钟" in result4

        # 非管理员只能为当前会话创建
        member_event = FakeEvent(umo="default:GroupMessage:20002",
                                 sender_id="40004", role="member")
        result5 = await impl.run(
            member_event, action="create", target_type="group", target_id="33333",
            run_at=_future(), background="b", purpose="p", how="h",
        )
        assert "管理员" in result5
        result6 = await impl.run(
            member_event, action="create", target_type="current",
            run_at=_future(), background="b", purpose="p", how="h",
        )
        assert "定好了" in result6

        # 深夜免打扰：无约定理由拒绝
        night = datetime.now(TZ).replace(hour=1, minute=0) + timedelta(days=1)
        result7 = await impl.run(
            admin_event, action="create", target_type="group", target_id="20002",
            run_at=night.strftime("%Y-%m-%d %H:%M"), background="b", purpose="p", how="h",
        )
        assert "深夜" in result7
        result8 = await impl.run(
            admin_event, action="create", target_type="group", target_id="20002",
            run_at=night.strftime("%Y-%m-%d %H:%M"), background="b", purpose="p",
            how="h", agreed=True, agreed_reason="约好的生日零点",
        )
        assert "定好了" in result8

        # 权限：非管理员只能看到/操作当前会话的 AstrHe 闹钟
        list_text = await impl.run(member_event, action="list")
        assert "外部任务" not in list_text  # 非管理员看不到外部任务清单
        # 管理员 list 含外部任务
        ctx.cron_manager.jobs["ext-1"] = type(
            "J", (), {"job_id": "ext-1", "name": "外部任务", "payload": {"session": "x"},
                      "enabled": True, "run_once": False}
        )()
        list_admin = await impl.run(admin_event, action="list")
        assert "外部任务" in list_admin

        # 取消：非管理员不能取消别的会话的闹钟
        cancel_deny = await impl.run(member_event, action="cancel", alarm_id=2)
        assert "当前会话" in cancel_deny
        # 对管理员本人保密的 #1（生日惊喜）在聊天里同样查不到，需要时走面板
        assert await impl.run(admin_event, action="cancel", alarm_id=1) == "找不到闹钟 #1"
        open_alarm = next(
            a["id"]
            for a in await s.alarms.list_alarms(-1)
            if not json.loads(a["card_json"]).get("secret_from")
        )
        cancel_ok = await impl.run(admin_event, action="cancel", alarm_id=open_alarm)
        assert "已取消" in cancel_ok
        assert ctx.cron_manager.deleted  # 对应 cron 任务被删除

        # 外部任务只能管理员取消
        deny_ext = await impl.run(member_event, action="cancel", job_id="ext-1")
        assert "管理员" in deny_ext
        ok_ext = await impl.run(admin_event, action="cancel", job_id="ext-1")
        assert "已取消" in ok_ext
    finally:
        await s.close()


def test_schedule_tool(tmp_path):
    arun(_main(tmp_path))
