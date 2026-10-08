"""日记草稿的动作、范围、同事务复核及普通读取隐藏删除记录。"""

import json
from zoneinfo import ZoneInfo

import pytest

from astrhe.injector import Injector
from astrhe.night.planner import Planner
from astrhe.timeutil import utc_now
from astrhe.tools.reader_tools import ReaderTools
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage
from tests.test_draft_revision import setup, draft_id

TZ = ZoneInfo("Asia/Shanghai")
UMO = "default:GroupMessage:20002"


async def seed_memory(s, kind, status="done"):
    if kind == "plan":
        pid = await s.plans.save_plan(
            run_id=1, plan_date="2098-12-31", full_text="原始日记", reflection="旧反思"
        )
        await s.plans.save_sections(pid, {UMO: "秘密旧段落"})
        return "2098-12-31", pid
    if kind == "todo":
        tid = await s.plans.add_todo(
            content="原始日记", visible_umos=[UMO], due_date="2098-12-31"
        )
        await s.plans.update_todo_status(tid, status, "原备注")
    else:
        tid = await s.plans.add_promise(
            from_id="99999", to_id="10001", content="原始日记", due_date="2098-12-31"
        )
        await s.plans.update_promise_status(tid, status)
        await s.db.execute("UPDATE promises SET note='原备注' WHERE id=?", (tid,))
    return str(tid), tid


@pytest.mark.parametrize("kind", ["plan", "todo", "promise"])
@pytest.mark.parametrize("action", ["append", "replace", "delete", "restore"])
def test_memory_actions_commit_with_exact_revision_and_stable_plan_date(
    tmp_path, kind, action
):
    async def check():
        s = await make_storage(tmp_path)
        try:
            target, tid = await seed_memory(s, kind)
            before = await s.memory.get_entry(kind, target)
            if action == "restore":
                await s.db.execute(
                    f"UPDATE { {'plan': 'plans', 'todo': 'todos', 'promise': 'promises'}[kind] }"
                    " SET deleted_at=?,deleted_reason='删错了' WHERE id=?",
                    (utc_now(), tid),
                )
                before = await s.memory.get_entry(kind, target)
            rid, _, _, call = await setup(s, FakeContext())
            await call("astrhe_draft_plan", full_text="当前规划")
            field = "full_text" if kind == "plan" else "content"
            result = await call(
                "astrhe_draft_memory_edit",
                kind=kind,
                target=target,
                action=action,
                field=field,
                content="补充内容",
                reason="回顾后修正",
            )
            assert "已保存" in result, result
            assert await s.memory.get_entry(kind, target) == before
            await call("astrhe_request_review")
            await call("astrhe_commit")
            after = await s.memory.get_entry(kind, target)
            revisions, total = await s.memory.revisions()
            assert total == 1 and revisions[0]["run_id"] == rid
            assert json.loads(revisions[0]["before_json"]) == before
            assert json.loads(revisions[0]["after_json"]) == after
            if action == "append":
                assert (
                    ("【后记 2099-01-01】补充内容" in after["full_text"])
                    if kind == "plan"
                    else after["note"] == "原备注\n补充内容"
                )
                if kind != "plan":
                    assert after["content"] == "原始日记"
            elif action == "replace":
                assert after[field] == "补充内容"
            elif action == "delete":
                assert (
                    after["deleted_at"] is not None
                    and after["deleted_reason"] == "回顾后修正"
                )
            else:
                assert after["deleted_at"] is None
            if kind == "plan":
                assert after["created_at"] == before["created_at"]
                assert (await s.plans.get_latest_plan())["plan_date"] == "2099-01-01"
            assert "已经提交" in await call(
                "astrhe_draft_memory_edit",
                kind=kind,
                target=target,
                action="replace",
                content="迟到",
                reason="迟到",
            )
        finally:
            await s.close()

    arun(check())


@pytest.mark.parametrize(
    "kind,status",
    [("plan", ""), ("todo", "open"), ("todo", "progress"), ("promise", "open")],
)
def test_memory_scope_rejects_current_plan_and_unfinished_items(tmp_path, kind, status):
    async def check():
        s = await make_storage(tmp_path)
        try:
            target, _ = await seed_memory(s, kind, status)
            if kind == "plan":
                await s.plans.save_plan(
                    run_id=1, plan_date="2099-01-01", full_text="今天"
                )
                target = "2099-01-01"
            _, _, _, call = await setup(s, FakeContext())
            result = await call(
                "astrhe_draft_memory_edit",
                kind=kind,
                target=target,
                action="delete",
                reason="尝试",
            )
            assert "已保存" not in result and ("规划日" in result or "已了结" in result)
        finally:
            await s.close()

    arun(check())


