"""白天注入：on_llm_request 里隐藏 future_task，并把该会话的待办与
规划段落作为临时内容追加到请求末尾（不写进对话历史，保护前缀缓存）。

组装顺序（总长超 600 字时从第 5 项往前截断，陈旧提示不参与截断）：
1. 陈旧提示（上次运行失败时才有）
2. 保密提醒（当前会话有保密对象「在场」时）
3. 本会话的规划段落
4. 本会话可见的待办（今天的、逾期的、已到 show_from 的未来待办）
5. 1-2 条自我反思
"""

from __future__ import annotations

import json
from typing import Any

from . import constants as C
from .timeutil import local_date_str, utc_now
from .tools.secrecy import filter_secret_text, is_secret_visible_here

try:
    from astrbot.core.agent.message import TextPart
except Exception:  # pragma: no cover
    TextPart = None  # type: ignore[assignment]


class Injector:
    def __init__(
        self,
        storage: Any,
        tz_getter,
        secrecy_resolver: Any,
        enabled_getter,
        logger: Any,
    ):
        self.storage = storage
        self._tz_getter = tz_getter
        self.secrecy = secrecy_resolver
        self._enabled_getter = enabled_getter
        self.logger = logger

    def _enabled(self) -> bool:
        try:
            return bool(self._enabled_getter())
        except Exception:  # noqa: BLE001
            return False

    async def on_llm_request(self, event: Any, req: Any) -> None:
        if not self._enabled():
            return
        try:
            self._hide_future_task(req)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"[AstrHe] 隐藏 future_task 失败: {exc}")
        try:
            await self._inject(event, req)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"[AstrHe] 注入失败: {exc}")

    @staticmethod
    def _hide_future_task(req: Any) -> None:
        func_tool = getattr(req, "func_tool", None)
        if func_tool is None:
            return
        tools = getattr(func_tool, "tools", None)
        if isinstance(tools, list):
            func_tool.tools = [t for t in tools if getattr(t, "name", "") != "future_task"]

    async def build_injection(self, umo: str, viewer_id: str) -> str:
        """组装注入文本；没有内容时返回空串。单独抽出来方便测试。"""
        tz = self._tz_getter()
        today = local_date_str(utc_now(), tz)
        present = await self.secrecy.present_ids(umo)

        # 1. 陈旧提示：上次运行失败，且昨晚没提交新计划
        stale = ""
        latest_run = await self.storage.runs.latest_run()
        latest_plan = await self.storage.plans.get_latest_plan()
        if latest_run and latest_run["status"] == "failed" and latest_plan:
            stale = (
                f"（昨晚的复盘没完成，下面的计划来自 {latest_plan['plan_date']}）\n"
            )

        # 2. 保密提醒
        secrecy_notes: list[str] = []
        for todo in await self.storage.plans.open_todos():
            secret_from = json.loads(todo["secret_from_json"] or "[]")
            if not secret_from:
                continue
            visible = json.loads(todo["visible_umos_json"] or "[]")
            if umo not in visible:
                continue
            if not is_secret_visible_here(
                secret_from, viewer_id=viewer_id, session_umo=umo, present_ids=present
            ):
                # 保密对象在场：提醒引导私聊
                # 提醒本身不含待办内容，避免变相泄密
                if not secrecy_notes:  # 提醒只贴一次
                    secrecy_notes.append(
                        "注意：有些事要对现在这个群里在场的人保密；被问起时引导对方"
                        "私聊或岔开话题，不要在这里说。"
                    )

        # 3. 规划段落
        section = await self.storage.plans.get_section_for_umo(umo)
        section = filter_secret_text(
            section, viewer_id=viewer_id, session_umo=umo, present_ids=present
        )

        # 4. 待办
        todos = await self.storage.plans.visible_todos(umo, today)
        todo_lines = []
        for t in todos:
            if not is_secret_visible_here(
                json.loads(t["secret_from_json"] or "[]"),
                viewer_id=viewer_id, session_umo=umo, present_ids=present,
            ):
                continue
            mark = "（未来）" if t["due_kind"] == "future" else ""
            todo_lines.append(f"#{t['id']}{mark} {t['content']}")
        todos_text = "\n".join(todo_lines)

        # 5. 自我反思
        reflection = ""
        if latest_plan and latest_plan["reflection"]:
            lines = [line.strip() for line in latest_plan["reflection"].splitlines() if line.strip()]
            reflection = "\n".join(lines[:2])

        if not (stale or secrecy_notes or section or todos_text or reflection):
            return ""

        # 组装：陈旧提示预留固定空间不参与截断；其余从第 5 项往前截断
        body_parts = []
        if secrecy_notes:
            body_parts.append("\n".join(secrecy_notes))
        if section:
            body_parts.append(f"今天的规划（和这里相关的部分）：\n{section}")
        if todos_text:
            body_parts.append(f"待办：\n{todos_text}")
        if reflection:
            body_parts.append(f"自我提醒：\n{reflection}")

        budget = C.INJECT_MAX_CHARS
        # 从最后一项往前丢；单项仍然超长时硬截断
        body = ""
        while body_parts:
            candidate = "\n".join(body_parts)
            if len(candidate) <= budget:
                body = candidate
                break
            body_parts.pop()
        else:
            body = ""
        if not body and section:
            # 只剩超长规划段落：截断到预算内
            body = f"今天的规划（和这里相关的部分）：\n{section[: budget - 30]}…"
        return stale + body

    async def _inject(self, event: Any, req: Any) -> None:
        if TextPart is None:
            return
        try:
            umo = event.unified_msg_origin
            viewer_id = str(event.get_sender_id())
        except Exception:  # noqa: BLE001
            return
        text = await self.build_injection(umo, viewer_id)
        if not text:
            return
        part = TextPart(text=text)
        part.mark_as_temp()
        req.extra_user_content_parts.append(part)
