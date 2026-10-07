"""平台相关工具：aiocqhttp client 获取、UMO 解析与构造、会话规范化。"""

from __future__ import annotations

import re
from typing import Any

#: UMO 格式：{platform_id}:{MessageType}:{session_id}
#: 例如 default:GroupMessage:12345 / default:FriendMessage:67890

_QQ_ID_PATTERN = re.compile(r"^\d{5,12}$")


def parse_umo(umo: str) -> tuple[str, str, str]:
    """拆 UMO 为 (platform_id, message_type, session_id)。不合法返回空串三元组。"""
    parts = (umo or "").split(":", 2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0], parts[1], parts[2]


def normalize_session_id(message_type: str, session_id: str) -> str:
    """规范化 session_id。

    unique_session 开启时，群消息的 session_id 形如 {sender_id}_{group_id}，
    拆出真正的群号，让账本、待办可见性、闹钟目标都按「会话」而不是「个人」对齐。
    私聊 session_id 就是 QQ 号，不动。
    """
    if message_type == "GroupMessage" and "_" in session_id:
        # aiocqhttp 的 unique_session 格式为 sender_group（QQ 号纯数字，无下划线）
        maybe_group = session_id.split("_", 1)[1]
        if _QQ_ID_PATTERN.match(maybe_group):
            return maybe_group
    return session_id


def build_umo(platform_id: str, message_type: str, session_id: str) -> str:
    """构造规范化 UMO（自动处理 unique_session 的群 session_id）。"""
    sid = normalize_session_id(message_type, session_id)
    return f"{platform_id}:{message_type}:{sid}"


def group_umo(platform_id: str, group_id: str) -> str:
    return f"{platform_id}:GroupMessage:{group_id}"


def friend_umo(platform_id: str, user_id: str) -> str:
    return f"{platform_id}:FriendMessage:{user_id}"


def is_valid_qq(value: str) -> bool:
    return bool(_QQ_ID_PATTERN.match(value or ""))


class PlatformHelper:
    """从 context 取 aiocqhttp 适配器与 client；所有 QQ 接口调用走这里。"""

    def __init__(self, context: Any, logger: Any):
        self.context = context
        self.logger = logger

    def get_aiocqhttp_platforms(self) -> list[Any]:
        """所有 aiocqhttp 平台实例（按 meta().name 判断）。"""
        result = []
        manager = getattr(self.context, "platform_manager", None)
        insts = getattr(manager, "platform_insts", []) if manager else []
        for inst in insts or []:
            try:
                meta = inst.meta()
            except Exception:  # noqa: BLE001
                continue
            if getattr(meta, "name", "") == "aiocqhttp":
                result.append(inst)
        return result

    def get_client(self, platform_id: str | None = None) -> Any | None:
        """取 aiocqhttp 的 CQHttp client。

        指定 platform_id 时取对应实例；否则取第一个 aiocqhttp 实例
        （单 NapCat 账号场景下没有事件时也可用）。
        """
        if platform_id:
            inst = self.context.get_platform_inst(platform_id)
            if inst is not None:
                try:
                    if inst.meta().name == "aiocqhttp":
                        return inst.get_client()
                except Exception:  # noqa: BLE001
                    return None
            return None
        platforms = self.get_aiocqhttp_platforms()
        if not platforms:
            return None
        try:
            return platforms[0].get_client()
        except Exception:  # noqa: BLE001
            return None

    def default_platform_id(self) -> str:
        """第一个 aiocqhttp 平台的 id，取不到返回空串。"""
        platforms = self.get_aiocqhttp_platforms()
        if not platforms:
            return ""
        try:
            return str(platforms[0].meta().id)
        except Exception:  # noqa: BLE001
            return ""

    async def call_action(self, action: str, **params) -> Any:
        """调用 OneBot 接口；失败时抛 RuntimeError 并带可读信息。"""
        client = self.get_client()
        if client is None:
            raise RuntimeError("当前没有可用的 aiocqhttp 平台（仅支持 NapCat）")
        try:
            return await client.api.call_action(action, **params)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"QQ 接口 {action} 调用失败: {exc}") from exc
