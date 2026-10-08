"""日记只读工具：段落搜索、状态筛选和完整条目分页。"""

import re

from .. import constants as C
from ..timeutil import local_datetime_str
from .base import AstrHeFunctionTool

PLAN_READ_PARAMETERS = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "list": {"type": "boolean"},
        "offset": {"type": "integer"},
    },
}


def build_memory_readers(owner):
    return [
        AstrHeFunctionTool(
            name="astrhe_search_memory",
            description=(
                "搜索日记，keyword 必填；kind=all/plan/todo/promise。"
                "规划书返回命中的完整段落，待办与承诺返回完整条目含备注和日期。"
                "每页 30 条，offset 翻页；夜间自行阅读不遮挡。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["all", "plan", "todo", "promise"],
                    },
                    "offset": {"type": "integer"},
                },
                "required": ["keyword"],
            },
            fn=owner._search_memory,
        )
    ]


def page_footer(total, offset, size):
    return (
        f"\n还有更多，继续翻传 offset={offset + size}" if offset + size < total else ""
    )


def format_entry(kind, row, tz):
    if kind == "todo":
        detail = (
            f"{row['content']}（{row['due_kind']} {row['due_date'] or '无日期'}，"
            f"显示起日 {row['show_from'] or '未指定'}，可见于 {row['visible_umos_json']}，"
            f"保密对象 {row['secret_from_json']}，出处 {row['evidence_json']}，"
            f"闹钟 {row['alarm_id'] or '无'}）"
        )
    else:
        detail = (
            f"{row['from_id']} → {row['to_id']}：{row['content']}"
            f"（期限 {row['due_date'] or '无'}，出处 {row['evidence_json']}，"
            f"创建 {local_datetime_str(row['created_at'], tz)}）"
        )
    return (
        f"[{kind}] #{row['id']} [{row['status']}] {detail}\n"
        f"备注：{row['note'] or '无'}；更新 {local_datetime_str(row['updated_at'], tz)}"
    )


async def read_items(storage, kind, tz, *, status, offset=0):
    offset = max(0, int(offset))
    repo = storage.plans
    try:
        total = await repo.count_entries(kind, status)
        method = repo.list_todos if kind == "todo" else repo.list_promises
        rows = await method(C.MEMORY_ITEM_PAGE_SIZE, status=status, offset=offset)
    except ValueError as exc:
        return str(exc)
    lines = [format_entry(kind, row, tz) for row in rows]
    return (
        f"{'待办列表' if kind == 'todo' else '承诺账本'}（{status}，共 {total} 条，本页 {len(rows)} 条）：\n"
        + "\n".join(lines)
        + page_footer(total, offset, len(rows))
    )


async def search_memory(storage, keyword, kind, offset, tz):
    if not str(keyword).strip():
        return "需要 keyword 参数"
    if kind not in ("all", "plan", "todo", "promise"):
        return "kind 只能是 all / plan / todo / promise"
    offset = max(0, int(offset))
    rows, total = await storage.memory.search(
        keyword, kind, offset, C.MEMORY_SEARCH_PAGE_SIZE
    )
    lines = []
    for result in rows:
        row = await storage.memory.get_entry(result["kind"], result["id"], by_id=True)
        if row is None or row["deleted_at"] is not None:
            continue
        if result["kind"] == "plan":
            paragraphs = []
            for field, label in (
                ("full_text", "正文"),
                ("reflection", "反思"),
                ("day_reminders", "提醒"),
            ):
                for paragraph in re.split(r"\n\s*\n", row[field] or ""):
                    if keyword.lower() in paragraph.lower():
                        paragraphs.append(f"{label}：{paragraph}")
            lines.append(
                f"[plan] {row['plan_date']}：\n"
                + "\n\n".join(paragraphs)
                + f"\n全文用 astrhe_read_plan(date={row['plan_date']})"
            )
        else:
            lines.append(format_entry(result["kind"], row, tz))
    return (
        f"日记搜索「{keyword}」（共 {total} 条，本页 {len(rows)} 条）：\n"
        + "\n\n".join(lines)
        + page_footer(total, offset, len(rows))
    )
