"""调度器测试：下一次 00:00 计算、plan_date 语义、漏跑判断、运行重叠跳过、
stop 指令（提交前后）。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from astrhe.scheduler import NightScheduler
from astrhe.timeutil import local_date_str, next_midnight_ts, utc_now
from tests.conftest import FakeLogger, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")


def test_next_midnight():
    now = datetime(2026, 10, 7, 21, 30, tzinfo=TZ).timestamp()
    nxt = next_midnight_ts(now, TZ)
    dt = datetime.fromtimestamp(nxt, TZ)
    assert (dt.year, dt.month, dt.day) == (2026, 10, 8)
    assert (dt.hour, dt.minute) == (0, 0)
    # 恰好 00:00 时取下一个 00:00（明天）
    midnight = datetime(2026, 10, 8, 0, 0, tzinfo=TZ).timestamp()
    nxt2 = datetime.fromtimestamp(next_midnight_ts(midnight, TZ), TZ)
    assert nxt2.day == 9


def test_plan_date_is_local_date():
    # plan_date = 运行时刻的本地日期
    assert (
        local_date_str(datetime(2026, 10, 8, 0, 0, tzinfo=TZ).timestamp(), TZ)
        == "2026-10-08"
    )


async def _main_missed(tmp_path):
    s = await make_storage(tmp_path)
    try:
        triggered = []

        async def callback(mode):
            triggered.append(mode)
            return {"status": "committed"}

        scheduler = NightScheduler(s, lambda: TZ, callback, FakeLogger())
        # 没有成功提交记录 → 补跑
        await scheduler._missed_run_check_inner()
        if scheduler._running_task is not None:
            await scheduler._running_task
        assert triggered == ["auto"]

        # 24 小时内有成功提交 → 不补跑
        triggered.clear()
        run_id = await s.runs.start_run(plan_date=local_date_str(utc_now(), TZ))
        await s.runs.finish_run(run_id, "committed")
        await scheduler._missed_run_check_inner()
        await asyncio.sleep(0)
        assert triggered == []

        # 残留的 running 记录被标记 failed
        stale_id = await s.runs.start_run(plan_date="2026-10-06")
        await scheduler._missed_run_check_inner()
        stale = await s.runs.get_run(stale_id)
        assert stale["status"] == "failed"
    finally:
        await s.close()


def test_missed_run(tmp_path):
    arun(_main_missed(tmp_path))


async def _main_overlap_and_stop(tmp_path):
    s = await make_storage(tmp_path)
    try:
        started = asyncio.Event()
        finish = asyncio.Event()

        async def callback(mode):
            started.set()
            await finish.wait()
            return {"status": "committed"}

        scheduler = NightScheduler(s, lambda: TZ, callback, FakeLogger())
        # 触发一次（正在跑）
        assert await scheduler.trigger("manual") is not None
        await asyncio.wait_for(started.wait(), 2)
        # 重叠：再触发被跳过
        assert await scheduler.trigger("manual") is None
        # stop：取消运行
        msg = await scheduler.stop_running()
        assert "停止" in msg
        await asyncio.sleep(0.05)
        finish.set()
    finally:
        await s.close()


def test_overlap_and_stop(tmp_path):
    arun(_main_overlap_and_stop(tmp_path))


def test_stop_preserves_next_midnight_loop(tmp_path, monkeypatch):
    async def check():
        s = await make_storage(tmp_path)
        try:
            import astrhe.scheduler as module

            real_sleep = asyncio.sleep
            midnight = asyncio.Queue()
            calls = asyncio.Queue()

            async def clock(delay):
                await midnight.get()

            async def callback(mode):
                await calls.put(mode)
                await asyncio.Event().wait()

            scheduler = NightScheduler(s, lambda: TZ, callback, FakeLogger())
            monkeypatch.setattr(module.asyncio, "sleep", clock)
            task = asyncio.create_task(scheduler._loop())
            scheduler._task = task
            await midnight.put(True)
            assert await asyncio.wait_for(calls.get(), 1) == "auto"
            await scheduler.stop_running()
            await real_sleep(0)
            await real_sleep(0)
            assert not task.done()
            await midnight.put(True)
            assert await asyncio.wait_for(calls.get(), 1) == "auto"
            await scheduler.stop()
            await real_sleep(0)
        finally:
            await s.close()

    arun(check())


def test_restart_failed_date_catches_up(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            today = local_date_str(utc_now(), TZ)
            old = await s.runs.start_run(plan_date="2000-01-01")
            await s.runs.finish_run(old, "committed")
            interrupted = await s.runs.start_run(plan_date=today)
            calls = []

            async def callback(mode):
                calls.append(mode)

            scheduler = NightScheduler(s, lambda: TZ, callback, FakeLogger())
            await scheduler._missed_run_check_inner()
            await scheduler._running_task
            assert calls == ["auto"]
            assert (await s.runs.get_run(interrupted))["status"] == "failed"
            now = await s.runs.start_run(plan_date=today)
            await s.runs.finish_run(now, "committed")
            calls.clear()
            await scheduler._missed_run_check_inner()
            await asyncio.sleep(0)
            assert calls == []
            assert (await s.runs.previous_run(now))["id"] == interrupted
        finally:
            await s.close()

    arun(check())
