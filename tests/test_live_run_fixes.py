"""真机首跑发现的问题：规划书白天权限、空汇报、无效审稿、闹钟只管本会话、
管理员按编号处理对自己保密的闹钟。"""

import json
from zoneinfo import ZoneInfo

import pytest

from astrhe.alarm_tracker import AlarmTracker
from astrhe.night.draft import CommitError, DraftCommitter
from astrhe.night.planner import Planner
from astrhe.night.reporter import Reporter
from astrhe.night.reviewer import Reviewer, is_valid_review
from astrhe.timeutil import utc_now
from astrhe.tools.alarm_card import render_card_note
from astrhe.tools.alarm_view import platform_tasks
from astrhe.tools.reader_tools import ReaderTools
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage
from tests.test_alarm_round4 import UMO, seed
from tests.test_reporter_json import HistoryLoop
from tests.test_schedule_tool import _impl

TZ = ZoneInfo("Asia/Shanghai")


def test_day_read_plan_full_text_only_in_admin_private_chat(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            pid = await s.plans.save_plan(
                run_id=1, plan_date="2099-01-01", full_text="私聊里的私事。群里的安排。"
            )
            await s.plans.save_sections(pid, {UMO: "群里的安排"})
            reader = ReaderTools(s, FakeContext(), lambda: TZ, lambda: (0, 2e10))

            group = await reader._read_plan(FakeEvent(umo=UMO, sender_id="40004"))
            assert "群里的安排" in group and "私聊里的私事" not in group
            other = await reader._read_plan(FakeEvent(umo="default:GroupMessage:30003"))
            assert "没有专门写给本会话的段落" in other and "私聊里的私事" not in other
            # 管理员在群里也只拿到本会话段落，全文只在私聊里给
            admin_group = FakeEvent(umo=UMO, sender_id="10001", role="admin")
            assert "私聊里的私事" not in await reader._read_plan(admin_group)
            admin_dm = FakeEvent(
                umo="default:FriendMessage:10001", sender_id="10001", role="admin"
            )
            assert "私聊里的私事" in await reader._read_plan(admin_dm)
        finally:
            await s.close()

    arun(check())


async def _report(tmp_path, outputs):
    s = await make_storage(tmp_path)
    now = utc_now()
    rid = await s.runs.start_run(plan_date="2026-10-09")
    await s.ledger.add_message(
        umo=UMO,
        platform_id="default",
        message_type="GroupMessage",
        session_id="20002",
        sender_id="10001",
        text="零点一起发祝福",
        ts=now - 1,
        platform_message_id="7001",
    )
    ctx = FakeContext()
    loop = HistoryLoop(outputs)
    ctx.tool_loop_agent = loop
    reporter = Reporter(s, ctx, "fake", "人格", TZ, [], self_id="99999")
    result = await reporter.report_session(rid, UMO, now - 10, now + 1)
    return s, ctx, loop, result


def test_empty_report_is_retried_then_flagged_for_planner(tmp_path):
    async def check():
        s, ctx, loop, result = await _report(tmp_path, ["{}", "嘿嘿"])
        try:
            assert not result["parse_ok"] and len(loop.calls) == 2
            materials = await Planner(
                s, ctx, "fake", "", ["10001"], TZ, window=(0, 2e10)
            ).build_materials([result], "", False)
            assert "汇报失败" in materials and "astrhe_read_messages" in materials
            assert f"读 {UMO} 的原始记录" in materials
        finally:
            await s.close()

    arun(check())


def test_empty_report_recovered_by_format_follow_up(tmp_path):
    async def check():
        s, _, loop, result = await _report(tmp_path, ["{}", '{"summary":"约好零点"}'])
        try:
            assert result["parse_ok"] and result["report"]["summary"] == "约好零点"
            assert len(loop.calls) == 2
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize(
    "text, ok",
    [
        ("结论：通过", True),
        ("**结论：** 需要修改\n#3 保密标记不全", True),
        ("通过。没有问题", True),
        ("需要修改：#2 闹钟给别的会话发消息", True),
        ("我先把这些理一下，晚点再讲", False),
        ("得改，串号和撞车我重新排。白天再补一条陪你。", False),
        ("嘿嘿", False),
    ],
)
def test_review_needs_a_verdict(text, ok):
    assert is_valid_review(text) is ok


def test_chatty_review_is_retried_and_not_counted(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            rid = await s.runs.start_run(plan_date="2026-10-09")
            ctx = FakeContext()
            loop = HistoryLoop(["我先把这些理一下，晚点再讲", "得改，我重新排"])
            ctx.tool_loop_agent = loop
            reviewer = Reviewer(s, ctx, "fake", "人格", ["10001"], [])
            out = await reviewer.review(rid, "全面")
            assert "不计入审稿次数" in out and len(loop.calls) == 2
            # 追问时沿用首轮上下文
            assert loop.calls[1]["contexts"]
            assert await s.runs.count_ok_reviews(rid) == 0
            assert await s.runs.count_reviews(rid, "invalid") == 1

            loop.outputs = ["嗯嗯", "结论：需要修改\n#1 保密标记不全"]
            assert "保密标记不全" in await reviewer.review(rid, "全面")
            assert await s.runs.count_ok_reviews(rid) == 1
        finally:
            await s.close()

    arun(check())


def test_commit_allowed_after_two_invalid_reviews(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            rid = await s.runs.start_run(plan_date="2026-10-09")
            await s.runs.add_draft(
                run_id=rid, kind="plan", payload={"full_text": "规划"}, seq=1
            )
            ctx = FakeContext()
            committer = DraftCommitter(s, ctx, rid, "2026-10-09", TZ, admins=[])
            with pytest.raises(CommitError):
                await committer.validate()

            loop = HistoryLoop(["闲聊"] * 4)
            ctx.tool_loop_agent = loop
            reviewer = Reviewer(s, ctx, "fake", "人格", ["10001"], [])
            await reviewer.review(rid, "")
            await reviewer.review(rid, "")
            third = await reviewer.review(rid, "")
            # 第三次不再调用模型，提示自查后提交
            assert "不再审稿" in third and len(loop.calls) == 4
            await committer.validate()
        finally:
            await s.close()

    arun(check())


def test_alarm_note_keeps_to_its_own_session():
    note = render_card_note(
        {"background": "b", "purpose": "喊帮手", "how": "私聊帮手"},
        "default:FriendMessage:20003",
    )
    assert "只在本任务的目标会话里说话" in note
    # 卡片到执行时刻才读：写绝对时间，醒来按当前时间换算
    assert "绝对时间" in note and "X-1 号晚上 12 点" in note


def test_prompts_require_absolute_time_wording():
    from astrhe.prompts import planner as planner_prompts
    from astrhe.prompts import reviewer as reviewer_prompts

    planner = planner_prompts.build_planner_system("人格", ["10001"], "时间")
    reviewer = reviewer_prompts.build_reviewer_system("人格", ["10001"], "全面", "时间")
    assert "绝对日期和时刻" in planner and "X-1 号晚上 12 点" in planner
    assert "相对说法" in reviewer and "X-1 号晚上 12 点" in reviewer
    assert "明天" not in planner and "明天" not in reviewer


def test_admin_can_edit_and_cancel_alarm_secret_from_himself_by_id(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            impl = _impl(s, ctx)
            aid, job_id = await seed(s, ctx)
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
                    aid,
                ),
            )
            admin = FakeEvent(umo=UMO, sender_id="10001", role="admin")
            # 列表里照样看不到，惊喜不被剧透
            assert f"#{aid} " not in await impl.run(admin, action="list")
            edited = await impl.run(admin, action="edit", alarm_id=aid, how="只喊帮手")
            assert edited == f"闹钟 #{aid} 已更新"
            card = json.loads((await s.alarms.get_alarm(aid))["card_json"])
            assert card["how"] == "只喊帮手" and card["purpose"] == "惊喜"
            assert "只喊帮手" in ctx.cron_manager.jobs[job_id].payload["note"]
            assert "已取消" in await impl.run(admin, action="cancel", alarm_id=aid)
            assert job_id not in ctx.cron_manager.jobs
        finally:
            await s.close()

    arun(check())


def test_platform_tasks_show_run_time_and_external_note(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            cron = ctx.cron_manager
            # AstrBot 建一次性任务时把 run_at 写进 payload，这里按真实格式放进去
            await cron.add_active_job(
                name="给帮手发私信",
                cron_expression=None,
                run_once=True,
                payload={
                    "session": "default:FriendMessage:20003",
                    "run_at": "2099-10-10T12:00:00+00:00",
                    "note": "到点私聊帮手，邀请她一起发祝福",
                },
            )
            await cron.add_active_job(
                name="旧任务",
                cron_expression=None,
                run_once=True,
                enabled=False,
                payload={"session": UMO, "run_at": "2000-01-01T08:00:00+08:00"},
            )
            await cron.add_active_job(
                name="每日早安", cron_expression="0 8 * * *", payload={"session": UMO}
            )
            _, job_id = await seed(s, ctx)
            text = await platform_tasks(s, ctx, TZ)
            # UTC 时间换算成本地时间，外部任务附完整说明
            assert "执行时间 2099-10-10 20:00" in text
            assert "说明：到点私聊帮手，邀请她一起发祝福" in text
            assert "2000-01-01 08:00" in text and "（已过）" in text
            assert "重复规则 0 8 * * *" in text
            astrhe_line = next(line for line in text.splitlines() if job_id in line)
            assert astrhe_line.startswith("[AstrHe]")
        finally:
            await s.close()

    arun(check())


def test_orphan_job_after_data_reset_is_ignored_then_dropped(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            cron = ctx.cron_manager
            tracker = AlarmTracker(s, ctx, lambda: TZ, FakeLogger())
            aid, job_id = await seed(s, ctx)
            # 数据重置前留下的旧任务：闹钟编号和新闹钟相同，平台任务却是另一个
            old = await cron.add_active_job(
                name=f"astrhe闹钟#{aid}",
                cron_expression=None,
                run_once=True,
                payload={"astrhe_alarm_id": str(aid)},
            )
            ghost = await cron.add_active_job(
                name="astrhe闹钟#9",
                cron_expression=None,
                run_once=True,
                payload={"astrhe_alarm_id": "9"},
            )
            external = await cron.add_active_job(
                name="外部任务", cron_expression=None, payload={"session": UMO}
            )

            def wake(cron_job_id):
                return FakeEvent(
                    extras={
                        "cron_payload": {"astrhe_alarm_id": str(aid)},
                        "cron_job": {"id": cron_job_id},
                    }
                )

            # 旧任务到点：不认，新闹钟不被标记、平台任务不被停
            await tracker.on_agent_begin(wake(old.job_id))
            await tracker.on_agent_done(wake(old.job_id))
            assert (await s.alarms.get_alarm(aid))["status"] == "scheduled"
            assert not await s.alarms.events(aid)
            assert cron.jobs[job_id].enabled
            # 任务编号对得上才认
            await tracker.on_agent_begin(wake(job_id))
            assert (await s.alarms.get_alarm(aid))["status"] == "fired"

            # 对账删掉遗留任务，自己的任务和外部任务都保留
            text = await tracker.nightly_reconcile(0, utc_now())
            assert old.job_id not in cron.jobs and ghost.job_id not in cron.jobs
            assert job_id in cron.jobs and external.job_id in cron.jobs
            assert "遗留的平台任务" in text and "astrhe闹钟#9" in text
        finally:
            await s.close()

    arun(check())
