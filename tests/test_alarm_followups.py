"""总结隐私、平台短暂不可用、白天改期及其他补充修复。"""

import json
from datetime import datetime

import pytest

from astrhe import constants as C
from astrhe.backfill import Backfiller
from astrhe.platform import PlatformHelper
from astrhe.qq.client import QQClient
from astrhe.qq.lookup_tool import QQLookupTool
from astrhe.timeutil import utc_now
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage
from tests.test_draft_revision import TZ, draft_id, setup
from tests.test_night_alarm_cancel import ALARM_KW
from tests.test_night_pipeline import (
    _build_pipeline, _seed_message, _make_handler, _reporter_handler, _planner_handler,
)
from tests.test_schedule_tool import _impl


@pytest.mark.parametrize(
    "umo, secret_from, hide",
    [
        ("default:GroupMessage:20002", ["10001"], True),
        ("default:FriendMessage:10001", ["10001"], True),
        ("default:FriendMessage:40004", ["10001"], False),
        ("default:GroupMessage:20002", [], False),
        ("default:FriendMessage:40004", [], False),
    ],
)
def test_alarm_summary_depends_on_destination_in_day_and_night(
    tmp_path, umo, secret_from, hide
):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            impl = _impl(s, ctx)
            event = FakeEvent(umo=umo, role="admin")
            result = await impl.run(
                event, action="create", run_at=ALARM_KW["run_at"],
                background="惊喜的背景", purpose="给帮手安排分工", how="私聊沟通",
                secret_from=secret_from,
            )
            assert "定好了" in result
            _, _, committer, call = await setup(s, ctx)
            assert "已保存" in await call(
                "astrhe_draft_alarm",
                **{**ALARM_KW, "target_umo": umo, "secret_from": secret_from},
            )
            await call("astrhe_draft_plan", full_text="安排")
            await call("astrhe_request_review")
            await call("astrhe_commit")
            results = await committer.run_external_actions()
            assert "已建" in results[0]
            for job in ctx.cron_manager.added:
                note = job["payload"]["note"]
                assert "背景：" in note and "怎么做：" in note
                assert ("总结只写一句『已完成』" in note) is hide
                if not hide:
                    assert "实际发出的消息内容及发送是否成功" in note
                    assert "不要复述卡片里的背景、保密对象或禁忌" in note
                if secret_from:
                    assert job["description"].startswith("AstrHe 闹钟 #")
                    assert "安排" not in job["description"]
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize("kind", ["group", "private"])
def test_platform_list_failure_is_unknown_and_does_not_reject_alarm(tmp_path, kind):
    async def check():
        s = await make_storage(tmp_path)
        try:
            action = "get_group_list" if kind == "group" else "get_friend_list"
            ctx = FakeContext(api_actions={action: RuntimeError("NapCat 暂时掉线")})
            qq = QQClient(PlatformHelper(ctx, FakeLogger()))
            assert await (qq.group_ids() if kind == "group" else qq.friend_ids()) is None
            target = "group:20002" if kind == "group" else "private:40004"
            _, _, committer, call = await setup(s, ctx)
            result = await call(
                "astrhe_draft_alarm", **{**ALARM_KW, "target_umo": target}
            )
            assert "已保存" in result and "平台暂时不可用" in result
            assert "不在群" not in result and "不是好友" not in result
            await call("astrhe_draft_plan", full_text="规划")
            await call("astrhe_request_review")
            await call("astrhe_commit")
            results = await committer.run_external_actions()
            assert "已建" in results[0] and "平台暂时不可用" in results[0]
            event = FakeEvent(role="admin")
            result = await _impl(s, ctx).run(
                event, action="create", target_type=kind, target_id=(
                    "20002" if kind == "group" else "40004"
                ),
                run_at=ALARM_KW["run_at"], background="背景", purpose="目的", how="做法",
            )
            assert "定好了" in result and "平台暂时不可用" in result
            if kind == "private":
                tool = QQLookupTool(qq_client=qq)
                assert "平台暂时不可用" in await tool.run(
                    event, action="is_friend", user_id="40004"
                )
        finally:
            await s.close()

    arun(check())


def test_successful_empty_platform_lists_are_still_authoritative():
    async def check():
        ctx = FakeContext(api_actions={"get_group_list": [], "get_friend_list": []})
        qq = QQClient(PlatformHelper(ctx, FakeLogger()))
        assert await qq.group_ids() == set()
        assert await qq.friend_ids() == set()
    arun(check())


