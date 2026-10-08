"""日记搜索完整段落、分页、管理恢复/回退以及提示词和迁移。"""

import json
import sqlite3
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astrhe.prompts import planner, reporter, reviewer
from astrhe.storage import Storage
from astrhe.timeutil import utc_now
from astrhe.tools.reader_tools import ReaderTools
from astrhe.webapi import WebApi
from tests.conftest import FakeContext, FakeEvent, arun, make_storage
from tests.test_memory_edit import seed_memory

TZ = ZoneInfo("Asia/Shanghai")


def test_memory_search_and_readers_paginate_without_truncating_paragraphs(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            long_paragraph = "关键词" + "完整内容" * 300
            for index in range(65):
                await s.plans.save_plan(
                    run_id=1,
                    plan_date=f"2098-{index // 28 + 1:02d}-{index % 28 + 1:02d}",
                    full_text=f"不相关段落\n\n{long_paragraph} 第 {index} 篇\n\n无关结尾",
                    reflection="关键词出现在反思",
                    day_reminders="关键词提醒",
                )
            for index in range(105):
                tid = await s.plans.add_todo(
                    content=f"关键词待办 {index}",
                    visible_umos=[],
                    due_date="2099-01-01",
                )
                await s.plans.update_todo_status(tid, "done", f"完整备注 {index}")
                pid = await s.plans.add_promise(
                    from_id="99999", to_id="10001", content=f"关键词承诺 {index}"
                )
                await s.plans.update_promise_status(pid, "done")
                await s.db.execute(
                    "UPDATE promises SET note='承诺备注' WHERE id=?", (pid,)
                )
            reader = ReaderTools(s, FakeContext(), lambda: TZ, lambda: (0, 2e10))
            first = await reader._search_memory(None, keyword="关键词", kind="plan")
            assert (
                long_paragraph in first
                and "不相关段落" not in first
                and "无关结尾" not in first
            )
            assert first.count("[plan]") == 30 and "offset=30" in first
            assert "2098-03-09" in first and "全文用 astrhe_read_plan" in first
            last = await reader._search_memory(
                None, keyword="关键词", kind="plan", offset=60
            )
            assert last.count("[plan]") == 5 and "还有更多" not in last
            assert "关键词出现在反思" in last and "关键词提醒" in last
            dates = await reader._read_plan(None, list=True)
            assert (
                "共 65 份" in dates and "本页 60 份" in dates and "offset=60" in dates
            )
            assert "本页 5 份" in await reader._read_plan(None, list=True, offset=60)
            for kind in ("todo", "promise"):
                method = reader._read_todos if kind == "todo" else reader._read_promises
                page = await method(None, status="done")
                assert "共 105 条，本页 100 条" in page and "offset=100" in page
                assert "备注" in page
                if kind == "todo":
                    assert "2099" in page
                assert "本页 5 条" in await method(None, status="done", offset=100)
                assert "共 0 条" in await method(None, status="open")
                assert "共 105 条" in await method(None, status="all")
            mixed = await reader._search_memory(None, keyword="关键词")
            assert mixed.count("[todo]") == 30 and "共 275 条" in mixed
        finally:
            await s.close()

    arun(check())


def test_web_trash_restore_and_revision_revert_record_history(tmp_path, monkeypatch):
    async def check():
        import astrhe.webapi as module

        fake_web = SimpleNamespace(
            json_response=lambda value: value,
            error_response=lambda text, status_code=400: {
                "error": text,
                "status": status_code,
            },
            request=SimpleNamespace(query={}),
        )
        monkeypatch.setattr(module, "astrbot_web", fake_web)
        s = await make_storage(tmp_path)
        try:
            target, _ = await seed_memory(s, "plan")
            payload = {
                "kind": "plan",
                "target": target,
                "action": "replace",
                "field": "full_text",
                "content": "更正的回忆",
                "reason": "真实更正",
            }
            async with s.db.write_lock:
                await s.db.conn.execute("BEGIN")
                await s.memory.apply_edit(payload, "2099-01-01", 1, utc_now())
                await s.db.conn.commit()
            revision_id = (await s.memory.revisions())[0][0]["id"]
            ctx = FakeContext()
            api = WebApi(s, ctx, lambda: TZ, lambda: {})
            api.register()
            assert all(
                any(route.endswith(path) for route, *_ in ctx.registered_web_apis)
                for path in (
                    "/memory/trash",
                    "/memory/restore",
                    "/memory/revisions",
                    "/memory/revert",
                )
            )
            body = {}

            async def json_body():
                return body

            api.memory_api._body = json_body
            body.update(revision_id=revision_id, reason="管理员确认应还原")
            result = await api.memory_api.revert()
            assert result["ok"] and result["entry"]["full_text"] == "原始日记"
            revisions = await api.memory_api.revisions()
            assert (
                revisions["total"] == 2
                and revisions["revisions"][0]["action"] == "revert"
            )
            assert (
                json.loads(revisions["revisions"][0]["before_json"])["full_text"]
                == "更正的回忆"
            )
            async with s.db.write_lock:
                await s.db.conn.execute("BEGIN")
                await s.memory.apply_edit(
                    {**payload, "action": "delete", "reason": "删错了"},
                    "2099-01-01",
                    1,
                    utc_now(),
                )
                await s.db.conn.commit()
            trash = await api.memory_api.trash()
            assert trash["total"] == 1 and trash["trash"][0]["target"] == target
            assert trash["trash"][0]["deleted_reason"] == "删错了"
            body.clear()
            body.update(kind="plan", target=target)
            assert (await api.memory_api.restore())["ok"]
            assert (await api.memory_api.trash())["total"] == 0
            assert (await api.memory_api.revisions())["total"] == 4
        finally:
            await s.close()

    arun(check())


def test_migrate_old_memory_tables_and_preserve_existing_content(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "astrhe.db")
    conn.executescript("""
        CREATE TABLE plans(id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, plan_date TEXT NOT NULL,
          full_text TEXT DEFAULT '',reflection TEXT DEFAULT '',created_at REAL NOT NULL);
        CREATE TABLE todos(id INTEGER PRIMARY KEY,content TEXT NOT NULL,visible_umos_json TEXT DEFAULT '[]',
          secret_from_json TEXT DEFAULT '[]',due_kind TEXT DEFAULT 'today',due_date TEXT DEFAULT '',
          show_from TEXT DEFAULT '',status TEXT DEFAULT 'done',note TEXT DEFAULT '',evidence_json TEXT DEFAULT '[]',
          alarm_id INTEGER,created_run_id INTEGER,updated_at REAL NOT NULL);
        CREATE TABLE promises(id INTEGER PRIMARY KEY,from_id TEXT DEFAULT '',to_id TEXT DEFAULT '',
          content TEXT NOT NULL,evidence_json TEXT DEFAULT '[]',due_date TEXT DEFAULT '',status TEXT DEFAULT 'done');
        INSERT INTO plans VALUES(1,1,'2026-10-07','旧日记','旧反思',123);
        INSERT INTO todos(id,content,updated_at) VALUES(1,'旧待办',123);
        INSERT INTO promises(id,content) VALUES(1,'旧承诺');
    """)
    conn.close()

    async def check():
        s = Storage(data)
        await s.open()
        try:
            plan = await s.plans.get_latest_plan()
            assert (
                plan["full_text"] == "旧日记"
                and plan["created_at"] == 123
                and plan["deleted_at"] is None
            )
            assert (await s.plans.get_todo(1))["deleted_reason"] == ""
            promise = (await s.plans.list_promises())[0]
            assert (
                promise["note"] == ""
                and promise["created_at"] == 0
                and promise["updated_at"] == 0
            )
            assert not await s.db.fetchall("SELECT * FROM memory_revisions")
        finally:
            await s.close()

    arun(check())


def test_prompts_describe_diary_and_admin_cancel_evidence():
    main = planner.build_planner_system("", ["10001"], "", "99999")
    review = reviewer.build_reviewer_system("", ["10001"], "")
    report = reporter.build_reporter_system("", "")
    assert (
        "【日记】" in main
        and "astrhe_draft_memory_edit" in main
        and "evidence_message_id" in main
    )
    assert "回收站" in main and "30 天" in main
    assert "日记删改是否必要" in review and "管理员本人" in review
    assert "astrhe_search_memory" in report


def test_day_read_plan_secrecy_and_night_read_plan_full_text(tmp_path):
    async def check():
        class Secrecy:
            async def present_ids(self, umo):
                return {"10001"}

        s = await make_storage(tmp_path)
        try:
            await s.plans.save_plan(
                run_id=1,
                plan_date="2099-01-01",
                full_text="普通内容【保密:10001】生日惊喜【/保密】",
            )
            day = ReaderTools(
                s, FakeContext(), lambda: TZ, lambda: (0, 2e10), Secrecy()
            )
            night = ReaderTools(
                s, FakeContext(), lambda: TZ, lambda: (0, 2e10), Secrecy(), run_id=1
            )
            assert "生日惊喜" not in await day._read_plan(FakeEvent())
            assert "生日惊喜" in await night._read_plan(FakeEvent())
        finally:
            await s.close()

    arun(check())
