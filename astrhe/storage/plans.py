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
            " day_reminders=excluded.day_reminders, created_at=excluded.created_at",
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
            "SELECT * FROM plans WHERE plan_date=?", (plan_date,)
        )

    async def get_latest_plan(self) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM plans ORDER BY created_at DESC LIMIT 1"
        )

    async def list_plans(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT id, run_id, plan_date, reflection, created_at,"
            " length(full_text) AS text_len FROM plans ORDER BY plan_date DESC LIMIT ?",
            (limit,),
        )

    async def get_sections(self, plan_id: int) -> dict[str, str]:
        rows = await self.db.fetchall(
            "SELECT umo, text FROM plan_sections WHERE plan_id=?", (plan_id,)
        )
        return {r["umo"]: r["text"] for r in rows}

    async def get_section_for_umo(self, umo: str) -> str:
        """取最新一份规划书中属于该会话的段落。"""
        plan = await self.get_latest_plan()
        if not plan:
            return ""
        row = await self.db.fetchone(
            "SELECT text FROM plan_sections WHERE plan_id=? AND umo=?",
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
            "UPDATE todos SET status=?, note=?, updated_at=? WHERE id=?",
            (status, note, utc_now(), todo_id),
        )
        return bool(cur.rowcount)

    async def get_todo(self, todo_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM todos WHERE id=?", (todo_id,))

    async def open_todos(self) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM todos WHERE status IN ('open','progress') ORDER BY id ASC"
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

    async def list_todos(self, limit: int = 200) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM todos ORDER BY updated_at DESC LIMIT ?", (limit,)
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
            "INSERT INTO promises(from_id, to_id, content, evidence_json, due_date)"
            " VALUES(?,?,?,?,?)",
            (
                from_id,
                to_id,
                content,
                json.dumps(evidence or [], ensure_ascii=False),
                due_date,
            ),
        )
        return int(cur.lastrowid)

    async def update_promise_status(self, promise_id: int, status: str) -> bool:
        cur = await self.db.execute(
            "UPDATE promises SET status=? WHERE id=?", (status, promise_id)
        )
        return bool(cur.rowcount)

    async def open_promises(self) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM promises WHERE status='open' ORDER BY id ASC"
        )

    async def list_promises(self, limit: int = 200) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM promises ORDER BY id DESC LIMIT ?", (limit,)
        )
