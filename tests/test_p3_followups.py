"""终审 P3 跟进：全角数字、白天改撤保密闹钟、执行中断的重复闹钟计频。"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from astrhe.platform import is_valid_qq, resolve_session_ref
from astrhe.tools.secrecy import normalize_qq_ids, normalize_secret_text
from astrhe.tools.validation import validate_night_alarm_frequency
from tests.conftest import FakeContext, FakeEvent, arun, make_storage
from tests.test_alarm_round4 import UMO, seed
from tests.test_schedule_tool import _impl

TZ = ZoneInfo("Asia/Shanghai")


def test_fullwidth_digits_are_not_accepted_as_qq_numbers():
    assert is_valid_qq("10001") and not is_valid_qq("１０００１")
    with pytest.raises(ValueError):
        normalize_qq_ids(["１０００１"])
    with pytest.raises(ValueError):
        normalize_secret_text("【保密:１０００１】惊喜【/保密】")
    with pytest.raises(ValueError):
        resolve_session_ref("group:２０００２", "default")


def test_member_cannot_edit_or_cancel_alarm_secret_from_present_person(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext(
                {"get_group_member_list": [{"user_id": 10001}, {"user_id": 40004}]}
            )
            impl = _impl(s, ctx)
            secret, secret_job = await seed(s, ctx)
            await s.db.execute(
                "UPDATE alarms SET card_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "background": "b",
                            "purpose": "惊喜",
                            "how": "h",
                            "secret_from": ["10001"],
                        },
                        ensure_ascii=False,
                    ),
                    secret,
                ),
            )
            normal, normal_job = await seed(s, ctx)
            member = FakeEvent(umo=UMO, sender_id="40004", role="member")
            cancel = await impl.run(member, action="cancel", alarm_id=secret)
            edit = await impl.run(member, action="edit", alarm_id=secret, purpose="改")
            missing = await impl.run(member, action="cancel", alarm_id=999)
            # 与不存在的编号同样回复，任务和卡片都没被动过
            assert cancel == f"找不到闹钟 #{secret}" and edit == cancel
            assert missing == "找不到闹钟 #999"
            assert secret_job in ctx.cron_manager.jobs
            card = json.loads((await s.alarms.get_alarm(secret))["card_json"])
            assert card["purpose"] == "惊喜"
            # 普通闹钟照常可以取消
            assert "已取消" in await impl.run(member, action="cancel", alarm_id=normal)
            assert normal_job not in ctx.cron_manager.jobs
        finally:
            await s.close()

    arun(check())


def test_interrupted_repeating_alarm_still_counts_toward_daily_limit(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            await seed(s, ctx, repeat=True)
            interrupted, _ = await seed(s, ctx, repeat=True)
            await s.db.execute(
                "UPDATE alarms SET cron_expression='0 13 * * *' WHERE id=?",
                (interrupted,),
            )
            # 某次执行中断被标为 failed，但平台任务还在，之后照常会响
            await s.alarms.set_status(interrupted, "failed", "执行被中断")
            target = (datetime.now(TZ) + timedelta(days=7)).replace(hour=18, minute=0)
            payload = {"target_umo": UMO, "next_run_at": target.timestamp()}
            with pytest.raises(ValueError, match="同一目标每天"):
                await validate_night_alarm_frequency(s, payload, TZ, run_id=99)
            # 平台任务根本没建成的重复闹钟不会响，不计数
            await s.db.execute(
                "UPDATE alarms SET cron_job_id='' WHERE id=?", (interrupted,)
            )
            await validate_night_alarm_frequency(s, payload, TZ, run_id=99)
        finally:
            await s.close()

    arun(check())
