"""白天维护与夜间草稿共用的待办字段规范化。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .secrecy import normalize_qq_ids, normalize_secret_text


def json_list(value: Any) -> list:
    """沿用夜间草稿的列表解析，兼容模型直接传列表或单项。"""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, list) else [parsed]
    except (ValueError, TypeError):
        return [str(value)]


def normalize_todo_fields(
    fields: dict[str, Any],
    *,
    resolve: Callable[[str], str],
    default_date: str,
    default_umos: list[str] | None = None,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """新增补齐默认值；编辑只规范化传入的字段，保留其他原值。"""
    result = dict(fields)
    adding = current is None
    if adding or "content" in fields:
        content = fields.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("待办内容不能为空")
        result["content"] = normalize_secret_text(content)
    if adding or "visible_umos" in fields:
        umos = json_list(fields.get("visible_umos")) or default_umos or []
        if not umos:
            raise ValueError("visible_umos 不能为空：待办要知道贴给哪些会话看")
        result["visible_umos"] = [resolve(u) for u in umos]
    if adding or "secret_from" in fields:
        result["secret_from"] = normalize_qq_ids(json_list(fields.get("secret_from")))
    if adding or "due_kind" in fields:
        kind = str(fields.get("due_kind", "today") or "today")
        if kind not in ("today", "future", "deadline"):
            raise ValueError("due_kind 只能为 today / future / deadline")
        result["due_kind"] = kind
    if adding or "due_date" in fields:
        result["due_date"] = str(fields.get("due_date") or default_date)
    if adding or "show_from" in fields:
        base = current or {}
        kind = result.get("due_kind", base.get("due_kind", "today"))
        due = result.get("due_date", base.get("due_date", "")) or default_date
        result["show_from"] = str(
            fields.get("show_from") or (default_date if kind == "deadline" else due)
        )
    if "note" in fields:
        result["note"] = normalize_secret_text(fields["note"])
    return result
