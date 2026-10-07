"""闹钟跟踪与对账。

- 唤醒钩子：on_agent_begin → started；on_llm_tool_respond 里看
  send_message_to_user 的结果文字 → sent / send_failed；on_agent_done → done。
- 「有 started 没有 done」（on_agent_done 只在正常结束时触发）→ failed。
- 立即执行识别：cron_job.run_started_at 比 payload.run_at 早 5 分钟以上，
  视为面板「立即执行」：标记 manual_run，并对 run_once 任务 update_job
  enabled=False，防止原定时间再跑一次。
- 夜间对账：run_at 已过、cron 行不存在、也没有 started 记录的 → missing。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .timeutil import local_datetime_str, utc_now

#: 判断「立即执行」的容差（秒）
MANUAL_RUN_TOLERANCE = 300

_SEND_OK_PREFIX = "Message sent to session"


class AlarmTracker:
    def __init__(self, storage: Any, context: Any, tz_getter, logger: Any):
        self.storage = storage
        self.context = context
        self._tz_getter = tz_getter
        self.logger = logger

    # ---------------- 钩子入口（由 main.py 转发） ----------------

    @staticmethod
    def _alarm_id_from_event(event: Any) -> str:
        extras = getattr(event, "_extras", None) or {}
        if not isinstance(extras, dict):
            return ""
        payload = extras.get("cron_payload")
        if isinstance(payload, dict) and payload.get("astrhe_alarm_id"):
            return str(payload["astrhe_alarm_id"])
        return ""

    async def on_agent_begin(self, event: Any) -> None:
        """闹钟唤醒开始。"""
        alarm_id = self._alarm_id_from_event(event)
        if not alarm_id:
            return
        alarm = await self.storage.alarms.get_by_alarm_id_str(alarm_id)
        if alarm is None:
            return
        # 立即执行识别
        extras = getattr(event, "_extras", {}) or {}
        cron_job = extras.get("cron_job") or {}
        run_started_at = str(cron_job.get("run_started_at", "") or "")
        run_at = alarm["run_at"]
        if run_at and run_started_at:
            try:
                started_ts = datetime.fromisoformat(run_started_at).timestamp()
                if started_ts < float(run_at) - MANUAL_RUN_TOLERANCE:
                    await self.storage.alarms.set_status(alarm["id"], "manual_run")
                    await self._disable_run_once(alarm)
                    return
            except (ValueError, TypeError):
                pass
        await self.storage.alarms.set_status(alarm["id"], "started")

    async def on_llm_tool_respond(
        self, event: Any, tool: Any, tool_args: Any, tool_result: Any
    ) -> None:
        """看 send_message_to_user 的结果文字，标记 sent / send_failed。"""
        alarm_id = self._alarm_id_from_event(event)
        if not alarm_id:
            return
        if getattr(tool, "name", "") != "send_message_to_user":
            return
        text = ""
        try:
            content = getattr(tool_result, "content", None) or []
            text = " ".join(str(getattr(c, "text", "")) for c in content)
        except Exception:  # noqa: BLE001
            text = str(tool_result or "")
        alarm = await self.storage.alarms.get_by_alarm_id_str(alarm_id)
        if alarm is None:
            return
        if _SEND_OK_PREFIX in text:
            await self.storage.alarms.set_status(alarm["id"], "sent")
        elif "error" in text.lower() or "failed" in text.lower():
            await self.storage.alarms.set_status(alarm["id"], "send_failed", text[:200])

    async def on_agent_done(self, event: Any) -> None:
        """正常结束 → done。"""
        alarm_id = self._alarm_id_from_event(event)
        if not alarm_id:
            return
        alarm = await self.storage.alarms.get_by_alarm_id_str(alarm_id)
        if alarm is None:
            return
        if alarm["status"] in ("started", "sent", "send_failed", "manual_run"):
            await self.storage.alarms.set_status(alarm["id"], "done")

    async def finalize_stale_started(self) -> None:
        """把「started 但没有 done」的闹钟判为 failed（夜间对账时调用）。"""
        for alarm in await self.storage.alarms.active_alarms():
            if alarm["status"] == "started":
                await self.storage.alarms.set_status(
                    alarm["id"], "failed", "执行被中断（没有正常结束）"
                )

    async def _disable_run_once(self, alarm: dict) -> None:
        """面板立即执行后，停用 run_once 任务防止原定时间再跑一次。"""
        if not alarm["cron_job_id"] or alarm["cron_expression"]:
            return
        try:
            await self.context.cron_manager.update_job(
                alarm["cron_job_id"], enabled=False
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"[AstrHe] 停用 run_once 任务失败: {exc}")

    # ---------------- 夜间对账 ----------------

    async def nightly_reconcile(self) -> str:
        """对账：把失踪的闹钟标记 missing，返回给主 agent 看的文本。"""
        await self.finalize_stale_started()
        now = utc_now()
        tz = self._tz_getter()
        cron_jobs: dict[str, Any] = {}
        try:
            for job in await self.context.cron_manager.list_jobs("active_agent"):
                cron_jobs[job.job_id] = job
        except Exception:  # noqa: BLE001
            pass

        lines: list[str] = []
        for alarm in await self.storage.alarms.active_alarms():
            run_at = alarm["run_at"]
            if run_at is None:
                continue  # 重复任务不参与失踪判定
            if float(run_at) > now:
                continue  # 还没到点
            status = alarm["status"]
            if status in ("done", "sent", "send_failed", "manual_run"):
                continue
            job_missing = alarm["cron_job_id"] and alarm["cron_job_id"] not in cron_jobs
            if job_missing and status == "scheduled":
                await self.storage.alarms.set_status(
                    alarm["id"], "missing", "cron 行不存在，可能被手动删除"
                )
                lines.append(
                    f"闹钟 #{alarm['id']} → {alarm['target_umo']}"
                    f"（原定 {local_datetime_str(float(run_at), tz)}）失踪了："
                    "定时任务行不存在，也没有执行记录。可能是被手动删除，也可能执行失败。"
                )
        if not lines:
            return "对账完成：没有失踪的闹钟"
        return "对账发现失踪的闹钟：\n" + "\n".join(lines)
