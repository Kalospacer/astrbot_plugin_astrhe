"""草稿箱提交：事务写库 + 外部动作收尾。

提交点：先在一个数据库事务里写入规划书、段落、待办、关系本、承诺。
事务成功，这次运行就算已提交（committed）。
之后的外部动作（建或删定时任务、改签名或状态）用 asyncio.shield 包住，
不受运行取消的影响；每条记录成功或失败，失败的留给下一晚处理。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from .. import constants as C
from ..timeutil import is_quiet_time, parse_run_at, utc_now
from ..tools.schedule_tool import render_card_note


class CommitError(Exception):
    """提交被拒绝（缺规划书 / 缺审稿等）。"""


class DraftCommitter:
    def __init__(
        self,
        storage: Any,
        context: Any,
        run_id: int,
        plan_date: str,
        tz: Any,
        rate_limiter: Any = None,
    ):
        self.storage = storage
        self.context = context
        self.run_id = run_id
        self.plan_date = plan_date
        self.tz = tz
        self.rate_limiter = rate_limiter

    async def validate(self) -> None:
        """提交前校验；不通过抛 CommitError。"""
        drafts = await self.storage.runs.get_drafts(self.run_id)
        if not any(d["kind"] == "plan" for d in drafts):
            raise CommitError("草稿箱里没有规划书，不能提交")
        ok_reviews = await self.storage.runs.count_ok_reviews(self.run_id)
        if ok_reviews < C.REVIEW_MIN_OK:
            raise CommitError("还没有成功完成过审稿，不能提交；先用 astrhe_request_review")

    async def commit_db(self) -> dict[str, Any]:
        """在一个事务里应用全部数据库草稿，返回统计。"""
        drafts = await self.storage.runs.get_drafts(self.run_id)
        stats: dict[str, Any] = {
            "plan": 0, "sections": 0, "todos": 0, "todo_drops": 0,
            "persons": 0, "promises": 0,
        }
        db = self.storage.db
        now = utc_now()
        async with db.write_lock:
            try:
                await db.conn.execute("BEGIN")
                for d in drafts:
                    kind = d["kind"]
                    payload = json.loads(d["payload_json"] or "{}")
                    if kind == "plan":
                        await db.conn.execute(
                            "INSERT INTO plans(run_id, plan_date, full_text, reflection,"
                            " created_at) VALUES(?,?,?,?,?) "
                            "ON CONFLICT(plan_date) DO UPDATE SET run_id=excluded.run_id,"
                            " full_text=excluded.full_text, reflection=excluded.reflection,"
                            " created_at=excluded.created_at",
                            (self.run_id, self.plan_date, payload.get("full_text", ""),
                             payload.get("reflection", ""), now),
                        )
                        stats["plan"] = 1
                    elif kind == "sections":
                        row = await db.conn.execute(
                            "SELECT id FROM plans WHERE plan_date=?", (self.plan_date,)
                        )
                        plan_row = await row.fetchone()
                        if plan_row:
                            plan_id = plan_row[0]
                            await db.conn.execute(
                                "DELETE FROM plan_sections WHERE plan_id=?", (plan_id,)
                            )
                            for umo, text in (payload.get("sections") or {}).items():
                                await db.conn.execute(
                                    "INSERT INTO plan_sections(plan_id, umo, text)"
                                    " VALUES(?,?,?)",
                                    (plan_id, umo, text),
                                )
                                stats["sections"] += 1
                    elif kind == "todo":
                        await db.conn.execute(
                            "INSERT INTO todos(content, visible_umos_json,"
                            " secret_from_json, due_kind, due_date, show_from, status,"
                            " note, evidence_json, created_run_id, updated_at)"
                            " VALUES(?,?,?,?,?,?, 'open', '', ?, ?, ?)",
                            (
                                payload.get("content", ""),
                                json.dumps(payload.get("visible_umos") or [], ensure_ascii=False),
                                json.dumps(payload.get("secret_from") or [], ensure_ascii=False),
                                payload.get("due_kind", "today"),
                                payload.get("due_date", ""),
                                payload.get("show_from", ""),
                                json.dumps(payload.get("evidence") or [], ensure_ascii=False),
                                self.run_id,
                                now,
                            ),
                        )
                        stats["todos"] += 1
                    elif kind == "todo_drop":
                        await db.conn.execute(
                            "UPDATE todos SET status='dropped', note=?, updated_at=?"
                            " WHERE id=?",
                            (f"夜间删除：{payload.get('reason', '')}", now,
                             int(payload.get("todo_id", 0))),
                        )
                        stats["todo_drops"] += 1
                    elif kind == "person":
                        await self._apply_person(db, payload, now)
                        stats["persons"] += 1
                    elif kind == "promise":
                        await self._apply_promise(db, payload)
                        stats["promises"] += 1
                await db.conn.execute(
                    "UPDATE drafts SET applied=1 WHERE run_id=?", (self.run_id,)
                )
                await db.conn.commit()
            except Exception:
                await db.conn.rollback()
                raise
        return stats

    async def _apply_person(self, db: Any, payload: dict, now: float) -> None:
        qq = str(payload.get("qq", ""))
        if not qq:
            return
        existing = await self.storage.persons.get_person(qq)
        aliases = payload.get("aliases")
        if existing is None:
            await db.conn.execute(
                "INSERT INTO persons(qq, aliases_json, relation_text, recent_text,"
                " anniversaries_json, updated_at) VALUES(?,?,?,?,?,?)",
                (
                    qq,
                    json.dumps(aliases or [], ensure_ascii=False),
                    payload.get("relation_text", ""),
                    payload.get("recent_text", ""),
                    json.dumps(payload.get("anniversaries") or [], ensure_ascii=False),
                    now,
                ),
            )
        else:
            if aliases is None:
                merged = json.loads(existing["aliases_json"] or "[]")
            else:
                merged = list(dict.fromkeys(json.loads(existing["aliases_json"] or "[]") + aliases))
            await db.conn.execute(
                "UPDATE persons SET aliases_json=?, relation_text=?, recent_text=?,"
                " anniversaries_json=?, updated_at=? WHERE qq=?",
                (
                    json.dumps(merged, ensure_ascii=False),
                    payload.get("relation_text", existing["relation_text"]),
                    payload.get("recent_text", existing["recent_text"]),
                    json.dumps(payload["anniversaries"], ensure_ascii=False)
                    if payload.get("anniversaries") is not None
                    else existing["anniversaries_json"],
                    now,
                    qq,
                ),
            )
        if payload.get("expected_friend"):
            until = now + C.EXPECTED_FRIEND_TTL_SECONDS
            await db.conn.execute(
                "UPDATE persons SET expected_friend_until=?, expected_reason=? WHERE qq=?",
                (until, payload.get("expected_reason", ""), qq),
            )

    async def _apply_promise(self, db: Any, payload: dict) -> None:
        if payload.get("action") == "add":
            await db.conn.execute(
                "INSERT INTO promises(from_id, to_id, content, due_date)"
                " VALUES(?,?,?,?)",
                (payload.get("from_id", ""), payload.get("to_id", ""),
                 payload.get("content", ""), payload.get("due_date", "")),
            )
        elif payload.get("action") == "update":
            status = payload.get("status", "")
            if status in ("done", "broken", "waived"):
                await db.conn.execute(
                    "UPDATE promises SET status=? WHERE id=?",
                    (status, int(payload.get("promise_id", 0))),
                )

    async def run_external_actions(self) -> list[str]:
        """提交后的外部动作：建闹钟、自我形象。shield 包住，不被取消影响。

        返回每条动作的结果描述（成功或失败原因）。
        """

        async def _run() -> list[str]:
            results: list[str] = []
            drafts = await self.storage.runs.get_drafts(self.run_id)
            for d in drafts:
                kind = d["kind"]
                payload = json.loads(d["payload_json"] or "{}")
                if kind == "alarm":
                    results.append(await self._create_alarm(payload))
                elif kind == "appearance":
                    results.append(await self._apply_appearance(payload))
            return results

        return await asyncio.shield(_run())

    async def _create_alarm(self, payload: dict) -> str:
        target_umo = payload.get("target_umo", "")
        card = payload.get("card") or {}
        run_at_str = payload.get("run_at", "")
        cron_expression = payload.get("cron_expression", "")
        if not target_umo:
            return "闹钟失败：没有目标会话"
        run_at_ts: float | None = None
        if run_at_str:
            try:
                run_at_ts = parse_run_at(run_at_str, self.tz)
            except ValueError as exc:
                return f"闹钟失败（{target_umo}）：{exc}"
            if run_at_ts <= utc_now() + C.ALARM_MIN_LEAD_SECONDS:
                return f"闹钟失败（{target_umo}）：执行时间早于现在 5 分钟以后"
            if is_quiet_time(run_at_ts, self.tz) and not (
                card.get("agreed") and card.get("agreed_reason")
            ):
                return f"闹钟失败（{target_umo}）：落在深夜免打扰时段且没有约定理由"
        elif not cron_expression:
            return f"闹钟失败（{target_umo}）：没有执行时间"

        if self.rate_limiter is not None:
            deny = await self.rate_limiter.check_alarm_creation(
                origin="night", target_umo=target_umo, creator_id=C.NIGHT_ALARM_SENDER_ID,
                now_ts=utc_now(),
            )
            if deny:
                return f"闹钟被频率上限拦下（{target_umo}）：{deny}"

        note_text = render_card_note(card)
        alarm_id = await self.storage.alarms.add_alarm(
            target_umo=target_umo,
            creator_id=C.NIGHT_ALARM_SENDER_ID,
            origin="night",
            run_at=run_at_ts,
            cron_expression=cron_expression,
            card=card,
            note_text=note_text,
            created_run_id=self.run_id,
        )
        try:
            job = await self.context.cron_manager.add_active_job(
                name=f"astrhe闹钟#{alarm_id}",
                cron_expression=cron_expression or None,
                payload={
                    "session": target_umo,
                    "sender_id": C.NIGHT_ALARM_SENDER_ID,
                    "note": note_text,
                    "origin": C.NIGHT_ALARM_ORIGIN,
                    "astrhe_alarm_id": str(alarm_id),
                },
                description=str(card.get("purpose", ""))[:100],
                timezone=getattr(self.tz, "key", None) or str(self.tz),
                run_once=run_at_ts is not None,
                run_at=datetime.fromtimestamp(run_at_ts, self.tz) if run_at_ts else None,
            )
            await self.storage.alarms.bind_cron_job(alarm_id, job.job_id)
            return f"闹钟 #{alarm_id} 已建：{target_umo}"
        except Exception as exc:  # noqa: BLE001
            await self.storage.alarms.set_status(alarm_id, "failed", str(exc))
            return f"闹钟失败（{target_umo}）：{exc}"

    async def _apply_appearance(self, payload: dict) -> str:
        from ..qq.client import QQClient
        from ..platform import PlatformHelper
        from astrbot.api import logger

        signature = payload.get("signature", "")
        preset = payload.get("status_preset", "")
        qq = QQClient(PlatformHelper(self.context, logger))
        results = []
        if signature:
            if self.rate_limiter is not None:
                deny = await self.rate_limiter.check("signature", utc_now())
                if deny:
                    return f"改签名被拦下：{deny}"
            try:
                await qq.call("set_self_longnick", longNick=signature)
                if self.rate_limiter is not None:
                    await self.rate_limiter.record("signature")
                results.append("签名已更新")
            except Exception as exc:  # noqa: BLE001
                results.append(f"改签名失败：{exc}")
        if preset:
            presets = {"在线": (10, 0), "离开": (30, 0), "忙碌": (50, 0),
                       "请勿打扰": (70, 0), "Q我吧": (60, 0)}
            if preset in presets:
                if self.rate_limiter is not None:
                    deny = await self.rate_limiter.check("status", utc_now())
                    if deny:
                        results.append(f"改状态被拦下：{deny}")
                        return "；".join(results)
                status, ext = presets[preset]
                try:
                    await qq.call("set_online_status", status=status, ext_status=ext,
                                  battery_status=0)
                    if self.rate_limiter is not None:
                        await self.rate_limiter.record("status")
                    results.append(f"状态已改为{preset}")
                except Exception as exc:  # noqa: BLE001
                    results.append(f"改状态失败：{exc}")
        return "；".join(results) if results else "自我形象：无动作"
