"""草稿、白天定时与提交共用的输入校验。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from apscheduler.triggers.cron import CronTrigger

from .. import constants as C
from ..platform import parse_umo, resolve_session_ref
from ..timeutil import is_quiet_time, parse_run_at, utc_now

ANNIVERSARY_EXAMPLE = '[{"name":"生日","date":"10-11"}]'


def validate_anniversaries(value: Any) -> list:
    """限制持久化格式，同时允许空列表清空纪念日。"""
    if not isinstance(value, list):
        raise ValueError(f"anniversaries 必须是数组，例如 {ANNIVERSARY_EXAMPLE}")
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
        ):
            raise ValueError(f"纪念日需要 name 和 date，例如 {ANNIVERSARY_EXAMPLE}")
        text = item.get("date")
        if not isinstance(text, str) or not re.fullmatch(
            r"\d{2}-\d{2}|\d{4}-\d{2}-\d{2}", text
        ):
            raise ValueError(
                f"纪念日日期须为 MM-DD 或 YYYY-MM-DD，例如 {ANNIVERSARY_EXAMPLE}"
            )
        try:
            datetime.strptime("2000-" + text if len(text) == 5 else text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"纪念日日期不合法，例如 {ANNIVERSARY_EXAMPLE}") from exc
    return value


def validate_alarm_time(
    run_at: str,
    cron_expression: str,
    card: dict,
    tz: Any,
    *,
    allow_repeat: bool = True,
) -> float:
    """返回下一次触发的时间戳；重复规则检查跨完整一周的深夜时段。"""
    now = utc_now()
    agreed = card.get("agreed") and str(card.get("agreed_reason", "")).strip()
    if run_at and cron_expression:
        raise ValueError("run_at 和 cron_expression 只能选一个")
    if run_at:
        ts = parse_run_at(run_at, tz)
        if ts <= now + C.ALARM_MIN_LEAD_SECONDS:
            raise ValueError("执行时间必须晚于现在 5 分钟以后")
        if is_quiet_time(ts, tz) and not agreed:
            raise ValueError(
                "深夜免打扰（00:30-08:00）：必须 agreed=true 并写 agreed_reason"
            )
        return ts
    if not cron_expression:
        raise ValueError("需要 run_at 或 cron_expression")
    if not allow_repeat:
        raise ValueError("只有管理员或夜间主 agent 能建重复闹钟")
    try:
        trigger = CronTrigger.from_crontab(cron_expression, timezone=tz)
    except ValueError as exc:
        raise ValueError(f"重复规则不合法：{exc}") from exc
    cursor = datetime.fromtimestamp(now, tz)
    previous = None
    first = None
    # 一周逐分钟规则最多 10080 次；这里只校验重复频率，不限制 agent 工作量。
    for _ in range(10082):
        nxt = trigger.get_next_fire_time(previous, cursor)
        if nxt is None:
            break
        ts = nxt.timestamp()
        if first is None:
            first = ts
            if ts <= now + C.ALARM_MIN_LEAD_SECONDS:
                raise ValueError("首次执行时间必须晚于现在 5 分钟以后")
        if previous is not None and ts - previous.timestamp() < 3600:
            raise ValueError("重复闹钟相邻触发间隔不能短于 1 小时")
        if is_quiet_time(ts, tz) and not agreed:
            raise ValueError("重复规则包含深夜免打扰时段，必须填写约定理由")
        if first is not None and ts - first >= 8 * 86400:
            break
        previous = nxt
        cursor = nxt
    if first is None:
        raise ValueError("重复规则没有未来触发时间")
    return first


async def validate_alarm(
    payload: dict,
    qq: Any,
    tz: Any,
    *,
    allow_repeat: bool = True,
) -> tuple[dict, str]:
    """验证会话、平台、卡片和时间。私聊非好友只给提醒，不阻止创建。"""
    pid = qq.platform.default_platform_id()
    if not pid:
        raise ValueError("当前没有可用的 aiocqhttp 平台")
    result = dict(payload)
    result["target_umo"] = resolve_session_ref(payload.get("target_umo", ""), pid)
    _, kind, sid = parse_umo(result["target_umo"])
    warning = ""
    if kind == "GroupMessage":
        if sid not in await qq.group_ids():
            raise ValueError(f"我不在群 {sid} 里")
    elif sid not in await qq.friend_ids():
        warning = "对方不是好友，消息可能被 QQ 拦截"
    card = result.get("card") or {}
    for key in ("background", "purpose", "how"):
        if not str(card.get(key, "")).strip():
            raise ValueError(f"闹钟卡片缺少「{key}」")
    result["next_run_at"] = validate_alarm_time(
        result.get("run_at", ""),
        result.get("cron_expression", ""),
        card,
        tz,
        allow_repeat=allow_repeat,
    )
    return result, warning


async def validate_night_alarm_frequency(
    storage, payload: dict, tz, run_id: int, active=None
) -> None:
    """按本次运行和目标执行日计数，提交时再次检查长运行期间的变化。"""
    from ..timeutil import local_date_str

    active = active or []
    alarms = [
        a
        for a in await storage.alarms.list_alarms(-1)
        if a["status"] not in ("cancelled", "failed")
    ]
    if (
        sum(a["created_run_id"] == run_id for a in alarms) + len(active)
        >= C.RATE_ALARM_NIGHT_PER_RUN
    ):
        raise ValueError("本晚主动闹钟已达到频率上限")
    date = local_date_str(payload["next_run_at"], tz)
    count = 0
    for alarm in alarms:
        if alarm["target_umo"] != payload["target_umo"]:
            continue
        run_at = alarm["run_at"]
        if run_at is None and alarm["cron_expression"]:
            trigger = CronTrigger.from_crontab(alarm["cron_expression"], timezone=tz)
            fire = trigger.get_next_fire_time(
                None, datetime.fromtimestamp(utc_now(), tz)
            )
            run_at = fire.timestamp() if fire else None
        if run_at is not None and local_date_str(run_at, tz) == date:
            count += 1
    count += sum(
        a["target_umo"] == payload["target_umo"]
        and local_date_str(a["next_run_at"], tz) == date
        for a in active
    )
    if count >= C.RATE_ALARM_SAME_TARGET_PER_DAY:
        raise ValueError("同一目标每天的主动闹钟达到频率上限")
