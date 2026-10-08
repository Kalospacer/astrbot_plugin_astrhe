"""夜间主 agent：材料组装与规划循环。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .. import constants as C
from ..prompts import planner as planner_prompts
from ..timeutil import utc_now
from .agent_runner import run_night_agent


def anniversary_days_until(anniversaries: list[dict], today: datetime) -> int | None:
    """最近的纪念日在几天内（不含今天之外超过前瞻期的返回 None）。"""
    best: int | None = None
    for ann in anniversaries if isinstance(anniversaries, list) else []:
        if not isinstance(ann, dict):
            continue
        date_str = str(ann.get("date", ""))
        try:
            if len(date_str) == 5:  # MM-DD
                month, day = date_str.split("-")
                target = today.replace(month=int(month), day=int(day))
                if target.date() < today.date():
                    target = target.replace(year=today.year + 1)
            else:
                target = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=today.tzinfo
                )
            days = (target.date() - today.date()).days
            if 0 <= days <= C.ANNIVERSARY_LOOKAHEAD_DAYS:
                if best is None or days < best:
                    best = days
        except (ValueError, TypeError):
            continue
    return best


class Planner:
    """夜间主 agent。"""

    def __init__(
        self,
        storage: Any,
        context: Any,
        provider_id: str,
        persona_prompt: str,
        admins: list[str],
        tz: Any,
        *,
        time_info="",
        window=None,
    ):
        self.storage = storage
        self.context = context
        self.provider_id = provider_id
        self.persona_prompt = persona_prompt
        self.admins = admins
        self.tz = tz
        self.time_text = time_info
        self.window = window or (0, utc_now())

    def time_info(self, now_ts: float) -> str:
        return self.time_text

    async def build_materials(
        self,
        reports: list[dict[str, Any]],
        reconcile_text: str,
        last_run_failed: bool,
    ) -> str:
        """组装主 agent 的输入材料。"""
        tz = self.tz
        now = datetime.fromtimestamp(utc_now(), tz)

        report_items = []
        for r in reports:
            report = r.get("report") or {}
            text = report.get("summary") or r.get("raw", "")
            detail = json.dumps(
                {k: v for k, v in report.items() if k != "summary"}, ensure_ascii=False
            )
            report_items.append({"umo": r["umo"], "text": f"{text}\n{detail}"})

        # 关系本：今天涉及的人 + 未来 14 天有纪念日的人
        speakers = await self.storage.db.fetchall(
            "SELECT DISTINCT sender_id FROM messages WHERE ts>=? AND ts<? AND recalled=0",
            self.window,
        )
        involved_ids = {r["sender_id"] for r in speakers}
        for r in reports:
            for update in (r.get("report") or {}).get("person_updates", []) or []:
                if update.get("qq"):
                    involved_ids.add(str(update["qq"]))
        persons_lines = []
        for person in await self.storage.persons.list_persons():
            try:
                ann = json.loads(person["anniversaries_json"] or "[]")
            except (ValueError, TypeError):
                ann = []
            days = anniversary_days_until(ann, now)
            if person["qq"] in involved_ids or days is not None:
                suffix = f"；纪念日 {days} 天后" if days is not None else ""
                persons_lines.append(
                    f"{person['qq']}：别名 {person['aliases_json']}；"
                    f"关系 {person['relation_text'] or '未记录'}；"
                    f"近况 {person['recent_text'] or '未记录'}{suffix}"
                )
        persons_text = "\n".join(persons_lines)

        todos = await self.storage.plans.open_todos()
        todos_text = "\n".join(
            f"#{t['id']} [{t['status']}] {t['content']}（{t['due_kind']} {t['due_date']}，"
            f"可见于 {t['visible_umos_json']}；备注：{t['note']}）"
            for t in todos
        )

        completed = await self.storage.db.fetchall(
            "SELECT * FROM todos WHERE status IN ('done','dropped') AND updated_at>=? AND updated_at<?",
            self.window,
        )
        todos_text += "\n【窗口内完成或放弃的待办】\n" + "\n".join(
            f"#{t['id']} [{t['status']}] {t['content']}；备注：{t['note']}"
            for t in completed
        )
        pending = await self.storage.ledger.pending_friend_requests()
        from ..timeutil import local_datetime_str

        pending_text = "\n【待处理好友申请】\n" + "\n".join(
            f"QQ {r['user_id']} 验证：{r['comment']} 时间：{local_datetime_str(r['ts'], tz)}"
            for r in pending
        )

        promises = await self.storage.plans.open_promises()
        promises_text = "\n".join(
            f"#{p['id']} {p['from_id']} → {p['to_id']}：{p['content']}（期限 {p['due_date'] or '无'}）"
            for p in promises
        )

        latest_plan = await self.storage.plans.get_latest_plan()
        yesterday_plan = latest_plan["full_text"] if latest_plan else ""

        cron_text = ""
        cron = getattr(self.context, "cron_manager", None)
        if cron is not None:
            try:
                jobs = await cron.list_jobs("active_agent")
                alarms = await self.storage.alarms.list_alarms(-1)
                astrhe_ids = {a["cron_job_id"] for a in alarms if a["cron_job_id"]}
                lines = []
                for j in jobs:
                    payload = j.payload or {}
                    tag = "AstrHe" if j.job_id in astrhe_ids else "外部"
                    lines.append(
                        f"[{tag}] {j.job_id}「{j.name}」→ {payload.get('session', '')} "
                        f"enabled={j.enabled} run_once={j.run_once}"
                    )
                cron_text = "\n".join(lines)
            except Exception:  # noqa: BLE001
                cron_text = "（读取唤醒任务失败）"

        last_run_note = (
            "上一次运行失败了，今天沿用上一份计划" if last_run_failed else ""
        )

        return (
            pending_text
            + "\n\n"
            + planner_prompts.build_planner_prompt(
                report_items,
                persons_text,
                todos_text,
                promises_text,
                yesterday_plan,
                cron_text,
                reconcile_text,
                last_run_note,
            )
        )

    async def run_planner(
        self,
        *,
        materials: str,
        tools: list,
        commit_state: dict,
    ) -> str:
        """跑主 agent；结束没提交就追问一次。返回最终文本。

        模型失败抛 NightAgentError。
        """
        system = planner_prompts.build_planner_system(
            self.persona_prompt, self.admins, self.time_info(utc_now())
        )
        text, contexts = await run_night_agent(
            self.context,
            umo="",  # 主 agent 用虚拟会话
            provider_id=self.provider_id,
            system_prompt=system,
            prompt=materials,
            tools=tools,
        )
        if not commit_state.get("committed"):
            text2, _ = await run_night_agent(
                self.context,
                umo="",
                provider_id=self.provider_id,
                system_prompt=system,
                prompt=(
                    "你还没有调用 astrhe_commit。如果草稿写好了，请调用它提交；"
                    "如果今晚确实不该提交，请说明原因。"
                ),
                tools=tools,
                contexts=contexts,
            )
            text = text2 or text
        return text
