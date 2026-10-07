"""运行记录仓库：runs / reports / drafts / reviews。"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import utc_now
from .db import Database


class RunsRepo:
    def __init__(self, db: Database):
        self.db = db

    # ---------------- runs ----------------

    async def start_run(
        self,
        *,
        plan_date: str,
        mode: str = "auto",
        window_start: float | None = None,
        window_end: float | None = None,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO runs(started_at, window_start, window_end, plan_date, mode,"
            " status) VALUES(?,?,?,?,?, 'running')",
            (utc_now(), window_start, window_end, plan_date, mode),
        )
        return int(cur.lastrowid)

    async def finish_run(
        self,
        run_id: int,
        status: str,
        *,
        error: str = "",
        stats: dict[str, Any] | None = None,
    ) -> None:
        await self.db.execute(
            "UPDATE runs SET ended_at=?, status=?, error=?, stats_json=? WHERE id=?",
            (utc_now(), status, error, json.dumps(stats or {}, ensure_ascii=False), run_id),
        )

    async def update_run_stats(self, run_id: int, stats: dict[str, Any]) -> None:
        await self.db.execute(
            "UPDATE runs SET stats_json=? WHERE id=?",
            (json.dumps(stats, ensure_ascii=False), run_id),
        )

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM runs WHERE id=?", (run_id,))

    async def latest_run(self) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
        )

    async def latest_committed_run(self) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM runs WHERE status='committed' ORDER BY id DESC LIMIT 1"
        )

    async def running_runs(self) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM runs WHERE status='running' ORDER BY id ASC"
        )

    async def list_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        )

    # ---------------- reports ----------------

    async def add_report(
        self,
        *,
        run_id: int,
        umo: str,
        chunk_index: int,
        content: dict[str, Any] | None,
        raw_text: str,
    ) -> None:
        await self.db.execute(
            "INSERT INTO reports(run_id, umo, chunk_index, content_json, raw_text)"
            " VALUES(?,?,?,?,?)",
            (run_id, umo, chunk_index, json.dumps(content or {}, ensure_ascii=False), raw_text),
        )

    async def get_reports(self, run_id: int) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM reports WHERE run_id=? ORDER BY umo, chunk_index",
            (run_id,),
        )

    # ---------------- drafts ----------------

    async def add_draft(
        self, *, run_id: int, kind: str, payload: dict[str, Any], seq: int
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO drafts(run_id, kind, payload_json, seq) VALUES(?,?,?,?)",
            (run_id, kind, json.dumps(payload, ensure_ascii=False), seq),
        )
        return int(cur.lastrowid)

    async def get_drafts(self, run_id: int) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM drafts WHERE run_id=? ORDER BY seq ASC", (run_id,)
        )

    async def mark_drafts_applied(self, run_id: int) -> None:
        await self.db.execute(
            "UPDATE drafts SET applied=1 WHERE run_id=?", (run_id,)
        )

    # ---------------- reviews ----------------

    async def add_review(
        self, *, run_id: int, focus: str, result_text: str, status: str = "ok"
    ) -> None:
        await self.db.execute(
            "INSERT INTO reviews(run_id, focus, result_text, status) VALUES(?,?,?,?)",
            (run_id, focus, result_text, status),
        )

    async def count_ok_reviews(self, run_id: int) -> int:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS c FROM reviews WHERE run_id=? AND status='ok'",
            (run_id,),
        )
        return int(row["c"]) if row else 0

    async def get_reviews(self, run_id: int) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM reviews WHERE run_id=? ORDER BY id ASC", (run_id,)
        )
