"""个性签名 7 天内最多换一次：白天夜里共用额度，草稿时就提示，被拦时在线状态照改。"""

from zoneinfo import ZoneInfo

from astrhe import constants as C
from astrhe.night.draft import DraftCommitter
from astrhe.night.planner import signature_material
from astrhe.qq.rate_limit import RateLimiter
from astrhe.timeutil import utc_now
from astrhe.tools.draft_tools import DraftTools
from tests.conftest import FakeContext, FakeEvent, arun, make_storage

TZ = ZoneInfo("Asia/Shanghai")


def test_signature_once_per_interval_and_material_shows_current(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            limiter = RateLimiter(s, lambda: TZ)
            now = utc_now()
            assert await limiter.check("signature", now) == ""
            assert "最近没换过签名" in await signature_material(s, TZ)

            await limiter.record("signature", target="最近嘴巴很紧")
            deny = await limiter.check("signature", now)
            assert f"{C.RATE_SIGNATURE_INTERVAL_DAYS} 天内最多换一次" in deny
            text = await signature_material(s, TZ)
            assert "最近嘴巴很紧" in text and "这次不要写签名草稿" in text

            # 过了间隔就能再换，材料提示可以换但别为了换而换
            later = now + C.RATE_SIGNATURE_INTERVAL_DAYS * 86400 + 60
            assert await limiter.check("signature", later) == ""
            await s.db.execute(
                "UPDATE action_log SET ts=? WHERE action='signature'",
                (now - C.RATE_SIGNATURE_INTERVAL_DAYS * 86400 - 60,),
            )
            text = await signature_material(s, TZ)
            assert "这次可以换" in text and "最近嘴巴很紧" in text
        finally:
            await s.close()

    arun(check())


def test_signature_draft_rejected_early_and_status_still_applied(tmp_path):
    async def check():
        s = await make_storage(tmp_path)
        try:
            rid = await s.runs.start_run(plan_date="2026-10-09")
            limiter = RateLimiter(s, lambda: TZ)
            await limiter.record("signature", target="旧签名")

            async def noop(_):
                return ""

            tools = DraftTools(s, rid, noop, noop, tz_getter=lambda: TZ)
            out = await tools._draft_appearance(FakeEvent(), signature="新签名")
            assert "这次不能换签名" in out
            assert not await s.runs.get_drafts(rid)
            # 只改在线状态的草稿照常收下
            assert "这次不能换签名" not in await tools._draft_appearance(
                FakeEvent(), status_preset="忙碌"
            )

            # 提交时签名被拦，同一份草稿里的在线状态照常改
            ctx = FakeContext()
            committer = DraftCommitter(
                s, ctx, rid, "2026-10-09", TZ, limiter, admins=[]
            )
            result = await committer._apply_appearance(
                {"signature": "新签名", "status_preset": "忙碌"}
            )
            assert "改签名被拦下" in result
            called = [action for action, _ in ctx.api.calls]
            assert "set_self_longnick" not in called
            assert "set_online_status" in called
        finally:
            await s.close()

    arun(check())
