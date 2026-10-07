"""夜间流程测试：假 tool_loop_agent 模拟子代理与主 agent。

覆盖：正常提交；审稿 0 次拒绝提交；第 3 次审稿被拒；审稿模型失败整晚终止；
role="err" 失败；异常不提交；提交后外部动作失败不改变 committed；
dry 模式不写正式表不执行外部动作；不设限参数与 stream=True。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from zoneinfo import ZoneInfo

from astrhe import constants as C
from astrhe.alarm_tracker import AlarmTracker
from astrhe.backfill import Backfiller
from astrhe.night.pipeline import NightPipeline
from astrhe.platform import PlatformHelper
from astrhe.qq.client import QQClient
from astrhe.qq.friend_requests import FriendRequestManager
from astrhe.qq.rate_limit import RateLimiter
from astrhe.tools.draft_tools import DraftTools
from astrhe.tools.reader_tools import ReaderTools
from astrhe.tools.secrecy import PresentResolver
from astrhe.timeutil import local_date_str, utc_now
from tests.conftest import FakeContext, FakeLogger, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")
GROUP_UMO = "default:GroupMessage:20002"


def _build_pipeline(s, ctx, logger):
    qq = QQClient(PlatformHelper(ctx, logger))
    secrecy = PresentResolver(s, qq)
    rate_limiter = RateLimiter(s, lambda: TZ)

    def provider(kind: str, **kwargs: Any):
        if kind == "reader":
            window = kwargs.get("window") or (0, 2e10)
            return ReaderTools(s, ctx, lambda: TZ, lambda: window, secrecy).build()
        if kind == "draft":
            return DraftTools(
                s, kwargs["run_id"], kwargs["request_review_cb"], kwargs["commit_cb"]
            ).build()
        return []

    pipeline = NightPipeline(
        storage=s, context=ctx, config={"provider_id": "fake-provider"},
        platform_helper=PlatformHelper(ctx, logger), qq_client=qq,
        rate_limiter=rate_limiter, secrecy_resolver=secrecy,
        admins_getter=lambda: ["10001"], tz_getter=lambda: TZ,
        backfiller=Backfiller(s, PlatformHelper(ctx, logger), logger),
        friend_request_manager=FriendRequestManager(s, qq, logger),
        internal_tools_provider=provider, logger=logger,
    )
    pipeline.alarm_tracker = AlarmTracker(s, ctx, lambda: TZ, logger)
    return pipeline


async def _seed_message(s):
    await s.ledger.add_message(
        umo=GROUP_UMO, platform_id="default", message_type="GroupMessage",
        session_id="20002", sender_id="10001", text="明天商量一下生日的事",
        ts=utc_now() - 3600, platform_message_id="7001",
    )


def _reporter_handler(kwargs):
    return json.dumps({
        "summary": "今天群里商量了生日的事",
        "big_events": [], "interesting": [], "self_interest": [],
        "promises": [], "plan_candidates": [], "person_updates": [],
        "reflection_hints": [],
    }, ensure_ascii=False)


def _planner_handler(kwargs):
    async def drive():
        tools = kwargs["tools"]
        event = kwargs["event"]

        async def call(name, **args):
            return await tools.get_tool(name).run(event, **args)

        await call("astrhe_draft_plan", full_text="规划书正文", reflection="今天还行")
        await call("astrhe_draft_sections",
                   sections_json=json.dumps({GROUP_UMO: "这个群的段落"}))
        await call("astrhe_draft_todo", content="零点发祝福",
                   visible_umos=json.dumps([GROUP_UMO]), due_kind="today")
        await call("astrhe_draft_alarm", target_umo=GROUP_UMO,
                   run_at="2099-01-02 12:00",
                   background="生日", purpose="送祝福", how="发消息")
        review = await call("astrhe_request_review", focus="全面")
        assert "审稿意见" in review
        commit = await call("astrhe_commit", summary="定了")
        return commit

    return drive()


def _make_handler(fn):
    """把同步返回驱动协程的函数包成 handler。"""

    async def handler(kwargs):
        result = fn(kwargs)
        if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
            return await result
        return result

    return handler


async def _main_commit(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext(api_actions={"get_login_info": {"user_id": 99999}})
        loop = ctx.tool_loop_agent
        await _seed_message(s)
        loop.handlers = [
            _make_handler(_reporter_handler),
            _make_handler(_planner_handler),
            _make_handler(lambda kw: "通过，没问题"),
        ]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
        assert result["status"] == "committed", result

        today = local_date_str(utc_now(), TZ)
        plan = await s.plans.get_plan_by_date(today)
        assert plan and plan["full_text"] == "规划书正文"
        sections = await s.plans.get_sections(plan["id"])
        assert sections.get(GROUP_UMO) == "这个群的段落"
        todos = await s.plans.open_todos()
        assert len(todos) == 1 and todos[0]["content"] == "零点发祝福"
        alarms = await s.alarms.list_alarms()
        assert len(alarms) == 1 and alarms[0]["origin"] == "night"
        job_kwargs = ctx.cron_manager.added[0]
        assert job_kwargs["payload"]["sender_id"] == "astrhe"
        assert job_kwargs["payload"]["origin"] == "tool"
        assert job_kwargs["payload"]["astrhe_alarm_id"] == str(alarms[0]["id"])
        # 审稿记录
        assert await s.runs.count_ok_reviews(1) == 1
        # 不设限参数与 stream=True
        for call in loop.calls:
            assert call.get("stream") is True
            assert call.get("max_steps") == C.UNLIMITED_STEPS
            assert call.get("tool_call_timeout") == C.UNLIMITED_SECONDS
        # stats 记录各阶段耗时
        run = await s.runs.get_run(1)
        stats = json.loads(run["stats_json"])
        assert "backfill" in stats["stages"] and "plan" in stats["stages"]
    finally:
        await s.close()


def test_night_commit(tmp_path):
    arun(_main_commit(tmp_path))


async def _main_no_review(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        await _seed_message(s)

        async def planner_no_review(kwargs):
            tools = kwargs["tools"]
            event = kwargs["event"]
            await tools.get_tool("astrhe_draft_plan").run(event, full_text="规划")
            return await tools.get_tool("astrhe_commit").run(event, summary="x")

        ctx.tool_loop_agent.handlers = [
            _make_handler(_reporter_handler),
            planner_no_review,
            _make_handler(lambda kw: "好的"),  # 追问那次
        ]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
        # 追问后仍未提交 → 失败
        assert result["status"] == "failed"
        assert await s.plans.get_latest_plan() is None
    finally:
        await s.close()


def test_commit_refused_without_review(tmp_path):
    arun(_main_no_review(tmp_path))


async def _main_third_review(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        await _seed_message(s)
        review_results = []

        async def planner_three_reviews(kwargs):
            tools = kwargs["tools"]
            event = kwargs["event"]
            await tools.get_tool("astrhe_draft_plan").run(event, full_text="规划")
            for _ in range(3):
                review_results.append(
                    await tools.get_tool("astrhe_request_review").run(event, focus="")
                )
            return await tools.get_tool("astrhe_commit").run(event, summary="ok")

        ctx.tool_loop_agent.handlers = [
            _make_handler(_reporter_handler),
            planner_three_reviews,
            _make_handler(lambda kw: "意见1"),
            _make_handler(lambda kw: "意见2"),
            # 第 3 次审稿在代码层就被拒，不会消耗模型调用
        ]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
        assert result["status"] == "committed"
        assert "上限" in review_results[2]  # 第 3 次被拒
        assert await s.runs.count_ok_reviews(1) == 2
    finally:
        await s.close()


def test_third_review_refused(tmp_path):
    arun(_main_third_review(tmp_path))


async def _main_review_err(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        await _seed_message(s)

        async def planner(kwargs):
            tools = kwargs["tools"]
            event = kwargs["event"]
            await tools.get_tool("astrhe_draft_plan").run(event, full_text="规划")
            review = await tools.get_tool("astrhe_request_review").run(event, focus="")
            assert "审稿失败" in review
            commit = await tools.get_tool("astrhe_commit").run(event, summary="x")
            assert "拒绝" in commit
            return "结束"

        ctx.tool_loop_agent.handlers = [
            _make_handler(_reporter_handler),
            planner,
            _make_handler(lambda kw: "ERR"),  # 审稿的模型请求失败
        ]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
        assert result["status"] == "failed"
        assert await s.plans.get_latest_plan() is None  # 不提交
    finally:
        await s.close()


def test_review_model_failure_terminates_run(tmp_path):
    arun(_main_review_err(tmp_path))


async def _main_role_err(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        await _seed_message(s)
        ctx.tool_loop_agent.handlers = [
            _make_handler(lambda kw: "ERR"),  # 汇报就失败
        ]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
        assert result["status"] == "failed"
        assert result["stage"] == "report"
        run = await s.runs.get_run(1)
        assert "模型请求失败" in run["error"]
    finally:
        await s.close()


def test_role_err_fails_run(tmp_path):
    arun(_main_role_err(tmp_path))


async def _main_external_failure(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        await _seed_message(s)

        # add_active_job 抛异常：外部动作失败
        async def boom(**kwargs):
            raise RuntimeError("数据库被锁")

        ctx.cron_manager.add_active_job = boom
        ctx.tool_loop_agent.handlers = [
            _make_handler(_reporter_handler),
            _make_handler(_planner_handler),
            _make_handler(lambda kw: "通过"),
        ]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
        # 提交点已过：外部动作失败不改变 committed
        assert result["status"] == "committed"
        stats = result["stats"]
        assert any("失败" in r for r in stats["external_results"])
        alarm = (await s.alarms.list_alarms())[0]
        assert alarm["status"] == "failed"  # 闹钟本身记录失败，留给下一晚
    finally:
        await s.close()


def test_external_action_failure_keeps_committed(tmp_path):
    arun(_main_external_failure(tmp_path))


async def _main_dry(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        await _seed_message(s)
        ctx.tool_loop_agent.handlers = [
            _make_handler(_reporter_handler),
            _make_handler(_planner_handler),
            _make_handler(lambda kw: "通过"),
        ]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("dry")
        assert result["status"] == "dry_done"
        # 不写正式表
        assert await s.plans.get_latest_plan() is None
        assert await s.plans.open_todos() == []
        # 不执行外部动作
        assert ctx.cron_manager.added == []
        # 草稿与汇报保留在运行记录里
        drafts = await s.runs.get_drafts(1)
        assert drafts
        reports = await s.runs.get_reports(1)
        assert reports
    finally:
        await s.close()


def test_dry_mode(tmp_path):
    arun(_main_dry(tmp_path))


async def _main_reporter_failure_cancels(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        # 两个会话：一个汇报失败，一个慢
        await _seed_message(s)
        await s.ledger.add_message(
            umo="default:FriendMessage:40004", platform_id="default",
            message_type="FriendMessage", session_id="40004",
            sender_id="40004", text="私聊消息",
            ts=utc_now() - 3600, platform_message_id="7002",
        )
        slow_finished = False

        async def failing(kwargs):
            raise RuntimeError("模型服务挂了")

        async def slow(kwargs):
            nonlocal slow_finished
            await asyncio.sleep(30)
            slow_finished = True
            return "{}"

        ctx.tool_loop_agent.handlers = [slow, failing]
        result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
        assert result["status"] == "failed"
        assert not slow_finished  # 其余子代理被取消
    finally:
        await s.close()


def test_reporter_failure_cancels_others(tmp_path):
    arun(_main_reporter_failure_cancels(tmp_path))
