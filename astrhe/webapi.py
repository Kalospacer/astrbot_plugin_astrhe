"""查看页后端 Web API（前端页面后续再加）。

路由前缀 /astrbot_plugin_astrhe/...（metadata 中保留大小写的插件名）。
查看页只对管理员开放（AstrBot 面板本身需要登录）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import constants as C
from .tools.validation import validate_anniversaries
from .timeutil import local_datetime_str, utc_now
from .memory_webapi import MemoryWebApi

try:
    from astrbot.api import web as astrbot_web
except Exception:  # pragma: no cover
    astrbot_web = None  # type: ignore[assignment]

ROUTE_BASE = "/astrbot_plugin_astrhe"


def _plugin_version() -> str:
    """查看页显示的版本号，唯一来源是 metadata.yaml。"""
    try:
        text = (Path(__file__).resolve().parents[1] / "metadata.yaml").read_text(
            encoding="utf-8"
        )
    except OSError:
        return "unknown"
    match = re.search(r"^version:\s*(\S+)", text, re.MULTILINE)
    return match.group(1) if match else "unknown"


class WebApi:
    def __init__(
        self, storage: Any, context: Any, tz_getter, runtime_status, admins_getter=None
    ):
        self.storage = storage
        self.context = context
        self._tz_getter = tz_getter
        self._runtime_status = runtime_status  # () -> dict 运行中状态
        # 查看页判断「对管理员保密」
        self._admins_getter = admins_getter or (lambda: [])
        self.memory_api = MemoryWebApi(storage, lambda: astrbot_web, self._json_body)

    def register(self) -> None:
        if astrbot_web is None:
            return
        register = getattr(self.context, "register_web_api", None)
        if not callable(register):
            return
        routes = [
            (
                "/overview",
                self._overview,
                ["GET"],
                "总览：运行、规划、待办、闹钟、关系本、承诺",
            ),
            ("/runs", self._runs, ["GET"], "运行记录"),
            ("/run_detail", self._run_detail, ["GET"], "单次运行详情（汇报、审稿）"),
            ("/todo/delete", self._todo_delete, ["POST"], "删除待办"),
            ("/alarm/cancel", self._alarm_cancel, ["POST"], "取消闹钟"),
            ("/person/save", self._person_save, ["POST"], "编辑关系本关系层与纪念日"),
            ("/promise/delete", self._promise_delete, ["POST"], "删除承诺"),
        ]
        for path, handler, methods, desc in routes + self.memory_api.routes():
            try:
                register(f"{ROUTE_BASE}{path}", handler, methods, desc)
            except Exception:  # noqa: BLE001
                pass

    # ---------------- 查询 ----------------

    async def _overview(self):
        tz = self._tz_getter()
        latest_plan = await self.storage.plans.get_latest_plan()
        todos = await self.storage.plans.list_todos(100)
        alarms = await self.storage.alarms.list_alarms(100)
        persons = await self.storage.persons.list_persons()
        promises = await self.storage.plans.list_promises(100)
        alarm_events = {
            str(a["id"]): await self.storage.alarms.events(a["id"]) for a in alarms
        }
        return astrbot_web.json_response(
            {
                "now": local_datetime_str(utc_now(), tz),
                "timezone": str(tz),
                "version": _plugin_version(),
                "admins": list(self._admins_getter()),
                "runtime": self._runtime_status(),
                "latest_plan": (
                    {
                        "plan_date": latest_plan["plan_date"],
                        "full_text": latest_plan["full_text"],
                        "reflection": latest_plan["reflection"],
                        "sections": await self.storage.plans.get_sections(
                            latest_plan["id"]
                        ),
                    }
                    if latest_plan
                    else None
                ),
                "plans": await self.storage.plans.list_plans(30),
                # 档案阵列的规划书列：每份的全文与段落（与每列上限一致）
                "plan_details": await self.storage.plans.list_plan_details(
                    C.DASHBOARD_COLUMN_LIMIT
                ),
                "alarm_events": alarm_events,
                "todos": [
                    self._json_fields(
                        t, ("visible_umos_json", "secret_from_json", "evidence_json")
                    )
                    for t in todos
                ],
                "alarms": [self._json_fields(a, ("card_json",)) for a in alarms],
                "persons": [
                    self._json_fields(p, ("aliases_json", "anniversaries_json"))
                    for p in persons
                ],
                "promises": [
                    self._json_fields(p, ("evidence_json",)) for p in promises
                ],
            }
        )

    async def _runs(self):
        runs = await self.storage.runs.list_runs(50)
        return astrbot_web.json_response({"runs": runs})

    async def _run_detail(self):
        try:
            run_id = int(astrbot_web.request.query.get("run_id", "0"))
        except (TypeError, ValueError):
            return astrbot_web.error_response("run_id 不合法", status_code=400)
        reports = await self.storage.runs.get_reports(run_id)
        reviews = await self.storage.runs.get_reviews(run_id)
        drafts = await self.storage.runs.get_drafts(run_id, None)
        return astrbot_web.json_response(
            {"reports": reports, "reviews": reviews, "drafts": drafts}
        )

    # ---------------- 操作 ----------------

    async def _todo_delete(self):
        payload = await self._json_body()
        todo_id = int(payload.get("todo_id", 0) or 0)
        return await self._move_to_trash("todo", todo_id)

    async def _alarm_cancel(self):
        payload = await self._json_body()
        alarm_id = int(payload.get("alarm_id", 0) or 0)
        alarm = await self.storage.alarms.get_alarm(alarm_id)
        if alarm is None:
            return astrbot_web.error_response("闹钟不存在", status_code=404)
        if alarm["cron_job_id"]:
            try:
                await self.context.cron_manager.delete_job(alarm["cron_job_id"])
            except Exception as exc:  # noqa: BLE001
                return astrbot_web.error_response(
                    f"取消失败，闹钟保持原状态：{exc}", status_code=500
                )
        await self.storage.alarms.set_status(alarm_id, "cancelled")
        return astrbot_web.json_response({"ok": True})

    async def _person_save(self):
        payload = await self._json_body()
        qq = str(payload.get("qq", "") or "")
        if not qq:
            return astrbot_web.error_response("qq 不能为空", status_code=400)
        anniversaries = payload.get("anniversaries")
        if isinstance(anniversaries, str):
            try:
                anniversaries = json.loads(anniversaries)
            except (ValueError, TypeError):
                return astrbot_web.error_response(
                    "纪念日不是合法 JSON 数组", status_code=400
                )
        if "anniversaries" in payload:
            try:
                validate_anniversaries(anniversaries)
            except ValueError as exc:
                return astrbot_web.error_response(str(exc), status_code=400)
        aliases = payload.get("aliases")
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except (ValueError, TypeError):
                aliases = None
        await self.storage.persons.upsert_person(
            qq,
            aliases=aliases,
            relation_text=payload.get("relation_text"),
            anniversaries=anniversaries,
            merge_aliases=False,
        )
        return astrbot_web.json_response({"ok": True})

    async def _promise_delete(self):
        payload = await self._json_body()
        promise_id = int(payload.get("promise_id", 0) or 0)
        return await self._move_to_trash("promise", promise_id)

    async def _move_to_trash(self, kind: str, target_id: int):
        """删除不对的条目：进回收站，30 天内可用 /memory/restore 恢复。"""
        try:
            await self.storage.memory.move_to_trash(kind, target_id)
        except ValueError as exc:
            return astrbot_web.error_response(str(exc), status_code=400)
        return astrbot_web.json_response({"ok": True, "trash": True})

    # ---------------- 工具 ----------------

    async def _json_body(self) -> dict:
        try:
            payload = await astrbot_web.request.json(default={})
        except Exception:  # noqa: BLE001
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _json_fields(row: dict, fields: tuple) -> dict:
        out = dict(row)
        for f in fields:
            try:
                out[f] = json.loads(out.get(f) or "[]")
            except (ValueError, TypeError):
                pass
        return out
