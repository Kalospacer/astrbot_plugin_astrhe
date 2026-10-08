"""白天注入测试：可见性、show_from、保密提醒与在场判定、600 字截断、
移除 future_task、无内容不注入。"""

from __future__ import annotations

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from astrhe.injector import Injector
from astrhe.timeutil import local_date_str, utc_now
from astrhe.tools.secrecy import PresentResolver
from tests.conftest import FakeContext, FakeLogger, arun, make_storage

GROUP_UMO = "default:GroupMessage:20002"
OTHER_UMO = "default:GroupMessage:33333"
TODAY = local_date_str(utc_now(), ZoneInfo("Asia/Shanghai"))  # 真实今天


def _injector(s, ctx=None, enabled=True):
    ctx = ctx or FakeContext()

    # PresentResolver 需要 qq client；测试里用一个最小的假 client
    class _QQ:
        async def call(self, action, **params):
            return []

    secrecy = PresentResolver(s, _QQ())
    return Injector(
        s,
        lambda: __import__("zoneinfo").ZoneInfo("Asia/Shanghai"),
        secrecy,
        lambda: enabled,
        FakeLogger(),
    )


async def _setup(s):
    run_id = await s.runs.start_run(plan_date=TODAY, mode="auto")
    plan_id = await s.plans.save_plan(
        run_id=run_id,
        plan_date=TODAY,
        full_text="规划全文",
        reflection="完整反思不自动切片",
        day_reminders="别太复读\n少熬夜\n多倾听",
    )
    await s.plans.save_sections(plan_id, {GROUP_UMO: "这个群今天要聊生日的事"})


async def _main_visible(tmp_path):
    s = await make_storage(tmp_path)
    try:
        await _setup(s)
        await s.plans.add_todo(
            content="给哥哥准备生日",
            visible_umos=[GROUP_UMO],
            due_kind="today",
            due_date=TODAY,
        )
        await s.plans.add_todo(
            content="别的群的事",
            visible_umos=[OTHER_UMO],
            due_kind="today",
            due_date=TODAY,
        )
        inj = _injector(s)
        text = await inj.build_injection(GROUP_UMO, "10001")
        assert "给哥哥准备生日" in text
        assert "别的群的事" not in text  # 可见性过滤
        assert "这个群今天要聊生日的事" in text
        assert "别太复读" in text  # 自我反思
    finally:
        await s.close()


def test_visible_filter(tmp_path):
    arun(_main_visible(tmp_path))


async def _main_show_from(tmp_path):
    s = await make_storage(tmp_path)
    try:
        await _setup(s)
        # 未来待办：show_from 是明天，今天不贴
        await s.plans.add_todo(
            content="未来的事",
            visible_umos=[GROUP_UMO],
            due_kind="future",
            due_date="2099-01-05",
            show_from="2099-01-03",
        )
        inj = _injector(s)
        text = await inj.build_injection(GROUP_UMO, "10001")
        assert "未来的事" not in text
    finally:
        await s.close()


def test_show_from(tmp_path):
    arun(_main_show_from(tmp_path))


async def _main_secret(tmp_path):
    s = await make_storage(tmp_path)
    try:
        await _setup(s)
        # 保密待办：对 10001 保密；10001 在群里发过言（在场）
        await s.plans.add_todo(
            content="给 10001 准备惊喜派对",
            visible_umos=[GROUP_UMO],
            secret_from=["10001"],
            due_kind="today",
            due_date=TODAY,
        )
        await s.ledger.add_message(
            umo=GROUP_UMO,
            platform_id="default",
            message_type="GroupMessage",
            session_id="20002",
            sender_id="10001",
            text="冒泡",
            ts=__import__("time").time(),
            platform_message_id="9001",
        )
        inj = _injector(s)
        text = await inj.build_injection(GROUP_UMO, "40004")
        assert "惊喜派对" not in text  # 保密对象在场 → 待办不贴
        assert "不要承认在准备什么" in text  # 有保密提醒
        # 保密对象本人视角同样看不到
        text2 = await inj.build_injection(GROUP_UMO, "10001")
        assert "惊喜派对" not in text2
    finally:
        await s.close()


def test_secret_presence(tmp_path):
    arun(_main_secret(tmp_path))


async def _main_truncate(tmp_path):
    s = await make_storage(tmp_path)
    try:
        # 上次运行失败 + 超长内容：陈旧提示不被截掉
        run_id = await s.runs.start_run(plan_date=TODAY, mode="auto")
        await s.runs.finish_run(run_id, "failed", error="测试失败")
        plan_id = await s.plans.save_plan(
            run_id=run_id - 1 or 1,
            plan_date="2098-12-31",
            full_text="旧规划",
            reflection="",
        )
        long_section = "很长的规划段落。" * 200
        await s.plans.save_sections(plan_id, {GROUP_UMO: long_section})
        inj = _injector(s)
        text = await inj.build_injection(GROUP_UMO, "10001")
        assert "昨晚的复盘没完成" in text  # 陈旧提示保留
        assert long_section in text  # 完整注入，不截断
    finally:
        await s.close()


def test_full_injection_keeps_stale_note(tmp_path):
    arun(_main_truncate(tmp_path))


async def _main_empty(tmp_path):
    s = await make_storage(tmp_path)
    try:
        inj = _injector(s)
        text = await inj.build_injection(GROUP_UMO, "10001")
        assert text == ""  # 没有任何内容时不注入
    finally:
        await s.close()


def test_no_injection_when_empty(tmp_path):
    arun(_main_empty(tmp_path))


def test_hide_future_task():
    class _T:
        def __init__(self, name):
            self.name = name

    req = SimpleNamespace(
        func_tool=SimpleNamespace(tools=[_T("future_task"), _T("other")])
    )
    Injector._hide_future_task(req)
    names = [t.name for t in req.func_tool.tools]
    assert "future_task" not in names and "other" in names
