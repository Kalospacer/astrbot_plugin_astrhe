"""长期存储：失败夜照常清理、停机错过的闹钟结清、白天保护管理员闹钟、面板删除进回收站。"""

from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astrhe import constants as C
from astrhe.alarm_tracker import AlarmTracker
from astrhe.night.planner import overdue_mark
from astrhe.storage.retention import cleanup_history
from astrhe.timeutil import utc_now
from astrhe.tools.alarm_view import night_alarm_materials
from astrhe.tools.memory_readers import format_entry
from astrhe.webapi import WebApi
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage
from tests.test_alarm_round4 import UMO, seed
from tests.test_night_pipeline import _build_pipeline
from tests.test_schedule_tool import _impl

TZ = ZoneInfo("Asia/Shanghai")
DAY = 86400


def test_failed_night_still_cleans_but_keeps_unreviewed_messages(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            now = utc_now()
            anchor = await s.runs.start_run(
                plan_date="2026-08-01",
                window_start=now - 36 * DAY,
                window_end=now - 35 * DAY,
            )
            await s.runs.finish_run(anchor, "committed")
            old_fail = await s.runs.start_run(plan_date="2026-08-02")
            await s.runs.add_report(
                run_id=old_fail, umo=UMO, chunk_index=0, content={}, raw_text="旧汇报"
            )
            await s.runs.finish_run(old_fail, "failed")
            await s.db.execute(
                "UPDATE runs SET ended_at=? WHERE id IN (?,?)",
                (now - 40 * DAY, anchor, old_fail),
            )
            for text, ts in (
                ("已复盘的旧消息", now - 40 * DAY),
                ("还没复盘的消息", now - 33 * DAY),
            ):
                await s.ledger.add_message(
                    umo=UMO,
                    platform_id="default",
                    message_type="GroupMessage",
                    session_id="20002",
                    sender_id="40004",
                    text=text,
                    ts=ts,
                )
            await s.db.execute(
                "INSERT INTO action_log(action,ts) VALUES('poke',?)", (now - 40 * DAY,)
            )
            # 脚本里没有模型回复：主 agent 不提交，当晚判失败
            result = await _build_pipeline(s, FakeContext(), FakeLogger()).run("auto")
            assert result["status"] == "failed", result
            texts = {
                r["text"] for r in await s.db.fetchall("SELECT text FROM messages")
            }
            assert texts == {"还没复盘的消息"}
            assert await s.runs.get_run(old_fail) is None
            assert not await s.runs.get_reports(old_fail)
            assert await s.runs.get_run(anchor)
            assert not await s.db.fetchall("SELECT * FROM action_log")
        finally:
            await s.close()

    arun(check())


def test_missed_one_shot_alarm_is_finished_and_platform_job_removed(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            now = utc_now()
            zombie, zjid = await seed(s, ctx)
            recent, rjid = await seed(s, ctx)
            await s.db.execute(
                "UPDATE alarms SET run_at=? WHERE id=?", (now - 2 * DAY, zombie)
            )
            await s.db.execute(
                "UPDATE alarms SET run_at=? WHERE id=?", (now - 1800, recent)
            )
            tracker = AlarmTracker(s, ctx, lambda: TZ, FakeLogger())
            # 窗口不含错过的时间点，也要一次结清
            text = await tracker.nightly_reconcile(now - DAY, now)
            alarm = await s.alarms.get_alarm(zombie)
            assert alarm["status"] == "missing" and alarm["finished_at"]
            assert f"#{zombie}" in text and "错过" in text
            assert zjid in ctx.cron_manager.deleted
            # 次晚不再重复报告同一次错过
            again = await tracker.nightly_reconcile(now, utc_now() + 60)
            assert f"#{zombie}" not in again
            live = {a["id"] for a in await s.alarms.live_alarms()}
            assert zombie not in live
            # 宽限内的仍在等待，任务保留
            assert (await s.alarms.get_alarm(recent))["status"] == "scheduled"
            assert recent in live and rjid in ctx.cron_manager.jobs
            await cleanup_history(
                s, utc_now() + 31 * DAY, -1, cron_manager=ctx.cron_manager
            )
            assert await s.alarms.get_alarm(zombie) is None
            assert await s.alarms.get_alarm(recent)
        finally:
            await s.close()

    arun(check())


def test_reconcile_does_not_guess_missing_when_task_list_unavailable(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            now = utc_now()
            due, _ = await seed(s, ctx)
            repeat, _ = await seed(s, ctx, repeat=True)
            await s.db.execute(
                "UPDATE alarms SET run_at=? WHERE id=?", (now - 1800, due)
            )

            async def broken(*args, **kwargs):
                raise RuntimeError("平台未就绪")

            ctx.cron_manager.list_jobs = broken
            tracker = AlarmTracker(s, ctx, lambda: TZ, FakeLogger())
            await tracker.nightly_reconcile(now - DAY, now)
            assert (await s.alarms.get_alarm(due))["status"] == "scheduled"
            assert (await s.alarms.get_alarm(repeat))["status"] == "scheduled"
        finally:
            await s.close()

    arun(check())


def test_repeating_alarm_without_platform_task_stops_being_live(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            vanished, vjid = await seed(s, ctx, repeat=True)
            interrupted, _ = await seed(s, ctx, repeat=True)
            ctx.cron_manager.jobs.pop(vjid)
            await s.alarms.set_status(interrupted, "failed", "执行被中断")
            never_built = await s.alarms.add_alarm(
                target_umo=UMO, cron_expression="0 12 * * *", card={"purpose": "p"}
            )
            await s.alarms.set_status(never_built, "failed", "创建定时任务失败")
            tracker = AlarmTracker(s, ctx, lambda: TZ, FakeLogger())
            text = await tracker.nightly_reconcile(utc_now() - DAY, utc_now())
            live = {a["id"] for a in await s.alarms.live_alarms()}
            gone = await s.alarms.get_alarm(vanished)
            assert gone["status"] == "missing" and gone["finished_at"]
            assert f"#{vanished}" in text and "不会再触发" in text
            assert vanished not in live and never_built not in live
            assert (await s.alarms.get_alarm(never_built))["finished_at"]
            # 上一次执行中断但任务还在：仍会按规则触发，保持生效
            assert interrupted in live
            assert (await s.alarms.get_alarm(interrupted))["finished_at"] is None
        finally:
            await s.close()

    arun(check())


def test_day_tool_cannot_change_admin_alarm_for_non_admin(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            impl = _impl(s, ctx)
            admin_alarm, ajid = await seed(s, ctx, creator="10001")
            member_alarm, mjid = await seed(s, ctx, creator="40004")
            member = FakeEvent(umo=UMO, sender_id="40004", role="member")
            woken = FakeEvent(
                umo=UMO,
                sender_id="40004",
                role="member",
                extras={"cron_payload": {"sender_id": C.NIGHT_ALARM_SENDER_ID}},
            )
            for event in (member, woken):
                result = await impl.run(event, action="cancel", alarm_id=admin_alarm)
                assert "管理员" in result and ajid in ctx.cron_manager.jobs
                result = await impl.run(
                    event, action="edit", alarm_id=admin_alarm, purpose="改掉"
                )
                assert "管理员" in result
            assert (await s.alarms.get_alarm(admin_alarm))["status"] == "scheduled"
            await impl.run(member, action="cancel", alarm_id=member_alarm)
            assert mjid not in ctx.cron_manager.jobs
            admin = FakeEvent(umo=UMO, sender_id="10001", role="admin")
            await impl.run(admin, action="cancel", alarm_id=admin_alarm)
            assert ajid not in ctx.cron_manager.jobs
        finally:
            await s.close()

    arun(check())


def test_panel_delete_moves_todo_and_promise_into_trash(tmp_path, monkeypatch):
    async def check():
        import astrhe.webapi as module

        monkeypatch.setattr(
            module,
            "astrbot_web",
            SimpleNamespace(
                json_response=lambda value: value,
                error_response=lambda text, status_code=400: {
                    "error": text,
                    "status": status_code,
                },
            ),
        )
        s = await make_storage(tmp_path)
        try:
            todo = await s.plans.add_todo(content="写错的待办", visible_umos=[UMO])
            promise = await s.plans.add_promise(
                from_id="99999", to_id="10001", content="写错的承诺"
            )
            api = WebApi(s, FakeContext(), lambda: TZ, lambda: {})
            body = {}

            async def json_body():
                return body

            api._json_body = json_body
            body.update(todo_id=todo)
            assert (await api._todo_delete())["ok"]
            assert (await api._todo_delete())["status"] == 400
            body.clear()
            body.update(promise_id=promise)
            assert (await api._promise_delete())["ok"]
            assert not await s.plans.open_todos()
            assert promise not in {p["id"] for p in await s.plans.list_promises()}
            _, total = await s.memory.trash()
            assert total == 2
            await s.memory.restore("todo", todo)
            assert [t["id"] for t in await s.plans.open_todos()] == [todo]
            # 回收站满期后随清理硬删除
            await cleanup_history(s, utc_now() + 31 * DAY, -1)
            assert await s.memory.get_entry("promise", promise) is None
            assert await s.memory.get_entry("todo", todo)
        finally:
            await s.close()

    arun(check())


def test_night_materials_list_recent_finished_alarms_and_overdue_todos(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            now = utc_now()
            ids = {}
            for name, age in (("recent", 1), ("old", C.NIGHT_FINISHED_ALARM_DAYS + 3)):
                aid = await s.alarms.add_alarm(
                    target_umo=UMO, run_at=now - age * DAY, card={"purpose": name}
                )
                await s.alarms.set_status(aid, "done")
                await s.db.execute(
                    "UPDATE alarms SET finished_at=? WHERE id=?", (now - age * DAY, aid)
                )
                ids[name] = aid
            text = await night_alarm_materials(s, TZ)
            assert f"#{ids['recent']} [done]" in text
            assert f"#{ids['old']} [done]" not in text
            assert "更早结束的还有 1 条" in text
        finally:
            await s.close()

        today = date(2026, 10, 11)
        assert overdue_mark({"due_kind": "today", "due_date": "2026-10-09"}, today) == (
            "（已逾期 2 天）"
        )
        assert (
            overdue_mark({"due_kind": "deadline", "due_date": "2026-10-11"}, today)
            == ""
        )
        assert (
            overdue_mark({"due_kind": "future", "due_date": "2026-10-01"}, today) == ""
        )

    arun(check())


def test_migrated_promise_time_and_wal_size_limit(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            promise = await s.plans.add_promise(
                from_id="99999", to_id="10001", content="旧版本的承诺"
            )
            await s.db.execute(
                "UPDATE promises SET created_at=0, updated_at=0 WHERE id=?", (promise,)
            )
            row = await s.memory.get_entry("promise", promise)
            text = format_entry("promise", row, TZ)
            assert "时间未知" in text and "1970" not in text
            limit = await s.db.fetchone("PRAGMA journal_size_limit")
            assert list(limit.values())[0] == C.SQLITE_JOURNAL_SIZE_LIMIT
        finally:
            await s.close()

    arun(check())
