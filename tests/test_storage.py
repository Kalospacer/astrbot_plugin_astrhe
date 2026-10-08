"""存储层测试：建表、读写、部分唯一索引去重。"""

from __future__ import annotations

from tests.conftest import arun, make_storage


async def _main(tmp_path):
    s = await make_storage(tmp_path)
    try:
        # 写入与读取
        row_id = await s.ledger.add_message(
            umo="default:GroupMessage:20002",
            platform_id="default",
            message_type="GroupMessage",
            session_id="20002",
            sender_id="10001",
            sender_name="甲",
            text="你好",
            ts=1700000000.0,
            platform_message_id="1001",
        )
        assert row_id is not None

        # 部分唯一索引：同 umo + 同平台 id 去重
        dup = await s.ledger.add_message(
            umo="default:GroupMessage:20002",
            platform_id="default",
            message_type="GroupMessage",
            session_id="20002",
            sender_id="10001",
            text="你好",
            ts=1700000001.0,
            platform_message_id="1001",
        )
        assert dup is None

        # 空 platform_message_id 不参与去重（bot 临时记录）
        b1 = await s.ledger.add_message(
            umo="default:GroupMessage:20002",
            platform_id="default",
            message_type="GroupMessage",
            session_id="20002",
            sender_id="99999",
            text="回复",
            ts=1700000002.0,
            platform_message_id=None,
            is_bot=True,
        )
        b2 = await s.ledger.add_message(
            umo="default:GroupMessage:20002",
            platform_id="default",
            message_type="GroupMessage",
            session_id="20002",
            sender_id="99999",
            text="回复",
            ts=1700000003.0,
            platform_message_id=None,
            is_bot=True,
        )
        assert b1 is not None and b2 is not None and b1 != b2

        # 撤回标记
        await s.ledger.mark_recalled("default:GroupMessage:20002", "1001")
        msgs = await s.ledger.get_messages(
            "default:GroupMessage:20002", 1699999999.0, 1700000100.0
        )
        assert all(m["id"] != row_id for m in msgs)  # 默认排除已撤回
        msgs_all = await s.ledger.get_messages(
            "default:GroupMessage:20002",
            1699999999.0,
            1700000100.0,
            include_recalled=True,
        )
        assert any(m["id"] == row_id and m["recalled"] == 1 for m in msgs_all)

        # bot 临时记录查询与补 id
        temps = await s.ledger.find_bot_temp_messages(
            "default:GroupMessage:20002", 1700000000.0
        )
        assert len(temps) == 2
        await s.ledger.attach_platform_id(temps[0]["id"], "2002")
        temps2 = await s.ledger.find_bot_temp_messages(
            "default:GroupMessage:20002", 1700000000.0
        )
        assert len(temps2) == 1

        # 规划书与待办
        plan_id = await s.plans.save_plan(
            run_id=1, plan_date="2026-10-08", full_text="正文", reflection="反思"
        )
        await s.plans.save_sections(plan_id, {"default:GroupMessage:20002": "段落"})
        assert await s.plans.get_section_for_umo("default:GroupMessage:20002") == "段落"

        todo_id = await s.plans.add_todo(
            content="发祝福",
            visible_umos=["default:GroupMessage:20002"],
            due_kind="today",
            due_date="2026-10-08",
        )
        visible = await s.plans.visible_todos(
            "default:GroupMessage:20002", "2026-10-08"
        )
        assert [t["id"] for t in visible] == [todo_id]
        assert (
            await s.plans.visible_todos("default:GroupMessage:33333", "2026-10-08")
            == []
        )

        # 关系本
        await s.persons.upsert_person("10001", aliases=["甲"], relation_text="群友")
        person = await s.persons.get_person("10001")
        assert "甲" in person["aliases_json"]
        assert (await s.persons.find_by_alias("甲"))["qq"] == "10001"

        # 预期联系人
        assert not await s.persons.is_expected_friend("10001", 100.0)
        await s.persons.set_expected_friend("10001", 200.0, "测试")
        assert await s.persons.is_expected_friend("10001", 100.0)
        assert not await s.persons.is_expected_friend("10001", 300.0)  # 过期失效
    finally:
        await s.close()


def test_storage(tmp_path):
    arun(_main(tmp_path))


def test_migrates_old_drafts_and_plan_columns(tmp_path):
    import sqlite3
    from astrhe.storage.db import Database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE drafts(id INTEGER PRIMARY KEY,run_id INTEGER,kind TEXT,payload_json TEXT,seq INTEGER,applied INTEGER);INSERT INTO drafts VALUES(1,1,'todo','{}',1,1);CREATE TABLE plans(id INTEGER PRIMARY KEY,run_id INTEGER,plan_date TEXT,full_text TEXT,reflection TEXT,created_at REAL);"
    )
    conn.close()

    async def check():
        db = Database(path)
        await db.open()
        try:
            assert (await db.fetchone("SELECT status FROM drafts WHERE id=1"))[
                "status"
            ] == "applied"
            columns = await db.fetchall("PRAGMA table_info(plans)")
            assert "day_reminders" in {r["name"] for r in columns}
        finally:
            await db.close()

    arun(check())
