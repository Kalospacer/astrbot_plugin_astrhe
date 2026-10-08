"""闹钟跟踪与对账。

- 生命周期与发送结果分离：fired/done 状态，send_ok/send_failed 事件。
- 手动提前执行记 manual_run 事件，并停用一次性任务避免重复触发。
- 完整回流窗口内的执行、发送失败、缺失和中断；触发一小时内不判中断。
"""

from __future__ import annotations

import json
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
                    await self.storage.alarms.add_event(alarm["id"], "manual_run")
                    await self.storage.alarms.set_status(alarm["id"], "fired")
                    await self._disable_run_once(alarm)
                    return
            except (ValueError, TypeError):
                pass
        await self.storage.alarms.add_event(alarm["id"], "fired")
        await self.storage.alarms.set_status(alarm["id"], "fired")

    async def on_llm_tool_respond(
        self, event: Any, tool: Any, tool_args: Any, tool_result: Any
    ) -> None:
        """记录 send_message_to_user 的独立发送结果，不覆盖生命周期。"""
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
            await self.storage.alarms.add_event(
                alarm["id"], "send_ok", json.dumps(tool_args, ensure_ascii=False)
            )
        elif "error" in text.lower() or "failed" in text.lower():
            await self.storage.alarms.add_event(
                alarm["id"],
                "send_failed",
                text + "；参数：" + json.dumps(tool_args, ensure_ascii=False),
            )

    async def on_agent_done(self, event: Any) -> None:
        """正常结束 → done。"""
        alarm_id = self._alarm_id_from_event(event)
        if not alarm_id:
            return
        alarm = await self.storage.alarms.get_by_alarm_id_str(alarm_id)
        if alarm is None:
            return
        if alarm["status"] == "fired":
            await self.storage.alarms.add_event(alarm["id"], "done")
            await self.storage.alarms.set_status(alarm["id"], "done")

    async def finalize_stale_started(self) -> None:
        """触发超过一小时仍未正常结束才判中断。"""
        for alarm in await self.storage.alarms.active_alarms():
            if alarm["status"] != "fired":
                continue
            events = await self.storage.alarms.events(alarm["id"])
            fired = [e for e in events if e["kind"] in ("fired", "manual_run")]
            if fired and utc_now() - fired[-1]["ts"] > 3600:
                await self.storage.alarms.set_status(
                    alarm["id"], "failed", "执行被中断（超过一小时没有正常结束）"
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

    async def nightly_reconcile(self, window_start=0, window_end=None) -> str:
        """完整回流窗口内触发或应触发的闹钟，发送结果独立于生命周期。"""
        await self.finalize_stale_started()
        now = utc_now() if window_end is None else window_end
        tz = self._tz_getter()
        cron_jobs = {}
        try:
            cron_jobs = {
                j.job_id: j
                for j in await self.context.cron_manager.list_jobs("active_agent")
            }
        except Exception:
            pass
        lines = []
        for alarm in await self.storage.alarms.list_alarms(-1):
            events = await self.storage.alarms.events(alarm["id"], window_start, now)
            due = alarm["run_at"] is not None and window_start <= alarm["run_at"] <= now
            # 外部创建失败也要回流，不能等到永远不会发生的 fired 事件。
            failed = (
                alarm["status"] == "failed"
                and window_start <= alarm["created_at"] <= now
            )
            if not events and not due and not failed:
                continue
            all_events = await self.storage.alarms.events(alarm["id"])
            fired = any(e["kind"] in ("fired", "manual_run") for e in all_events)
            status = alarm["status"]
            if due and status == "scheduled" and not fired:
                job = cron_jobs.get(alarm["cron_job_id"])
                if job is None or not job.enabled:
                    status = "missing"
                    await self.storage.alarms.set_status(
                        alarm["id"], status, "到点没执行，任务缺失或停用"
                    )
            details = []
            if any(e["kind"] == "manual_run" for e in events):
                details.append("面板立即执行过")
            sends = [e for e in events if e["kind"] in ("send_ok", "send_failed")]
            for e in sends:
                details.append(
                    ("消息已发出：" if e["kind"] == "send_ok" else "发送失败：")
                    + e["detail"]
                )
            labels = {
                "scheduled": "到点未见执行记录",
                "fired": "正在执行",
                "done": "已执行完成",
                "failed": "执行中断或创建失败",
                "missing": "到点没执行（失踪）",
                "cancelled": "已取消",
            }
            details.append(labels.get(status, status))
            if alarm["result_note"]:
                details.append(alarm["result_note"])
            when = (
                local_datetime_str(alarm["run_at"], tz)
                if alarm["run_at"]
                else alarm["cron_expression"] or "时间未建立"
            )
            lines.append(
                f"#{alarm['id']} → {alarm['target_umo']}（原定 {when}）："
                + "；".join(details)
            )
        return (
            "闹钟对账：\n" + "\n".join(lines)
            if lines
            else "对账完成：窗口内没有触发或应触发的闹钟"
        )
