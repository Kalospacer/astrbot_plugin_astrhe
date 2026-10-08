"""零点调度器：每天 00:00 触发夜间复盘；漏跑补跑；运行重叠跳过。

- 时区取 AstrBot 配置 timezone，取不到用系统时区。
- 下一个 00:00 到来时若上次还在跑，跳过本次触发（不并发）。
- 启动约 2 分钟后检查：当前本地日期还没有成功提交就补跑一次。
"""

from __future__ import annotations

import asyncio
from typing import Any

from . import constants as C
from .timeutil import local_date_str, next_midnight_ts, utc_now


class NightScheduler:
    def __init__(self, storage: Any, tz_getter, run_callback, logger: Any):
        self.storage = storage
        self._tz_getter = tz_getter
        self._run_callback = run_callback  # async (mode: str) -> dict
        self.logger = logger
        self._task: asyncio.Task | None = None
        self._running_task: asyncio.Task | None = None
        self._stopped = False
        self._missed_task: asyncio.Task | None = None

    def start(self) -> None:
        self._stopped = False
        self._task = asyncio.ensure_future(self._loop())
        # 启动后检查漏跑
        self._missed_task = asyncio.ensure_future(self._missed_run_check())

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._missed_task is not None:
            self._missed_task.cancel()
            self._missed_task = None
        if self._running_task is not None and not self._running_task.done():
            self._running_task.cancel()
            try:
                await asyncio.wait({self._running_task})
                if not self._running_task.cancelled():
                    self._running_task.result()
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._running_task = None

    @property
    def is_running(self) -> bool:
        return self._running_task is not None and not self._running_task.done()

    async def trigger(self, mode: str = "manual") -> dict[str, Any] | None:
        """手动触发（指令 run / dryrun）。已在跑则返回 None。"""
        if self.is_running:
            return None
        self._running_task = asyncio.ensure_future(self._run_callback(mode))
        return {"started": True}

    async def stop_running(self) -> str:
        """人工停止正在进行的运行。"""
        if not self.is_running:
            return "现在没有正在进行的夜间运行"
        self._running_task.cancel()
        return "已发送停止信号：提交前停止判失败，提交后外部动作照常收尾"

    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while not self._stopped:
            tz = self._tz_getter()
            wait = max(next_midnight_ts(utc_now(), tz) - utc_now(), 1)
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                return
            if self._stopped:
                return
            if self.is_running:
                # 运行重叠：跳过本次触发
                self.logger.info("[AstrHe] 上次夜间运行还没结束，跳过本次 00:00 触发")
                continue
            try:
                self._running_task = asyncio.ensure_future(self._run_callback("auto"))
                await asyncio.wait({self._running_task})
                if not self._running_task.cancelled():
                    self._running_task.result()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"[AstrHe] 夜间运行异常: {exc}")

    async def _missed_run_check(self) -> None:
        try:
            await asyncio.sleep(C.MISSED_RUN_CHECK_DELAY_SECONDS)
        except asyncio.CancelledError:
            return
        if self._stopped or self.is_running:
            return
        await self._missed_run_check_inner()

    async def _missed_run_check_inner(self) -> None:
        """漏跑检查本体（抽出方便测试）。"""
        try:
            # 启动时把残留的 running 记录标记为 failed
            for run in await self.storage.runs.running_runs():
                await self.storage.runs.finish_run(
                    run["id"], "failed", error="进程重启，运行中断"
                )
            today = local_date_str(utc_now(), self._tz_getter())
            last = await self.storage.runs.committed_run_for_date(today)
            if last is None:
                self.logger.info("[AstrHe] 检测到漏跑，补跑一次夜间复盘")
                self._running_task = asyncio.ensure_future(self._run_callback("auto"))
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"[AstrHe] 漏跑检查失败: {exc}")
