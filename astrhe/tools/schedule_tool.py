"""astrhe_schedule：增强定时工具，替代自带 future_task。

- 任务仍写入 AstrBot 定时任务系统（cron_manager.add_active_job），面板可见可改。
- 卡片（来龙去脉）完整写进 note/description：闹钟唤醒路径不经过 on_llm_request，
  被叫醒时只能看到 note，所以卡片必须完整到「只看卡片就能办成事」。
- 权限：管理员可跨会话；非管理员只能操作当前会话的 AstrHe 闹钟；
  外部任务（非 AstrHe 创建）只能看和取消。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .. import constants as C
from ..platform import build_umo, is_valid_qq, parse_umo
from ..timeutil import (
    is_quiet_time,
    local_datetime_str,
    parse_run_at,
    utc_now,
)
from .secrecy import filter_secret_text, is_secret_visible_here

TOOL_NAME = "astrhe_schedule"

#: 卡片渲染时附在 note 末尾的标准操作说明
STANDARD_NOTE_SUFFIX = (
    "\n\n【标准操作说明】发送消息用 send_message_to_user：session 留空表示当前会话"
    "（即本任务的目标会话）；需要 @ 某人时，在消息里用 mention_user 组件"
    "（mention_user_id=对方 QQ 号）。对方回复时，参考 AstrHe 待办里属于这个会话的内容。"
    "新建或修改定时任务请用 astrhe_schedule，不要用 future_task。"
)


def render_card_note(card: dict[str, Any]) -> str:
    """把闹钟卡片渲染成完整的 note 文本。"""
    lines = ["【闹钟卡片】"]
    labels = [
        ("background", "背景"),
        ("purpose", "目的"),
        ("how", "怎么做"),
        ("involved", "牵涉的人"),
        ("mentions", "需要 @ 的人（QQ 号）"),
        ("secret_from", "对谁保密"),
        ("taboo", "禁忌（不能做的事、不能说漏的话）"),
        ("agreed_reason", "约定时刻的理由"),
    ]
    for key, label in labels:
        value = card.get(key)
        if isinstance(value, list):
            value = "、".join(str(v) for v in value)
        if value:
            lines.append(f"{label}：{value}")
    return "\n".join(lines) + STANDARD_NOTE_SUFFIX


class ScheduleToolImpl:
    """astrhe_schedule 的实现。"""

    def __init__(
        self,
        storage: Any,
        context: Any,
        qq_client: Any,
        rate_limiter: Any,
        tz_getter,
        secrecy_resolver: Any,
        admins_getter,
    ):
        self.storage = storage
        self.context = context
        self.qq = qq_client
        self.rate_limiter = rate_limiter
        self._tz_getter = tz_getter
        self.secrecy_resolver = secrecy_resolver
        self._admins_getter = admins_getter

    # ---------------- 入口 ----------------

    async def run(self, event: Any, action: str = "", **kwargs: Any) -> str:
        if action == "create":
            return await self._create(event, **kwargs)
        if action == "list":
            return await self._list(event)
        if action == "edit":
            return await self._edit(event, **kwargs)
        if action == "cancel":
            return await self._cancel(event, **kwargs)
        return "action 只能是 create / list / edit / cancel"

    # ---------------- 权限与发起人 ----------------

    def _caller(self, event: Any) -> tuple[str, bool]:
        """返回 (发起人 sender_id, 是否管理员)。

        闹钟唤醒路径里发起人沿用 cron_payload.sender_id，权限看 event.role。
        """
        extras = getattr(event, "_extras", None) or {}
        cron_payload = extras.get("cron_payload") if isinstance(extras, dict) else None
        if isinstance(cron_payload, dict) and cron_payload.get("sender_id"):
            sender_id = str(cron_payload["sender_id"])
        else:
            try:
                sender_id = str(event.get_sender_id())
            except Exception:  # noqa: BLE001
                sender_id = ""
        is_admin = getattr(event, "role", "member") == "admin"
        return sender_id, is_admin

    # ---------------- create ----------------

    async def _create(self, event: Any, **kwargs: Any) -> str:
        sender_id, is_admin = self._caller(event)
        target_type = str(kwargs.get("target_type", "current"))
        target_id = str(kwargs.get("target_id", "") or "")
        platform_id = ""
        current_umo = ""
        try:
            platform_id = event.get_platform_id()
            current_umo = event.unified_msg_origin
        except Exception:  # noqa: BLE001
            pass

        # 目标会话
        if target_type == "current":
            target_umo = current_umo
        elif target_type == "group":
            if not is_admin:
                return "只有管理员才能给别的会话定闹钟；给自己所在的会话定用 target_type=current"
            if not is_valid_qq(target_id):
                return "target_id 需要是群号（5-12 位数字）"
            target_umo = build_umo(platform_id or self.qq.platform.default_platform_id(), "GroupMessage", target_id)
        elif target_type == "private":
            if not is_admin:
                return "只有管理员才能给别的会话定闹钟；给自己所在的会话定用 target_type=current"
            if not is_valid_qq(target_id):
                return "target_id 需要是 QQ 号（5-12 位数字）"
            target_umo = build_umo(platform_id or self.qq.platform.default_platform_id(), "FriendMessage", target_id)
        else:
            return "target_type 只能是 current / group / private"
        if not target_umo or target_umo.startswith(":"):
            return "确定不了目标会话，请检查 target_type 和 target_id"

        # 校验平台与目标
        pid, mtype, sid = parse_umo(target_umo)
        if self.qq.platform.default_platform_id() == "":
            return "当前没有 aiocqhttp 平台，定不了闹钟"
        if mtype == "GroupMessage":
            groups = await self.qq.group_ids()
            if groups and sid not in groups:
                return f"我不在群 {sid} 里，定不了这个闹钟"
        friend_warning = ""
        if mtype == "FriendMessage":
            friends = await self.qq.friend_ids()
            if friends and sid not in friends:
                friend_warning = "\n注意：对方不是好友，消息可能被 QQ 拦截"

        # 时间
        run_at_str = str(kwargs.get("run_at", "") or "")
        cron_expression = str(kwargs.get("cron_expression", "") or "")
        tz = self._tz_getter()
        run_at_ts: float | None = None
        if run_at_str:
            try:
                run_at_ts = parse_run_at(run_at_str, tz)
            except ValueError as exc:
                return str(exc)
            if run_at_ts <= utc_now() + C.ALARM_MIN_LEAD_SECONDS:
                return "执行时间必须晚于现在 5 分钟以后"
        elif not cron_expression:
            return "需要 run_at（一次性，如 2026-10-11 00:00）或 cron_expression（重复）"

        # 卡片
        card = {
            "background": str(kwargs.get("background", "") or ""),
            "purpose": str(kwargs.get("purpose", "") or ""),
            "how": str(kwargs.get("how", "") or ""),
            "involved": kwargs.get("involved") or [],
            "mentions": kwargs.get("mentions") or [],
            "secret_from": kwargs.get("secret_from") or [],
            "taboo": str(kwargs.get("taboo", "") or ""),
            "agreed": bool(kwargs.get("agreed", False)),
            "agreed_reason": str(kwargs.get("agreed_reason", "") or ""),
        }
        for key in ("background", "purpose", "how"):
            if not card[key]:
                return f"卡片缺少「{key}」：闹钟要讲清楚来龙去脉，被叫醒时只看卡片就要能办成事"
        if isinstance(card["mentions"], str):
            card["mentions"] = [card["mentions"]]
        if isinstance(card["involved"], str):
            card["involved"] = [card["involved"]]
        if isinstance(card["secret_from"], str):
            card["secret_from"] = [card["secret_from"]]

        # 深夜免打扰
        if run_at_ts is not None and is_quiet_time(run_at_ts, tz):
            if not (card["agreed"] and card["agreed_reason"]):
                return (
                    "这个时间落在深夜免打扰时段（00:30-08:00）。"
                    "如果是事先约定好的时刻（比如生日零点），请设 agreed=true 并写 agreed_reason"
                )

        # 频率上限
        deny = await self.rate_limiter.check_alarm_creation(
            origin="day", target_umo=target_umo, creator_id=sender_id, now_ts=utc_now()
        )
        if deny:
            return deny

        note_text = render_card_note(card)
        alarm_id = await self.storage.alarms.add_alarm(
            target_umo=target_umo,
            creator_id=sender_id,
            origin="day",
            run_at=run_at_ts,
            cron_expression=cron_expression,
            card=card,
            note_text=note_text,
        )
        try:
            job = await self.context.cron_manager.add_active_job(
                name=f"astrhe闹钟#{alarm_id}",
                cron_expression=cron_expression or None,
                payload={
                    "session": target_umo,
                    "sender_id": sender_id,
                    "note": note_text,
                    "origin": "tool",
                    "astrhe_alarm_id": str(alarm_id),
                },
                description=card["purpose"][:100],
                timezone=getattr(tz, "key", None) or str(tz),
                run_once=run_at_ts is not None,
                run_at=datetime.fromtimestamp(run_at_ts, tz) if run_at_ts else None,
            )
        except Exception as exc:  # noqa: BLE001
            await self.storage.alarms.set_status(alarm_id, "failed", str(exc))
            return f"创建定时任务失败: {exc}"
        await self.storage.alarms.bind_cron_job(alarm_id, job.job_id)
        when = (
            local_datetime_str(run_at_ts, tz) if run_at_ts else f"重复规则 {cron_expression}"
        )
        return f"闹钟 #{alarm_id} 定好了：{when} → {target_umo}{friend_warning}"

    # ---------------- list ----------------

    async def _list(self, event: Any) -> str:
        sender_id, is_admin = self._caller(event)
        current_umo = ""
        try:
            current_umo = event.unified_msg_origin
        except Exception:  # noqa: BLE001
            pass
        viewer_id = sender_id if not self._is_cron_event(event) else ""
        present = await self.secrecy_resolver.present_ids(current_umo) if current_umo else set()
        tz = self._tz_getter()

        lines: list[str] = []
        alarms = await self.storage.alarms.list_alarms(100)
        for a in alarms:
            if not is_admin and a["target_umo"] != current_umo:
                continue
            card = json.loads(a["card_json"] or "{}")
            secret_from = card.get("secret_from") or []
            if not is_secret_visible_here(
                secret_from, viewer_id=viewer_id, session_umo=current_umo, present_ids=present
            ):
                continue
            when = (
                local_datetime_str(a["run_at"], tz) if a["run_at"] else a["cron_expression"]
            )
            purpose = filter_secret_text(
                str(card.get("purpose", "")),
                viewer_id=viewer_id,
                session_umo=current_umo,
                present_ids=present,
            )
            lines.append(f"#{a['id']} [{a['status']}] {when} → {a['target_umo']}：{purpose}")

        if is_admin:
            cron = getattr(self.context, "cron_manager", None)
            if cron is not None:
                try:
                    jobs = await cron.list_jobs("active_agent")
                except Exception:  # noqa: BLE001
                    jobs = []
                astrhe_ids = {a["cron_job_id"] for a in alarms if a["cron_job_id"]}
                external = [j for j in jobs if j.job_id not in astrhe_ids]
                if external:
                    lines.append("外部任务（不是 AstrHe 建的，只能查看和取消）：")
                    for j in external:
                        payload = j.payload or {}
                        lines.append(
                            f"  {j.job_id}「{j.name}」→ {payload.get('session', '')}"
                            f" enabled={j.enabled}"
                        )
        return "\n".join(lines) if lines else "现在没有可见的闹钟"

    def _is_cron_event(self, event: Any) -> bool:
        extras = getattr(event, "_extras", None) or {}
        return isinstance(extras, dict) and "cron_payload" in extras

    # ---------------- edit / cancel ----------------

    async def _edit(self, event: Any, **kwargs: Any) -> str:
        sender_id, is_admin = self._caller(event)
        alarm_id = kwargs.get("alarm_id")
        try:
            alarm_id = int(alarm_id)
        except (TypeError, ValueError):
            return "edit 需要 alarm_id（闹钟编号）"
        alarm = await self.storage.alarms.get_alarm(alarm_id)
        if alarm is None:
            return f"找不到闹钟 #{alarm_id}"
        deny = self._check_manage(event, alarm, is_admin)
        if deny:
            return deny

        updates: dict[str, Any] = {}
        card = json.loads(alarm["card_json"] or "{}")
        for key in ("background", "purpose", "how", "taboo", "agreed_reason"):
            if kwargs.get(key):
                card[key] = str(kwargs[key])
        for key in ("involved", "mentions", "secret_from"):
            if kwargs.get(key):
                value = kwargs[key]
                card[key] = [value] if isinstance(value, str) else value
        note_text = render_card_note(card)
        run_at_str = str(kwargs.get("run_at", "") or "")
        tz = self._tz_getter()
        if run_at_str:
            try:
                run_at_ts = parse_run_at(run_at_str, tz)
            except ValueError as exc:
                return str(exc)
            if run_at_ts <= utc_now() + C.ALARM_MIN_LEAD_SECONDS:
                return "执行时间必须晚于现在 5 分钟以后"
            updates["run_at"] = run_at_ts
            if alarm["cron_job_id"]:
                try:
                    await self.context.cron_manager.delete_job(alarm["cron_job_id"])
                    job = await self.context.cron_manager.add_active_job(
                        name=f"astrhe闹钟#{alarm_id}",
                        cron_expression=None,
                        payload={
                            "session": alarm["target_umo"],
                            "sender_id": alarm["creator_id"],
                            "note": note_text,
                            "origin": "tool",
                            "astrhe_alarm_id": str(alarm_id),
                        },
                        description=str(card.get("purpose", ""))[:100],
                        timezone=getattr(tz, "key", None) or str(tz),
                        run_once=True,
                        run_at=datetime.fromtimestamp(run_at_ts, tz),
                    )
                    await self.storage.alarms.bind_cron_job(alarm_id, job.job_id)
                except Exception as exc:  # noqa: BLE001
                    return f"修改定时任务失败: {exc}"
        # 更新卡片与 note
        await self.storage.db.execute(
            "UPDATE alarms SET card_json=?, note_text=?, run_at=COALESCE(?, run_at)"
            " WHERE id=?",
            (json.dumps(card, ensure_ascii=False), note_text, updates.get("run_at"), alarm_id),
        )
        if alarm["cron_job_id"] and not run_at_str:
            # 只改卡片：同步更新 cron 任务里的 note
            try:
                job_list = await self.context.cron_manager.list_jobs("active_agent")
                job = next((j for j in job_list if j.job_id == alarm["cron_job_id"]), None)
                if job is not None:
                    payload = dict(job.payload or {})
                    payload["note"] = note_text
                    await self.context.cron_manager.update_job(
                        alarm["cron_job_id"], payload=payload, description=str(card.get("purpose", ""))[:100]
                    )
            except Exception:  # noqa: BLE001
                pass
        return f"闹钟 #{alarm_id} 已更新"

    async def _cancel(self, event: Any, **kwargs: Any) -> str:
        sender_id, is_admin = self._caller(event)
        alarm_id = kwargs.get("alarm_id")
        job_id = str(kwargs.get("job_id", "") or "")
        if job_id:
            # 取消外部任务：只有管理员可以
            if not is_admin:
                return "外部任务只有管理员能取消"
            try:
                await self.context.cron_manager.delete_job(job_id)
            except Exception as exc:  # noqa: BLE001
                return f"取消失败: {exc}"
            return f"外部任务 {job_id} 已取消"
        try:
            alarm_id = int(alarm_id)
        except (TypeError, ValueError):
            return "cancel 需要 alarm_id（AstrHe 闹钟编号）或 job_id（外部任务）"
        alarm = await self.storage.alarms.get_alarm(alarm_id)
        if alarm is None:
            return f"找不到闹钟 #{alarm_id}"
        deny = self._check_manage(event, alarm, is_admin)
        if deny:
            return deny
        if alarm["cron_job_id"]:
            try:
                await self.context.cron_manager.delete_job(alarm["cron_job_id"])
            except Exception:  # noqa: BLE001
                pass
        await self.storage.alarms.set_status(alarm_id, "cancelled")
        return f"闹钟 #{alarm_id} 已取消"

    def _check_manage(self, event: Any, alarm: dict, is_admin: bool) -> str:
        """非管理员只能操作当前会话的 AstrHe 闹钟；返回空串表示允许。"""
        if is_admin:
            return ""
        current_umo = ""
        try:
            current_umo = event.unified_msg_origin
        except Exception:  # noqa: BLE001
            pass
        if alarm["target_umo"] != current_umo:
            return "只能操作当前会话的闹钟"
        return ""
