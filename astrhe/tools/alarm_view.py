"""夜间闹钟分层展示；完整字段不截断，历史列表用分页。"""

import json
from datetime import datetime

from .. import constants as C
from ..storage.alarms import is_live_alarm
from ..timeutil import local_datetime_str, utc_now

CARD_LABELS = {
    "background": "背景",
    "purpose": "目的",
    "how": "做法",
    "involved": "牵涉的人",
    "mentions": "提及对象",
    "secret_from": "保密对象",
    "taboo": "禁忌",
    "agreed": "事先约定",
    "agreed_reason": "约定理由",
    "plan_date": "关联规划日",
}


def creator_label(alarm: dict, admins=()) -> str:
    if alarm["origin"] == "night":
        return "夜间自己"
    qq = alarm["creator_id"]
    return f"白天{'管理员' if qq in admins else '其他人'} QQ {qq or '未知'}"


def alarm_time(alarm: dict, tz) -> str:
    if alarm["cron_expression"]:
        return f"重复规则 {alarm['cron_expression']}"
    if alarm["run_at"] is not None:
        return local_datetime_str(alarm["run_at"], tz)
    return "时间未建立"


def format_night_alarm(alarm: dict, tz, admins=(), last_event=None) -> str:
    """完整卡片：每个字段出现一次，夜间自行阅读不遮挡秘密。"""
    status = alarm["status"]
    if alarm["cron_expression"] and is_live_alarm(alarm):
        latest = (
            f"{local_datetime_str(last_event['ts'], tz)}（{last_event.get('result', last_event['kind'])}）"
            if last_event
            else "未见执行记录"
        )
        status = f"重复中，最近一次执行于 {latest}"
    card = json.loads(alarm["card_json"] or "{}")
    lines = [
        f"#{alarm['id']} [{status}] {alarm_time(alarm, tz)} → {alarm['target_umo']}"
        f"（定时任务 {alarm['cron_job_id']}；创建者：{creator_label(alarm, admins)}）"
    ]
    for key, value in card.items():
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"{CARD_LABELS.get(key, key)}：{value}")
    lines.append(f"结果：{alarm['result_note'] or '未记录'}")
    return "\n".join(lines)


def format_finished_alarm(alarm: dict, tz, admins=()) -> str:
    card = json.loads(alarm["card_json"] or "{}")
    text = (
        f"#{alarm['id']} [{alarm['status']}] {alarm_time(alarm, tz)} → {alarm['target_umo']}"
        f"；创建者：{creator_label(alarm, admins)}；目的：{card.get('purpose', '')}"
        f"；结果：{alarm['result_note'] or '未记录'}"
    )
    return text.replace("\n", " ↵ ").replace("\r", "")


async def full_alarm(storage, alarm, tz, admins=()):
    event = await storage.db.fetchone(
        "SELECT * FROM alarm_events WHERE alarm_id=? "
        "AND kind IN ('fired','manual_run') ORDER BY ts DESC,id DESC LIMIT 1",
        (alarm["id"],),
    )
    if event and alarm["cron_expression"]:
        rows = await storage.alarms.events(alarm["id"], event["ts"])
        failed = [e for e in rows if e["kind"] == "send_failed"]
        event["result"] = (
            "发送失败：" + failed[-1]["detail"]
            if failed
            else "已完成"
            if any(e["kind"] == "done" for e in rows)
            else "消息已发出"
            if any(e["kind"] == "send_ok" for e in rows)
            else alarm["result_note"] or alarm["status"]
        )
    return format_night_alarm(alarm, tz, admins, event)


