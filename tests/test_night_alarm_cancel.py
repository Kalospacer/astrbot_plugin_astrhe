"""夜间撤回安排：草稿、审稿、取消顺序、频率、执行失败与演练。"""

import json
from datetime import datetime

import pytest

from astrhe import constants as C
from astrhe.night.planner import Planner
from astrhe.tools.alarm_card import render_card_note
from astrhe.tools.reader_tools import ReaderTools
from tests.conftest import FakeContext, FakeLogger, arun, make_storage
from tests.test_draft_revision import TZ, UMO, draft_id, setup
from tests.test_night_pipeline import _build_pipeline

ALARM_KW = {
    "target_umo": "group:20002",
    "run_at": "2099-01-02 12:00",
    "background": "帮手已经负责蛋糕",
    "purpose": "商量新的安排",
    "how": "先问对方是否方便",
}


async def seed_alarm(s, ctx, *, run_id=None, purpose="商量蛋糕"):
    card = {
        "background": "生日惊喜的背景",
        "purpose": purpose,
        "how": "私下沟通",
        "secret_from": ["10001"],
    }
    run_at = datetime(2099, 1, 2, 12, tzinfo=TZ)
    aid = await s.alarms.add_alarm(
        target_umo=UMO,
        run_at=run_at.timestamp(),
        card=card,
        created_run_id=run_id,
    )
    job = await ctx.cron_manager.add_active_job(
        name=f"astrhe闹钟#{aid}",
        cron_expression=None,
        payload={
            "session": UMO,
            "astrhe_alarm_id": str(aid),
            "note": render_card_note(card, UMO),
        },
        description=f"AstrHe 闹钟 #{aid}",
        run_at=run_at,
        run_once=True,
    )
    await s.alarms.bind_cron_job(aid, job.job_id)
    return aid, job.job_id


@pytest.mark.parametrize("per_run", [False, True])
def test_cancellation_releases_draft_quota_and_executes_before_creation(
    tmp_path, monkeypatch, per_run
):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            rid, _, committer, call = await setup(s, ctx)
            if per_run:
                monkeypatch.setattr(C, "RATE_ALARM_NIGHT_PER_RUN", 2)
            aid, jid = await seed_alarm(s, ctx, run_id=rid if per_run else None)
            await seed_alarm(s, ctx, run_id=rid if per_run else None)
            blocked = await call("astrhe_draft_alarm", **ALARM_KW)
            assert ("本晚" if per_run else "同一目标") in blocked
            result = await call(
                "astrhe_draft_alarm_cancel", alarm_id=aid, reason="蛋糕已完成"
            )
            assert "已保存" in result
            assert jid in ctx.cron_manager.jobs
            assert (await s.alarms.get_alarm(aid))["status"] == "scheduled"
            assert "已保存" in await call("astrhe_draft_alarm", **ALARM_KW)
            await call("astrhe_draft_plan", full_text="取消过期提醒，安排下一步")
            await call("astrhe_request_review")
            await call("astrhe_commit")
            results = await committer.run_external_actions()
            assert "已取消" in results[0] and "已建" in results[1]
            assert jid not in ctx.cron_manager.jobs
            assert (await s.alarms.get_alarm(aid))["status"] == "cancelled"
            assert (await s.alarms.events(aid))[-1]["detail"] == "蛋糕已完成"
            assert len(ctx.cron_manager.jobs) == 2
            assert "已经提交" in await call(
                "astrhe_draft_alarm_cancel", alarm_id=aid, reason="重复"
            )
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize("failure", ["delete", "already_fired"])
def test_failed_cancel_keeps_old_status_and_rechecks_real_quota(tmp_path, failure):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            _, _, committer, call = await setup(s, ctx)
            aid, jid = await seed_alarm(s, ctx)
            await seed_alarm(s, ctx)
            await call("astrhe_draft_alarm_cancel", alarm_id=aid, reason="改期")
            assert "已保存" in await call("astrhe_draft_alarm", **ALARM_KW)
            await call("astrhe_draft_plan", full_text="改期")
            await call("astrhe_request_review")
            await call("astrhe_commit")
            if failure == "delete":
                async def fail_delete(job_id):
                    raise RuntimeError("定时服务暂不可用")
                ctx.cron_manager.delete_job = fail_delete
            else:
                await s.alarms.set_status(aid, "fired")
                await s.alarms.add_event(aid, "fired")
            results = await committer.run_external_actions()
            assert "取消闹钟" in results[0] and "失败" in results[0]
            assert "频率上限" in results[1]
            assert jid in ctx.cron_manager.jobs
            assert (await s.alarms.get_alarm(aid))["status"] == (
                "scheduled" if failure == "delete" else "fired"
            )
            assert len(ctx.cron_manager.added) == 2
        finally:
            await s.close()

    arun(check())


