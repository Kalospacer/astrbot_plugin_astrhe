"""频率上限：基于 action_log 表统计。

所有「活人感」动作与闹钟创建都经过这里。规则见 constants.py 的 RATE_* 常量。
"""

from __future__ import annotations

from datetime import datetime

from .. import constants as C
from ..storage import Storage
from ..timeutil import local_datetime_str


def _day_start_ts(now_ts: float, tz) -> float:
    dt = datetime.fromtimestamp(now_ts, tz)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _hour_start_ts(now_ts: float, tz) -> float:
    dt = datetime.fromtimestamp(now_ts, tz)
    return dt.replace(minute=0, second=0, microsecond=0).timestamp()


class RateLimiter:
    """频率上限检查与记账。"""

    def __init__(self, storage: Storage, tz_getter):
        self.storage = storage
        self._tz_getter = tz_getter

    def _tz(self):
        return self._tz_getter()

    async def check(
        self, action: str, now_ts: float, *, target: str = "", umo: str = ""
    ) -> str:
        """检查动作是否允许执行；允许返回空串，否则返回给模型看的拒绝理由。"""
        ledger = self.storage.ledger
        tz = self._tz()
        day_start = _day_start_ts(now_ts, tz)
        hour_start = _hour_start_ts(now_ts, tz)

        if action == "react":
            n = await ledger.count_actions("react", hour_start, umo=umo)
            if n >= C.RATE_REACT_PER_SESSION_PER_HOUR:
                return "这个会话这小时贴表情够多了，歇一会儿吧"
        elif action == "poke":
            n_user = await ledger.count_actions("poke", day_start, target=target)
            if n_user >= C.RATE_POKE_PER_USER_PER_DAY:
                return "今天戳过这个人好几次了，再戳要被嫌弃了"
            n_all = await ledger.count_actions("poke", day_start)
            if n_all >= C.RATE_POKE_GLOBAL_PER_DAY:
                return "今天戳一戳次数用完了"
        elif action == "like":
            n_user = await ledger.count_actions("like", day_start, target=target)
            if n_user >= C.RATE_LIKE_PER_USER_PER_DAY:
                return "今天已经给这个人点过赞了"
            n_all = len(await ledger.distinct_action_targets("like", day_start))
            if n_all >= C.RATE_LIKE_GLOBAL_PER_DAY:
                return "今天点赞的人数到上限了"
        elif action == "signature":
            next_ts = await self.next_signature_ts()
            if next_ts > now_ts:
                return (
                    f"签名 {C.RATE_SIGNATURE_INTERVAL_DAYS} 天内最多换一次，"
                    f"{local_datetime_str(next_ts, tz)} 以后才能再换"
                )
        elif action == "status":
            n = await ledger.count_actions("status", hour_start)
            if n >= C.RATE_STATUS_PER_HOUR:
                return "这小时在线状态换过两次了，等会儿再换"
        return ""

    async def record(self, action: str, *, target: str = "", umo: str = "") -> None:
        await self.storage.ledger.log_action(action, target=target, umo=umo)

    async def next_signature_ts(self) -> float:
        """最早可以再换签名的时间；从没换过返回 0。"""
        last = await self.storage.ledger.last_action("signature")
        if not last:
            return 0.0
        return float(last["ts"]) + C.RATE_SIGNATURE_INTERVAL_DAYS * 86400

    async def check_alarm_creation(
        self, *, origin: str, target_umo: str, creator_id: str, now_ts: float
    ) -> str:
        """闹钟创建频率检查；允许返回空串。"""
        alarms = self.storage.alarms
        tz = self._tz()
        day_start = _day_start_ts(now_ts, tz)
        if origin == "night":
            n = await alarms.count_created_since(day_start, origin="night")
            if n >= C.RATE_ALARM_NIGHT_PER_RUN:
                return "今晚新建的主动闹钟够多了，剩下的写进规划书明天再说"
            n_target = await alarms.count_created_since(day_start, target_umo=target_umo)
            if n_target >= C.RATE_ALARM_SAME_TARGET_PER_DAY:
                return "今天给这个会话定的闹钟够多了"
        else:
            n_session = await alarms.count_created_since(
                day_start, origin="day", target_umo=target_umo
            )
            if n_session >= C.RATE_ALARM_DAY_PER_SESSION:
                return "这个会话今天建的闹钟到上限了"
            n_all = await alarms.count_created_since(day_start, origin="day")
            if n_all >= C.RATE_ALARM_DAY_GLOBAL_PER_DAY:
                return "今天建的闹钟总数到上限了"
        return ""
