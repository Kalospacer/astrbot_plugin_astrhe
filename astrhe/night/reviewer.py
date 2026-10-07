"""审稿子代理。

- 主 agent 通过 astrhe_request_review(focus) 触发；
- 成功完成（模型没报错）的审稿计入次数：至少 1 次、至多 2 次；
- 审稿模型请求失败（NightAgentError）：不算次数，但按 2026-10-07 修订，
  任何夜间 agent 的模型失败都要终止整晚运行，所以异常直接向上抛。
"""

from __future__ import annotations

import json
from typing import Any

from .. import constants as C
from ..prompts import reviewer as reviewer_prompts
from .agent_runner import run_night_agent


class Reviewer:
    def __init__(
        self,
        storage: Any,
        context: Any,
        provider_id: str,
        persona_prompt: str,
        admins: list[str],
        internal_tools: list,
    ):
        self.storage = storage
        self.context = context
        self.provider_id = provider_id
        self.persona_prompt = persona_prompt
        self.admins = admins
        self.internal_tools = internal_tools

    async def review(self, run_id: int, focus: str) -> str:
        """跑一次审稿，把意见写进 reviews 表并返回意见文本。

        模型失败抛 NightAgentError（由 pipeline 捕获并终止整晚）。
        """
        ok_count = await self.storage.runs.count_ok_reviews(run_id)
        if ok_count >= C.REVIEW_MAX_OK:
            return f"已经成功审稿 {ok_count} 次，达到上限（至多 {C.REVIEW_MAX_OK} 次），可以直接提交了"

        drafts = await self.storage.runs.get_drafts(run_id)
        draft_text = self._render_drafts(drafts)
        system = reviewer_prompts.build_reviewer_system(
            self.persona_prompt, self.admins, focus
        )
        prompt = "这是主 agent 写好的草稿，请按审稿清单审查：\n\n" + draft_text
        text, _ = await run_night_agent(
            self.context,
            umo="",  # 审稿用虚拟会话
            provider_id=self.provider_id,
            system_prompt=system,
            prompt=prompt,
            tools=self.internal_tools,
        )
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
            lines.append(f"#{d['seq']} [{d['kind']}]\n{text}")
        return "\n\n".join(lines) if lines else "（草稿箱是空的）"
