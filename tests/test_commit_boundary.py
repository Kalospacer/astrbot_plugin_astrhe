"""提交边界：模型失败、人工停止、插件卸载与外部动作。"""

import asyncio
import json

import pytest

from astrhe.night.draft import DraftCommitter
from astrhe.runtime import AstrHeRuntime
from tests.conftest import FakeContext, FakeLogger, arun
from tests.test_night_pipeline import (
    _build_pipeline,
    _seed_message,
    _make_handler,
    _reporter_handler,
    _planner_handler,
)
from tests.conftest import make_storage


def test_model_failure_after_commit_keeps_plan_and_alarm(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            await _seed_message(s)

            async def planner(kw):
                await _planner_handler(kw)
                assert len(ctx.cron_manager.added) == 1  # 提交工具返回前已经建好
                return "ERR"

            ctx.tool_loop_agent.handlers = [
                _make_handler(_reporter_handler),
                planner,
                _make_handler(lambda kw: "通过"),
                *[_make_handler(lambda kw: "ERR") for _ in range(2)],
            ]
            result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
            assert result["status"] == "committed"
            assert (await s.runs.latest_committed_run())["window_end"] > 0
            assert await s.plans.get_latest_plan()
            assert len(ctx.cron_manager.added) == 1
            run = await s.runs.get_run(1)
            assert len(json.loads(run["stats_json"])["model_failures"]) == 3
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize("after_commit", [False, True])
def test_stop_before_or_after_commit(tmp_path, after_commit):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            await _seed_message(s)
            reached = asyncio.Event()
            release = asyncio.Event()
            original = ctx.cron_manager.add_active_job

            async def delayed(**kw):
                reached.set()
                await release.wait()
                return await original(**kw)

            ctx.cron_manager.add_active_job = delayed

            async def planner(kw):
                if not after_commit:
                    reached.set()
                    await release.wait()
                return await _planner_handler(kw)

            ctx.tool_loop_agent.handlers = [
                _make_handler(_reporter_handler),
                planner,
                _make_handler(lambda kw: "通过"),
            ]
            pipe = _build_pipeline(s, ctx, FakeLogger())
            task = asyncio.create_task(pipe.run("manual"))
            await asyncio.wait_for(reached.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            if after_commit:
                assert pipe.external_tasks  # 收尾任务仍在运行
                release.set()
                await asyncio.gather(*pipe.external_tasks)
                assert len(ctx.cron_manager.added) == 1
                assert (await s.runs.get_run(1))["status"] == "committed"
            else:
                assert (await s.runs.get_run(1))["status"] == "failed"
                assert await s.plans.get_latest_plan() is None
                assert not ctx.cron_manager.added
        finally:
            await s.close()

    arun(check())


def test_runtime_waits_for_external_before_database_close(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        ctx = FakeContext()
        rt = AstrHeRuntime(ctx, {"enabled": True}, FakeLogger())
        rt.storage = s
        started = asyncio.Event()
        release = asyncio.Event()

        async def external():
            started.set()
            await release.wait()
            await s.db.set_state("external_finished", "yes")

        task = asyncio.create_task(external())
        rt._external_tasks.add(task)
        task.add_done_callback(rt._external_tasks.discard)
        await started.wait()
        from types import SimpleNamespace
        import time

        rt._current_pipeline = SimpleNamespace(
            stage="external", stage_since=time.time(), started_at=time.time()
        )
        assert rt.status_dict()["running"]
        assert "进行中" in await rt.cmd_status()
        assert "收尾" in await rt.cmd_run("manual")
        assert (await rt.run_night("auto"))["status"] == "skipped"
        assert "已经提交" in await rt.cmd_stop()
        closing = asyncio.create_task(rt.terminate())
        await asyncio.sleep(0)
        assert not closing.done()
        assert s.db.conn is not None
        release.set()
        await closing
        assert s.db._conn is None

    arun(check())


def test_cancel_at_database_commit_return_still_finishes_external(
    tmp_path, monkeypatch
):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            await _seed_message(s)
            original = DraftCommitter.commit_db

            async def interrupted(self):
                await original(self)
                raise asyncio.CancelledError()

            monkeypatch.setattr(DraftCommitter, "commit_db", interrupted)
            ctx.tool_loop_agent.handlers = [
                _make_handler(_reporter_handler),
                _make_handler(_planner_handler),
                _make_handler(lambda kw: "通过"),
            ]
            pipe = _build_pipeline(s, ctx, FakeLogger())
            with pytest.raises(asyncio.CancelledError):
                await pipe.run("manual")
            await asyncio.gather(*pipe.external_tasks)
            assert (await s.runs.get_run(1))["status"] == "committed"
            assert len(ctx.cron_manager.added) == 1
        finally:
            await s.close()

    arun(check())
