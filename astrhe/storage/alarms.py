"""闹钟卡片仓库：alarms 表。"""

from __future__ import annotations

import json
from typing import Any

from .db import Database
from ..timeutil import utc_now


class AlarmsRepo:
    def __init__(self, db: Database):
        self.db = db

    async def add_alarm(
        self,
        *,
        cron_job_id: str = "",
        target_umo: str,
        creator_id: str = "",
        origin: str = "night",
        run_at: float | None = None,
        cron_expression: str = "",
        card: dict[str, Any] | None = None,
        note_text: str = "",
        created_run_id: int | None = None,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO alarms(cron_job_id, target_umo, creator_id, origin, run_at,
                cron_expression, card_json, note_text, status, created_run_id,
                created_at)
            VALUES(?,?,?,?,?,?,?,?, 'scheduled', ?, ?)
            """,
            (
                cron_job_id,
                target_umo,
                creator_id,
                origin,
                run_at,
                cron_expression,
                json.dumps(card or {}, ensure_ascii=False),
                note_text,
                created_run_id,
                utc_now(),
            ),
        )
        return int(cur.lastrowid)

    async def bind_cron_job(self, alarm_id: int, cron_job_id: str) -> None:
        await self.db.execute(
            "UPDATE alarms SET cron_job_id=? WHERE id=?", (cron_job_id, alarm_id)
        )

    async def set_status(
        self, alarm_id: int, status: str, result_note: str | None = None
    ) -> None:
        await self.db.execute(
            "UPDATE alarms SET status=?, result_note=COALESCE(?, result_note) WHERE id=?",
            (status, result_note, alarm_id),
        )

    async def set_status_by_job(
        self, cron_job_id: str, status: str, result_note: str | None = None
    ) -> None:
        await self.db.execute(
            "UPDATE alarms SET status=?, result_note=COALESCE(?, result_note) WHERE cron_job_id=?",
            (status, result_note, cron_job_id),
        )

    async def get_alarm(self, alarm_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM alarms WHERE id=?", (alarm_id,))

    async def get_by_job(self, cron_job_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM alarms WHERE cron_job_id=?", (cron_job_id,)
        )

    async def get_by_alarm_id_str(self, astrhe_alarm_id: str) -> dict[str, Any] | None:
        """cron payload 里的 astrhe_alarm_id 即 alarms.id 的字符串形式。"""
        try:
            alarm_id = int(astrhe_alarm_id)
        except (TypeError, ValueError):
            return None
        return await self.get_alarm(alarm_id)

    async def active_alarms(self) -> list[dict[str, Any]]:
        """仍在等待执行或执行中的闹钟（对账与注入用）。"""
        return await self.db.fetchall(
            "SELECT * FROM alarms WHERE status IN"
            " ('scheduled','fired') OR (cron_expression!='' AND status='done') ORDER BY id ASC"
        )

    async def list_alarms(self, limit: int = 200) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM alarms ORDER BY id DESC LIMIT ?", (limit,)
        )

    async def count_created_since(
        self,
        since_ts: float,
        *,
        origin: str = "",
        target_umo: str = "",
        creator_id: str = "",
    ) -> int:
        """频率上限统计：since_ts 之后创建且未取消的闹钟数量。"""
        sql = (
            "SELECT COUNT(*) AS c FROM alarms"
            " WHERE created_at>=? AND status NOT IN ('cancelled')"
        )
        params: list[Any] = [since_ts]
        if origin:
            sql += " AND origin=?"
            params.append(origin)
        if target_umo:
            sql += " AND target_umo=?"
            params.append(target_umo)
        if creator_id:
            sql += " AND creator_id=?"
            params.append(creator_id)
        row = await self.db.fetchone(sql, tuple(params))
        return int(row["c"]) if row else 0

    async def add_event(
        self, alarm_id: int, kind: str, detail: str = "", ts=None
    ) -> None:
        await self.db.execute(
            "INSERT INTO alarm_events(alarm_id,ts,kind,detail) VALUES(?,?,?,?)",
            (alarm_id, utc_now() if ts is None else ts, kind, detail),
        )

    async def events(
        self, alarm_id: int, start: float = 0, end: float = 1e20
    ) -> list[dict]:
        return await self.db.fetchall(
            "SELECT * FROM alarm_events WHERE alarm_id=? AND ts>=? AND ts<=? ORDER BY ts,id",
            (alarm_id, start, end),
        )
