"""闹钟跟踪测试：钩子驱动的状态变化、立即执行识别与停用、对账 missing。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astrhe.alarm_tracker import AlarmTracker
from astrhe.timeutil import utc_now
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")


def _cron_event(alarm_id, run_started_at=None):
    extras = {"cron_payload": {"astrhe_alarm_id": str(alarm_id)}}
    if run_started_at:
        extras["cron_job"] = {"run_started_at": run_started_at}
    return FakeEvent(extras=extras)


def _tool_result(text):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


async def _main(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        tracker = AlarmTracker(s, ctx, lambda: TZ, FakeLogger())
        run_at = utc_now() + 3600
        alarm_id = await s.alarms.add_alarm(
            target_umo="default:GroupMessage:20002", origin="night", run_at=run_at,
            card={"purpose": "测试"},
        )
        job = await ctx.cron_manager.add_active_job(
            name="t", cron_expression=None, payload={"session": "x"}, run_once=True
        )
        await s.alarms.bind_cron_job(alarm_id, job.job_id)

        # started → sent → done
        event = _cron_event(alarm_id)
        await tracker.on_agent_begin(event)
        assert (await s.alarms.get_alarm(alarm_id))["status"] == "started"
        await tracker.on_llm_tool_respond(
            event, SimpleNamespace(name="send_message_to_user"), {},
            _tool_result("Message sent to session default:GroupMessage:20002"),
        )
        assert (await s.alarms.get_alarm(alarm_id))["status"] == "sent"
        await tracker.on_agent_done(event)
        assert (await s.alarms.get_alarm(alarm_id))["status"] == "done"

        # send_failed
        alarm2 = await s.alarms.add_alarm(
            target_umo="default:GroupMessage:20002", origin="night", run_at=run_at,
        )
        event2 = _cron_event(alarm2)
        await tracker.on_agent_begin(event2)
        await tracker.on_llm_tool_respond(
            event2, SimpleNamespace(name="send_message_to_user"), {},
            _tool_result("error: failed to send message"),
        )
        assert (await s.alarms.get_alarm(alarm2))["status"] == "send_failed"

        # 有 started 没有 done → failed
        alarm3 = await s.alarms.add_alarm(
            target_umo="default:GroupMessage:20002", origin="night", run_at=run_at,
        )
        await tracker.on_agent_begin(_cron_event(alarm3))
        await tracker.finalize_stale_started()
        assert (await s.alarms.get_alarm(alarm3))["status"] == "failed"

        # 立即执行：run_started_at 比 run_at 早 5 分钟以上 → manual_run + 停用
        alarm4 = await s.alarms.add_alarm(
            target_umo="default:GroupMessage:20002", origin="night", run_at=run_at,
        )
        job4 = await ctx.cron_manager.add_active_job(
            name="t4", cron_expression=None, payload={}, run_once=True
        )
        await s.alarms.bind_cron_job(alarm4, job4.job_id)
        early = datetime.fromtimestamp(run_at - 600, timezone.utc).isoformat()
        await tracker.on_agent_begin(_cron_event(alarm4, run_started_at=early))
        assert (await s.alarms.get_alarm(alarm4))["status"] == "manual_run"
        assert any(u[0] == job4.job_id and u[1].get("enabled") is False
                   for u in ctx.cron_manager.updated)

        # 对账 missing：run_at 已过、cron 行不存在、没有 started
        alarm5 = await s.alarms.add_alarm(
            target_umo="default:GroupMessage:20002", origin="night",
            run_at=utc_now() - 3600,
        )
        await s.alarms.bind_cron_job(alarm5, "ghost-job")  # cron 表里没有
        text = await tracker.nightly_reconcile()
        assert "失踪" in text
        assert (await s.alarms.get_alarm(alarm5))["status"] == "missing"
    finally:
        await s.close()


def test_alarm_tracker(tmp_path):
    arun(_main(tmp_path))
