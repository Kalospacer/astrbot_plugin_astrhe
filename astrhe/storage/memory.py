"""日记修改、回收站与修订记录；夜间应用由提交者持有同一个事务。"""

import json
from datetime import date

from .. import constants as C
from ..timeutil import utc_now
from ..tools.secrecy import normalize_secret_text

TABLES = {"plan": "plans", "todo": "todos", "promise": "promises"}
FIELDS = {
    "plan": ("full_text", "reflection"),
    "todo": ("content", "note"),
    "promise": ("content", "note"),
}
FINISHED = {"todo": ("done", "dropped"), "promise": ("done", "broken", "waived")}


class MemoryRepo:
    def __init__(self, db):
        self.db = db

    async def get_entry(self, kind, target, *, by_id=False):
        if kind not in TABLES:
            raise ValueError("kind 只能是 plan / todo / promise")
        key = "plan_date" if kind == "plan" and not by_id else "id"
        if key == "plan_date":
            target = str(target)
            if date.fromisoformat(target).isoformat() != target:
                raise ValueError("规划书 target 必须为 YYYY-MM-DD")
        else:
            target = int(str(target).lstrip("#"))
        return await self.db.fetchone(
            f"SELECT * FROM {TABLES[kind]} WHERE {key}=?", (target,)
        )

    @staticmethod
    def _restore_allowed(row, now):
        if row["deleted_at"] is None:
            raise ValueError("这条日记不在回收站里")
        if now - row["deleted_at"] >= C.LEDGER_RETENTION_SECONDS:
            raise ValueError("删除已满 30 天，不能恢复")

    async def validate_edit(self, payload, plan_date, now=None):
        """返回原记录与变更字段；草稿阶段和事务应用阶段都使用此规则。"""
        now = utc_now() if now is None else now
        kind, action = payload.get("kind"), payload.get("action")
        row = await self.get_entry(kind, payload.get("target", ""))
        if row is None:
            raise ValueError("找不到这条日记")
        if not str(payload.get("reason", "")).strip():
            raise ValueError("日记修改必须写理由")
        if action not in ("append", "replace", "delete", "restore"):
            raise ValueError("action 只能是 append / replace / delete / restore")
        if kind == "plan":
            if row["plan_date"] >= plan_date:
                raise ValueError(
                    "只能修改早于本次规划日的规划书；今天的请用 astrhe_draft_plan"
                )
        elif row["status"] not in FINISHED[kind]:
            raise ValueError("只能修改已了结的待办或承诺；未了结的请用现有草稿工具")
        if action == "restore":
            self._restore_allowed(row, now)
            return row, {"deleted_at": None, "deleted_reason": ""}
        if row["deleted_at"] is not None:
            raise ValueError("日记已删除，请先恢复")
        if action == "delete":
            return row, {"deleted_at": now, "deleted_reason": payload["reason"].strip()}
        content = str(payload.get("content", "") or "")
        if not content.strip():
            raise ValueError("append / replace 必须填写 content")
        field = payload.get("field") or ("full_text" if kind == "plan" else "note")
        if field not in FIELDS[kind]:
            raise ValueError("field 只能是 " + " / ".join(FIELDS[kind]))
        if action == "append":
            if kind == "plan":
                content = (row[field] or "") + f"\n\n【后记 {plan_date}】{content}"
            else:
                field = "note"
                content = (row[field] + "\n" if row[field] else "") + content
        if kind == "plan":
            content = normalize_secret_text(content)
        return row, {field: content}

    async def _write_revision(self, before, kind, changes, action, reason, run_id, now):
        """调用者必须持有写锁和事务；只允许固定日记字段，不碰创建时间与业务状态。"""
        changes = {**changes, "updated_at": now}
        await self.db.conn.execute(
            f"UPDATE {TABLES[kind]} SET "
            + ",".join(f"{field}=?" for field in changes)
            + " WHERE id=?",
            (*changes.values(), before["id"]),
        )
        after = await self.get_entry(kind, before["id"], by_id=True)
        await self.db.conn.execute(
            "INSERT INTO memory_revisions(kind,target_id,action,before_json,after_json,"
            "reason,run_id,ts) VALUES(?,?,?,?,?,?,?,?)",
            (
                kind,
                before["id"],
                action,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                reason,
                run_id,
                now,
            ),
        )
        return after

    async def apply_edit(self, payload, plan_date, run_id, now):
        before, changes = await self.validate_edit(payload, plan_date, now)
        return await self._write_revision(
            before,
            payload["kind"],
            changes,
            payload["action"],
            payload["reason"],
            run_id,
            now,
        )

    async def restore(self, kind, target, reason="管理员从回收站恢复"):
        async with self.db.write_lock:
            try:
                await self.db.conn.execute("BEGIN")
                before = await self.get_entry(kind, target)
                if before is None:
                    raise ValueError("找不到这条日记")
                now = utc_now()
                self._restore_allowed(before, now)
                result = await self._write_revision(
                    before,
                    kind,
                    {"deleted_at": None, "deleted_reason": ""},
                    "restore",
                    reason,
                    None,
                    now,
                )
                await self.db.conn.commit()
                return result
            except BaseException:
                await self.db.conn.rollback()
                raise

    async def revert(self, revision_id, reason=""):
        async with self.db.write_lock:
            try:
                await self.db.conn.execute("BEGIN")
                revision = await self.db.fetchone(
                    "SELECT * FROM memory_revisions WHERE id=?", (int(revision_id),)
                )
                if revision is None:
                    raise ValueError("找不到修订记录")
                kind = revision["kind"]
                before = await self.get_entry(kind, revision["target_id"], by_id=True)
                if before is None:
                    raise ValueError("原日记已清理，不能回退")
                old = json.loads(revision["before_json"])
                if before["deleted_at"] is not None and old["deleted_at"] is None:
                    self._restore_allowed(before, utc_now())
                changes = {
                    key: old[key]
                    for key in (*FIELDS[kind], "deleted_at", "deleted_reason")
                }
                # 回退恢复操作即再次删除，从这次回退起计算回收站保留期。
                if changes["deleted_at"] is not None:
                    changes["deleted_at"] = utc_now()
                if kind == "plan":
                    for key in FIELDS[kind]:
                        changes[key] = normalize_secret_text(changes[key])
                result = await self._write_revision(
                    before,
                    kind,
                    changes,
                    "revert",
                    reason.strip() or f"管理员回退修订 #{revision_id}",
                    None,
                    utc_now(),
                )
                await self.db.conn.commit()
                return result
            except BaseException:
                await self.db.conn.rollback()
                raise

    async def trash(self, offset=0, limit=C.MEMORY_ADMIN_PAGE_SIZE):
        sql = " UNION ALL ".join(
            f"SELECT '{kind}' AS kind,id AS target_id,"
            + ("plan_date" if kind == "plan" else "CAST(id AS TEXT)")
            + f" AS target,deleted_at,deleted_reason FROM {table} WHERE deleted_at IS NOT NULL"
            for kind, table in TABLES.items()
        )
        total = await self.db.fetchone(f"SELECT COUNT(*) AS n FROM ({sql})")
        rows = await self.db.fetchall(
            f"SELECT * FROM ({sql}) ORDER BY deleted_at DESC,kind,target_id DESC LIMIT ? OFFSET ?",
            (limit, max(0, int(offset))),
        )
        return rows, total["n"]

    async def revisions(self, offset=0, limit=C.MEMORY_ADMIN_PAGE_SIZE):
        total = await self.db.fetchone("SELECT COUNT(*) AS n FROM memory_revisions")
        rows = await self.db.fetchall(
            "SELECT * FROM memory_revisions ORDER BY ts DESC,id DESC LIMIT ? OFFSET ?",
            (limit, max(0, int(offset))),
        )
        return rows, total["n"]

    async def search(
        self, keyword, kind="all", offset=0, limit=C.MEMORY_SEARCH_PAGE_SIZE
    ):
        if kind not in ("all", *TABLES):
            raise ValueError("kind 只能是 all / plan / todo / promise")
        pattern = (
            "%"
            + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        queries, params = [], []
        for current, table in TABLES.items():
            if kind not in ("all", current):
                continue
            fields = (
                ("full_text", "reflection", "day_reminders")
                if current == "plan"
                else ("content", "note")
            )
            day = (
                "plan_date"
                if current == "plan"
                else "COALESCE(NULLIF(due_date,''),date(updated_at,'unixepoch'))"
            )
            queries.append(
                f"SELECT '{current}' AS kind,id,{day} AS day,COALESCE(updated_at,0) AS ts FROM {table}"
                " WHERE deleted_at IS NULL AND ("
                + " OR ".join(f"{field} LIKE ? ESCAPE '\\'" for field in fields)
                + ")"
            )
            params.extend([pattern] * len(fields))
        sql = " UNION ALL ".join(queries)
        total = await self.db.fetchone(
            f"SELECT COUNT(*) AS n FROM ({sql})", tuple(params)
        )
        rows = await self.db.fetchall(
            f"SELECT * FROM ({sql}) ORDER BY day DESC,ts DESC,kind,id DESC LIMIT ? OFFSET ?",
            (*params, limit, max(0, int(offset))),
        )
        return rows, total["n"]