def test_cancel_draft_validation_and_discard_restore_quota(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            rid, _, _, call = await setup(s, ctx)
            aid, _ = await seed_alarm(s, ctx)
            await seed_alarm(s, ctx)
            assert "找不到" in await call(
                "astrhe_draft_alarm_cancel", alarm_id=999, reason="多余"
            )
            assert "理由" in await call(
                "astrhe_draft_alarm_cancel", alarm_id=aid, reason=" "
            )
            await s.alarms.add_event(aid, "manual_run")
            assert "已执行" in await call(
                "astrhe_draft_alarm_cancel", alarm_id=aid, reason="多余"
            )
            await s.db.execute("DELETE FROM alarm_events WHERE alarm_id=?", (aid,))
            cancelled = draft_id(await call(
                "astrhe_draft_alarm_cancel", alarm_id=aid, reason="改期"
            ))
            await call("astrhe_draft_discard", draft_id=cancelled, reason="仍然需要")
            assert "频率上限" in await call("astrhe_draft_alarm", **ALARM_KW)
            assert not await s.runs.get_drafts(rid)
        finally:
            await s.close()

    arun(check())


def test_commit_cancels_first_even_when_new_draft_was_written_first(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            _, _, committer, call = await setup(s, ctx)
            aid, jid = await seed_alarm(s, ctx)
            assert "已保存" in await call("astrhe_draft_alarm", **ALARM_KW)
            await call("astrhe_draft_alarm_cancel", alarm_id=aid, reason="换安排")
            await call("astrhe_draft_plan", full_text="新的计划")
            await call("astrhe_request_review")
            await call("astrhe_commit")
            order = []
            original_add = ctx.cron_manager.add_active_job
            original_delete = ctx.cron_manager.delete_job

            async def add(**kw):
                order.append("add")
                assert jid not in ctx.cron_manager.jobs
                return await original_add(**kw)

            async def delete(job_id):
                order.append("delete")
                await original_delete(job_id)

            ctx.cron_manager.add_active_job = add
            ctx.cron_manager.delete_job = delete
            await committer.run_external_actions()
            assert order == ["delete", "add"]
        finally:
            await s.close()

    arun(check())


def test_dryrun_lists_cancel_without_deleting_or_changing_alarm(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            aid, jid = await seed_alarm(s, ctx)

            async def planner(kw):
                tools, event = kw["tools"], kw["event"]
                await tools.get_tool("astrhe_draft_plan").run(event, full_text="计划")
                await tools.get_tool("astrhe_draft_alarm_cancel").run(
                    event, alarm_id=aid, reason="事情已完成"
                )
                await tools.get_tool("astrhe_request_review").run(event)
                return await tools.get_tool("astrhe_commit").run(event, summary="取消")

            async def review(kw):
                assert "alarm_cancel" in kw["prompt"]
                return "通过"

            ctx.tool_loop_agent.handlers = [planner, review]
            result = await _build_pipeline(s, ctx, FakeLogger()).run("dry")
            assert result["status"] == "dry_done", result
            assert "将执行" in result["final_text"]
            assert "事情已完成" in result["final_text"]
            action = json.loads(result["final_text"].split("将执行：")[1])[0]
            assert action == {
                "kind": "alarm_cancel", "alarm_id": aid, "reason": "事情已完成",
            }
            assert jid in ctx.cron_manager.jobs and not ctx.cron_manager.deleted
            assert (await s.alarms.get_alarm(aid))["status"] == "scheduled"
        finally:
            await s.close()

    arun(check())


def test_night_materials_and_reader_show_secret_alarm_cards_without_redaction(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            aid, jid = await seed_alarm(s, ctx)
            planner = Planner(s, ctx, "fake", "人格", ["10001"], TZ)
            reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, 2e10))
            for text in (
                await planner.build_materials([], "", False),
                await reader._read_alarms(None),
            ):
                assert all(value in text for value in (
                    f"#{aid}", jid, "2099-01-02 12:00", "商量蛋糕", "生日惊喜的背景",
                    "私下沟通", "10001",
                ))
        finally:
            await s.close()

    arun(check())
