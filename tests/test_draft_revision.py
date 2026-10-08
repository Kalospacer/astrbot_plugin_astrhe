"""草稿替换、校验与提交顺序的入口回归。"""

import json
import re
from zoneinfo import ZoneInfo

import pytest

from astrhe import constants as C
from astrhe.night.draft import CommitError, DraftCommitter
from astrhe.platform import PlatformHelper, resolve_session_ref
from astrhe.qq.client import QQClient
from astrhe.tools.draft_tools import DraftTools
from astrhe.tools.validation import validate_anniversaries
from astrhe.night.planner import anniversary_days_until
from tests.conftest import FakeContext, FakeLogger, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")
UMO = "default:GroupMessage:20002"


async def setup(s, ctx):
    rid = await s.runs.start_run(plan_date="2099-01-01")
    qq = QQClient(PlatformHelper(ctx, FakeLogger()))
    committer = DraftCommitter(s, ctx, rid, "2099-01-01", TZ, qq_client=qq)
    state = {}

    async def review(focus):
        await s.runs.add_review(run_id=rid, focus=focus, result_text="通过")
        return "通过"

    async def commit(summary):
        if state.get("committed"):
            return "今晚已经提交"
        await committer.validate()
        await committer.commit_db()
        state["committed"] = True
        return "已提交"

    owner = DraftTools(
        s, rid, review, commit, qq_client=qq, tz_getter=lambda: TZ, commit_state=state
    )
    tools = {t.name: t for t in owner.build()}

    async def call(name, **kw):
        return await tools[name].run(None, **kw)

    return rid, owner, committer, call


def draft_id(text):
    return int(re.search(r"#(\d+)", text).group(1))


def test_replacements_discard_and_merge_before_plan(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            rid, owner, committer, call = await setup(s, ctx)
            # 段落早于规划书，且分两次写；同一会话后写的生效。
            await call(
                "astrhe_draft_sections",
                sections_json=json.dumps(
                    {"group:20002": "旧段落", "private:40004": "私聊段落"}
                ),
            )
            await call(
                "astrhe_draft_sections",
                sections_json=json.dumps({"group:20002": "新段落"}),
            )
            await call(
                "astrhe_draft_plan", full_text="全文" * 800, day_reminders="提醒" * 400
            )
            old = draft_id(
                await call(
                    "astrhe_draft_todo",
                    content="旧待办",
                    visible_umos='["group:20002"]',
                )
            )
            new = draft_id(
                await call(
                    "astrhe_draft_todo",
                    content="新待办",
                    visible_umos='["group:20002"]',
                    replace_draft_id=old,
                    due_kind="deadline",
                    due_date="2099-01-03",
                )
            )
            removed = draft_id(
                await call(
                    "astrhe_draft_todo",
                    content="撤回待办",
                    visible_umos='["group:20002"]',
                )
            )
            assert "撤回" in await call(
                "astrhe_draft_discard", draft_id=removed, reason="不再需要"
            )
            assert "替换被拒绝" in await call(
                "astrhe_draft_todo",
                content="错误替换",
                visible_umos='["group:20002"]',
                replace_draft_id=old,
            )
            alarm_kw = dict(
                target_umo="group:20002",
                run_at="2099-01-02 12:00",
                background="背景",
                purpose="目的",
                how="做法",
            )
            a = draft_id(await call("astrhe_draft_alarm", **alarm_kw))
            await call(
                "astrhe_draft_alarm",
                **{**alarm_kw, "purpose": "新目的"},
                replace_draft_id=a,
            )
            read = await call("astrhe_read_drafts")
            assert "全文" * 800 in read and "提醒" * 400 in read
            assert f"#{new}" in read and "旧待办" not in read and "撤回待办" not in read
            await call("astrhe_request_review")
            assert "已提交" in await call("astrhe_commit")
            assert "已经提交" in await call("astrhe_commit")
            assert "已经提交" in await call(
                "astrhe_draft_todo", content="迟到", visible_umos='["group:20002"]'
            )
            assert "已经提交" in await call(
                "astrhe_draft_discard", draft_id=new, reason="迟到"
            )
            plan = await s.plans.get_latest_plan()
            sections = await s.plans.get_sections(plan["id"])
            assert sections == {
                UMO: "新段落",
                "default:FriendMessage:40004": "私聊段落",
            }
            todos = await s.plans.open_todos()
            assert len(todos) == 1 and todos[0]["content"] == "新待办"
            assert todos[0]["show_from"] == "2099-01-01"
            assert len(await s.plans.visible_todos(UMO, "2099-01-01")) == 1
            await committer.run_external_actions()
            assert len(ctx.cron_manager.added) == 1
            with pytest.raises(CommitError):
                await committer.commit_db()
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"target_umo": "wrong"}, "会话格式"),
        ({"target_umo": "group:33333"}, "不在群"),
        ({"run_at": "坏时间"}, "解析"),
        ({"run_at": "2000-01-01 12:00"}, "5 分钟"),
        ({"run_at": "2099-01-02 03:00"}, "深夜"),
        ({"run_at": "", "cron_expression": "garbage"}, "重复规则"),
        (
            {
                "run_at": "",
                "cron_expression": "* * * * *",
                "agreed": True,
                "agreed_reason": "约定",
            },
            "分钟",
        ),
    ],
)
def test_alarm_validation_at_draft_time(tmp_path, changes, expected):
    async def check():
        s = await make_storage(tmp_path)
        try:
            rid, _, _, call = await setup(s, FakeContext())
            text = await call(
                "astrhe_draft_alarm",
                **{
                    "target_umo": "group:20002",
                    "run_at": "2099-01-02 12:00",
                    "background": "背景",
                    "purpose": "目的",
                    "how": "做法",
                    **changes,
                },
            )
            assert expected in text, text
            assert not await s.runs.get_drafts(rid)
        finally:
            await s.close()

    arun(check())