def test_memory_draft_replace_discard_and_transaction_revalidation(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            target, tid = await seed_memory(s, "todo")
            rid, _, committer, call = await setup(s, FakeContext())
            old = draft_id(
                await call(
                    "astrhe_draft_memory_edit",
                    kind="todo",
                    target=target,
                    action="append",
                    content="旧备注",
                    reason="补记",
                )
            )
            replaced = draft_id(
                await call(
                    "astrhe_draft_memory_edit",
                    kind="todo",
                    target=target,
                    action="append",
                    content="新备注",
                    reason="改正",
                    replace_draft_id=old,
                )
            )
            assert len(await s.runs.get_drafts(rid)) == 1
            await call("astrhe_draft_discard", draft_id=replaced, reason="暂不改")
            assert not await s.runs.get_drafts(rid)
            await call(
                "astrhe_draft_memory_edit",
                kind="todo",
                target=target,
                action="delete",
                reason="清理",
            )
            await call("astrhe_draft_plan", full_text="必须一起提交")
            await call("astrhe_request_review")
            # 草稿合法，提交前条目重新变成进行中；整个事务必须回滚。
            await s.plans.update_todo_status(tid, "progress")
            with pytest.raises(ValueError, match="已了结"):
                await committer.commit_db()
            assert await s.plans.get_plan_by_date("2099-01-01") is None
            assert (await s.runs.get_run(rid))["status"] == "running"
            assert (await s.memory.get_entry("todo", target))["deleted_at"] is None
            assert (await s.memory.revisions())[1] == 0
        finally:
            await s.close()

    arun(check())


def test_deleted_memories_hidden_from_every_normal_read(tmp_path, monkeypatch):
    async def check():
        import astrhe.webapi as web_module

        class Secrecy:
            async def present_ids(self, umo):
                return set()

        monkeypatch.setattr(
            web_module,
            "astrbot_web",
            type(
                "Web",
                (),
                {
                    "json_response": staticmethod(lambda value: value),
                },
            ),
        )
        s = await make_storage(tmp_path)
        try:
            target, pid = await seed_memory(s, "plan")
            _, tid = await seed_memory(s, "todo")
            _, promise = await seed_memory(s, "promise")
            for table, identifier in (
                ("plans", pid),
                ("todos", tid),
                ("promises", promise),
            ):
                await s.db.execute(
                    f"UPDATE {table} SET deleted_at=? WHERE id=?",
                    (utc_now(), identifier),
                )
            assert await s.plans.get_plan_by_date(target) is None
            assert await s.plans.get_latest_plan() is None
            assert not await s.plans.get_sections(pid)
            assert not await s.plans.get_section_for_umo(UMO)
            assert not await s.plans.list_plans()
            assert not await s.plans.list_todos()
            assert not await s.plans.list_promises()
            assert await s.plans.get_todo(tid) is None
            ctx = FakeContext()
            reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, 2e10))
            outputs = [
                await reader._read_plan(FakeEvent(), date=target),
                await reader._read_plan(None, list=True),
                await reader._read_todos(None, status="all"),
                await reader._read_promises(None, status="all"),
                await reader._search_memory(None, keyword="原始"),
                await Planner(
                    s, ctx, "fake", "", ["10001"], TZ, window=(0, 2e10)
                ).build_materials([], "", False),
                await Injector(
                    s, lambda: TZ, Secrecy(), lambda: True, FakeLogger()
                ).build_injection(UMO, "10001"),
            ]
            assert all(
                "原始日记" not in output and "秘密旧段落" not in output
                for output in outputs
            )
            api = web_module.WebApi(s, ctx, lambda: TZ, lambda: {})
            overview = await api._overview()
            assert overview["latest_plan"] is None
            assert (
                not overview["plans"]
                and not overview["todos"]
                and not overview["promises"]
            )
            # 即使数据库中异常地保留了 open 状态，普通读取也必须先排除删除项。
            await s.db.execute("UPDATE todos SET status='open'")
            await s.db.execute("UPDATE promises SET status='open'")
            assert not await s.plans.open_todos()
            assert not await s.plans.visible_todos(UMO, "2099-01-01")
            assert not await s.plans.open_promises()
        finally:
            await s.close()

    arun(check())


def test_memory_expiry_secret_validation_and_note_field(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            from astrhe import constants as C

            target, pid = await seed_memory(s, "plan")
            _, _, _, call = await setup(s, FakeContext())
            malformed = await call(
                "astrhe_draft_memory_edit",
                kind="plan",
                target=target,
                action="replace",
                content="【保密：10001】未闭合",
                reason="校正",
            )
            assert "已保存" not in malformed
            await s.db.execute(
                "UPDATE plans SET deleted_at=? WHERE id=?",
                (utc_now() - C.LEDGER_RETENTION_SECONDS - 1, pid),
            )
            expired = await call(
                "astrhe_draft_memory_edit",
                kind="plan",
                target=target,
                action="restore",
                reason="恢复",
            )
            assert "30 天" in expired and "已保存" not in expired
        finally:
            await s.close()

    arun(check())
