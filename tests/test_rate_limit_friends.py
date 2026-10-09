"""频率上限与好友申请测试。"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from astrhe import constants as C
from astrhe.qq.friend_requests import FriendRequestManager
from astrhe.qq.rate_limit import RateLimiter
from tests.conftest import FakeContext, FakeLogger, arun, make_storage
from astrhe.platform import PlatformHelper
from astrhe.qq.client import QQClient
from astrhe.timeutil import utc_now

TZ = ZoneInfo("Asia/Shanghai")


async def _main_rate(tmp_path):
    s = await make_storage(tmp_path)
    try:
        limiter = RateLimiter(s, lambda: TZ)
        now = utc_now()
        # 戳一戳：每人每天 3 次
        for _ in range(C.RATE_POKE_PER_USER_PER_DAY):
            assert await limiter.check("poke", now, target="10001") == ""
            await limiter.record("poke", target="10001")
        assert "嫌弃" in await limiter.check("poke", now, target="10001")
        # 换个人不受此人上限影响
        assert await limiter.check("poke", now, target="40004") == ""
        # 贴表情：每会话每小时 6 次
        for _ in range(C.RATE_REACT_PER_SESSION_PER_HOUR):
            assert await limiter.check("react", now, umo="default:GroupMessage:1") == ""
            await limiter.record("react", umo="default:GroupMessage:1")
        assert "歇" in await limiter.check("react", now, umo="default:GroupMessage:1")
        # 签名：7 天内最多换一次（白天夜里共用）
        assert await limiter.check("signature", now) == ""
        await limiter.record("signature", target="新签名")
        assert "天内最多换一次" in await limiter.check("signature", now)
    finally:
        await s.close()


def test_rate_limit(tmp_path):
    arun(_main_rate(tmp_path))


async def _main_friend(tmp_path):
    s = await make_storage(tmp_path)
    try:
        ctx = FakeContext()
        qq = QQClient(PlatformHelper(ctx, FakeLogger()))
        manager = FriendRequestManager(s, qq, FakeLogger())

        # 申请进来：非预期联系人不动
        await s.ledger.add_friend_request(
            user_id="50005", flag="flag-1", comment="", ts=utc_now()
        )
        assert not await manager.handle_incoming("50005", "flag-1", "")
        assert not any(c[0] == "set_friend_add_request" for c in ctx.api.calls)

        # 预期联系人：自动同意并清掉预期标记
        await s.persons.set_expected_friend("50005", utc_now() + 86400, "生日帮手")
        assert await manager.handle_incoming("50005", "flag-1", "")
        assert any(c[0] == "set_friend_add_request" for c in ctx.api.calls)
        assert not await s.persons.is_expected_friend("50005", utc_now())

        # 事后补做同意：先申请、后被标为预期 → 夜间 followup 补同意
        await s.ledger.add_friend_request(
            user_id="60006", flag="flag-2", comment="", ts=utc_now()
        )
        await s.persons.set_expected_friend("60006", utc_now() + 86400, "帮手2")
        results = await manager.nightly_followup()
        assert any("补同意" in r for r in results)
        pending = await s.ledger.pending_friend_requests()
        assert all(p["user_id"] != "60006" for p in pending)

        # 过期失效：expected_friend_until 已过的不再同意
        await s.ledger.add_friend_request(
            user_id="70007", flag="flag-3", comment="", ts=utc_now()
        )
        await s.persons.set_expected_friend("70007", utc_now() - 10, "过期的")
        assert not await manager.handle_incoming("70007", "flag-3", "")
    finally:
        await s.close()


def test_friend_requests(tmp_path):
    arun(_main_friend(tmp_path))
