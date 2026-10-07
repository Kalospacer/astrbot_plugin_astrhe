"""SilentNightEvent：夜间 agent 专用的静默事件。

重写 send / send_streaming：只丢弃并在 DEBUG 记录，绝不向任何会话发送消息。
这是「夜间全程无感」的代码层保证（硬性要求 9）。

注意：每次 agent 调用各用一个新对象，不要共用；role 保持默认 member。
"""

from __future__ import annotations

from typing import Any

from astrbot.core.cron.events import CronMessageEvent
from astrbot.core.platform.message_session import MessageSession


class SilentNightEvent(CronMessageEvent):
    """发送被静默的 CronMessageEvent。"""

    def __init__(self, *, discard_sink: list | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # 测试用：被丢弃的内容记录在这里（生产中传 None，只走 DEBUG 日志）
        self._discard_sink = discard_sink

    async def send(self, message) -> None:
        """静默：不发送，只记录。"""
        if self._discard_sink is not None:
            self._discard_sink.append(message)
        try:
            from astrbot.api import logger

            logger.debug("[AstrHe] 夜间静默事件拦截了一次 send")
        except Exception:  # noqa: BLE001
            pass

    async def send_streaming(self, generator, use_fallback: bool = False) -> None:
        """静默：消费掉生成器，不发送任何内容。"""
        try:
            async for chain in generator:
                if self._discard_sink is not None:
                    self._discard_sink.append(chain)
        except Exception:  # noqa: BLE001
            pass
        try:
            from astrbot.api import logger

            logger.debug("[AstrHe] 夜间静默事件拦截了一次 send_streaming")
        except Exception:  # noqa: BLE001
            pass


def make_silent_event(
    context: Any, umo: str, message: str = "", discard_sink: list | None = None
) -> SilentNightEvent:
    """按 UMO 构造一个静默事件。umo 为空时用虚拟会话。"""
    if umo:
        session = MessageSession.from_str(umo)
    else:
        from astrbot.core.platform.message_type import MessageType

        session = MessageSession(
            platform_name="astrhe",
            message_type=MessageType.FRIEND_MESSAGE,
            session_id="astrhe-night",
        )
    return SilentNightEvent(
        context=context,
        session=session,
        message=message or "夜间复盘",
        discard_sink=discard_sink,
    )
