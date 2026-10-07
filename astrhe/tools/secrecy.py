"""保密过滤：白天工具与注入共用。

规划书中的保密段落用 【保密:QQ1,QQ2】…【/保密】 包裹；待办与闹钟卡片
带 secret_from 字段。当前发送者属于保密对象、当前会话是与保密对象的私聊、
或保密对象在当前群「在场」（群成员或近 7 天发过言）时，保密内容不得出现。
"""

from __future__ import annotations

import re
from typing import Any

from .. import constants as C
from ..platform import parse_umo
from ..timeutil import utc_now

_SECRET_BLOCK = re.compile(
    re.escape(C.SECRET_MARK_OPEN_PREFIX) + r"([^】]*)】.*?" + re.escape(C.SECRET_MARK_CLOSE),
    re.DOTALL,
)
SECRET_PLACEHOLDER = "（保密内容）"


def parse_secret_mark(mark_content: str) -> list[str]:
    """解析标记里的 QQ 号列表，例如 '123,456'。"""
    return [x.strip() for x in re.split(r"[,，、\s]+", mark_content) if x.strip()]


def filter_secret_text(
    text: str,
    *,
    viewer_id: str,
    session_umo: str,
    present_ids: set[str],
) -> str:
    """把对当前查看者应保密的段落替换为占位符。

    viewer_id：当前发送者 QQ 号；session_umo：当前会话；present_ids：
    当前群里「在场」的 QQ 号集合（群成员或近期发言者），私聊给空集。
    """
    _, message_type, session_id = parse_umo(session_umo)

    def _replace(match: re.Match) -> str:
        secret_from = parse_secret_mark(match.group(1))
        if not secret_from:
            return SECRET_PLACEHOLDER
        # 发送者本人是保密对象
        if viewer_id and viewer_id in secret_from:
            return SECRET_PLACEHOLDER
        # 当前会话是与保密对象的私聊
        if message_type == "FriendMessage" and session_id in secret_from:
            return SECRET_PLACEHOLDER
        # 群聊：保密对象在场
        if message_type == "GroupMessage" and present_ids & set(secret_from):
            return SECRET_PLACEHOLDER
        return match.group(0)

    return _SECRET_BLOCK.sub(_replace, text)


def is_secret_visible_here(
    secret_from: list[str],
    *,
    viewer_id: str,
    session_umo: str,
    present_ids: set[str],
) -> bool:
    """判断带 secret_from 的条目是否应在当前会话出现（True = 可以出现）。"""
    if not secret_from:
        return True
    _, message_type, session_id = parse_umo(session_umo)
    if viewer_id and viewer_id in secret_from:
        return False
    if message_type == "FriendMessage" and session_id in secret_from:
        return False
    if message_type == "GroupMessage" and present_ids & set(secret_from):
        return False
    return True


class PresentResolver:
    """「在场」判定：群成员缓存 + 近 7 天发言记录。"""

    def __init__(self, storage: Any, qq_client: Any):
        self.storage = storage
        self.qq = qq_client
        # group_id -> (缓存时间戳, 成员 QQ 集合)
        self._member_cache: dict[str, tuple[float, set[str]]] = {}

    async def present_ids(self, umo: str) -> set[str]:
        """当前会话中「在场」的 QQ 号集合；私聊返回空集。"""
        _, message_type, session_id = parse_umo(umo)
        if message_type != "GroupMessage" or not session_id:
            return set()
        ids: set[str] = set()
        # 群成员列表（带缓存）
        now = utc_now()
        cached = self._member_cache.get(session_id)
        if cached and now - cached[0] < C.GROUP_MEMBER_CACHE_TTL:
            ids |= cached[1]
        else:
            try:
                members = await self.qq.call(
                    "get_group_member_list", group_id=int(session_id)
                )
                member_ids = {
                    str(m.get("user_id")) for m in members or [] if m.get("user_id")
                }
                self._member_cache[session_id] = (now, member_ids)
                ids |= member_ids
            except Exception:  # noqa: BLE001 - 取不到成员列表就只靠发言记录
                pass
        # 近 7 天在该会话发过言的人
        ids |= await self.storage.ledger.speaker_ids_since(
            umo, now - C.SECRET_PRESENT_SPEAK_DAYS * 86400
        )
        return ids

    def refresh_member_cache_nightly(self) -> None:
        """夜间刷新缓存：直接清空，白天用到再拉。"""
        self._member_cache.clear()


def wrap_secret(text: str, secret_from: list[str]) -> str:
    """把一段文本包上保密标记（主 agent 提示词里也会要求它自己包）。"""
    ids = ",".join(secret_from)
    return f"{C.SECRET_MARK_OPEN_PREFIX}{ids}】{text}{C.SECRET_MARK_CLOSE}"
