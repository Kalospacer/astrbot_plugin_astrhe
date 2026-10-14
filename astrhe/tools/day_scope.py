"""白天待办的会话范围、保密过滤与会话标签。"""

from __future__ import annotations

import json
from typing import Any

from ..platform import parse_umo
from ..timeutil import local_date_str, utc_now
from .secrecy import filter_secret_text, is_secret_visible_here


async def todos_for_view(
    storage: Any,
    *,
    umo: str,
    viewer_id: str,
    present_ids: set[str] | None,
    tz: Any,
    full_view: bool = False,
    status: str = "open",
) -> list[dict[str, Any]]:
    """先取会话范围，再过滤保密；分页必须在过滤后进行。"""
    if status == "open":
        rows = (
            await storage.plans.open_todos()
            if full_view
            else await storage.plans.visible_todos(umo, local_date_str(utc_now(), tz))
        )
    else:
        rows = await storage.plans.list_todos(limit=-1, status=status)
        if not full_view:
            rows = [
                r for r in rows if umo in json.loads(r["visible_umos_json"] or "[]")
            ]
    visible = []
    for row in rows:
        if not is_secret_visible_here(
            json.loads(row["secret_from_json"] or "[]"),
            viewer_id=viewer_id,
            session_umo=umo,
            present_ids=present_ids,
        ):
            continue
        item = dict(row)
        for field in ("content", "note"):
            item[field] = filter_secret_text(
                item[field],
                viewer_id=viewer_id,
                session_umo=umo,
                present_ids=present_ids,
            )
        visible.append(item)
    return visible


async def session_labels(storage: Any, umos: list[str]) -> str:
    """只用现有关系本的私聊别名；群名未存储时显示群号。"""
    labels = []
    for umo in umos:
        _, kind, sid = parse_umo(umo)
        label = f"{'群' if kind == 'GroupMessage' else '私聊'} {sid}"
        if kind == "FriendMessage":
            person = await storage.persons.get_person(sid)
            aliases = json.loads(person["aliases_json"] or "[]") if person else []
            if aliases:
                label += f"（{aliases[0]}）"
        labels.append(label)
    return "、".join(labels)


def todo_not_found(todo_id: int, visible: list[dict[str, Any]]) -> str:
    visible_ids = ", ".join(f"#{t['id']}" for t in visible) or "（无）"
    return f"找不到 #{todo_id}。这个会话可见的待办：{visible_ids}"