def test_alarm_frequency_and_expected_contacts(tmp_path, monkeypatch):
    async def check():
        s = await make_storage(tmp_path)
        try:
            _, _, _, call = await setup(s, FakeContext())
            kw = dict(
                target_umo="group:20002",
                run_at="2099-01-02 12:00",
                background="背景",
                purpose="目的",
                how="做法",
            )
            for _ in range(2):
                assert "已保存" in await call("astrhe_draft_alarm", **kw)
            assert "同一目标" in await call("astrhe_draft_alarm", **kw)
            monkeypatch.setattr(C, "RATE_ALARM_NIGHT_PER_RUN", 2)
            assert "本晚" in await call(
                "astrhe_draft_alarm", **{**kw, "target_umo": "private:50005"}
            )
            for qq in ("50005", "60006", "70007"):
                assert "已保存" in await call(
                    "astrhe_draft_person", qq=qq, expected_friend=True
                )
            assert "最多 3 人" in await call(
                "astrhe_draft_person", qq="80008", expected_friend=True
            )
            assert "会话格式" in await call(
                "astrhe_draft_todo", content="事", visible_umos='["wrong"]'
            )
            assert "会话格式" in await call(
                "astrhe_draft_sections", sections_json='{"wrong":"事"}'
            )
            assert "保密标记" in await call(
                "astrhe_draft_plan", full_text="【保密：10001】未结束"
            )
            assert "数组" in await call(
                "astrhe_draft_person", qq="50005", anniversaries='"生日 10-11"'
            )
            assert "已保存" in await call(
                "astrhe_draft_person",
                qq="50005",
                anniversaries='[{"name":"生日","date":"10-11"}]',
            )
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize(
    "value",
    [
        "生日 10-11",
        ["生日 10-11"],
        [{"name": "生日", "date": "13-40"}],
        [{"name": "生日", "date": "10-1"}],
    ],
)
def test_anniversary_rejects_malformed_and_reads_safely(value):
    from datetime import datetime

    with pytest.raises(ValueError):
        validate_anniversaries(value)
    assert anniversary_days_until(value, datetime(2026, 10, 8, tzinfo=TZ)) is None
    assert validate_anniversaries([{"name": "生日", "date": "02-29"}])


def test_session_reference_formats():
    assert resolve_session_ref("群:20002", "default") == UMO
    assert resolve_session_ref("私聊:40004", "default") == "default:FriendMessage:40004"
    assert resolve_session_ref("default:GroupMessage:10001_20002", "default") == UMO


def test_repeat_interval_quiet_hours_and_admin_gate(tmp_path, monkeypatch):
    from datetime import datetime
    from astrhe.tools.validation import validate_alarm_time
    import astrhe.tools.validation as validation

    monkeypatch.setattr(
        validation,
        "utc_now",
        lambda: datetime(2026, 10, 8, 10, 0, tzinfo=TZ).timestamp(),
    )
    card = {"agreed": True, "agreed_reason": "已约定"}
    with pytest.raises(ValueError, match="1 小时"):
        validate_alarm_time("", "0,30 12 * * *", card, TZ)
    with pytest.raises(ValueError, match="深夜"):
        validate_alarm_time("", "0 3 * * *", {}, TZ)
    with pytest.raises(ValueError, match="管理员"):
        validate_alarm_time("", "0 12 * * *", card, TZ, allow_repeat=False)
    assert validate_alarm_time("", "0 12 * * *", {}, TZ) > 0


def test_commit_revalidates_alarm_and_reports_failure(tmp_path, monkeypatch):
    async def check():
        from astrhe.alarm_tracker import AlarmTracker
        import astrhe.tools.validation as validation
        from datetime import datetime

        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            rid, _, committer, call = await setup(s, ctx)
            kw = dict(
                target_umo="group:20002",
                run_at="2099-01-02 12:00",
                background="背景",
                purpose="目的",
                how="做法",
            )
            assert "已保存" in await call("astrhe_draft_alarm", **kw)
            await call("astrhe_draft_plan", full_text="规划")
            await call("astrhe_request_review")
            await call("astrhe_commit")
            monkeypatch.setattr(
                validation,
                "utc_now",
                lambda: datetime(2099, 1, 2, 11, 59, tzinfo=TZ).timestamp(),
            )
            result = await committer.run_external_actions()
            assert "5 分钟" in result[0] and "失败" in result[0]
            assert not ctx.cron_manager.added
            alarm = (await s.alarms.list_alarms())[0]
            assert alarm["status"] == "failed"
            text = await AlarmTracker(
                s, ctx, lambda: TZ, FakeLogger()
            ).nightly_reconcile()
            assert "创建失败" in text and "5 分钟" in text
        finally:
            await s.close()

    arun(check())
