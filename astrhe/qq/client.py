"""QQ 接口封装：平台检查与错误转译。

只封装计划允许的第一批接口；以下接口永不封装：
get_cookies / get_credentials / get_clientkey / get_csrf_token / get_rkey /
send_packet / delete_friend / set_group_leave / set_restart / bot_exit。
"""

from __future__ import annotations

import re
from typing import Any

from ..platform import PlatformHelper

_MSG_NOT_FOUND = re.compile(r"msg not found|消息不存在", re.IGNORECASE)


class QQClient:
    """对 PlatformHelper 的薄封装：统一错误转译。"""

    def __init__(self, platform: PlatformHelper):
        self.platform = platform

    async def call(self, action: str, **params) -> Any:
        return await self.platform.call_action(action, **params)

    async def call_friendly(self, action: str, **params) -> tuple[bool, Any]:
        """调用并转译常见错误，返回 (ok, result_or_error_text)。"""
        try:
            return True, await self.platform.call_action(action, **params)
        except RuntimeError as exc:
            text = str(exc)
            if _MSG_NOT_FOUND.search(text):
                return False, "这条消息太久了，贴不了表情"
            return False, text

    async def group_ids(self) -> set[str] | None:
        """bot 所在的群号集合；失败返回 None，区别于确实没有群。"""
        try:
            groups = await self.call("get_group_list")
            if not isinstance(groups, list):
                return None
            return {str(g.get("group_id")) for g in groups if g.get("group_id")}
        except Exception:  # noqa: BLE001
            return None

    async def friend_ids(self) -> set[str] | None:
        """好友 QQ 号集合；失败返回 None，区别于确实没有好友。"""
        try:
            friends = await self.call("get_friend_list")
            if not isinstance(friends, list):
                return None
            return {str(f.get("user_id")) for f in friends if f.get("user_id")}
        except Exception:  # noqa: BLE001
            return None

    async def self_id(self) -> str:
        try:
            info = await self.call("get_login_info")
            return str(info.get("user_id", "") or "")
        except Exception:  # noqa: BLE001
            return ""
