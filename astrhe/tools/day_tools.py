"""白天工具：待办新增、修改、勾选、读取与规划维护。

astrhe_read_plan 在 reader_tools.py 中与夜间共用。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .. import constants as C
from ..platform import event_umo, is_admin_private, parse_umo, resolve_session_ref
from ..timeutil import local_date_str, utc_now
from .base import AstrHeFunctionTool
from .day_scope import session_labels, todo_not_found, todos_for_view
from .memory_readers import page_footer
from .secrecy import filter_secret_text, normalize_secret_text
from .todo_fields import normalize_todo_fields


class DayTools:
    """白天工具的实现函数（工具壳在 runtime 装配时用 AstrHeFunctionTool 包）。"""

    def __init__(
        self,
        storage: Any,
        tz_getter,
        secrecy_resolver: Any = None,
        platform: Any = None,
    ):
        self.storage = storage
        self._tz_getter = tz_getter
        self.secrecy = secrecy_resolver
        self.platform = platform

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
        visible = await self._todos(event)
        target = next((t for t in visible if t["id"] == todo_id), None)
        if target is None:
            return todo_not_found(todo_id, visible)
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
                "管理员私聊（含自主心跳）可操作全部未完成待办，其他会话只操作当前可见的；保密待办仍不可见。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "待办编号（# 后面的数字）",
                    },
                    "status": {
                        "type": "string",
                        "description": "progress（有进展）/ done（完成）/ dropped（放弃）",
                    },
                    "note": {"type": "string", "description": "备注，可空"},
                },
                "required": ["todo_id", "status"],
            },
        }

    async def _todos(self, event: Any, status: str = "open") -> list[dict[str, Any]]:
        umo = event_umo(event)
        present = (
            await self.secrecy.present_ids(umo) if self.secrecy is not None else None
        )
        return await todos_for_view(
            self.storage,
            umo=umo,
            viewer_id=str(event.get_sender_id()),
            present_ids=present,
            tz=self._tz_getter(),
            full_view=is_admin_private(event),
            status=status,
        )

    def _resolve(self, event: Any, ref: str) -> str:
        pid = parse_umo(event_umo(event))[0]
        if not pid and self.platform is not None:
            pid = self.platform.default_platform_id()
        return resolve_session_ref(ref, pid)

    async def todo_add(
        self,
        event: Any,
        content: str = "",
        visible_umos: str = "",
        secret_from: str = "",
        due_kind: str = "today",
        due_date: str = "",
        show_from: str = "",
        note: str = "",
    ) -> str:
        fields = normalize_todo_fields(
            dict(
                content=content,
                visible_umos=visible_umos,
                secret_from=secret_from,
                due_kind=due_kind,
                due_date=due_date,
                show_from=show_from,
                note=note,
            ),
            resolve=lambda ref: self._resolve(event, ref),
            default_date=local_date_str(utc_now(), self._tz_getter()),
            default_umos=[event_umo(event)],
        )
        todo_id = await self.storage.plans.add_todo(
            **fields, created_run_id=None, evidence=["白天新增"]
        )
        labels = await session_labels(self.storage, fields["visible_umos"])
        umo = event_umo(event)
        present = (
            await self.secrecy.present_ids(umo) if self.secrecy is not None else None
        )
        text = filter_secret_text(
            fields["content"],
            viewer_id=str(event.get_sender_id()),
            session_umo=umo,
            present_ids=present,
        )
        return f"已新增 #{todo_id}「{text}」，挂在：{labels}"

    async def todo_edit(self, event: Any, todo_id: int = 0, **fields: Any) -> str:
        todo_id = int(todo_id)
        visible = await self._todos(event)
        target = next((t for t in visible if t["id"] == todo_id), None)
        if target is None:
            return todo_not_found(todo_id, visible)
        if not fields:
            return "请提供要修改的待办字段"
        normalized = normalize_todo_fields(
            fields,
            resolve=lambda ref: self._resolve(event, ref),
            default_date=local_date_str(utc_now(), self._tz_getter()),
            default_umos=[event_umo(event)],
            current=target,
        )
        await self.storage.plans.update_todo_fields(todo_id, **normalized)
        return f"已修改 #{todo_id}，调整字段：{'、'.join(normalized)}"

    async def read_todos(
        self, event: Any, status: str = "open", offset: int = 0
    ) -> str:
        if status not in ("open", "done", "dropped", "all"):
            return "status 只能是 open（含 progress）/ done / dropped / all"
        visible = await self._todos(event, status)
        offset = max(0, int(offset))
        rows = visible[offset : offset + C.MEMORY_ITEM_PAGE_SIZE]
        lines = []
        for row in rows:
            labels = await session_labels(
                self.storage, json.loads(row["visible_umos_json"] or "[]")
            )
            lines.append(
                f"#{row['id']} [{row['status']}] {row['content']}"
                f"（{row['due_kind']} {row['due_date'] or '无日期'}，"
                f"显示起日 {row['show_from'] or '未指定'}，挂在：{labels}）\n"
                f"备注：{row['note'] or '无'}"
            )
        return (
            f"待办列表（{status}，共 {len(visible)} 条，本页 {len(rows)} 条）：\n"
            + "\n".join(lines)
            + page_footer(len(visible), offset, len(rows))
        )

    async def plan_edit(
        self,
        event: Any,
        field: str = "",
        text: str = "",
        mode: str = "append",
        umo: str = "",
    ) -> str:
        plan = await self.storage.plans.get_latest_plan()
        if not plan:
            return "还没有规划书，今晚复盘后才有"
        if field not in ("full_text", "day_reminders", "section"):
            return "field 只能是 full_text / day_reminders / section"
        if mode not in ("append", "replace"):
            return "mode 只能是 append / replace"
        current_umo = event_umo(event)
        target_umo = (
            self._resolve(event, umo or current_umo) if field == "section" else ""
        )
        if not is_admin_private(event) and (
            field != "section" or target_umo != current_umo
        ):
            return "这里只能修改本会话的规划段落；全文、自我提醒和其他会话段落只在管理员私聊里能改"
        text = normalize_secret_text(text)
        if field == "section":
            old = (await self.storage.plans.get_sections(plan["id"])).get(
                target_umo, ""
            )
        else:
            old = plan[field]
        if mode == "append":
            when = datetime.fromtimestamp(utc_now(), self._tz_getter()).strftime(
                "%H:%M"
            )
            text = (old + "\n" if old else "") + f"（{when} 白天调整）" + text
        if field == "section":
            await self.storage.plans.update_section(plan["id"], target_umo, text)
        else:
            await self.storage.plans.update_plan_field(plan["id"], field, text)
        return f"已{'追加' if mode == 'append' else '替换'}规划书（{plan['plan_date']}）的 {field}"

    def build(self) -> list[AstrHeFunctionTool]:
        """装配白天工具壳；不会加入夜间白名单。"""
        fields = {
            "content": {
                "type": "string",
                "description": "待办内容，不能为空；支持保密标记",
            },
            "visible_umos": {
                "type": "string",
                "description": "会话 JSON 数组；可用 group:群号 / private:QQ号，空时挂当前会话",
            },
            "secret_from": {
                "type": "string",
                "description": "保密对象 QQ 号 JSON 数组，空时不保密",
            },
            "due_kind": {
                "type": "string",
                "enum": ["today", "future", "deadline"],
                "description": "日期类型，新增默认 today",
            },
            "due_date": {"type": "string", "description": "YYYY-MM-DD，新增默认今天"},
            "show_from": {
                "type": "string",
                "description": "YYYY-MM-DD；新增默认 deadline 取今天，其他取 due_date",
            },
            "note": {"type": "string", "description": "备注，可空；支持保密标记"},
        }
        scope = (
            "管理员私聊（含自主心跳）可看全部，其他会话只看挂在这里的；照常保密过滤。"
        )
        update = self.todo_update_tool()
        return [
            AstrHeFunctionTool(**update, fn=self.todo_update),
            AstrHeFunctionTool(
                name="astrhe_todo_add",
                fn=self.todo_add,
                description="白天新增待办，content 必填；日期与会话可省略，备注可空。新增后进入白天可见范围，夜里照常合并清理。"
                + scope,
                parameters={
                    "type": "object",
                    "properties": fields,
                    "required": ["content"],
                },
            ),
            AstrHeFunctionTool(
                name="astrhe_todo_edit",
                fn=self.todo_edit,
                description="修改未完成待办，todo_id 必填；只改传入字段，不改状态，未传字段保持原值。"
                + scope,
                parameters={
                    "type": "object",
                    "properties": {
                        "todo_id": {"type": "integer", "description": "待办编号"},
                        **fields,
                    },
                    "required": ["todo_id"],
                },
            ),
            AstrHeFunctionTool(
                name="astrhe_read_todos",
                fn=self.read_todos,
                description="白天读取待办，附状态、备注、日期和会话出处；status=open（默认，含 progress）/done/dropped/all，每页 100 条，offset 翻页。"
                + scope,
                parameters={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["open", "done", "dropped", "all"],
                        },
                        "offset": {
                            "type": "integer",
                            "description": "过滤后的列表偏移，默认 0",
                        },
                    },
                },
            ),
            AstrHeFunctionTool(
                name="astrhe_plan_edit",
                fn=self.plan_edit,
                description="白天调整最近的规划书。field 和 text 必填；append 追加带时间的调整（默认），replace 替换。管理员私聊可改全文、自我提醒、任意会话段落；其他会话只能改自己的段落。文本支持保密标记。",
                parameters={
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": ["full_text", "day_reminders", "section"],
                        },
                        "text": {"type": "string", "description": "新增或替换的文本"},
                        "mode": {"type": "string", "enum": ["append", "replace"]},
                        "umo": {
                            "type": "string",
                            "description": "section 的目标会话，默认当前会话，可用会话简写",
                        },
                    },
                    "required": ["field", "text"],
                },
            ),
        ]
