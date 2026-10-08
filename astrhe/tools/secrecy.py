"""保密过滤：白天工具与注入共用。

规划书中的保密段落用 【保密:QQ1,QQ2】…【/保密】 包裹；待办与闹钟卡片
带 secret_from 字段。当前发送者属于保密对象、当前会话是与保密对象的私聊、
或保密对象在当前群「在场」（群成员或近 7 天发过言）时，保密内容不得出现。
"""

from __future__ import annotations

import re
from typing import Any

from .. import constants as C
from ..platform import is_valid_qq, parse_umo
from ..timeutil import utc_now

_SECRET_BLOCK = re.compile(
    r"【保密[:：]\s*([^】]*)】.*?" + re.escape(C.SECRET_MARK_CLOSE),
    re.DOTALL,
)
SECRET_PLACEHOLDER = "（保密内容）"


def secret_ids(text: str) -> set[str]:
    return {
        qq
        for m in _SECRET_BLOCK.finditer(text or "")
        for qq in parse_secret_mark(m.group(1))
    }


def normalize_secret_text(text: str) -> str:
    """规范标记；残缺或无法识别的保密标记拒绝入草稿。"""
    if not isinstance(text, str):
        raise ValueError("段落需要是文本")
    for match in _SECRET_BLOCK.finditer(text):
        ids = parse_secret_mark(match.group(1))
        if not ids or not all(q.isdigit() for q in ids):
            raise ValueError("保密标记需填写 QQ 号：【保密:QQ号】内容【/保密】")
    remainder = _SECRET_BLOCK.sub("", text)
    if "【保密" in remainder or "【/保密" in remainder:
        raise ValueError("保密标记不完整，请用【保密:QQ号】内容【/保密】")
    return re.sub(
        r"【保密[:：]\s*([^】]*)】",
        lambda m: "【保密:" + ",".join(parse_secret_mark(m.group(1))) + "】",
        text,
    )


def normalize_qq_ids(value: Any) -> list[str]:
    """把保密对象等身份列表统一成 QQ 号字符串。

    模型常把 QQ 号写成不带引号的数字数组，存成整数后与字符串比较永远失配，
    保密会整体失效，所以入库前统一转字符串，并拒绝非 QQ 号的写法。
    """
    if value is None or value == "":
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    ids = [str(x).strip() for x in items if str(x).strip()]
    bad = [x for x in ids if not is_valid_qq(x)]
    if bad:
        raise ValueError(
            f"保密对象和要 @ 的人都要写 QQ 号码，无法识别：{'、'.join(bad)}"
        )
    return list(dict.fromkeys(ids))


def _id_set(values: Any) -> set[str]:
    """读取端兼容旧数据里存成整数的 QQ 号。"""
    return {str(x).strip() for x in values or [] if str(x).strip()}


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
    当前群里「在场」的 QQ 号集合（群成员或近期发言者），私聊给空集；
    为 None 表示查不清谁在场，群里的保密内容一律遮挡。
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
        # 群聊：保密对象在场，或查不清谁在场
        if message_type == "GroupMessage" and (
            present_ids is None or present_ids & set(secret_from)
        ):
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
    secret = _id_set(secret_from)
    if not secret:
        return True
    _, message_type, session_id = parse_umo(session_umo)
    if viewer_id and str(viewer_id) in secret:
        return False
    if message_type == "FriendMessage" and session_id in secret:
        return False
    if message_type == "GroupMessage" and (present_ids is None or present_ids & secret):
        return False
    return True


class PresentResolver:
    """「在场」判定：群成员缓存 + 近 7 天发言记录。"""

    def __init__(self, storage: Any, qq_client: Any):
        self.storage = storage
        self.qq = qq_client
        # group_id -> (缓存时间戳, 成员 QQ 集合)
        self._member_cache: dict[str, tuple[float, set[str]]] = {}

    async def present_ids(self, umo: str) -> set[str] | None:
        """当前会话中「在场」的 QQ 号集合；私聊返回空集。

        群成员列表查不到、也没有旧缓存时返回 None（查不清谁在场），
        由调用方按「可能在场」遮挡保密内容，不能只凭近期发言判断。
        """
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
                if not isinstance(members, list):
                    raise ValueError("群成员列表格式不对")
                member_ids = {
                    str(m.get("user_id")) for m in members if m.get("user_id")
                }
                self._member_cache[session_id] = (now, member_ids)
                ids |= member_ids
            except Exception:  # noqa: BLE001 - 查询失败时退回旧缓存
                if cached is None:
                    return None
                ids |= cached[1]
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
