"""聊天账本仓库：messages / notices / friend_requests / action_log。"""

from __future__ import annotations

import json
from typing import Any

from .db import Database


class LedgerRepo:
    """消息、通知、好友申请与动作日志的读写。"""

    def __init__(self, db: Database):
        self.db = db

    # ---------------- messages ----------------

    async def add_message(
        self,
        *,
        umo: str,
        platform_id: str,
        message_type: str,
        session_id: str,
        sender_id: str,
        sender_name: str = "",
        sender_card: str = "",
        text: str = "",
        ts: float,
        platform_message_id: str | None = None,
        is_bot: bool = False,
        source: str = "live",
    ) -> int | None:
        """写入一条消息；platform_message_id 冲突（非空）时忽略，返回行 id 或 None。"""
        cur = await self.db.execute(
            """
            INSERT OR IGNORE INTO messages(
                umo, platform_id, message_type, session_id, platform_message_id,
                sender_id, sender_name, sender_card, text, ts, is_bot, source
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                umo,
                platform_id,
                message_type,
                session_id,
                platform_message_id or None,
                sender_id,
                sender_name,
                sender_card,
                text,
                ts,
                1 if is_bot else 0,
                source,
            ),
        )
        if cur.lastrowid and cur.rowcount:
            return int(cur.lastrowid)
        return None

    async def find_bot_temp_messages(
        self, umo: str, since_ts: float
    ) -> list[dict[str, Any]]:
        """查某会话中 platform_message_id 为空的 bot 临时记录（供补拉合并）。"""
        return await self.db.fetchall(
            """
            SELECT * FROM messages
            WHERE umo=? AND is_bot=1
              AND (platform_message_id IS NULL OR platform_message_id='')
              AND ts>=?
            ORDER BY ts ASC
            """,
            (umo, since_ts),
        )

    async def bot_self_id(self) -> str:
        """账本里最近一条 bot 消息的发送者 QQ；没有时返回空串。"""
        row = await self.db.fetchone(
            "SELECT sender_id FROM messages WHERE is_bot=1 AND sender_id!=''"
            " AND sender_id NOT GLOB '*[^0-9]*' ORDER BY id DESC LIMIT 1"
        )
        return str(row["sender_id"]) if row else ""

    async def remove_bot_temps(self, umo: str, start: float, end: float) -> int:
        """仅在历史完整覆盖窗口后，用平台消息替换无 id 的临时回复。"""
        cur = await self.db.execute(
            "DELETE FROM messages WHERE umo=? AND is_bot=1 AND ts>=? AND ts<=?"
            " AND (platform_message_id IS NULL OR platform_message_id='')",
            (umo, start, end),
        )
        return cur.rowcount

    async def attach_platform_id(self, row_id: int, platform_message_id: str) -> None:
        """给 bot 临时记录补上平台 message_id（合并时）。"""
        await self.db.execute(
            "UPDATE messages SET platform_message_id=?, source='live+backfill' WHERE id=?",
            (platform_message_id, row_id),
        )

    async def mark_recalled(self, umo: str, platform_message_id: str) -> None:
        await self.db.execute(
            "UPDATE messages SET recalled=1 WHERE umo=? AND platform_message_id=?",
            (umo, platform_message_id),
        )

    async def mark_recalled_any(self, platform_message_id: str) -> None:
        """撤回事件拿不到会话时的兜底：按 message_id 全局标记。"""
        await self.db.execute(
            "UPDATE messages SET recalled=1 WHERE platform_message_id=?",
            (platform_message_id,),
        )

    async def list_session_umos(self, since_ts: float) -> list[str]:
        """窗口内有消息记录的会话 UMO 列表。"""
        rows = await self.db.fetchall(
            "SELECT umo FROM messages WHERE ts>=? UNION SELECT umo FROM notices WHERE ts>=? ORDER BY umo",
            (since_ts, since_ts),
        )
        return [r["umo"] for r in rows]

    async def get_messages(
        self,
        umo: str,
        start_ts: float,
        end_ts: float,
        *,
        include_recalled: bool = False,
    ) -> list[dict[str, Any]]:
        """按时间窗口读某会话消息；默认排除已撤回。"""
        sql = (
            "SELECT * FROM messages WHERE umo=? AND ts>=? AND ts<?"
            + ("" if include_recalled else " AND recalled=0")
            + " ORDER BY ts ASC, id ASC"
        )
        return await self.db.fetchall(sql, (umo, start_ts, end_ts))

    async def get_messages_page(
        self, umo: str, *, before_row_id: int | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """分页读某会话消息（排除已撤回），返回从旧到新排列的一页。"""
        if before_row_id is None:
            rows = await self.db.fetchall(
                "SELECT * FROM messages WHERE umo=? AND recalled=0"
                " ORDER BY id DESC LIMIT ?",
                (umo, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM messages WHERE umo=? AND recalled=0 AND id<?"
                " ORDER BY id DESC LIMIT ?",
                (umo, before_row_id, limit),
            )
        return list(reversed(rows))

    async def search_messages(
        self,
        keyword: str,
        since_ts: float,
        *,
        umo: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """关键词搜索（排除已撤回）。since_ts=0 表示搜全部账本。"""
        like = f"%{keyword}%"
        if umo:
            return await self.db.fetchall(
                "SELECT * FROM messages WHERE umo=? AND ts>=? AND recalled=0 "
                "AND text LIKE ? ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                (umo, since_ts, like, limit, offset),
            )
        return await self.db.fetchall(
            "SELECT * FROM messages WHERE ts>=? AND recalled=0 "
            "AND text LIKE ? ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
            (since_ts, like, limit, offset),
        )

    async def get_message_by_platform_id(
        self, platform_message_id: str
    ) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM messages WHERE platform_message_id=? ORDER BY id DESC LIMIT 1",
            (platform_message_id,),
        )

    async def get_message_context(
        self, umo: str, center_ts: float, radius: int = 10
    ) -> list[dict[str, Any]]:
        """取某时间点前后的上下文消息。"""
        before = await self.db.fetchall(
            "SELECT * FROM messages WHERE umo=? AND ts<? AND recalled=0 "
            "ORDER BY ts DESC LIMIT ?",
            (umo, center_ts, radius),
        )
        after = await self.db.fetchall(
            "SELECT * FROM messages WHERE umo=? AND ts>=? AND recalled=0 "
            "ORDER BY ts ASC LIMIT ?",
            (umo, center_ts, radius),
        )
        return list(reversed(before)) + after

    async def speaker_ids_since(self, umo: str, since_ts: float) -> set[str]:
        """近 N 天内在该会话发言过的人（保密「在场」判定用）。"""
        rows = await self.db.fetchall(
            "SELECT DISTINCT sender_id FROM messages WHERE umo=? AND ts>=? AND is_bot=0",
            (umo, since_ts),
        )
        return {r["sender_id"] for r in rows}

    async def max_message_ts(self) -> float | None:
        row = await self.db.fetchone("SELECT MAX(ts) AS m FROM messages")
        return row["m"] if row and row["m"] is not None else None

    async def cleanup(self, older_than_ts: float) -> tuple[int, int]:
        """清理超过保留期的消息、通知和好友申请，返回消息与通知删除条数。"""
        cur1 = await self.db.execute(
            "DELETE FROM messages WHERE ts<?", (older_than_ts,)
        )
        cur2 = await self.db.execute("DELETE FROM notices WHERE ts<?", (older_than_ts,))
        await self.db.execute(
            "DELETE FROM friend_requests WHERE ts<?", (older_than_ts,)
        )
        return (cur1.rowcount or 0, cur2.rowcount or 0)

    # ---------------- notices ----------------

    async def add_notice(
        self,
        *,
        umo: str,
        kind: str,
        actor_id: str = "",
        target_id: str = "",
        message_id: str = "",
        detail: dict[str, Any] | None = None,
        ts: float,
    ) -> None:
        await self.db.execute(
            "INSERT INTO notices(umo, kind, actor_id, target_id, message_id, detail_json, ts)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                umo,
                kind,
                actor_id,
                target_id,
                message_id,
                json.dumps(detail or {}, ensure_ascii=False),
                ts,
            ),
        )

    async def get_notices(
        self, umo: str, start_ts: float, end_ts: float
    ) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM notices WHERE umo=? AND ts>=? AND ts<? ORDER BY ts ASC",
            (umo, start_ts, end_ts),
        )

    # ---------------- friend_requests ----------------

    async def add_friend_request(
        self,
        *,
        user_id: str,
        flag: str,
        comment: str = "",
        source: str = "normal",
        ts: float,
    ) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO friend_requests(user_id, flag, comment, source, ts)"
            " VALUES(?,?,?,?,?)",
            (user_id, flag, comment, source, ts),
        )

    async def pending_friend_requests(self) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM friend_requests WHERE status='pending' ORDER BY ts ASC"
        )

    async def set_friend_request_status(self, flag: str, status: str) -> None:
        await self.db.execute(
            "UPDATE friend_requests SET status=? WHERE flag=?", (status, flag)
        )

    # ---------------- action_log ----------------

    async def log_action(self, action: str, target: str = "", umo: str = "") -> None:
        from ..timeutil import utc_now

        await self.db.execute(
            "INSERT INTO action_log(action, target, umo, ts) VALUES(?,?,?,?)",
            (action, target, umo, utc_now()),
        )

    async def count_actions(
        self, action: str, since_ts: float, *, target: str = "", umo: str = ""
    ) -> int:
        """统计某动作在 since_ts 之后的次数，可按 target / umo 过滤。"""
        sql = "SELECT COUNT(*) AS c FROM action_log WHERE action=? AND ts>=?"
        params: list[Any] = [action, since_ts]
        if target:
            sql += " AND target=?"
            params.append(target)
        if umo:
            sql += " AND umo=?"
            params.append(umo)
        row = await self.db.fetchone(sql, tuple(params))
        return int(row["c"]) if row else 0

    async def last_action(self, action: str) -> dict[str, Any] | None:
        """某动作最近一次记录（target 与 ts）；没有记录返回 None。"""
        return await self.db.fetchone(
            "SELECT target, ts FROM action_log WHERE action=? ORDER BY ts DESC LIMIT 1",
            (action,),
        )

    async def distinct_action_targets(self, action: str, since_ts: float) -> set[str]:
        rows = await self.db.fetchall(
            "SELECT DISTINCT target FROM action_log WHERE action=? AND ts>=?",
            (action, since_ts),
        )
        return {r["target"] for r in rows}
