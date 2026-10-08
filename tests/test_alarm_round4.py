"""闹钟材料分层、管理员依据与重复撤销的真实仓库/钩子回归。"""

from zoneinfo import ZoneInfo

import pytest

from astrhe.alarm_tracker import AlarmTracker
from astrhe.night.draft import DraftCommitter
from astrhe.night.planner import Planner
from astrhe.timeutil import utc_now
from astrhe.tools.draft_tools import DraftTools
from astrhe.tools.reader_tools import ReaderTools
from astrhe.tools.validation import validate_alarm_cancel
from tests.conftest import FakeContext, FakeLogger, arun, make_storage
from tests.test_alarm_tracker import _cron_event

TZ = ZoneInfo("Asia/Shanghai")
UMO = "default:GroupMessage:20002"


async def seed(s, ctx, creator="astrhe", repeat=False):
    aid = await s.alarms.add_alarm(
        target_umo=UMO,
        creator_id=creator,
        origin="night" if creator == "astrhe" else "day",
        run_at=None if repeat else utc_now() + 86400,
        cron_expression="0 12 * * *" if repeat else "",
        card={"background": "背景内容", "purpose": "完整目的", "how": "执行做法"},
    )
    job = await ctx.cron_manager.add_active_job(
        name="测试", cron_expression=None, payload={}
    )
    await s.alarms.bind_cron_job(aid, job.job_id)
    return aid, job.job_id


@pytest.mark.parametrize(
    "evidence", ["none", "missing", "member", "old", "recalled", "valid"]
)
def test_admin_cancel_requires_valid_admin_message(tmp_path, evidence):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            aid, _ = await seed(s, ctx, "10001")
            alarm = await s.alarms.get_alarm(aid)
            if evidence not in ("none", "missing"):
                await s.ledger.add_message(
                    umo=UMO,
                    platform_id="default",
                    message_type="GroupMessage",
                    session_id="20002",
                    sender_id="30003" if evidence == "member" else "10001",
                    platform_message_id="7001",
                    text="请取消这条闹钟",
                    ts=alarm["created_at"] + (-1 if evidence == "old" else 1),
                )
            if evidence == "recalled":
                await s.db.execute("UPDATE messages SET recalled=1")
            rid = await s.runs.start_run(plan_date="2099-01-01")
            owner = DraftTools(s, rid, None, None, admins=["10001", "astrbot"])
            tool = next(
                t for t in owner.build() if t.name == "astrhe_draft_alarm_cancel"
            )
            result = await tool.run(
                None,
                alarm_id=aid,
                reason="管理员取消",
                evidence_message_id="" if evidence == "none" else "#7001",
            )
            assert ("已保存" in result) == (evidence == "valid"), result
            if evidence == "valid":
                payload = {
                    "alarm_id": aid,
                    "reason": "取消",
                    "evidence_message_id": "7001",
                }
                await s.db.execute("UPDATE messages SET recalled=1")
                committer = DraftCommitter(
                    s, ctx, rid, "2099-01-01", TZ, admins=["10001"]
                )
                assert "已经撤回" in await committer._cancel_alarm(payload)
                assert (await s.alarms.get_alarm(aid))["status"] == "scheduled"
                assert not ctx.cron_manager.deleted
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize("creator", ["astrhe", "30003"])
def test_non_admin_alarms_do_not_need_message_evidence(tmp_path, creator):
    async def check():
        s = await make_storage(tmp_path)
        try:
            aid, _ = await seed(s, FakeContext(), creator)
            assert await validate_alarm_cancel(s, aid, admins=["10001"])
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize("state", ["done", "failed", "missing", "fired"])
def test_repeating_alarm_can_cancel_after_real_tracker_hooks(tmp_path, state):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx, logger = FakeContext(), FakeLogger()
            aid, jid = await seed(s, ctx, repeat=True)
            tracker = AlarmTracker(s, ctx, lambda: TZ, logger)
            event = _cron_event(aid)
            await tracker.on_agent_begin(event)
            await tracker.on_agent_done(event)
            assert (await s.alarms.get_alarm(aid))["finished_at"] is None
            if state == "fired":
                await tracker.on_agent_begin(event)
            else:
                await s.alarms.set_status(aid, state)
            rid = await s.runs.start_run(plan_date="2099-01-01")
            committer = DraftCommitter(s, ctx, rid, "2099-01-01", TZ)
            result = await committer._cancel_alarm(
                {"alarm_id": aid, "reason": "事情已结束"}
            )
            assert "已取消" in result and jid not in ctx.cron_manager.jobs
            await tracker.on_agent_done(event)
            alarm = await s.alarms.get_alarm(aid)
            assert alarm["status"] == "cancelled" and alarm["finished_at"] is not None
            once, _ = await seed(s, ctx)
            await tracker.on_agent_begin(_cron_event(once))
            await tracker.on_agent_done(_cron_event(once))
            with pytest.raises(ValueError, match="已执行"):
                await validate_alarm_cancel(s, once)
        finally:
            await s.close()

    arun(check())


def test_270_finished_alarms_are_compact_complete_and_paginated(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            for index in range(270):
                aid = await s.alarms.add_alarm(
                    target_umo=UMO,
                    card={
                        "purpose": f"完整目的 {index}",
                        "background": "历史背景" * 150,
                        "how": "历史做法" * 150,
                    },
                )
                await s.alarms.set_status(aid, "failed", "时间已错过")
            active, _ = await seed(s, ctx, "10001")
            repeat, _ = await seed(s, ctx, repeat=True)
            tracker = AlarmTracker(s, ctx, lambda: TZ, FakeLogger())
            await tracker.on_agent_begin(_cron_event(repeat))
            await tracker.on_agent_done(_cron_event(repeat))
            text = await Planner(s, ctx, "fake", "", ["10001"], TZ).build_materials(
                [], "", False
            )
            finished_lines = [line for line in text.splitlines() if "[failed]" in line]
            assert len(finished_lines) == 270
            assert all(f"完整目的 {i}" in text for i in range(270))
            assert "历史背景" not in text and "历史做法" not in text
            assert len(text) < 50000
            assert "背景内容" in text and "执行做法" in text and f"#{active}" in text
            assert "白天管理员 QQ 10001" in text and "重复中，最近一次执行于" in text
            assert "时间未建立" in text
            reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, 2e10))
            page = await reader._read_alarms(None, scope="finished")
            assert "总数 270" in page and "offset=50" in page
            assert len([line for line in page.splitlines() if "[failed]" in line]) == 50
            second = await reader._read_alarms(None, scope="finished", offset=50)
            assert "完整目的 269" not in second and "完整目的 219" in second
            detail = await reader._read_alarms(None, alarm_id=repeat)
            assert (
                "全部执行事件" in detail and "[fired]" in detail and "[done]" in detail
            )
            default = await reader._read_alarms(None)
            assert "完整目的 269" not in default
        finally:
            await s.close()

    arun(check())