@pytest.mark.parametrize("failure", ["", "add", "delete"])
def test_day_edit_keeps_old_alarm_until_replacement_exists(tmp_path, failure):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            impl = _impl(s, ctx)
            event = FakeEvent(role="admin")
            aid = draft_id(await impl.run(
                event, action="create", run_at="2099-01-02 12:00",
                background="背景", purpose="旧提醒", how="做法",
            ))
            before = await s.alarms.get_alarm(aid)
            old_id = before["cron_job_id"]
            old_job = ctx.cron_manager.jobs[old_id]
            original_add = ctx.cron_manager.add_active_job
            original_delete = ctx.cron_manager.delete_job
            order = []

            async def add(**kw):
                order.append("add")
                assert old_id in ctx.cron_manager.jobs
                if failure == "add":
                    raise RuntimeError("新建失败")
                return await original_add(**kw)

            async def delete(job_id):
                order.append("delete")
                if failure == "delete" and job_id == old_id:
                    raise RuntimeError("旧任务删除失败")
                await original_delete(job_id)

            ctx.cron_manager.add_active_job = add
            ctx.cron_manager.delete_job = delete
            result = await impl.run(
                event, action="edit", alarm_id=aid,
                run_at="2099-01-03 12:00", purpose="新提醒",
            )
            after = await s.alarms.get_alarm(aid)
            if failure:
                assert "失败" in result and "旧闹钟已保留" in result
                assert after == before
                assert ctx.cron_manager.jobs == {old_id: old_job}
                assert order == (["add"] if failure == "add" else ["add", "delete", "delete"])
            else:
                assert "已更新" in result
                assert order == ["add", "delete"]
                assert old_id not in ctx.cron_manager.jobs
                assert after["cron_job_id"] in ctx.cron_manager.jobs
                assert after["run_at"] == datetime(2099, 1, 3, 12, tzinfo=TZ).timestamp()
                assert json.loads(after["card_json"])["purpose"] == "新提醒"
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize("value", ["", "  ", None, "null", "[]", []])
def test_empty_anniversary_is_optional_but_empty_array_clears_it(tmp_path, value):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            _, _, _, call = await setup(s, ctx)
            original = [{"name": "生日", "date": "10-11"}]
            await s.persons.upsert_person("40004", anniversaries=original)
            result = await call(
                "astrhe_draft_person", qq="40004", recent_text="蛋糕已准备",
                anniversaries=value,
            )
            assert "已保存" in result, result
            await call("astrhe_draft_plan", full_text="计划")
            await call("astrhe_request_review")
            await call("astrhe_commit")
            person = await s.persons.get_person("40004")
            assert person["recent_text"] == "蛋糕已准备"
            assert json.loads(person["anniversaries_json"]) == (
                [] if value == "[]" or value == [] else original
            )
        finally:
            await s.close()

    arun(check())


def test_bad_anniversary_json_error_includes_valid_example(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            _, _, _, call = await setup(s, FakeContext())
            result = await call(
                "astrhe_draft_person", qq="40004", anniversaries="生日 10-11"
            )
            assert "草稿未保存" in result and '[{"name":"生日","date":"10-11"}]' in result
        finally:
            await s.close()
    arun(check())


def test_friend_requests_use_the_same_thirty_day_retention(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            now = utc_now()
            for flag, ts in (
                ("old-pending", now - C.LEDGER_RETENTION_SECONDS - 1),
                ("old-approved", now - C.LEDGER_RETENTION_SECONDS - 1),
                ("boundary", now - C.LEDGER_RETENTION_SECONDS),
                ("recent", now - 1),
            ):
                await s.ledger.add_friend_request(user_id="40004", flag=flag, ts=ts)
            await s.ledger.set_friend_request_status("old-approved", "approved")
            ctx = FakeContext()
            backfill = Backfiller(s, PlatformHelper(ctx, FakeLogger()), FakeLogger())
            await backfill.cleanup_old(now)
            rows = await s.db.fetchall("SELECT * FROM friend_requests")
            assert {r["flag"] for r in rows} == {"boundary", "recent"}
        finally:
            await s.close()
    arun(check())


def test_all_night_roles_share_one_self_identity_lookup(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext(api_actions={"get_login_info": {"user_id": 99999}})
            await _seed_message(s)
            ctx.tool_loop_agent.handlers = [
                _make_handler(_reporter_handler),
                _make_handler(_planner_handler),
                _make_handler(lambda kw: "通过"),
            ]
            result = await _build_pipeline(s, ctx, FakeLogger()).run("manual")
            assert result["status"] == "committed", result
            for call in ctx.tool_loop_agent.calls:
                assert "你自己的 QQ：99999" in call["system_prompt"]
            for call in ctx.tool_loop_agent.calls[1:]:
                assert "from_id" in call["system_prompt"]
                assert "QQ 号码" in call["system_prompt"]
            assert sum(action == "get_login_info" for action, _ in ctx.api.calls) == 1
        finally:
            await s.close()

    arun(check())
