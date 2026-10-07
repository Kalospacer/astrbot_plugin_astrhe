"""汇报子代理：每个会话的窗口记录 → 详细汇报（JSON）。

- 记录预渲染成紧凑文本行，已撤回消息在代码里剔除（工具与 prompt 都看不到）。
- 不超过 300 条的会话一次读完；超过的切块，每块一个子代理，再一次合并调用。
- 子代理并发 3；JSON 解析失败追问一次；仍失败保存原文并在运行记录标注。
- 任何一次模型请求失败（NightAgentError）直接向上抛，整晚终止。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .. import constants as C
from ..prompts import reporter as reporter_prompts
from ..tools.reader_tools import format_message_line
from .agent_runner import run_night_agent

REPORT_JSON_KEYS = (
    "summary", "big_events", "interesting", "self_interest",
    "promises", "plan_candidates", "person_updates", "reflection_hints",
)

FIX_JSON_PROMPT = (
    "你的输出不是合法 JSON。请只输出一个 JSON 对象，不要包 markdown 代码块，"
    "包含这些键：" + "、".join(REPORT_JSON_KEYS)
)


def parse_report_json(text: str) -> dict | None:
    """从汇报文本中提取 JSON；失败返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    # 容忍模型包了 ```json 代码块
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        # 尝试截取第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            return None
    return data if isinstance(data, dict) else None


class Reporter:
    def __init__(
        self,
        storage: Any,
        context: Any,
        provider_id: str,
        persona_prompt: str,
        tz: Any,
        internal_tools: list,
    ):
        self.storage = storage
        self.context = context
        self.provider_id = provider_id
        self.persona_prompt = persona_prompt
        self.tz = tz
        self.internal_tools = internal_tools
        self._semaphore = asyncio.Semaphore(C.REPORT_CONCURRENCY)

    async def report_session(
        self, run_id: int, umo: str, window_start: float, window_end: float
    ) -> dict[str, Any]:
        """对一个会话生成汇报，返回 {umo, report, parse_ok, raw}。"""
        rows = await self.storage.ledger.get_messages(umo, window_start, window_end)
        lines = [format_message_line(r, self.tz) for r in rows]
        notices = await self.storage.ledger.get_notices(umo, window_start, window_end)
        for n in notices:
            lines.append(f"[通知] {n['kind']} actor={n['actor_id']} target={n['target_id']}")
        if not lines:
            return {"umo": umo, "report": {}, "parse_ok": True, "raw": "（窗口内无记录）", "skipped": True}

        chunks = [
            lines[i : i + C.REPORT_CHUNK_SIZE]
            for i in range(0, len(lines), C.REPORT_CHUNK_SIZE)
        ]
        participants = sorted({r["sender_id"] for r in rows if not r["is_bot"]})
        persons_brief = await self._persons_brief(participants)
        system = reporter_prompts.build_reporter_system(self.persona_prompt, persons_brief)

        async with self._semaphore:
            if len(chunks) == 1:
                raw = await self._report_chunk(umo, chunks[0], system, 1, 1)
                report = parse_report_json(raw)
                if report is None:
                    raw = await self._retry_json(umo, chunks[0], system)
                    report = parse_report_json(raw)
            else:
                partials = []
                for idx, chunk in enumerate(chunks, 1):
                    partials.append(await self._report_chunk(umo, chunk, system, idx, len(chunks)))
                merge_prompt = reporter_prompts.build_merge_prompt(partials)
                raw, _ = await run_night_agent(
                    self.context,
                    umo=umo,
                    provider_id=self.provider_id,
                    system_prompt=system,
                    prompt=merge_prompt,
                    tools=[],
                )
                report = parse_report_json(raw)
                if report is None:
                    raw2 = await self._retry_merge(umo, system, merge_prompt)
                    if raw2:
                        raw = raw2
                        report = parse_report_json(raw)

        await self.storage.runs.add_report(
            run_id=run_id, umo=umo, chunk_index=0,
            content=report or {}, raw_text=raw,
        )
        return {
            "umo": umo,
            "report": report or {},
            "parse_ok": report is not None,
            "raw": raw,
        }

    async def _report_chunk(
        self, umo: str, lines: list[str], system: str, index: int, total: int
    ) -> str:
        header = (
            f"这是会话 {umo} 的聊天记录（第 {index}/{total} 段）。"
            "读完后按 system 里的要求输出 JSON 汇报。\n\n"
        )
        text, _ = await run_night_agent(
            self.context,
            umo=umo,
            provider_id=self.provider_id,
            system_prompt=system,
            prompt=header + "\n".join(lines),
            tools=self.internal_tools,
        )
        return text

    async def _retry_json(self, umo: str, lines: list[str], system: str) -> str:
        """解析失败追问一次。"""
        text, contexts = await run_night_agent(
            self.context,
            umo=umo,
            provider_id=self.provider_id,
            system_prompt=system,
            prompt="这是会话 " + umo + " 的聊天记录，请输出 JSON 汇报。\n\n" + "\n".join(lines),
            tools=self.internal_tools,
        )
        # 追问：带着上一轮上下文再要一次合法 JSON
        text2, _ = await run_night_agent(
            self.context,
            umo=umo,
            provider_id=self.provider_id,
            system_prompt=system,
            prompt=FIX_JSON_PROMPT,
            tools=[],
            contexts=contexts,
        )
        return text2 or text

    async def _retry_merge(self, umo: str, system: str, merge_prompt: str) -> str:
        text, contexts = await run_night_agent(
            self.context,
            umo=umo,
            provider_id=self.provider_id,
            system_prompt=system,
            prompt=merge_prompt,
            tools=[],
        )
        text2, _ = await run_night_agent(
            self.context,
            umo=umo,
            provider_id=self.provider_id,
            system_prompt=system,
            prompt=FIX_JSON_PROMPT,
            tools=[],
            contexts=contexts,
        )
        return text2 or text

    async def _persons_brief(self, participant_ids: list[str]) -> str:
        lines = []
        for qq in participant_ids:
            person = await self.storage.persons.get_person(qq)
            if person:
                lines.append(
                    f"{qq}：别名 {person['aliases_json']}；关系 {person['relation_text'] or '未记录'}"
                )
        return "\n".join(lines)
