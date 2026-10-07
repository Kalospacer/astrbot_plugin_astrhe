"""白天工具：astrhe_todo_update（勾选待办）。

astrhe_read_plan 在 reader_tools.py 中与夜间共用。
"""

from __future__ import annotations

from typing import Any

from ..timeutil import local_date_str, utc_now


class DayTools:
    """白天工具的实现函数（工具壳在 runtime 装配时用 AstrHeFunctionTool 包）。"""

    def __init__(self, storage: Any, tz_getter):
        self.storage = storage
        self._tz_getter = tz_getter

    async def todo_update(
        self, event: Any, todo_id: int = 0, status: str = "", note: str = ""
    ) -> str:
        """astrhe_todo_update 的实现。"""
        try:
            todo_id = int(todo_id)
        except (TypeError, ValueError):
            return "todo_id 需要是数字"
        if status not in ("progress", "done", "dropped"):
            return "status 只能是 progress（有进展）/ done（完成）/ dropped（放弃）"
        umo = ""
        try:
            umo = event.unified_msg_origin
        except Exception:  # noqa: BLE001
            pass
        today = local_date_str(utc_now(), self._tz_getter())
        visible = await self.storage.plans.visible_todos(umo, today)
        target = next((t for t in visible if t["id"] == todo_id), None)
        if target is None:
            visible_ids = ", ".join(f"#{t['id']}" for t in visible) or "（无）"
            return f"找不到 #{todo_id}。这个会话可见的待办：{visible_ids}"
        await self.storage.plans.update_todo_status(todo_id, status, note)
        status_text = {"progress": "有进展", "done": "完成", "dropped": "放弃"}[status]
        suffix = f"，备注：{note}" if note else ""
        return f"已把 #{todo_id}「{target['content']}」标记为{status_text}{suffix}"

    @staticmethod
    def todo_update_tool() -> dict[str, Any]:
        """astrhe_todo_update 的工具元信息。"""
        return {
            "name": "astrhe_todo_update",
            "description": (
                "勾选待办：把某条待办标记为「有进展 / 完成 / 放弃」，可附备注。"
                "只能操作当前会话可见的待办（注入内容里带 #编号 的那些）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "待办编号（# 后面的数字）"},
                    "status": {
                        "type": "string",
                        "description": "progress（有进展）/ done（完成）/ dropped（放弃）",
                    },
                    "note": {"type": "string", "description": "备注，可空"},
                },
                "required": ["todo_id", "status"],
            },
        }
