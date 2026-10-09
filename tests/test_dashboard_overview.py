"""查看页总览接口：档案阵列需要的规划书全文、闹钟事件与保密判定数据。"""

from types import SimpleNamespace
from zoneinfo import ZoneInfo

import yaml

from astrhe import constants as C
from astrhe.webapi import WebApi
from tests.conftest import FakeContext, arun, make_storage


def test_overview_carries_dashboard_archive_fields(tmp_path, monkeypatch):
    async def check():
        import astrhe.webapi as module

        monkeypatch.setattr(
            module, "astrbot_web", SimpleNamespace(json_response=lambda value: value)
        )
        s = await make_storage(tmp_path)
        try:
            run_id = await s.runs.start_run(plan_date="2026-10-09")
            for day in range(C.DASHBOARD_COLUMN_LIMIT + 2):
                plan_id = await s.plans.save_plan(
                    run_id=run_id,
                    plan_date=f"2026-09-{day + 1:02d}",
                    full_text=f"第 {day} 天【保密:50001】惊喜【/保密】",
                    reflection="反思",
                    day_reminders="提醒",
                )
                await s.plans.save_sections(
                    plan_id, {"default:FriendMessage:50002": f"段落 {day}"}
                )
            alarm_id = await s.alarms.add_alarm(
                target_umo="default:FriendMessage:50002", card={"purpose": "提醒"}
            )
            await s.alarms.add_event(alarm_id, "fired")
            api = WebApi(
                s,
                FakeContext(),
                lambda: ZoneInfo("Asia/Shanghai"),
                lambda: {"running": False},
                lambda: ["50001"],
            )
            data = await api._overview()
            details = data["plan_details"]
            assert len(details) == C.DASHBOARD_COLUMN_LIMIT
            assert details[0]["plan_date"] == "2026-09-22"
            assert "【保密:50001】" in details[0]["full_text"]
            assert details[0]["sections"] == {"default:FriendMessage:50002": "段落 21"}
            assert details[0]["day_reminders"] == "提醒"
            assert [e["kind"] for e in data["alarm_events"][str(alarm_id)]] == ["fired"]
            assert data["admins"] == ["50001"]
            assert data["timezone"] == "Asia/Shanghai"
            metadata = yaml.safe_load(
                (module.Path(module.__file__).parents[1] / "metadata.yaml").read_text(
                    encoding="utf-8"
                )
            )
            assert data["version"] == str(metadata["version"])
            # 旧字段保持不变
            assert len(data["plans"]) == 22 and "full_text" not in data["plans"][0]
        finally:
            await s.close()

    arun(check())