async def night_alarm_materials(storage, tz, admins=()):
    lines = ["【生效中的 AstrHe 闹钟】"]
    for alarm in await storage.alarms.live_alarms():
        lines.append(await full_alarm(storage, alarm, tz, admins))
    # 已结束的只列最近几天，更早的给总数并提示翻页，避免每晚材料越积越长
    days = C.NIGHT_FINISHED_ALARM_DAYS
    recent = await storage.alarms.finished_since(utc_now() - days * 86400)
    lines.append(f"【最近 {days} 天结束的 AstrHe 闹钟】")
    lines.extend(format_finished_alarm(a, tz, admins) for a in recent)
    older = await storage.alarms.count_alarms("finished") - len(recent)
    if older > 0:
        lines.append(
            f"更早结束的还有 {older} 条，需要时用 astrhe_read_alarms(scope=finished) 翻页查看"
        )
    return "\n".join(lines)


def job_schedule_text(job, tz) -> str:
    """平台任务的执行时间：一次性任务取 payload.run_at（AstrBot 建任务时写入），
    重复任务给出重复规则。名字只是标签，主 agent 要按这里的时间判断会不会撞车。"""
    if job.cron_expression and not job.run_once:
        return f"重复规则 {job.cron_expression}"
    raw = (job.payload or {}).get("run_at")
    if not raw:
        return "执行时间未知"
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return f"执行时间 {raw}"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    ts = dt.timestamp()
    passed = "（已过）" if ts < utc_now() else ""
    return f"执行时间 {local_datetime_str(ts, tz)}{passed}"


async def platform_tasks(storage, context, tz):
    cron = getattr(context, "cron_manager", None)
    if cron is None:
        return ""
    try:
        jobs = await cron.list_jobs("active_agent")
    except Exception as exc:
        return f"读取平台当前任务失败：{exc}"
    ids = {a["cron_job_id"] for a in await storage.alarms.list_alarms(-1)}
    lines = []
    for j in jobs:
        payload = j.payload or {}
        line = (
            f"[{'AstrHe' if j.job_id in ids else '外部'}] {j.job_id}「{j.name}」"
            f"→ {payload.get('session', '')}；{job_schedule_text(j, tz)}；"
            f"enabled={j.enabled} run_once={j.run_once}"
        )
        if j.job_id not in ids:
            # AstrHe 闹钟的完整卡片在上面；外部任务只有这里，附上说明避免凭名字猜用途
            note = str(payload.get("note") or j.description or "").replace("\n", " ")
            if note:
                line += f"\n    说明：{note}"
        lines.append(line)
    return "【平台当前任务】（外部任务以这里的执行时间和说明为准）\n" + "\n".join(lines)


async def read_alarms(
    storage, context, tz, admins=(), *, scope="active", alarm_id=0, offset=0
):
    if alarm_id:
        alarm = await storage.alarms.get_alarm(int(alarm_id))
        if alarm is None:
            return f"找不到闹钟 #{alarm_id}"
        lines = [await full_alarm(storage, alarm, tz, admins), "全部执行事件："]
        lines.extend(
            f"{local_datetime_str(e['ts'], tz)} [{e['kind']}] {e['detail']}"
            for e in await storage.alarms.events(alarm["id"])
        )
        return "\n".join(lines)
    if scope not in ("active", "finished", "all"):
        return "scope 只能是 active / finished / all"
    total = await storage.alarms.count_alarms(scope)
    lines = [f"AstrHe 闹钟（{scope}，总数 {total}）："]
    if scope in ("active", "all"):
        for alarm in await storage.alarms.live_alarms():
            lines.append(await full_alarm(storage, alarm, tz, admins))
    if scope in ("finished", "all"):
        offset = max(0, int(offset))
        count = await storage.alarms.count_alarms("finished")
        page = await storage.alarms.finished_alarms(C.ALARM_HISTORY_PAGE_SIZE, offset)
        lines.append(f"已结束 {count} 条，本页 {len(page)} 条：")
        lines.extend(format_finished_alarm(a, tz, admins) for a in page)
        if offset + len(page) < count:
            lines.append(
                f"还有更多，继续翻传 scope={scope}, offset={offset + len(page)}"
            )
    lines.append(await platform_tasks(storage, context, tz))
    return "\n".join(lines)
