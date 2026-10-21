"""规划书、待办与承诺仓库。"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import utc_now
from .db import Database


class PlansRepo:
    def __init__(self, db: Database):
        self.db = db

    # ---------------- plans ----------------

    async def save_plan(
        self,
        *,
        run_id: int,
        plan_date: str,
        full_text: str,
        reflection: str = "",
        day_reminders: str = "",
    ) -> int:
        """写入规划书；同一天重复提交时覆盖。"""
        await self.db.execute(
            "INSERT INTO plans(run_id, plan_date, full_text, reflection, day_reminders, created_at)"
            " VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(plan_date) DO UPDATE SET run_id=excluded.run_id,"
            " full_text=excluded.full_text, reflection=excluded.reflection,"
            " day_reminders=excluded.day_reminders, updated_at=excluded.created_at,"
            " deleted_at=NULL, deleted_reason=''",
            (run_id, plan_date, full_text, reflection, day_reminders, utc_now()),
        )
        row = await self.db.fetchone(
            "SELECT id FROM plans WHERE plan_date=?", (plan_date,)
        )
        return int(row["id"])

    async def save_sections(self, plan_id: int, sections: dict[str, str]) -> None:
        """保存按会话切分的段落（先清旧）。"""
        await self.db.execute("DELETE FROM plan_sections WHERE plan_id=?", (plan_id,))
        await self.db.executemany(
            "INSERT INTO plan_sections(plan_id, umo, text) VALUES(?,?,?)",
            [(plan_id, umo, text) for umo, text in sections.items()],
        )

    async def get_plan_by_date(self, plan_date: str) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM plans WHERE plan_date=? AND deleted_at IS NULL", (plan_date,)
        )

    async def update_plan_field(self, plan_id: int, field: str, text: str) -> bool:
        """只更新最近规划中指定的正文或白天提醒，不触碰夜间反思。"""
        if field not in ("full_text", "day_reminders"):
            raise ValueError("field 只能是 full_text / day_reminders")
        cur = await self.db.execute(
            f"UPDATE plans SET {field}=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (text, utc_now(), plan_id),
        )
        return bool(cur.rowcount)

    async def update_section(self, plan_id: int, umo: str, text: str) -> None:
        """仅更新一个会话段落，没有时插入；其他会话的段落保持原值。"""
        cur = await self.db.execute(
            "UPDATE plan_sections SET text=? WHERE plan_id=? AND umo=?"
            " AND EXISTS (SELECT 1 FROM plans WHERE id=? AND deleted_at IS NULL)",
            (text, plan_id, umo, plan_id),
        )
        if not cur.rowcount:
            await self.db.execute(
                "INSERT INTO plan_sections(plan_id, umo, text)"
                " SELECT id, ?, ? FROM plans WHERE id=? AND deleted_at IS NULL"
                " AND NOT EXISTS (SELECT 1 FROM plan_sections WHERE plan_id=? AND umo=?)",
                (umo, text, plan_id, plan_id, umo),
            )
        await self.db.execute(
            "UPDATE plans SET updated_at=? WHERE id=? AND deleted_at IS NULL",
            (utc_now(), plan_id),
        )

    async def get_latest_plan(self) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM plans WHERE deleted_at IS NULL ORDER BY created_at DESC,id DESC LIMIT 1"
        )

    async def list_plans(
        self, limit: int = 30, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT id, run_id, plan_date, reflection, created_at,"
            " length(full_text) AS text_len FROM plans WHERE deleted_at IS NULL"
            " ORDER BY plan_date DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    async def list_plan_details(self, limit: int) -> list[dict[str, Any]]:
        """查看页：最近几份规划书的全文、反思、白天提醒与按会话段落。"""
        rows = await self.db.fetchall(
            "SELECT id, run_id, plan_date, full_text, reflection, day_reminders,"
            " created_at, updated_at FROM plans WHERE deleted_at IS NULL"
            " ORDER BY plan_date DESC LIMIT ?",
            (limit,),
        )
        plans = []
        for row in rows:
            plan = dict(row)
            plan["sections"] = await self.get_sections(plan["id"])
            plans.append(plan)
        return plans

    async def get_sections(self, plan_id: int) -> dict[str, str]:
        rows = await self.db.fetchall(
            "SELECT s.umo,s.text FROM plan_sections s JOIN plans p ON p.id=s.plan_id"
            " WHERE s.plan_id=? AND p.deleted_at IS NULL",
            (plan_id,),
        )
        return {r["umo"]: r["text"] for r in rows}

    async def get_section_for_umo(self, umo: str) -> str:
        """取最新一份规划书中属于该会话的段落。"""
        plan = await self.get_latest_plan()
        if not plan:
            return ""
        row = await self.db.fetchone(
            "SELECT s.text FROM plan_sections s JOIN plans p ON p.id=s.plan_id"
            " WHERE s.plan_id=? AND s.umo=? AND p.deleted_at IS NULL",
            (plan["id"], umo),
        )
        return row["text"] if row else ""

    # ---------------- todos ----------------

    async def add_todo(
        self,
        *,
        content: str,
        visible_umos: list[str],
        secret_from: list[str] | None = None,
        due_kind: str = "today",
        due_date: str = "",
        show_from: str = "",
        note: str = "",
        evidence: list | None = None,
        alarm_id: int | None = None,
        created_run_id: int | None = None,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO todos(content, visible_umos_json, secret_from_json, due_kind,
                due_date, show_from, status, note, evidence_json, alarm_id,
                created_run_id, updated_at)
            VALUES(?,?,?,?,?,?, 'open', ?,?,?,?,?)
            """,
            (
                content,
                json.dumps(visible_umos, ensure_ascii=False),
                json.dumps(secret_from or [], ensure_ascii=False),
                due_kind,
                due_date,
                show_from,
                note,
                json.dumps(evidence or [], ensure_ascii=False),
                alarm_id,
                created_run_id,
                utc_now(),
            ),
        )
        return int(cur.lastrowid)

    async def update_todo_status(
        self, todo_id: int, status: str, note: str = ""
    ) -> bool:
        cur = await self.db.execute(
            "UPDATE todos SET status=?, note=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (status, note, utc_now(), todo_id),
        )
        return bool(cur.rowcount)

    async def get_todo(self, todo_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM todos WHERE id=? AND deleted_at IS NULL", (todo_id,)
        )

    async def update_todo_fields(self, todo_id: int, **fields: Any) -> bool:
        """只写传入的可编辑字段，并刷新更新时间。"""
        columns = {
            "content": "content",
            "visible_umos": "visible_umos_json",
            "secret_from": "secret_from_json",
            "due_kind": "due_kind",
            "due_date": "due_date",
            "show_from": "show_from",
            "note": "note",
        }
        if not fields:
            return False
        assignments, values = [], []
        for field, value in fields.items():
            column = columns[field]
            assignments.append(f"{column}=?")
            values.append(
                json.dumps(value, ensure_ascii=False)
                if field in ("visible_umos", "secret_from") else value
            )
        cur = await self.db.execute(
            f"UPDATE todos SET {', '.join(assignments)}, updated_at=?"
            " WHERE id=? AND deleted_at IS NULL",
            (*values, utc_now(), todo_id),
        )
        return bool(cur.rowcount)

    async def open_todos(self) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM todos WHERE deleted_at IS NULL"
            " AND status IN ('open','progress') ORDER BY id ASC"
        )

    async def visible_todos(self, umo: str, today: str) -> list[dict[str, Any]]:
        """取某会话当前可见的待办：今天的、逾期的、已到 show_from 的未来待办。

        「可见」指 visible_umos_json 包含该 umo；show_from 为空视为今天起可见。
        """
        rows = await self.open_todos()
        out: list[dict[str, Any]] = []
        for r in rows:
            visible = json.loads(r["visible_umos_json"] or "[]")
            if umo not in visible:
                continue
            show_from = r["show_from"] or r["due_date"] or today
            due_kind = r["due_kind"]
            due_date = r["due_date"] or today
            is_today = due_kind == "today" and due_date <= today
            is_overdue = due_kind == "deadline" and due_date <= today
            is_future_shown = show_from <= today
            if is_today or is_overdue or is_future_shown:
                out.append(r)
        return out

    async def list_todos(
        self, limit: int = 200, *, status="all", offset=0
    ) -> list[dict[str, Any]]:
        where, params = self._status_filter("todo", status)
        return await self.db.fetchall(
            f"SELECT * FROM todos WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )

    # ---------------- promises ----------------

    async def add_promise(
        self,
        *,
        from_id: str,
        to_id: str,
        content: str,
        evidence: list | None = None,
        due_date: str = "",
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO promises(from_id, to_id, content, evidence_json, due_date, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                from_id,
                to_id,
                content,
                json.dumps(evidence or [], ensure_ascii=False),
                due_date,
                utc_now(),
                utc_now(),
            ),
        )
        return int(cur.lastrowid)

    async def update_promise_status(self, promise_id: int, status: str) -> bool:
        cur = await self.db.execute(
            "UPDATE promises SET status=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
            (status, utc_now(), promise_id),
        )
        return bool(cur.rowcount)

    async def open_promises(self) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM promises WHERE deleted_at IS NULL AND status='open' ORDER BY id ASC"
        )

    async def list_promises(
        self, limit: int = 200, *, status="all", offset=0
    ) -> list[dict[str, Any]]:
        where, params = self._status_filter("promise", status)
        return await self.db.fetchall(
            f"SELECT * FROM promises WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )

    @staticmethod
    def _status_filter(kind, status):
        allowed = {
            "todo": ("open", "done", "dropped", "all"),
            "promise": ("open", "done", "broken", "waived", "all"),
        }
        if status not in allowed[kind]:
            raise ValueError("status 只能是 " + " / ".join(allowed[kind]))
        where, params = "deleted_at IS NULL", ()
        if status == "open" and kind == "todo":
            where += " AND status IN ('open','progress')"
        elif status != "all":
            where += " AND status=?"
            params = (status,)
        return where, params

    async def count_entries(self, kind, status="all"):
        if kind == "plan":
            table, where, params = "plans", "deleted_at IS NULL", ()
        else:
            table = {"todo": "todos", "promise": "promises"}[kind]
            where, params = self._status_filter(kind, status)
        row = await self.db.fetchone(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params
        )
        return row["n"]
