"""astrhe_qq_lookup：QQ 只读查询工具（白天与夜间共用）。

action: find_member / user_info / is_friend / groups / group_honor /
        essence / get_msg / get_forward
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..platform import is_valid_qq

try:
    from astrbot.api import FunctionTool
except Exception:  # pragma: no cover
    FunctionTool = None  # type: ignore[assignment]

TOOL_NAME = "astrhe_qq_lookup"

_ACTIONS = (
    "find_member（在某群按昵称或群名片找人，参数 group_id、keyword）\n"
    "user_info（查某人资料，参数 user_id）\n"
    "is_friend（查某人是否已是好友，参数 user_id）\n"
    "groups（列出我所在的全部群）\n"
    "group_honor（群荣誉：龙王、群聊之火等，参数 group_id）\n"
    "essence（群精华消息，参数 group_id）\n"
    "get_msg（按消息 id 取原文，参数 message_id）\n"
    "get_forward（展开合并转发，参数 forward_id）"
)


def _tool_base_class():
    return FunctionTool if FunctionTool is not None else object


@dataclass
class QQLookupTool(_tool_base_class()):  # type: ignore[misc]
    """QQ 只读查询工具。"""

    qq_client: Any = None
    name: str = TOOL_NAME
    description: str = "QQ 查询工具（只读，不会产生任何动作）。可用动作：\n" + _ACTIONS
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "动作名，见工具描述"},
                "keyword": {
                    "type": "string",
                    "description": "find_member 的昵称或群名片关键词",
                },
                "group_id": {"type": "string", "description": "群号"},
                "user_id": {"type": "string", "description": "QQ 号"},
                "message_id": {"type": "string", "description": "消息 id"},
                "forward_id": {"type": "string", "description": "合并转发 id"},
            },
            "required": ["action"],
        }
    )

    async def run(self, event: Any, action: str = "", **kwargs: Any) -> str:
        try:
            return await self._dispatch(action, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return f"查询失败: {exc}"

    async def _dispatch(self, action: str, **kwargs: Any) -> str:
        qq = self.qq_client
        if action == "find_member":
            return await self._find_member(
                kwargs.get("group_id", ""), kwargs.get("keyword", "")
            )
        if action == "user_info":
            user_id = str(kwargs.get("user_id", ""))
            if not is_valid_qq(user_id):
                return "user_id 需要是 5-12 位数字的 QQ 号"
            info = await qq.call("get_stranger_info", user_id=int(user_id))
            nickname = info.get("nickname", "")
            return f"QQ {user_id}：昵称 {nickname}"
        if action == "is_friend":
            user_id = str(kwargs.get("user_id", ""))
            friends = await qq.friend_ids()
            if friends is None:
                return "平台暂时不可用，无法确认好友关系"
            return (
                f"QQ {user_id} 是好友"
                if user_id in friends
                else f"QQ {user_id} 不是好友，私聊可能被 QQ 拦截"
            )
        if action == "groups":
            groups = await qq.call("get_group_list")
            lines = [
                f"{g.get('group_id')} {g.get('group_name', '')}" for g in groups or []
            ]
            return "我所在的群：\n" + ("\n".join(lines) if lines else "（没有群）")
        if action == "group_honor":
            group_id = str(kwargs.get("group_id", ""))
            result = await qq.call(
                "get_group_honor_info", group_id=int(group_id), type="all"
            )
            return f"群 {group_id} 荣誉信息：{result}"
        if action == "essence":
            group_id = str(kwargs.get("group_id", ""))
            result = await qq.call("get_essence_msg_list", group_id=int(group_id))
            items = (
                result
                if isinstance(result, list)
                else (result or {}).get("msg_list", [])
            )
            return f"群 {group_id} 精华消息共 {len(items)} 条"
        if action == "get_msg":
            message_id = str(kwargs.get("message_id", ""))
            result = await qq.call("get_msg", message_id=int(message_id))
            return f"消息 {message_id}：{result}"
        if action == "get_forward":
            forward_id = str(kwargs.get("forward_id", ""))
            result = await qq.call("get_forward_msg", id=forward_id)
            messages = (result or {}).get("messages", [])
            return f"合并转发 {forward_id} 共 {len(messages)} 条消息"
        return f"不认识的查询动作: {action}。可用动作见工具描述。"

    async def _find_member(self, group_id: str, keyword: str) -> str:
        if not group_id or not keyword:
            return "find_member 需要 group_id 和 keyword 两个参数"
        members = await self.qq_client.call(
            "get_group_member_list", group_id=int(group_id), no_cache=True
        )
        hits = []
        for m in members or []:
            card = str(m.get("card", "") or "")
            nickname = str(m.get("nickname", "") or "")
            if keyword in card or keyword in nickname:
                hits.append(f"{m.get('user_id')} 名片「{card}」昵称「{nickname}」")
        if not hits:
            return f"群 {group_id} 里没找到名字含「{keyword}」的人"
        return "找到这些成员：\n" + "\n".join(hits)
