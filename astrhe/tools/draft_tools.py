"""草稿工具：夜间主 agent 专用（写草稿、请求审稿、提交）。

所有产出先进 drafts 表（草稿箱），只有 astrhe_commit 才会触发真正提交。
这些工具只给夜间主 agent，不注册到白天。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from .base import AstrHeFunctionTool


class DraftTools:
    """草稿箱工具集工厂。"""

    def __init__(
        self,
        storage: Any,
        run_id: int,
        request_review_cb: Callable[[str], Awaitable[str]],
        commit_cb: Callable[[str], Awaitable[str]],
    ):
        self.storage = storage
        self.run_id = run_id
        self._request_review_cb = request_review_cb
        self._commit_cb = commit_cb
        self._seq = 0

    async def _add(self, kind: str, payload: dict[str, Any]) -> None:
        self._seq += 1
        await self.storage.runs.add_draft(
            run_id=self.run_id, kind=kind, payload=payload, seq=self._seq
        )

    def build(self) -> list[AstrHeFunctionTool]:
        return [
            AstrHeFunctionTool(
                name="astrhe_draft_plan",
                description=(
                    "写规划书草稿。参数：full_text（规划书全文，保密内容用"
                    "【保密:QQ号】…【/保密】包裹）、reflection（自我反思）。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "full_text": {"type": "string"},
                        "reflection": {"type": "string"},
                    },
                    "required": ["full_text"],
                },
                fn=self._draft_plan,
            ),
            AstrHeFunctionTool(
                name="astrhe_draft_sections",
                description=(
                    "按会话切分规划段落（白天注入用，每段要短）。"
                    "参数：sections_json（JSON 对象，键是会话 UMO，值是段落文本）。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"sections_json": {"type": "string"}},
                    "required": ["sections_json"],
                },
                fn=self._draft_sections,
            ),
            AstrHeFunctionTool(
                name="astrhe_draft_todo",
                description=(
                    "新增待办草稿。参数：content；visible_umos（JSON 数组，可见会话）；"
                    "secret_from（JSON 数组，对谁保密）；due_kind（today/future/deadline）；"
                    "due_date（YYYY-MM-DD）；show_from（从哪天开始贴出，默认等于 due_date）；"
                    "evidence（JSON 数组，依据）。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "visible_umos": {"type": "string"},
                        "secret_from": {"type": "string"},
                        "due_kind": {"type": "string"},
                        "due_date": {"type": "string"},
                        "show_from": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["content", "visible_umos"],
                },
                fn=self._draft_todo,
            ),
            AstrHeFunctionTool(
                name="astrhe_draft_todo_drop",
                description="删除已无必要的旧待办。参数：todo_id、reason（理由）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "todo_id": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["todo_id", "reason"],
                },
                fn=self._draft_todo_drop,
            ),
            AstrHeFunctionTool(
                name="astrhe_draft_alarm",
                description=(
                    "新增闹钟卡片草稿。参数：target_umo（目标会话）；run_at（执行时间，"
                    "如 2026-10-11 00:00）；background、purpose、how（必填，来龙去脉）；"
                    "involved、mentions、secret_from（JSON 数组）；taboo；"
                    "落在深夜（00:30-08:00）的必须 agreed=true 并写 agreed_reason。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "target_umo": {"type": "string"},
                        "run_at": {"type": "string"},
                        "cron_expression": {"type": "string"},
                        "background": {"type": "string"},
                        "purpose": {"type": "string"},
                        "how": {"type": "string"},
                        "involved": {"type": "string"},
                        "mentions": {"type": "string"},
                        "secret_from": {"type": "string"},
                        "taboo": {"type": "string"},
                        "agreed": {"type": "boolean"},
                        "agreed_reason": {"type": "string"},
                    },
                    "required": ["target_umo", "background", "purpose", "how"],
                },
                fn=self._draft_alarm,
            ),
            AstrHeFunctionTool(
                name="astrhe_draft_person",
                description=(
                    "更新关系本草稿。参数：qq；aliases（JSON 数组）；relation_text"
                    "（关系层，只在确有变化时给）；recent_text（近况层）；"
                    "anniversaries（JSON 数组，如 [{\"name\":\"生日\",\"date\":\"10-11\"}]）；"
                    "expected_friend（true 时标为预期联系人，配合 expected_reason）。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "qq": {"type": "string"},
                        "aliases": {"type": "string"},
                        "relation_text": {"type": "string"},
                        "recent_text": {"type": "string"},
                        "anniversaries": {"type": "string"},
                        "expected_friend": {"type": "boolean"},
                        "expected_reason": {"type": "string"},
                    },
                    "required": ["qq"],
                },
                fn=self._draft_person,
            ),
            AstrHeFunctionTool(
                name="astrhe_draft_promise",
                description=(
                    "承诺账本变更草稿。参数：action（add/update）；add 时给 from_id、"
                    "to_id、content、due_date；update 时给 promise_id、status"
                    "（done/broken/waived）、reason。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "from_id": {"type": "string"},
                        "to_id": {"type": "string"},
                        "content": {"type": "string"},
                        "due_date": {"type": "string"},
                        "promise_id": {"type": "integer"},
                        "status": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["action"],
                },
                fn=self._draft_promise,
            ),
            AstrHeFunctionTool(
                name="astrhe_draft_appearance",
                description=(
                    "自我形象动作草稿（可选，受频率上限约束）。参数：signature"
                    "（明天的个性签名）；status_preset（在线/离开/忙碌/请勿打扰/Q我吧）。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "signature": {"type": "string"},
                        "status_preset": {"type": "string"},
                    },
                },
                fn=self._draft_appearance,
            ),
            AstrHeFunctionTool(
                name="astrhe_request_review",
                description=(
                    "请审稿子代理复盘当前草稿。参数：focus（审稿重点，可空）。"
                    "至少要成功审稿 1 次、至多 2 次才能提交。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"focus": {"type": "string"}},
                },
                fn=self._request_review,
            ),
            AstrHeFunctionTool(
                name="astrhe_commit",
                description=(
                    "提交今晚的全部草稿（规划书、待办、闹钟、关系本、承诺）。"
                    "参数：summary（一句话总结今晚的决定）。"
                    "没有规划书或没经过审稿会被拒绝。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
                fn=self._commit,
            ),
            AstrHeFunctionTool(
                name="astrhe_read_drafts",
                description="读当前草稿箱（审稿时用）。",
                fn=self._read_drafts,
            ),
        ]

    # ------------------------------------------------------------------

    @staticmethod
    def _json_list(value: Any) -> list:
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, list) else [parsed]
        except (ValueError, TypeError):
            return [str(value)]

    async def _draft_plan(self, event: Any, full_text: str = "", reflection: str = "", **kw) -> str:
        if not full_text.strip():
            return "规划书正文不能为空"
        await self._add("plan", {"full_text": full_text, "reflection": reflection})
        return f"规划书草稿已保存（{len(full_text)} 字）"

    async def _draft_sections(self, event: Any, sections_json: str = "", **kw) -> str:
        try:
            sections = json.loads(sections_json)
        except (ValueError, TypeError):
            return "sections_json 不是合法 JSON"
        if not isinstance(sections, dict):
            return "sections_json 需要是 {会话UMO: 段落文本} 的对象"
        await self._add("sections", {"sections": sections})
        return f"会话段落草稿已保存（{len(sections)} 个会话）"

    async def _draft_todo(self, event: Any, content: str = "", visible_umos: Any = None, **kw) -> str:
        if not content.strip():
            return "待办内容不能为空"
        umos = self._json_list(visible_umos)
        if not umos:
            return "visible_umos 不能为空：待办要知道贴给哪些会话看"
        payload = {
            "content": content,
            "visible_umos": umos,
            "secret_from": self._json_list(kw.get("secret_from")),
            "due_kind": str(kw.get("due_kind", "today") or "today"),
            "due_date": str(kw.get("due_date", "") or ""),
            "show_from": str(kw.get("show_from", "") or ""),
            "evidence": self._json_list(kw.get("evidence")),
        }
        await self._add("todo", payload)
        return f"待办草稿已保存：{content[:30]}"

    async def _draft_todo_drop(self, event: Any, todo_id: int = 0, reason: str = "", **kw) -> str:
        if not reason.strip():
            return "删除待办要写理由"
        await self._add("todo_drop", {"todo_id": int(todo_id), "reason": reason})
        return f"待办 #{todo_id} 的删除草稿已保存"

    async def _draft_alarm(self, event: Any, target_umo: str = "", **kw) -> str:
        if not target_umo.strip():
            return "target_umo 不能为空"
        for key in ("background", "purpose", "how"):
            if not str(kw.get(key, "") or "").strip():
                return f"闹钟卡片缺少「{key}」"
        payload = {
            "target_umo": target_umo,
            "run_at": str(kw.get("run_at", "") or ""),
            "cron_expression": str(kw.get("cron_expression", "") or ""),
            "card": {
                "background": str(kw.get("background", "")),
                "purpose": str(kw.get("purpose", "")),
                "how": str(kw.get("how", "")),
                "involved": self._json_list(kw.get("involved")),
                "mentions": self._json_list(kw.get("mentions")),
                "secret_from": self._json_list(kw.get("secret_from")),
                "taboo": str(kw.get("taboo", "") or ""),
                "agreed": bool(kw.get("agreed", False)),
                "agreed_reason": str(kw.get("agreed_reason", "") or ""),
            },
        }
        await self._add("alarm", payload)
        return f"闹钟草稿已保存：{target_umo} @ {payload['run_at'] or payload['cron_expression']}"

    async def _draft_person(self, event: Any, qq: str = "", **kw) -> str:
        qq = str(qq).strip()
        if not qq:
            return "qq 不能为空"
        payload: dict[str, Any] = {"qq": qq}
        for key in ("relation_text", "recent_text", "expected_reason"):
            if kw.get(key):
                payload[key] = str(kw[key])
        for key in ("aliases", "anniversaries"):
            if kw.get(key):
                payload[key] = self._json_list(kw[key])
        if kw.get("expected_friend"):
            payload["expected_friend"] = True
        await self._add("person", payload)
        return f"关系本草稿已保存：{qq}"

    async def _draft_promise(self, event: Any, action: str = "", **kw) -> str:
        if action == "add":
            if not str(kw.get("content", "") or "").strip():
                return "承诺内容不能为空"
            await self._add(
                "promise",
                {
                    "action": "add",
                    "from_id": str(kw.get("from_id", "") or ""),
                    "to_id": str(kw.get("to_id", "") or ""),
                    "content": str(kw["content"]),
                    "due_date": str(kw.get("due_date", "") or ""),
                },
            )
            return "承诺新增草稿已保存"
        if action == "update":
            await self._add(
                "promise",
                {
                    "action": "update",
                    "promise_id": int(kw.get("promise_id", 0) or 0),
                    "status": str(kw.get("status", "") or ""),
                    "reason": str(kw.get("reason", "") or ""),
                },
            )
            return "承诺变更草稿已保存"
        return "action 只能是 add / update"

    async def _draft_appearance(self, event: Any, **kw) -> str:
        signature = str(kw.get("signature", "") or "")
        status_preset = str(kw.get("status_preset", "") or "")
        if not signature and not status_preset:
            return "signature 和 status_preset 至少给一个"
        await self._add("appearance", {"signature": signature, "status_preset": status_preset})
        return "自我形象草稿已保存"

    async def _request_review(self, event: Any, focus: str = "", **kw) -> str:
        return await self._request_review_cb(focus)

    async def _commit(self, event: Any, summary: str = "", **kw) -> str:
        return await self._commit_cb(summary)

    async def _read_drafts(self, event: Any, **kw) -> str:
        drafts = await self.storage.runs.get_drafts(self.run_id)
        if not drafts:
            return "草稿箱是空的"
        lines = []
        for d in drafts:
            payload = json.loads(d["payload_json"] or "{}")
            text = json.dumps(payload, ensure_ascii=False)
            if len(text) > 500:
                text = text[:500] + "…"
            lines.append(f"#{d['seq']} [{d['kind']}] {text}")
        return "当前草稿箱：\n" + "\n".join(lines)
