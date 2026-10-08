"""夜间闹钟材料：完整时间和卡片，不做白天会话的保密遮挡。"""

import json

from ..timeutil import local_datetime_str


def format_night_alarm(alarm: dict, tz) -> str:
    when = (
        local_datetime_str(alarm["run_at"], tz)
        if alarm["run_at"] is not None
        else f"重复规则 {alarm['cron_expression']}"
    )
    card = json.loads(alarm["card_json"] or "{}")
    return (
        f"#{alarm['id']} [{alarm['status']}] {when} → {alarm['target_umo']}"
        f"（定时任务 {alarm['cron_job_id']}）\n"
        f"目的：{card.get('purpose', '')}\n背景：{card.get('background', '')}\n"
        "完整卡片：" + json.dumps(card, ensure_ascii=False)
    )
