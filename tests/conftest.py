"""AstrHe 测试公共假对象。

全部用小型假对象模拟 AstrBot：不发真实网络请求，不调用真实模型。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from astrhe.storage import Storage


class FakeLogger:
    def __init__(self):
        self.infos: list = []
        self.warnings: list = []
        self.debugs: list = []

    def info(self, *args):
        self.infos.append(args)

    def warning(self, *args):
        self.warnings.append(args)

    def debug(self, *args):
        self.debugs.append(args)

    def error(self, *args, **kwargs):
        pass


class FakeCronJob:
    _seq = 0

    def __init__(self, **kwargs):
        FakeCronJob._seq += 1
        self.job_id = kwargs.get("job_id") or f"job-{FakeCronJob._seq}"
        self.name = kwargs.get("name", "")
        self.description = kwargs.get("description")
        self.job_type = "active_agent"
        self.cron_expression = kwargs.get("cron_expression")
        self.timezone = kwargs.get("timezone")
        self.payload = kwargs.get("payload", {})
        self.enabled = kwargs.get("enabled", True)
        self.persistent = kwargs.get("persistent", True)
        self.run_once = kwargs.get("run_once", False)


class FakeCronManager:
    """模拟 cron_manager：记录全部调用。"""

    def __init__(self):
        self.jobs: dict[str, FakeCronJob] = {}
        self.added: list[dict] = []
        self.deleted: list[str] = []
        self.updated: list[tuple] = []

    async def add_active_job(self, **kwargs) -> FakeCronJob:
        job = FakeCronJob(**kwargs)
        self.jobs[job.job_id] = job
        self.added.append(kwargs)
        return job

    async def list_jobs(self, job_type: str | None = None) -> list[FakeCronJob]:
        return list(self.jobs.values())

    async def update_job(self, job_id: str, **kwargs) -> FakeCronJob | None:
        job = self.jobs.get(job_id)
        self.updated.append((job_id, kwargs))
        if job is None:
            return None
        for k, v in kwargs.items():
            setattr(job, k, v)
        return job

    async def delete_job(self, job_id: str) -> None:
        self.deleted.append(job_id)
        self.jobs.pop(job_id, None)


class FakeApi:
    """模拟 CQHttp api.call_action，actions 是 {动作名: 返回值或callable或异常}。"""

    def __init__(self, actions: dict | None = None):
        self.actions = {
            "get_group_list": [{"group_id": 20002}],
            "get_friend_list": [{"user_id": 40004}],
        }
        self.actions.update(actions or {})
        self.calls: list[tuple] = []

    async def call_action(self, action: str, **params):
        self.calls.append((action, params))
        value = self.actions.get(action)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(**params)
        if value is not None:
            return value
        return {}


class FakeClient:
    def __init__(self, api: FakeApi):
        self.api = api


class FakePlatform:
    def __init__(self, api: FakeApi, platform_id: str = "default"):
        self._api = api
        self._id = platform_id

    def meta(self):
        return SimpleNamespace(name="aiocqhttp", id=self._id)

    def get_client(self):
        return FakeClient(self._api)


class FakePersonaManager:
    def get_persona_v3_by_id(self, persona_id):
        return {"prompt": "选定的人格"} if persona_id == "selected" else None

    async def get_default_persona_v3(self, umo=None):
        return {"prompt": "你是测试人格。"}


class ScriptedToolLoop:
    """假的 tool_loop_agent：按脚本顺序处理每次调用。

    handlers 中每项是 async callable(kwargs) -> str；返回空串即 role="err" 由
    raise_err 控制。handler 里可以手动调用工具驱动流程。
    """

    def __init__(self, handlers: list | None = None):
        self.handlers = list(handlers or [])
        self.calls: list[dict] = []

    async def __call__(self, **kwargs) -> Any:
        self.calls.append(kwargs)
        hooks = kwargs.get("agent_hooks")
        if not self.handlers:
            resp = SimpleNamespace(role="assistant", completion_text="好的")
        else:
            handler = self.handlers.pop(0)
            text = await handler(kwargs)
            if text == "ERR":  # 脚本约定：返回 ERR 表示模型请求失败
                resp = SimpleNamespace(role="err", completion_text="模拟模型报错")
            else:
                resp = SimpleNamespace(role="assistant", completion_text=text)
        if hooks is not None:
            run_context = SimpleNamespace(messages=[])
            await hooks.on_agent_done(run_context, resp)
        return resp


class FakeContext:
    def __init__(self, api_actions: dict | None = None, config: dict | None = None):
        self.cron_manager = FakeCronManager()
        self.api = FakeApi(api_actions)
        self.platform_manager = SimpleNamespace(platform_insts=[FakePlatform(self.api)])
        self.persona_manager = FakePersonaManager()
        self._config = config or {
            "timezone": "Asia/Shanghai",
            "admins_id": ["10001", "astrbot"],
        }
        self.sent_messages: list = []
        self.tool_loop_agent = ScriptedToolLoop()
        self.registered_web_apis: list = []
        self.registered_tools: list = []
        self.provider_manager = SimpleNamespace(llm_tools=SimpleNamespace(func_list=[]))

    def get_llm_tool_manager(self):
        from astrbot.core.agent.tool import ToolSet

        return SimpleNamespace(
            get_full_tool_set=lambda: ToolSet(
                tools=self.provider_manager.llm_tools.func_list
            )
        )

    def get_config(self, umo=None):
        return self._config

    def get_platform_inst(self, platform_id: str):
        for inst in self.platform_manager.platform_insts:
            if inst.meta().id == platform_id:
                return inst
        return None

    async def get_using_provider_async(self, umo=None):
        return SimpleNamespace(meta=lambda: SimpleNamespace(id="fake-provider"))

    async def send_message(self, session, message_chain):
        self.sent_messages.append((session, message_chain))
        return True

    def register_web_api(self, route, handler, methods, desc):
        self.registered_web_apis.append((route, handler, methods, desc))

    def add_llm_tools(self, *tools):
        self.registered_tools.extend(tools)
        self.provider_manager.llm_tools.func_list.extend(tools)


class Plain:
    """最简 Plain 组件（components_to_text 按类型名识别）。"""

    def __init__(self, text: str):
        self.text = text


class FakeSender:
    def __init__(self, user_id="10001", nickname="测试昵称", card=""):
        self.user_id = user_id
        self.nickname = nickname
        self.card = card


class FakeMessageObj:
    def __init__(
        self,
        *,
        message_type="GroupMessage",
        session_id="20002",
        sender=None,
        text="你好",
        message_id="1001",
        timestamp=1700000000.0,
        raw_message=None,
        self_id="99999",
    ):
        self.type = SimpleNamespace(value=message_type)
        self.session_id = session_id
        self.sender = sender or FakeSender()
        self.message = [Plain(text)] if text else []
        self.message_str = text
        self.message_id = message_id
        self.timestamp = timestamp
        self.raw_message = raw_message
        self.self_id = self_id


class FakeEvent:
    def __init__(
        self,
        *,
        umo="default:GroupMessage:20002",
        sender_id="10001",
        role="member",
        platform_id="default",
        platform_name="aiocqhttp",
        message_obj=None,
        extras=None,
    ):
        self.unified_msg_origin = umo
        self._sender_id = sender_id
        self.role = role
        self._platform_id = platform_id
        self._platform_name = platform_name
        self.message_obj = message_obj or FakeMessageObj()
        self._extras = extras or {}
        self._result = None

    def get_sender_id(self):
        return self._sender_id

    def get_platform_id(self):
        return self._platform_id

    def get_platform_name(self):
        return self._platform_name

    def get_result(self):
        return self._result

    def set_result(self, result):
        self._result = result

    def clear_result(self):
        self._result = None


@pytest.fixture
def logger():
    return FakeLogger()


@pytest.fixture
def context():
    return FakeContext()


def arun(coro):
    """同步测试里跑协程的助手（与 AstrNa 一致，不依赖 pytest-asyncio）。"""
    return asyncio.run(coro)


async def make_storage(tmp_path) -> Storage:
    """在临时目录建一个真实 Storage；调用方负责 arun(s.close())。"""
    s = Storage(Path(tmp_path))
    await s.open()
    return s


@pytest.fixture
def tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    from astrhe import constants as C

    monkeypatch.setattr(C, "NIGHT_RETRY_DELAY_SECONDS", 0)
