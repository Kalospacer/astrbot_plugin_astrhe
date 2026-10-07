"""关系本仓库：persons 表。一律按 QQ 号认人。"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import utc_now
from .db import Database


class PersonsRepo:
    def __init__(self, db: Database):
        self.db = db

    async def upsert_person(
        self,
        qq: str,
        *,
        aliases: list[str] | None = None,
        relation_text: str | None = None,
        recent_text: str | None = None,
        anniversaries: list[dict] | None = None,
        evidence: str | None = None,
        merge_aliases: bool = True,
    ) -> None:
        """更新关系本条目；None 的字段不动。别名默认与已有别名合并去重。"""
        existing = await self.get_person(qq)
        now = utc_now()
        if existing is None:
            await self.db.execute(
                "INSERT INTO persons(qq, aliases_json, relation_text, recent_text,"
                " anniversaries_json, updated_at, evidence) VALUES(?,?,?,?,?,?,?)",
                (
                    qq,
                    json.dumps(aliases or [], ensure_ascii=False),
                    relation_text or "",
                    recent_text or "",
                    json.dumps(anniversaries or [], ensure_ascii=False),
                    now,
                    evidence or "",
                ),
            )
            return
        if aliases is None:
            merged_aliases = json.loads(existing["aliases_json"] or "[]")
        elif merge_aliases:
            old = json.loads(existing["aliases_json"] or "[]")
            merged_aliases = list(dict.fromkeys(old + aliases))
        else:
            merged_aliases = aliases
        await self.db.execute(
            "UPDATE persons SET aliases_json=?, relation_text=?, recent_text=?,"
            " anniversaries_json=?, updated_at=?, evidence=? WHERE qq=?",
            (
                json.dumps(merged_aliases, ensure_ascii=False),
                relation_text if relation_text is not None else existing["relation_text"],
                recent_text if recent_text is not None else existing["recent_text"],
                json.dumps(anniversaries, ensure_ascii=False)
                if anniversaries is not None
                else existing["anniversaries_json"],
                now,
                evidence if evidence is not None else existing["evidence"],
                qq,
            ),
        )

    async def get_person(self, qq: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM persons WHERE qq=?", (qq,))

    async def find_by_alias(self, name: str) -> dict[str, Any] | None:
        """按别名模糊查找（LIKE，供工具按昵称找人）。"""
        rows = await self.db.fetchall("SELECT * FROM persons")
        for r in rows:
            aliases = json.loads(r["aliases_json"] or "[]")
            if name in aliases or any(name in a or a in name for a in aliases if a):
                return r
        return None

    async def list_persons(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM persons ORDER BY updated_at DESC")

    async def anniversary_persons(self) -> list[dict[str, Any]]:
        """有纪念日记录的人（夜间由主 agent 做 14 天前瞻）。"""
        rows = await self.db.fetchall(
            "SELECT * FROM persons WHERE anniversaries_json != '[]'"
        )
        return rows

    # ---------------- 预期联系人 ----------------

    async def set_expected_friend(
        self, qq: str, until_ts: float, reason: str = ""
    ) -> None:
        """把某人标记为预期联系人（自动同意其好友申请）。"""
        existing = await self.get_person(qq)
        if existing is None:
            await self.upsert_person(qq)
        await self.db.execute(
            "UPDATE persons SET expected_friend_until=?, expected_reason=? WHERE qq=?",
            (until_ts, reason, qq),
        )

    async def is_expected_friend(self, qq: str, now_ts: float) -> bool:
        row = await self.db.fetchone(
            "SELECT expected_friend_until FROM persons WHERE qq=?", (qq,)
        )
        if not row or row["expected_friend_until"] is None:
            return False
        return float(row["expected_friend_until"]) > now_ts

    async def expected_friends(self, now_ts: float) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM persons WHERE expected_friend_until IS NOT NULL"
            " AND expected_friend_until > ?",
            (now_ts,),
        )

    async def clear_expected_friend(self, qq: str) -> None:
        await self.db.execute(
            "UPDATE persons SET expected_friend_until=NULL, expected_reason=''"
            " WHERE qq=?",
            (qq,),
        )
