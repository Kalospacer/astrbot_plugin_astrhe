"""终审修复：保密身份规范化、待办工具保密、成员查询失败遮挡与闹钟边界。"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from astrhe.alarm_tracker import AlarmTracker
from astrhe.backfill import Backfiller
from astrhe.injector import Injector
from astrhe.night.planner import Planner
from astrhe.platform import PlatformHelper
from astrhe.prompts.planner import build_planner_prompt, build_planner_system
from astrhe.prompts.reporter import build_reporter_system
from astrhe.qq.client import QQClient
from astrhe.timeutil import utc_now
from astrhe.tools.day_tools import DayTools
from astrhe.tools.secrecy import (
    PresentResolver,
    filter_secret_text,
    is_secret_visible_here,
    normalize_qq_ids,
)
from astrhe.tools.validation import cron_trigger, validate_night_alarm_frequency
from astrhe.webapi import WebApi
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage
from tests.test_alarm_round4 import UMO, seed
from tests.test_alarm_tracker import _cron_event
from tests.test_draft_revision import setup
from tests.test_schedule_tool import _future, _impl

TZ = ZoneInfo("Asia/Shanghai")
FRIEND_UMO = "default:FriendMessage:50005"


class FixedPresence:
    def __init__(self, ids):
        self.ids = ids

    async def present_ids(self, umo):
        return self.ids if ":GroupMessage:" in umo else set()


def test_numeric_qq_arrays_are_stored_as_strings_and_legacy_ints_stay_hidden(
    tmp_path,
):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            _, _, _, call = await setup(s, ctx)
            await call(
                "astrhe_draft_todo",
                content="秘密蛋糕",
                visible_umos=f'["{UMO}"]',
                secret_from="[10001]",
            )
            await call(
                "astrhe_draft_alarm",
                target_umo="group:20002",
                run_at=_future(),
                background="背景",
                purpose="秘密安排",
                how="做法",
                mentions="[40004]",
                secret_from="[10001]",
            )
            drafts = {
                d["kind"]: json.loads(d["payload_json"])
                for d in await s.runs.get_drafts(1)
            }
            assert drafts["todo"]["secret_from"] == ["10001"]
            assert drafts["alarm"]["card"]["secret_from"] == ["10001"]
            assert drafts["alarm"]["card"]["mentions"] == ["40004"]
            bad = await call(
                "astrhe_draft_todo",
                content="写成昵称",
                visible_umos=f'["{UMO}"]',
                secret_from='["冰糖"]',
            )
            assert "草稿未保存" in bad and "QQ 号" in bad

            # 旧数据里已经存成整数的保密对象，读取时同样遮挡
            await s.plans.add_todo(
                content="旧数据秘密", visible_umos=[UMO], secret_from=[10001]
            )
            injector = Injector(
                s,
                lambda: TZ,
                FixedPresence({"10001", "40004"}),
                lambda: True,
                FakeLogger(),
            )
            text = await injector.build_injection(UMO, "40004")
            assert "旧数据秘密" not in text and "私下在准备的事" in text
        finally:
            await s.close()

        assert normalize_qq_ids([10001, " 10001 ", "40004"]) == ["10001", "40004"]
        assert not is_secret_visible_here(
            [10001], viewer_id="40004", session_umo=UMO, present_ids={"10001"}
        )

    arun(check())


def test_day_schedule_tool_normalizes_numeric_secret_ids(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext(
                {"get_group_member_list": [{"user_id": 10001}, {"user_id": 40004}]}
            )
            impl = _impl(s, ctx)
            member = FakeEvent(umo=UMO, sender_id="40004", role="member")
            result = await impl.run(
                member,
                action="create",
                target_type="current",
                run_at=_future(),
                background="背景",
                purpose="给寿星的秘密惊喜",
                how="做法",
                secret_from=[10001],
            )
            assert "定好了" in result, result
            alarm = (await s.alarms.list_alarms(-1))[0]
            assert json.loads(alarm["card_json"])["secret_from"] == ["10001"]
            listing = await impl.run(member, action="list")
            assert "秘密惊喜" not in listing
        finally:
            await s.close()

    arun(check())


def test_todo_update_cannot_find_or_reveal_hidden_secret_todo(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            secret = await s.plans.add_todo(
                content="买草莓生日蛋糕",
                visible_umos=[UMO, FRIEND_UMO],
                secret_from=["10001"],
            )
            normal = await s.plans.add_todo(content="普通待办", visible_umos=[UMO])
            day = DayTools(s, lambda: TZ, FixedPresence({"10001", "40004"}))
            member = FakeEvent(umo=UMO, sender_id="40004")
            result = await day.todo_update(member, todo_id=secret, status="progress")
            # 复述调用者给的编号无妨（与不存在的编号同一种回复），列表里不能出现隐藏待办
            listed = result.split("可见的待办：", 1)[1]
            assert f"#{secret}" not in listed and "草莓" not in result
            assert f"#{normal}" in listed
            assert (await s.plans.get_todo(secret))["status"] == "open"
            missing = await day.todo_update(member, todo_id=999, status="done")
            assert f"#{secret}" not in missing.split("可见的待办：", 1)[1]
            # 帮手私聊里保密对象不在场，可以正常勾选
            helper = FakeEvent(umo=FRIEND_UMO, sender_id="50005")
            done = await day.todo_update(helper, todo_id=secret, status="progress")
            assert "草莓" in done
        finally:
            await s.close()

    arun(check())


def test_member_lookup_failure_hides_secrets_unless_cache_is_available(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext({"get_group_member_list": RuntimeError("NapCat 掉线")})
            resolver = PresentResolver(s, QQClient(PlatformHelper(ctx, FakeLogger())))
            assert await resolver.present_ids(UMO) is None
            assert await resolver.present_ids(FRIEND_UMO) == set()
            # 有旧缓存时退回旧缓存，而不是只看近期发言
            resolver._member_cache["20002"] = (utc_now() - 3 * 86400, {"10001"})
            assert "10001" in await resolver.present_ids(UMO)
            resolver._member_cache.clear()

            text = "公开【保密:10001】秘密蛋糕【/保密】"
            hidden = filter_secret_text(
                text, viewer_id="40004", session_umo=UMO, present_ids=None
            )
            assert "秘密蛋糕" not in hidden
            assert not is_secret_visible_here(
                ["10001"], viewer_id="40004", session_umo=UMO, present_ids=None
            )
            await s.plans.add_todo(
                content="秘密待办", visible_umos=[UMO], secret_from=["10001"]
            )
            injector = Injector(s, lambda: TZ, resolver, lambda: True, FakeLogger())
            injected = await injector.build_injection(UMO, "40004")
            assert "秘密待办" not in injected and "私下在准备的事" in injected
        finally:
            await s.close()

    arun(check())


def test_manual_run_close_to_due_time_disables_one_shot_job(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            once, once_job = await seed(s, ctx)
            repeat, repeat_job = await seed(s, ctx, repeat=True)
            await s.db.execute(
                "UPDATE alarms SET run_at=? WHERE id=?", (utc_now() + 120, once)
            )
            tracker = AlarmTracker(s, ctx, lambda: TZ, FakeLogger())
            started = datetime.now(timezone.utc).isoformat()
            await tracker.on_agent_begin(_cron_event(once, started))
            await tracker.on_agent_begin(_cron_event(repeat, started))
            assert ctx.cron_manager.jobs[once_job].enabled is False
            assert ctx.cron_manager.jobs[repeat_job].enabled is True
        finally:
            await s.close()

    arun(check())


def test_cron_weekdays_follow_astrbot_standard_crontab():
    tuesday = datetime(2026, 10, 6, 11, 0, tzinfo=TZ)
    wednesday = cron_trigger("0 12 * * 3", TZ).get_next_fire_time(None, tuesday)
    assert wednesday.weekday() == 2 and wednesday.day == 7
    sunday = cron_trigger("0 12 * * 7", TZ).get_next_fire_time(None, tuesday)
    assert sunday.weekday() == 6
    with pytest.raises(ValueError):
        cron_trigger("0 12 * *", TZ)


def test_cancel_and_card_edit_failures_keep_original_state(tmp_path, monkeypatch):
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
            ctx = FakeContext()
            impl = _impl(s, ctx)
            admin = FakeEvent(umo=UMO, sender_id="10001", role="admin")
            aid, jid = await seed(s, ctx)

            async def broken_delete(job_id):
                raise RuntimeError("数据库被锁")

            original_delete = ctx.cron_manager.delete_job
            ctx.cron_manager.delete_job = broken_delete
            result = await impl.run(admin, action="cancel", alarm_id=aid)
            assert "取消失败" in result
            assert (await s.alarms.get_alarm(aid))["status"] == "scheduled"
            api = WebApi(s, ctx, lambda: TZ, lambda: {})

            async def json_body():
                return {"alarm_id": aid}

            api._json_body = json_body
            assert (await api._alarm_cancel())["status"] == 500
            assert (await s.alarms.get_alarm(aid))["status"] == "scheduled"
            ctx.cron_manager.delete_job = original_delete

            # 只改卡片：平台任务不见了，本地卡片不能先改掉
            ctx.cron_manager.jobs.pop(jid)
            result = await impl.run(
                admin, action="edit", alarm_id=aid, purpose="新目的"
            )
            assert "修改失败" in result
            card = json.loads((await s.alarms.get_alarm(aid))["card_json"])
            assert card["purpose"] == "完整目的"
        finally:
            await s.close()

    arun(check())


def test_daily_frequency_counts_repeating_alarms_on_the_target_date(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            noon, _ = await seed(s, ctx, repeat=True)
            one, _ = await seed(s, ctx, repeat=True)
            await s.db.execute(
                "UPDATE alarms SET cron_expression='0 13 * * *' WHERE id=?", (one,)
            )
            week_later = (datetime.now(TZ) + timedelta(days=7)).replace(
                hour=18, minute=0
            )
            payload = {"target_umo": UMO, "next_run_at": week_later.timestamp()}
            with pytest.raises(ValueError, match="同一目标每天"):
                await validate_night_alarm_frequency(s, payload, TZ, run_id=99)
            # 平台任务已消失的重复闹钟不再计数
            await s.alarms.set_status(one, "missing")
            await validate_night_alarm_frequency(s, payload, TZ, run_id=99)
            assert noon
        finally:
            await s.close()

    arun(check())


def test_backfill_enumerates_all_groups_after_a_long_gap(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            rid = await s.runs.start_run(plan_date="2026-10-01")
            await s.runs.finish_run(rid, "committed")
            ctx, logger = FakeContext(), FakeLogger()
            backfill = Backfiller(s, PlatformHelper(ctx, logger), logger)
            groups, _ = await backfill.candidate_sessions(utc_now() - 20 * 3600)
            assert groups == []
            groups, _ = await backfill.candidate_sessions(utc_now() - 14 * 86400)
            assert groups == ["20002"]
        finally:
            await s.close()

    arun(check())


def test_prompts_drop_fixed_night_and_yesterday_labels(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            await s.plans.save_plan(
                run_id=1, plan_date="2026-09-20", full_text="旧计划"
            )
            planner = Planner(
                s,
                FakeContext(),
                "p",
                "人格",
                ["10001"],
                TZ,
                time_info="t",
                window=(utc_now() - 86400, utc_now()),
            )
            materials = await planner.build_materials([], "", False)
            assert "【最近生效的规划书】" in materials
            assert "（规划日 2026-09-20）" in materials
        finally:
            await s.close()

        texts = (
            build_planner_system("人格", ["10001"], "t"),
            build_reporter_system("人格", ""),
            build_planner_prompt([], "", "", "", "计划", "", "", ""),
        )
        for text in texts:
            assert "现在是深夜" not in text and "深夜在回想" not in text
            assert "昨天的规划书" not in text

    arun(check())
