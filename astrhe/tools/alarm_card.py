"""闹钟卡片与面板描述：总结按写入的目标会话决定保密范围。"""

from typing import Any

from ..platform import parse_umo

STANDARD_NOTE_SUFFIX = (
    "\n\n【标准操作说明】发送消息用 send_message_to_user：session 留空表示当前会话"
    "（即本任务的目标会话）。这条任务只在本任务的目标会话里说话，不要给其他会话"
    "（包括别人的私聊）发消息，那些地方另有各自的任务负责。需要 @ 某人时，在消息里用 mention_user 组件"
    "（mention_user_id=对方 QQ 号）。对方回复时，参考 AstrHe 待办里属于这个会话的内容。"
    "卡片里写的日期时刻都是绝对时间，不是相对现在说的：跟人说话前先对照当前时间，"
    "换算成「今晚」「明早」这类对方听得懂的说法，别把零点说错日子（X 号零点就是 X-1 号晚上 12 点）。"
    "新建或修改定时任务请用 astrhe_schedule，不要用 future_task。"
)


def render_card_note(card: dict[str, Any], target_umo: str) -> str:
    """完整卡片只供唤醒执行；最终总结会进入目标会话历史。"""
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
    _, kind, sid = parse_umo(target_umo)
    secret_from = set(map(str, card.get("secret_from") or []))
    if secret_from and (kind == "GroupMessage" or sid in secret_from):
        summary = "执行完的总结只写一句『已完成』，不要复述卡片里的内容。"
    else:
        summary = (
            "执行完的总结要写清实际发出的消息内容及发送是否成功；"
            "不要复述卡片里的背景、保密对象或禁忌，不要泄露保密内容。"
        )
    return "\n".join(lines) + STANDARD_NOTE_SUFFIX + summary


def alarm_description(card: dict, alarm_id: int) -> str:
    return (
        f"AstrHe 闹钟 #{alarm_id}"
        if card.get("secret_from")
        else str(card.get("purpose", ""))
    )
