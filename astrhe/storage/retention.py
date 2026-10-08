"""成功提交后统一清理过程记录；日记和关系本保留，回收站满期才删除。"""

from .. import constants as C
from ..timeutil import utc_now
from .alarms import LIVE_ALARM_SQL


async def cleanup_history(
    storage, cutoff, keep_run_id, *, cron_manager=None, logger=None
):
    finished = await storage.db.fetchall(
        f"SELECT * FROM alarms WHERE NOT {LIVE_ALARM_SQL} "
        "AND COALESCE(finished_at, run_at, created_at)<?",
        (cutoff,),
    )
    if cron_manager is not None and finished:
        try:
            jobs = {j.job_id: j for j in await cron_manager.list_jobs("active_agent")}
            for alarm in finished:
                job = jobs.get(alarm["cron_job_id"])
                if job is not None and not job.enabled:
                    try:
                        await cron_manager.delete_job(job.job_id)
                    except Exception as exc:
                        if logger:
                            logger.warning(f"[AstrHe] 清理已停用闹钟任务失败：{exc}")
        except Exception as exc:
            if logger:
                logger.warning(f"[AstrHe] 清理时查询平台任务失败：{exc}")
    db = storage.db
    counts = {}
    async with db.write_lock:
        try:
            await db.conn.execute("BEGIN")
            # 最近一次提交用于确定复盘窗口，即使很久没运行也不能删除。
            latest = await storage.runs.latest_committed_run()
            keep = latest["id"] if latest else -1
            old_runs = await db.fetchall(
                "SELECT id FROM runs WHERE ended_at<? AND id NOT IN (?,?)",
                (cutoff, keep_run_id, keep),
            )
            for row in old_runs:
                for table in ("reports", "drafts", "reviews"):
                    await db.conn.execute(
                        f"DELETE FROM {table} WHERE run_id=?", (row["id"],)
                    )
                await db.conn.execute("DELETE FROM runs WHERE id=?", (row["id"],))
            counts["runs"] = len(old_runs)
            # 再按当前状态判定，避免外部清理期间闹钟又发生变化。
            deleted = 0
            for alarm in finished:
                cur = await db.conn.execute(
                    f"DELETE FROM alarms WHERE id=? AND NOT {LIVE_ALARM_SQL} "
                    "AND COALESCE(finished_at, run_at, created_at)<?",
                    (alarm["id"], cutoff),
                )
                if cur.rowcount:
                    deleted += 1
                    await db.conn.execute(
                        "DELETE FROM alarm_events WHERE alarm_id=?", (alarm["id"],)
                    )
            counts["alarms"] = deleted
            for table in ("alarm_events", "action_log", "memory_revisions"):
                cur = await db.conn.execute(
                    f"DELETE FROM {table} WHERE ts<?", (cutoff,)
                )
                counts[table] = cur.rowcount
            await db.conn.execute(
                "DELETE FROM plan_sections WHERE plan_id IN "
                "(SELECT id FROM plans WHERE deleted_at<?)",
                (cutoff,),
            )
            for table in ("plans", "todos", "promises"):
                cur = await db.conn.execute(
                    f"DELETE FROM {table} WHERE deleted_at<?", (cutoff,)
                )
                counts[table] = cur.rowcount
            await db.conn.commit()
        except BaseException:
            await db.conn.rollback()
            raise
    return counts


async def cleanup_after_commit(storage, context, backfiller, keep_run_id, logger):
    """清理失败只记日志；已提交状态和外部动作不受影响。"""
    now = utc_now()
    try:
        if backfiller is not None:
            await backfiller.cleanup_old(now)
        else:
            await storage.ledger.cleanup(now - C.LEDGER_RETENTION_SECONDS)
    except Exception as exc:
        logger.warning(f"[AstrHe] 聊天账本清理失败：{exc}")
    try:
        await cleanup_history(
            storage,
            now - C.LEDGER_RETENTION_SECONDS,
            keep_run_id,
            cron_manager=getattr(context, "cron_manager", None),
            logger=logger,
        )
    except Exception as exc:
        logger.warning(f"[AstrHe] 过程记录清理失败：{exc}")
