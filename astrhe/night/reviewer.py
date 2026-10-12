"""审稿子代理。

- 主 agent 通过 astrhe_request_review(focus) 触发；
- 成功完成（模型没报错）的审稿计入次数：至少 1 次、至多 2 次；
- 审稿意见第一行必须给出「结论：通过 / 需要修改」，否则追问一次格式；
  仍不合格记为无效审稿，不计次数，累计 2 次后不再重试，由主 agent 自查后提交；
- 审稿模型请求失败（NightAgentError）：不算次数，但按 2026-10-07 修订，
  连续三次失败后要终止未提交运行，所以异常直接向上抛。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import constants as C
from ..prompts import reviewer as reviewer_prompts
from ..prompts.persona import build_persona_material
from .agent_runner import run_night_agent

_CONCLUSION = re.compile(r"结论[\s*】]*[:：]?[\s*]*(通过|需要修改)")
_LEADING_VERDICT = re.compile(r"^[\s#*>]*(通过|需要修改)")

REVIEW_FORMAT_PROMPT = (
    "你刚才的回复不是审稿意见：第一行没有给出结论。现在你是审稿人，不是在和谁聊天。"
    "请重新输出，第一行必须是「结论：通过」或「结论：需要修改」，前面不加任何别的字；"
    "然后逐条列出问题与修改建议，每条点名草稿编号（#编号）。"
    "这次仍没有结论行，这份审稿就作废，主 agent 收不到你的意见。"
)


def is_valid_review(text: str) -> bool:
    """开头要有明确结论；一句闲聊或被截短的回复不算审稿意见。"""
    head = (text or "")[:200]
    return bool(_LEADING_VERDICT.match(head) or _CONCLUSION.search(head))


class Reviewer:
    def __init__(
        self,
        storage: Any,
        context: Any,
        provider_id: str,
        persona_prompt: str,
        admins: list[str],
        internal_tools: list,
        *,
        time_info="",
        self_id="",
        personas=None,
    ):
        self.storage = storage
        self.context = context
        self.provider_id = provider_id
        self.persona_prompt = persona_prompt
        self.admins = admins
        self.internal_tools = internal_tools
        self.time_info = time_info
        self.self_id = self_id
        self.personas = personas

    async def review(self, run_id: int, focus: str) -> str:
        """跑一次审稿，把意见写进 reviews 表并返回意见文本。

        模型失败抛 NightAgentError（由 pipeline 捕获并终止整晚）。
        """
        ok_count = await self.storage.runs.count_ok_reviews(run_id)
        if ok_count >= C.REVIEW_MAX_OK:
            return f"已经成功审稿 {ok_count} 次，达到上限（至多 {C.REVIEW_MAX_OK} 次），可以直接提交了"
        invalid_count = await self.storage.runs.count_reviews(run_id, "invalid")
        if invalid_count >= C.REVIEW_MAX_INVALID:
            return (
                f"审稿人已经有 {invalid_count} 次没给出有效意见，今晚不再审稿。"
                "请你自己按审稿清单把草稿逐条再检查一遍"
                "（保密标记、分寸、查重、闹钟卡片、待办挂在哪个会话），确认无误后直接提交。"
            )

        drafts = await self.storage.runs.get_drafts(run_id)
        draft_text = self._render_drafts(drafts)
        system = reviewer_prompts.build_reviewer_system(
            self.persona_prompt, self.admins, focus, self.time_info, self.self_id
        )
        reports = await self.storage.runs.get_reports(run_id)
        summaries = "\n".join(
            f"{r['umo']}："
            + (
                json.loads(r["content_json"]).get("summary", "")
                or "（这个会话的汇报失败了，需要时用 astrhe_read_messages 核对原始记录）"
            )
            for r in reports
        )
        persona_text = build_persona_material(self.personas, "reviewer")
        prompt = (
            (persona_text + "\n\n" if persona_text else "")
            + "【今晚会话清单与汇报摘要】\n"
            + summaries
            + "\n这是主 agent 写好的草稿，请按审稿清单审查：\n\n"
            + draft_text
        )
        text, contexts = await run_night_agent(
            self.context,
            umo="",  # 审稿用虚拟会话
            provider_id=self.provider_id,
            system_prompt=system,
            prompt=prompt,
            tools=self.internal_tools,
        )
        if not is_valid_review(text):
            retry, _ = await run_night_agent(
                self.context,
                umo="",
                provider_id=self.provider_id,
                system_prompt=system,
                prompt=REVIEW_FORMAT_PROMPT,
                tools=self.internal_tools,
                contexts=contexts,
            )
            if not is_valid_review(retry):
                original = retry or text
                await self.storage.runs.add_review(
                    run_id=run_id, focus=focus, result_text=original, status="invalid"
                )
                return (
                    "这次审稿没有给出有效意见（没有按「结论：通过 / 需要修改」回答），"
                    f"不计入审稿次数。审稿人原话：{original}\n可以再申请一次审稿。"
                )
            text = retry
        await self.storage.runs.add_review(
            run_id=run_id, focus=focus, result_text=text, status="ok"
        )
        return f"审稿意见：\n{text}"

    @staticmethod
    def _render_drafts(drafts: list[dict]) -> str:
        lines = []
        for d in drafts:
            payload = json.loads(d["payload_json"] or "{}")
            text = json.dumps(payload, ensure_ascii=False)
            lines.append(f"#{d['id']} [{d['kind']}]\n{text}")
        return "\n\n".join(lines) if lines else "（草稿箱是空的）"
