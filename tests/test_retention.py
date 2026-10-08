"""30 天过程清理：保护运行窗口、活跃任务和未删除的回忆。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from astrhe import constants as C
from astrhe.alarm_tracker import AlarmTracker
from astrhe.storage.retention import cleanup_history
from astrhe.timeutil import utc_now
from tests.conftest import FakeContext, FakeLogger, arun, make_storage
from tests.test_alarm_round4 import seed
from tests.test_alarm_tracker import _cron_event
from tests.test_night_pipeline import _build_pipeline


def test_cleanup_history_keeps_live_memory_and_window_anchor(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            cutoff = utc_now() - C.LEDGER_RETENTION_SECONDS
            old = cutoff - 100
            ids = []
            for day, status in (
                ("2026-08-01", "committed"),
                ("2026-08-02", "failed"),
                ("2026-08-03", "committed"),
                ("2026-10-08", "running"),
            ):
                rid = await s.runs.start_run(plan_date=day)
                await s.runs.add_report(
                    run_id=rid, umo="test", chunk_index=0, content={}, raw_text="汇报"
                )
                await s.runs.add_draft(run_id=rid, kind="plan", payload={}, seq=1)
                await s.runs.add_review(run_id=rid, focus="", result_text="通过")
                await s.db.execute(
                    "UPDATE runs SET ended_at=?,status=? WHERE id=?", (old, status, rid)
                )
                ids.append(rid)
            completed, jid = await seed(s, ctx)
            tracker = AlarmTracker(
                s, ctx, lambda: ZoneInfo("Asia/Shanghai"), FakeLogger()
            )
            event = _cron_event(completed, datetime.now(timezone.utc).isoformat())
            await tracker.on_agent_begin(event)
            await tracker.on_agent_done(event)
            assert not ctx.cron_manager.jobs[jid].enabled
            await s.db.execute(
                "UPDATE alarms SET finished_at=? WHERE id=?", (old, completed)
            )
            live, _ = await seed(s, ctx)
            repeat, _ = await seed(s, ctx, repeat=True)
            await s.alarms.set_status(repeat, "failed")
            for aid in (completed, live, repeat):
                # 更早一轮的触发应被清掉；最近一次触发及之后的流水保留
                await s.alarms.add_event(aid, "fired", ts=old - 50)
                await s.alarms.add_event(aid, "done", ts=old - 40)
                await s.alarms.add_event(aid, "fired", ts=old)
                await s.alarms.add_event(aid, "done", ts=utc_now())
            await s.db.execute(
                "INSERT INTO action_log(action,ts) VALUES('poke',?)", (old,)
            )
            await s.persons.upsert_person("10001", relation_text="朋友")
            pid = await s.plans.save_plan(
                run_id=ids[0], plan_date="2026-08-01", full_text="保留回忆"
            )
            await s.plans.save_sections(pid, {"test": "段落"})
            trash = await s.plans.save_plan(
                run_id=ids[0], plan_date="2026-08-02", full_text="删除回忆"
            )
            await s.plans.save_sections(trash, {"test": "旧段落"})
            await s.db.execute("UPDATE plans SET deleted_at=? WHERE id=?", (old, trash))
            todo = await s.plans.add_todo(content="已完成回忆", visible_umos=[])
            await s.plans.update_todo_status(todo, "done")
            promise = await s.plans.add_promise(
                from_id="99999", to_id="10001", content="已兑现"
            )
            await s.plans.update_promise_status(promise, "done")
            deleted_todo = await s.plans.add_todo(content="回收站待办", visible_umos=[])
            deleted_promise = await s.plans.add_promise(
                from_id="99999", to_id="10001", content="回收站承诺"
            )
            await s.db.execute(
                "UPDATE todos SET deleted_at=? WHERE id=?", (old, deleted_todo)
            )
            await s.db.execute(
                "UPDATE promises SET deleted_at=? WHERE id=?", (old, deleted_promise)
            )
            await s.db.execute(
                "INSERT INTO memory_revisions(kind,target_id,action,before_json,after_json,reason,ts)"
                " VALUES('plan',?,'delete','{}','{}','旧记录',?)",
                (trash, old),
            )
            counts = await cleanup_history(
                s, cutoff, ids[-1], cron_manager=ctx.cron_manager, logger=FakeLogger()
            )
            assert counts["runs"] == 2 and counts["alarms"] == 1
            assert (await s.runs.latest_committed_run())["id"] == ids[2]
            assert await s.runs.get_run(ids[3])
            for rid in ids[:2]:
                assert await s.runs.get_run(rid) is None
                assert not await s.runs.get_reports(rid)
                assert not await s.runs.get_drafts(rid, None)
                assert not await s.runs.get_reviews(rid)
            assert jid in ctx.cron_manager.deleted
            assert await s.alarms.get_alarm(completed) is None
            assert not await s.alarms.events(completed)
            for aid in (live, repeat):
                assert await s.alarms.get_alarm(aid)
                kept = await s.alarms.events(aid)
                assert [(e["kind"], e["ts"] >= old) for e in kept] == [
                    ("fired", True),
                    ("done", True),
                ]
            assert await s.plans.get_plan_by_date("2026-08-01")
            assert await s.plans.get_todo(todo)
            assert await s.plans.list_promises()
            assert await s.persons.get_person("10001")
            assert not await s.db.fetchall("SELECT * FROM plans WHERE id=?", (trash,))
            assert not await s.db.fetchall(
                "SELECT * FROM plan_sections WHERE plan_id=?", (trash,)
            )
            assert not await s.db.fetchall(
                "SELECT * FROM todos WHERE id=?", (deleted_todo,)
            )
            assert not await s.db.fetchall(
                "SELECT * FROM promises WHERE id=?", (deleted_promise,)
            )
            assert not await s.db.fetchall("SELECT * FROM memory_revisions")
            assert not await s.db.fetchall("SELECT * FROM action_log")
        finally:
            await s.close()

    arun(check())


def test_pipeline_dry_does_not_cleanup_and_cleanup_error_preserves_commit(
    tmp_path, monkeypatch
):
    async def check():
        import astrhe.storage.retention as retention

        s = await make_storage(tmp_path)
        calls = []

        async def cleanup(*args, **kw):
            calls.append(kw)
            raise RuntimeError("模拟清理失败")

        monkeypatch.setattr(retention, "cleanup_history", cleanup)
        try:
            for mode in ("dry", "manual"):

                async def planner(kw):
                    tools, event = kw["tools"], kw["event"]
                    await tools.get_tool("astrhe_draft_plan").run(
                        event, full_text="计划"
                    )
                    await tools.get_tool("astrhe_request_review").run(event)
                    return await tools.get_tool("astrhe_commit").run(event)

                async def reviewer(kw):
                    return "通过"

                ctx, logger = FakeContext(), FakeLogger()
                ctx.tool_loop_agent.handlers = [planner, reviewer]
                result = await _build_pipeline(s, ctx, logger).run(mode)
                assert result["status"] == (
                    "dry_done" if mode == "dry" else "committed"
                ), result
                if mode == "dry":
                    assert not calls
                else:
                    assert len(calls) == 1 and logger.warnings
                    assert (await s.runs.latest_run())["status"] == "committed"
        finally:
            await s.close()

    arun(check())
