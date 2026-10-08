"""只读工具集：夜间子代理、主 agent、审稿共用；astrhe_read_plan 同时给白天用。

所有工具只读，不写任何状态；输出都是给模型看的纯文本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import constants as C
from ..platform import parse_umo, event_umo
from .base import AstrHeFunctionTool
from .alarm_view import format_night_alarm
from .secrecy import filter_secret_text


def format_message_line(row: dict, tz) -> str:
    """渲染成紧凑文本行：[HH:MM] 名片或昵称(QQ): 文本  #msgid"""
    dt = datetime.fromtimestamp(row["ts"], tz)
    name = row["sender_card"] or row["sender_name"] or "?"
    text = (row["text"] or "").replace("\n", " ")
    mid = row["platform_message_id"] or f"local-{row['id']}"
    prefix = "[我] " if row["is_bot"] else ""
    return f"[{dt.strftime('%m-%d %H:%M')}] {prefix}{name}({row['sender_id']}): {text}  #{mid}"


class ReaderTools:
    """只读工具工厂。"""

    def __init__(
        self,
        storage: Any,
        context: Any,
        tz_getter,
        window_getter,
        secrecy_resolver: Any = None,
        run_id: int | None = None,
    ):
        self.storage = storage
        self.context = context
        self._tz_getter = tz_getter
        self._window_getter = window_getter
        self.secrecy_resolver = secrecy_resolver
        self.run_id = run_id

    def _tz(self):
        return self._tz_getter()

    def build(self) -> list[AstrHeFunctionTool]:
        return [
            AstrHeFunctionTool(
                name="astrhe_read_reports",
                description="完整读取今晚各会话汇报，审稿核对用。",
                fn=self._read_reports,
            ),
            AstrHeFunctionTool(
                name="astrhe_list_sessions",
                description="列出本次复盘窗口内有记录的会话（群聊和私聊），带消息条数。",
                fn=self._list_sessions,
            ),
            AstrHeFunctionTool(
                name="astrhe_read_messages",
                description=(
                    "按会话分页读取聊天记录（已撤回的消息看不到）。"
                    "参数：umo（必填）、before_row_id（可选，翻更旧的页）。"
                    "单次最多 200 条，从旧到新排列。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "umo": {"type": "string", "description": "会话 UMO"},
                        "before_row_id": {
                            "type": "integer",
                            "description": "翻页锚点：只取该行之前的消息",
                        },
                    },
                    "required": ["umo"],
                },
                fn=self._read_messages,
            ),
            AstrHeFunctionTool(
                name="astrhe_search_messages",
                description=(
                    "按关键词搜索全部聊天记录（不含已撤回）。"
                    "参数：keyword（必填）、umo（可选，限定会话）。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "offset": {"type": "integer", "description": "搜索翻页偏移"},
                        "keyword": {"type": "string"},
                        "umo": {"type": "string"},
                    },
                    "required": ["keyword"],
                },
                fn=self._search_messages,
            ),
            AstrHeFunctionTool(
                name="astrhe_message_context",
                description="按消息 id 取它前后的上下文。参数：message_id（# 后面的编号）。",
                parameters={
                    "type": "object",
                    "properties": {"message_id": {"type": "string"}},
                    "required": ["message_id"],
                },
                fn=self._message_context,
            ),
            AstrHeFunctionTool(
                name="astrhe_find_person",
                description="查关系本：按 QQ 号或昵称别名查一个人。参数：query。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                fn=self._find_person,
            ),
            AstrHeFunctionTool(
                name="astrhe_read_todos",
                description="读待办列表。参数：include_done（可选，true 时包含已完成）。",
                parameters={
                    "type": "object",
                    "properties": {"include_done": {"type": "boolean"}},
                },
                fn=self._read_todos,
            ),
            AstrHeFunctionTool(
                name="astrhe_read_promises",
                description="读承诺账本：谁答应了谁什么、兑现状态。",
                fn=self._read_promises,
            ),
            AstrHeFunctionTool(
                name="astrhe_read_alarms",
                description=(
                    "读闹钟状态：AstrHe 建的闹钟（含时间、目的、背景与完整卡片）+ 全部唤醒任务清单"
                    "（含其他方式建的，用于查重）。"
                ),
                fn=self._read_alarms,
            ),
            AstrHeFunctionTool(
                name="astrhe_read_plan",
                description=(
                    "读规划书全文。参数：date（可选，YYYY-MM-DD，默认最近一份）。"
                    "对别人保密的内容可能被遮挡。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"date": {"type": "string"}},
                },
                fn=self._read_plan,
            ),
        ]

    # ------------------------------------------------------------------

    async def _list_sessions(self, event: Any, **kwargs: Any) -> str:
        start_ts, end_ts = self._window_getter()
        umos = await self.storage.ledger.list_session_umos(start_ts)
        if not umos:
            return "窗口内没有任何聊天记录"
        lines = []
        for umo in umos:
            msgs = await self.storage.ledger.get_messages(umo, start_ts, end_ts)
            _, mtype, sid = parse_umo(umo)
            kind = "群聊" if mtype == "GroupMessage" else "私聊"
            lines.append(f"{umo}（{kind} {sid}，{len(msgs)} 条）")
        return "窗口内的会话：\n" + "\n".join(lines)

    async def _read_messages(self, event: Any, umo: str = "", **kwargs: Any) -> str:
        if not umo:
            return "需要 umo 参数"
        before_row_id = kwargs.get("before_row_id")
        rows = await self.storage.ledger.get_messages_page(
            umo, before_row_id=before_row_id, limit=C.READ_MESSAGES_PAGE_LIMIT
        )
        if not rows:
            return "没有更多消息了"
        tz = self._tz()
        lines = [format_message_line(r, tz) for r in rows]
        oldest = rows[0]["id"]
        header = f"共 {len(rows)} 条（最早行号 {oldest}，翻更旧的页传 before_row_id={oldest}）："
        return header + "\n" + "\n".join(lines)

    async def _search_messages(
        self, event: Any, keyword: str = "", umo: str = "", **kwargs: Any
    ) -> str:
        if not keyword:
            return "需要 keyword 参数"
        rows = await self.storage.ledger.search_messages(
            keyword,
            0,
            umo=umo or None,
            limit=51,
            offset=max(0, int(kwargs.get("offset", 0))),
        )
        if not rows:
            return f"没有找到含「{keyword}」的消息"
        tz = self._tz()
        more = len(rows) > 50
        rows = rows[:50]
        lines = [f"{r['umo']} " + format_message_line(r, tz) for r in rows]
        suffix = (
            f"\n还有更多，继续翻传 offset={max(0, int(kwargs.get('offset', 0))) + 50}"
            if more
            else ""
        )
        return f"找到 {len(rows)} 条：\n" + "\n".join(lines) + suffix

    async def _message_context(
        self, event: Any, message_id: str = "", **kwargs: Any
    ) -> str:
        mid = str(message_id).lstrip("#")
        if mid.startswith("local-") and mid[6:].isdigit():
            row = await self.storage.db.fetchone(
                "SELECT * FROM messages WHERE id=? AND recalled=0", (int(mid[6:]),)
            )
        else:
            row = await self.storage.ledger.get_message_by_platform_id(mid)
        if not row or row["recalled"]:
            return "账本里找不到这条消息"
        rows = await self.storage.ledger.get_message_context(row["umo"], row["ts"])
        tz = self._tz()
        return "上下文：\n" + "\n".join(format_message_line(r, tz) for r in rows)

    async def _find_person(self, event: Any, query: str = "", **kwargs: Any) -> str:
        query = str(query).strip()
        if not query:
            return "需要 query 参数"
        person = await self.storage.persons.get_person(query)
        if person is None:
            person = await self.storage.persons.find_by_alias(query)
        if person is None:
            return f"关系本里没有「{query}」"
        return (
            f"QQ {person['qq']}\n别名：{person['aliases_json']}\n"
            f"关系：{person['relation_text'] or '（未记录）'}\n"
            f"近况：{person['recent_text'] or '（未记录）'}\n"
            f"纪念日：{person['anniversaries_json']}"
        )

    async def _read_todos(self, event: Any, **kwargs: Any) -> str:
        include_done = bool(kwargs.get("include_done"))
        rows = await self.storage.plans.open_todos()
        if include_done:
            rows = await self.storage.plans.list_todos(-1)
        if not rows:
            return "没有待办"
        lines = []
        for r in rows:
            lines.append(
                f"#{r['id']} [{r['status']}] {r['content']}"
                f"（{r['due_kind']} {r['due_date']}，可见于 {r['visible_umos_json']}；备注：{r['note']}）"
            )
        return "待办列表：\n" + "\n".join(lines)

    async def _read_promises(self, event: Any, **kwargs: Any) -> str:
        rows = await self.storage.plans.list_promises(-1)
        if not rows:
            return "承诺账本是空的"
        lines = [
            f"#{r['id']} [{r['status']}] {r['from_id']} → {r['to_id']}：{r['content']}"
            f"（期限 {r['due_date'] or '无'}）"
            for r in rows
        ]
        return "承诺账本：\n" + "\n".join(lines)

    async def _read_alarms(self, event: Any, **kwargs: Any) -> str:
        alarms = await self.storage.alarms.list_alarms(-1)
        lines = []
        if alarms:
            lines.append("AstrHe 建的闹钟：")
            for a in alarms:
                lines.append(format_night_alarm(a, self._tz()))
        # 全部唤醒任务（含外部建的），用于查重
        cron = getattr(self.context, "cron_manager", None)
        if cron is not None:
            try:
                jobs = await cron.list_jobs("active_agent")
            except Exception as exc:  # noqa: BLE001
                jobs = []
                lines.append(f"读取全部唤醒任务失败: {exc}")
            astrhe_job_ids = {a["cron_job_id"] for a in alarms if a["cron_job_id"]}
            if jobs:
                lines.append("全部唤醒任务（含外部）：")
                for j in jobs:
                    payload = j.payload or {}
                    tag = "AstrHe" if j.job_id in astrhe_job_ids else "外部"
                    lines.append(
                        f"[{tag}] {j.job_id}「{j.name}」→ {payload.get('session', '')}"
                        f" enabled={j.enabled}"
                    )
        return "\n".join(lines) if lines else "现在没有任何闹钟"

    async def _read_plan(self, event: Any, date: str = "", **kwargs: Any) -> str:
        if date:
            plan = await self.storage.plans.get_plan_by_date(date)
        else:
            plan = await self.storage.plans.get_latest_plan()
        if not plan:
            return "还没有任何规划书"
        text = plan["full_text"]
        # 保密过滤：夜间虚拟会话不过滤；白天按发送者与在场判定过滤
        viewer_id = ""
        umo = ""
        try:
            viewer_id = str(event.get_sender_id())
            umo = event_umo(event)
        except Exception:  # noqa: BLE001
            pass
        if umo and self.secrecy_resolver is not None:
            present = await self.secrecy_resolver.present_ids(umo)
            text = filter_secret_text(
                text, viewer_id=viewer_id, session_umo=umo, present_ids=present
            )
        return f"规划书（{plan['plan_date']}）：\n{text}"

    async def _read_reports(self, event: Any, **kwargs) -> str:
        if self.run_id is None:
            return "当前没有夜间运行"
        reports = await self.storage.runs.get_reports(self.run_id)
        return (
            "\n\n".join(f"{r['umo']}\n{r['raw_text']}" for r in reports)
            or "今晚还没有汇报"
        )
