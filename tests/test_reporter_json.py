"""汇报 JSON 修复沿用首轮上下文，合法输出立即采用。"""

import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from astrhe import constants as C
from astrhe.night.reporter import FIX_JSON_PROMPT, Reporter
from astrhe.timeutil import utc_now
from tests.conftest import FakeContext, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")
UMO = "default:GroupMessage:20002"


class HistoryLoop:
    """模拟 AstrBot 的上下文钩子，保留请求和最终回答。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def __call__(self, **kw):
        self.calls.append(kw)
        messages = list(kw["contexts"])
        messages.append({"role": "user", "content": kw["prompt"]})
        run_context = SimpleNamespace(messages=messages)
        await kw["agent_hooks"].on_agent_begin(run_context)
        text = self.outputs.pop(0)
        messages.append({"role": "assistant", "content": text})
        response = SimpleNamespace(role="assistant", completion_text=text)
        await kw["agent_hooks"].on_agent_done(run_context, response)
        return response


@pytest.mark.parametrize("repair", [False, True])
def test_single_chunk_keeps_first_history_and_stops_at_first_valid_json(tmp_path, repair):
    async def check():
        s = await make_storage(tmp_path)
        try:
            now = utc_now()
            rid = await s.runs.start_run(plan_date="2026-10-08")
            await s.ledger.add_message(
                umo=UMO, platform_id="default", message_type="GroupMessage",
                session_id="20002", sender_id="10001", text="已经把蛋糕准备好了",
                ts=now - 1, platform_message_id="5010",
            )
            valid = '{"summary":"蛋糕已完成","big_events":[]}'
            ctx = FakeContext()
            loop = HistoryLoop(
                (["这是一段散文"] if repair else []) + [valid, "不要请求到这段"]
            )
            ctx.tool_loop_agent = loop
            reporter = Reporter(s, ctx, "fake", "人格", TZ, [], self_id="99999")
            result = await reporter.report_session(rid, UMO, now - 10, now + 1)
            assert result["parse_ok"] and result["report"]["summary"] == "蛋糕已完成"
            assert len(loop.calls) == (2 if repair else 1)
            assert all(call["stream"] for call in loop.calls)
            if repair:
                followup = loop.calls[1]
                assert followup["prompt"] == FIX_JSON_PROMPT
                assert "蛋糕" not in followup["prompt"]
                history = followup["contexts"]
                assert "已经把蛋糕准备好了" in history[0]["content"]
                assert history[-1]["content"] == "这是一段散文"
                assert followup["tools"].tools == []
            saved = (await s.runs.get_reports(rid))[0]
            assert json.loads(saved["content_json"])["summary"] == "蛋糕已完成"
        finally:
            await s.close()
    arun(check())


def test_merge_json_fix_only_reasks_format_without_remerging_materials(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "REPORT_CHUNK_SIZE", 1)

    async def check():
        s = await make_storage(tmp_path)
        try:
            now = utc_now()
            rid = await s.runs.start_run(plan_date="2026-10-08")
            for index in range(2):
                await s.ledger.add_message(
                    umo=UMO, platform_id="default", message_type="GroupMessage",
                    session_id="20002", sender_id="10001", text=f"聊天 {index}",
                    ts=now - 2 + index, platform_message_id=str(5010 + index),
                )
            ctx = FakeContext()
            loop = HistoryLoop([
                '{"summary":"第一块"}', '{"summary":"第二块"}',
                "这是一段合并散文", '{"summary":"完整汇报"}', "不应再次请求",
            ])
            ctx.tool_loop_agent = loop
            result = await Reporter(
                s, ctx, "fake", "人格", TZ, [], self_id="99999"
            ).report_session(rid, UMO, now - 10, now + 1)
            assert result["report"]["summary"] == "完整汇报"
            assert len(loop.calls) == 4
            merge, fix = loop.calls[2:]
            assert "第一块" in merge["prompt"] and "第二块" in merge["prompt"]
            assert fix["prompt"] == FIX_JSON_PROMPT
            assert fix["contexts"][0]["content"] == merge["prompt"]
            assert fix["contexts"][-1]["content"] == "这是一段合并散文"
        finally:
            await s.close()
    arun(check())


def test_still_invalid_json_preserves_raw_report_after_one_format_followup(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            now = utc_now()
            rid = await s.runs.start_run(plan_date="2026-10-08")
            await s.ledger.add_message(
                umo=UMO, platform_id="default", message_type="GroupMessage",
                session_id="20002", sender_id="10001", text="需要人工确认的安排",
                ts=now - 1, platform_message_id="5010",
            )
            ctx = FakeContext()
            ctx.tool_loop_agent = HistoryLoop(["第一次散文", "仍是散文"])
            result = await Reporter(
                s, ctx, "fake", "人格", TZ, []
            ).report_session(rid, UMO, now - 10, now + 1)
            assert not result["parse_ok"] and result["raw"] == "仍是散文"
            assert (await s.runs.get_reports(rid))[0]["raw_text"] == "仍是散文"
            assert len(ctx.tool_loop_agent.calls) == 2
        finally:
            await s.close()
    arun(check())
