"""绝对日期、人格边界、材料完整性与跨会话保密。"""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astrhe.injector import Injector
from astrhe.night.planner import Planner
from astrhe.night.reporter import Reporter
from astrhe.night.reviewer import Reviewer
from astrhe.platform import PlatformHelper, event_umo
from astrhe.prompts import planner, reporter, reviewer
from astrhe.qq.client import QQClient
from astrhe.timeutil import build_time_info, utc_now
from astrhe.tools.day_tools import DayTools
from astrhe.tools.reader_tools import ReaderTools
from astrhe.tools.secrecy import PresentResolver, filter_secret_text
from tests.conftest import FakeContext, FakeEvent, FakeLogger, arun, make_storage
from tests.test_schedule_tool import _impl, _future

TZ = ZoneInfo("Asia/Shanghai")
UMO = "default:GroupMessage:20002"


def test_shared_time_and_persona_prompts():
    start = datetime(2026, 10, 6, 12, tzinfo=TZ).timestamp()
    end = datetime(2026, 10, 8, 0, tzinfo=TZ).timestamp()
    info = build_time_info(start, end, "2026-10-08", TZ)
    prompts = [
        planner.build_planner_system("每次只说两句", ["10001"], info),
        reporter.build_reporter_system(
            "每次只说两句",
            "",
            time_info=info,
            session="群聊 20002",
            self_id="99999",
            admins=["10001"],
        ),
        reviewer.build_reviewer_system("每次只说两句", ["10001"], "全面", info),
    ]
    for text in prompts:
        assert "2026-10-08 星期四" in text
        assert "2026-10-06 12:00" in text
        assert "人格说明" in text and "不受人格里" in text
        assert "10001" in text and "明天" not in text
    assert "group:群号" in prompts[0] and "private:QQ号" in prompts[0]
    assert "99999" in prompts[1] and "20002" in prompts[1]
    assert "astrhe_read_reports" in prompts[2]


def test_materials_include_pending_notes_and_all_speakers(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext(api_actions={"get_login_info": {"user_id": 99999}})
            now = utc_now()
            await s.persons.upsert_person(
                "50005", relation_text="窗口内发言的朋友", anniversaries=["旧坏数据"]
            )
            await s.ledger.add_message(
                umo=UMO,
                platform_id="default",
                message_type="GroupMessage",
                session_id="20002",
                sender_id="50005",
                text="你好",
                ts=now - 10,
                platform_message_id="9010",
            )
            await s.ledger.add_friend_request(
                user_id="60006", flag="flag", comment="约定来加好友", ts=now - 5
            )
            await s.plans.add_todo(
                content="还在做", visible_umos=[UMO], note="她负责蛋糕"
            )
            tid = await s.plans.add_todo(content="已经完成", visible_umos=[UMO])
            await s.plans.update_todo_status(tid, "done", "已买好礼物")
            p = Planner(
                s, ctx, "fake", "人格", ["10001"], TZ, window=(now - 100, now + 1)
            )
            materials = await p.build_materials([], "发送失败", True)
            assert all(
                t in materials
                for t in (
                    "60006",
                    "约定来加好友",
                    "她负责蛋糕",
                    "已经完成",
                    "已买好礼物",
                    "窗口内发言的朋友",
                    "上一次运行失败",
                )
            )
            rid = await s.runs.start_run(plan_date="2026-10-08")
            await s.runs.add_report(
                run_id=rid,
                umo=UMO,
                chunk_index=0,
                content={"summary": "会话完整汇报"},
                raw_text="原文" * 600,
            )
            reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, now), run_id=rid)
            assert "原文" * 600 in await reader._read_reports(None)
            r = Reviewer(
                s,
                ctx,
                "fake",
                "人格",
                ["10001"],
                reader.build(),
                time_info="规划日：2026-10-08 星期四",
            )
            await r.review(rid, "全面")
            assert any("会话完整汇报" in c["prompt"] for c in ctx.tool_loop_agent.calls)
            rep = Reporter(
                s,
                ctx,
                "fake",
                "人格",
                TZ,
                [],
                time_info="规划日：2026-10-08 星期四",
                admins=["10001"],
                self_id="99999",
            )
            await rep.report_session(rid, UMO, now - 100, now + 1)
            system = ctx.tool_loop_agent.calls[-1]["system_prompt"]
            assert "群聊 20002" in system and "99999" in system
            assert "人格说明" in system and "2026-10-08" in system
        finally:
            await s.close()

    arun(check())


def test_isolated_session_injection_todo_plan_schedule_and_global_secrecy(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            ctx = FakeContext()
            qq = QQClient(PlatformHelper(ctx, FakeLogger()))
            secrecy = PresentResolver(s, qq)
            rid = await s.runs.start_run(plan_date="2026-10-08")
            secret = "【保密： 10001】惊喜内容【/保密】"
            plan_id = await s.plans.save_plan(
                run_id=rid,
                plan_date="2026-10-08",
                full_text=secret,
                day_reminders="提醒" * 500,
            )
            await s.plans.save_sections(plan_id, {UMO: "段落" * 1000 + secret})
            tid = await s.plans.add_todo(content="普通待办", visible_umos=[UMO])
            # 保密待办对这个群不可见，仍然触发不含秘密的通用提醒。
            await s.plans.add_todo(
                content="另一个群的惊喜",
                visible_umos=["default:GroupMessage:33333"],
                secret_from=["10001"],
            )
            event = FakeEvent(umo="default:GroupMessage:10001_20002")
            assert event_umo(event) == UMO
            inj = Injector(s, lambda: TZ, secrecy, lambda: True, FakeLogger())
            req = SimpleNamespace(extra_user_content_parts=[], func_tool=None)
            await inj.on_llm_request(event, req)
            text = req.extra_user_content_parts[-1].text
            assert "不要承认在准备什么" in text and "惊喜内容" not in text
            assert "段落" * 1000 in text and "提醒" * 500 in text and "普通待办" in text
            assert "完成" in await DayTools(s, lambda: TZ).todo_update(
                event, todo_id=tid, status="done", note="做好了"
            )
            reader = ReaderTools(s, ctx, lambda: TZ, lambda: (0, utc_now()), secrecy)
            assert "惊喜内容" not in await reader._read_plan(event)
            impl = _impl(s, ctx)
            result = await impl.run(
                event,
                action="create",
                run_at=_future(),
                background="背景",
                purpose="秘密目的",
                how="做法",
                secret_from=["10001"],
            )
            assert "定好了" in result
            job = ctx.cron_manager.added[-1]
            assert job["payload"]["session"] == UMO
            assert "秘密目的" not in job["description"]
            assert "总结只写一句『已完成』" in job["payload"]["note"]
            assert "惊喜内容" not in filter_secret_text(
                secret, viewer_id="10001", session_umo=UMO, present_ids=set()
            )
        finally:
            await s.close()

    arun(check())
