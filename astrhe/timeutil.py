"""AstrHe 时间与日期工具。

统一约定：数据库存 UTC 时间戳（秒，float/int）；展示与「本地日期」语义
使用 AstrBot 配置的时区（取不到时用系统本地时区）。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from . import constants as C


def utc_now() -> float:
    """当前 UTC 时间戳（秒）。"""
    return time.time()


def get_config_timezone(config: Any) -> tzinfo:
    """从 AstrBot 配置取时区；取不到或非法时用系统本地时区。

    config 可以是 AstrBotConfig（dict 风格访问）或普通 dict。
    """
    tz_name = ""
    try:
        tz_name = str(config.get("timezone", "") or "") if config is not None else ""
    except Exception:  # noqa: BLE001 - 配置对象异常时退回本地时区
        tz_name = ""
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001 - 非法时区名退回本地时区
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def local_date_str(ts: float, tz: tzinfo) -> str:
    """时间戳转本地日期字符串 YYYY-MM-DD。"""
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


def local_datetime_str(ts: float, tz: tzinfo) -> str:
    """时间戳转本地时间字符串，含星期。"""
    dt = datetime.fromtimestamp(ts, tz)
    weekdays = "一二三四五六日"
    return f"{dt.strftime('%Y-%m-%d %H:%M')} 星期{weekdays[dt.weekday()]}"


def next_midnight_ts(now: float, tz: tzinfo) -> float:
    """计算下一个 00:00（配置时区）的 UTC 时间戳。"""
    dt = datetime.fromtimestamp(now, tz)
    nxt = (dt + timedelta(days=1)).replace(
        hour=C.NIGHT_RUN_HOUR, minute=C.NIGHT_RUN_MINUTE, second=0, microsecond=0
    )
    return nxt.timestamp()


def is_quiet_time(ts: float, tz: tzinfo) -> bool:
    """判断时刻是否落在深夜免打扰时段 00:30-08:00。"""
    dt = datetime.fromtimestamp(ts, tz)
    minutes = dt.hour * 60 + dt.minute
    return C.QUIET_HOURS_START_MINUTES <= minutes < C.QUIET_HOURS_END_MINUTES


def parse_run_at(value: str, tz: tzinfo) -> float:
    """解析用户给出的执行时间为 UTC 时间戳。

    支持 ISO 格式（可带时区偏移）与「YYYY-MM-DD HH:MM」本地写法。
    解析失败抛 ValueError。
    """
    text = (value or "").strip()
    if not text:
        raise ValueError("执行时间不能为空")
    # 兼容「YYYY-MM-DD HH:MM」
    normalized = text.replace(" ", "T", 1) if "T" not in text else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"无法解析执行时间: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.timestamp()


def format_run_at(ts: float, tz: tzinfo) -> str:
    """把时间戳格式化为带时区偏移的 ISO 字符串（供 add_active_job 的 run_at）。"""
    return datetime.fromtimestamp(ts, tz).isoformat()
