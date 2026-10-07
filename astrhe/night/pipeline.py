"""夜间流程编排：补拉 → 对账 → 汇报 → 主 agent → 审稿 → 提交或失败回退。

停止条件（2026-10-07 修订）：唯一的自动停止条件是模型请求失败
（NightAgentError）；不设任何时长、步数、数据量上限。
人工停止：stop() / 任务被取消；提交前取消判失败，提交后外部动作照常收尾。
运行重叠：由调度器保证不并发；pipeline 开头再自查一次。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .. import constants as C
from ..backfill import Backfiller
from ..timeutil import local_date_str, utc_now
from .agent_runner import NightAgentError, get_persona_prompt
from .draft import CommitError, DraftCommitter
from .planner import Planner
from .reporter import Reporter
from .reviewer import Reviewer


class NightPipeline:
    """夜间复盘流程。一个实例对应一次运行。"""

    def __init__(
        self,
        storage: Any,
        context: Any,
        config: Any,
        platform_helper: Any,
        qq_client: Any,
        rate_limiter: Any,
        secrecy_resolver: Any,
        admins_getter,
        tz_getter,
        backfiller: Backfiller | None,
        friend_request_manager: Any,
        internal_tools_provider,
        logger: Any,
    ):
        self.storage = storage
        self.context = context
        self.config = config
        self.platform = platform_helper
        self.qq = qq_client
        self.rate_limiter = rate_limiter
        self.secrecy = secrecy_resolver
        self._admins_getter = admins_getter
        self._tz_getter = tz_getter
        self.backfiller = backfiller
        self.friend_requests = friend_request_manager
        self._internal_tools_provider = internal_tools_provider
        self.logger = logger

        self.stage = "init"
        self.stage_since = time.time()
        self._fatal: str = ""
        self._commit_state: dict[str, Any] = {"committed": False}

    def _set_stage(self, stage: str) -> None:
        self.stage = stage
        self.stage_since = time.time()

    # ------------------------------------------------------------------

    async def resolve_provider_id(self) -> str:
        """配置的 provider_id；留空用当前默认聊天模型并写日志。"""
        configured = ""
        try:
            configured = str(self.config.get("provider_id", "") or "")
        except Exception:  # noqa: BLE001
            configured = ""
        if configured:
            return configured
        try:
            prov = await self.context.get_using_provider_async()
            pid = str(prov.meta().id) if prov else ""
            if pid:
                self.logger.info(f"[AstrHe] 未配置模型，使用当前默认聊天模型: {pid}")
                return pid
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[AstrHe] 取默认模型失败: {exc}")
        raise NightAgentError("没有可用的聊天模型：请在插件设置里选择模型")

    def _admins(self) -> list[str]:
        try:
            ids = self._admins_getter() or []
        except Exception:  # noqa: BLE001
            ids = []
        # 过滤掉 "astrbot" 这类非数字占位
        return [str(x) for x in ids if str(x).isdigit()]

    # ------------------------------------------------------------------

    async def run(self, mode: str = "auto") -> dict[str, Any]:
        """跑一次夜间流程。mode: auto / manual / dry。"""
        tz = self._tz_getter()
        now = utc_now()

        # 运行重叠自查（调度器之外的双保险）
        running = await self.storage.runs.running_runs()
        if running:
            self.logger.info("[AstrHe] 已有夜间运行在进行，跳过本次触发")
            return {"status": "skipped", "reason": "已有运行在进行"}

        last_committed = await self.storage.runs.latest_committed_run()
        if last_committed and last_committed["window_end"]:
            window_start = float(last_committed["window_end"])
        else:
            window_start = now - C.COLD_START_SECONDS
        plan_date = local_date_str(now, tz)
        run_id = await self.storage.runs.start_run(
            plan_date=plan_date, mode=mode, window_start=window_start, window_end=now
        )

        stats: dict[str, Any] = {"stages": {}}
        dry = mode == "dry"
        try:
            result = await self._run_stages(
                run_id, plan_date, window_start, now, tz, dry, stats
            )
            return result
        except NightAgentError as exc:
            await self.storage.runs.finish_run(
                run_id, "failed", error=f"模型请求失败（{self.stage}）: {exc}", stats=stats
            )
            return {"status": "failed", "error": str(exc), "stage": self.stage}
        except asyncio.CancelledError:
            # 人工停止 / 插件终止：已提交的不改状态，未提交的判失败
            if self._commit_state.get("committed"):
                # 已提交：正式数据已落库，标记 committed；shield 保护的外部动作
                # 仍在后台收尾
                await self.storage.runs.finish_run(
                    run_id, "committed", error="提交后被停止，外部动作后台收尾",
                    stats=stats,
                )
            else:
                await self.storage.runs.finish_run(
                    run_id, "failed", error=f"运行被取消（{self.stage}）", stats=stats
                )
            raise
        except Exception as exc:  # noqa: BLE001
            await self.storage.runs.finish_run(
                run_id, "failed", error=f"{self.stage}: {exc}", stats=stats
            )
            self.logger.warning(f"[AstrHe] 夜间运行失败（{self.stage}）: {exc}")
            return {"status": "failed", "error": str(exc), "stage": self.stage}

    async def _run_stages(
        self,
        run_id: int,
        plan_date: str,
        window_start: float,
        window_end: float,
        tz: Any,
        dry: bool,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        stage_start = time.time()

        # ① 补拉
        self._set_stage("backfill")
        backfill_stats: dict[str, Any] = {}
        if self.backfiller is not None:
            try:
                backfill_stats = await self.backfiller.backfill_all(window_start, window_end)
            except Exception as exc:  # noqa: BLE001 - 补拉失败不让整晚失败
                backfill_stats = {"failed": [str(exc)]}
        stats["backfill"] = backfill_stats
        stats["stages"]["backfill"] = round(time.time() - stage_start, 2)

        # ② 闹钟对账
        self._set_stage("reconcile")
        stage_start = time.time()
        reconcile_text = ""
        tracker = getattr(self, "alarm_tracker", None)
        if tracker is not None:
            try:
                reconcile_text = await tracker.nightly_reconcile()
            except Exception as exc:  # noqa: BLE001
                reconcile_text = f"对账失败: {exc}"
        stats["stages"]["reconcile"] = round(time.time() - stage_start, 2)

        # ③ 汇报子代理
        self._set_stage("report")
        stage_start = time.time()
        provider_id = await self.resolve_provider_id()
        persona_prompt = await get_persona_prompt(self.context)
        reader_tools = self._internal_tools_provider(
            "reader", window=(window_start, window_end)
        )
        reporter = Reporter(
            self.storage, self.context, provider_id, persona_prompt, tz, reader_tools
        )
        umos = await self.storage.ledger.list_session_umos(window_start)
        reports = await self._run_reporters(reporter, run_id, umos, window_start, window_end)
        stats["sessions"] = len(umos)
        stats["reports"] = len(reports)
        stats["stages"]["report"] = round(time.time() - stage_start, 2)

        # ④ 主 agent
        self._set_stage("plan")
        stage_start = time.time()
        admins = self._admins()
        planner = Planner(
            self.storage, self.context, provider_id, persona_prompt, admins, tz
        )
        reviewer = Reviewer(
            self.storage, self.context, provider_id, persona_prompt, admins, reader_tools
        )
        committer = DraftCommitter(
            self.storage, self.context, run_id, plan_date, tz, self.rate_limiter
        )
        last_run = await self.storage.runs.latest_run()
        last_failed = bool(
            last_run and last_run["id"] != run_id and last_run["status"] == "failed"
        )
        materials = await planner.build_materials(reports, reconcile_text, last_failed)
        draft_tools = self._internal_tools_provider(
            "draft",
            run_id=run_id,
            request_review_cb=lambda focus: self._on_review(reviewer, run_id, focus),
            commit_cb=lambda summary: self._on_commit(committer, summary, dry),
        )
        planner_tools = reader_tools + draft_tools
        # 外部工具（代理 + 黑名单）
        planner_tools = planner_tools + self._external_proxied_tools(
            {t.name for t in planner_tools}
        )
        final_text = await planner.run_planner(
            materials=materials, tools=planner_tools, commit_state=self._commit_state
        )
        stats["stages"]["plan"] = round(time.time() - stage_start, 2)

        if self._fatal:
            raise NightAgentError(self._fatal)
        if not self._commit_state.get("committed"):
            await self.storage.runs.finish_run(
                run_id, "failed",
                error="主 agent 没有调用 astrhe_commit，视为失败",
                stats=stats,
            )
            return {"status": "failed", "error": "未提交"}

        # ⑤ 外部动作（已提交，shield 保护）
        self._set_stage("external")
        stage_start = time.time()
        external_results: list[str] = []
        if not dry:
            try:
                external_results = await committer.run_external_actions()
            except Exception as exc:  # noqa: BLE001
                external_results = [f"外部动作阶段异常: {exc}"]
            if self.friend_requests is not None:
                try:
                    external_results += await asyncio.shield(
                        self.friend_requests.nightly_followup()
                    )
                except Exception as exc:  # noqa: BLE001
                    external_results.append(f"好友申请收尾异常: {exc}")
            # 清理过期账本
            if self.backfiller is not None:
                try:
                    await self.backfiller.cleanup_old(utc_now())
                except Exception:  # noqa: BLE001
                    pass
        stats["external_results"] = external_results
        stats["stages"]["external"] = round(time.time() - stage_start, 2)

        final_status = "dry_done" if dry else "committed"
        await self.storage.runs.finish_run(run_id, final_status, stats=stats)
        self.logger.info(
            f"[AstrHe] 夜间运行完成：{plan_date} dry={dry} 会话 {stats.get('sessions', 0)} 个"
        )
        return {
            "status": final_status,
            "plan_date": plan_date,
            "stats": stats,
            "final_text": final_text[:200],
        }

    async def _run_reporters(
        self,
        reporter: Reporter,
        run_id: int,
        umos: list[str],
        window_start: float,
        window_end: float,
    ) -> list[dict[str, Any]]:
        """并发 3 跑汇报；任何一个模型失败，取消其余并终止整晚。"""
        tasks = [
            asyncio.ensure_future(
                reporter.report_session(run_id, umo, window_start, window_end)
            )
            for umo in umos
        ]
        results: list[dict[str, Any]] = []
        try:
            for fut in asyncio.as_completed(tasks):
                results.append(await fut)
        except BaseException:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return results

    # ------------------------------------------------------------------

    async def _on_review(self, reviewer: Reviewer, run_id: int, focus: str) -> str:
        """主 agent 的 astrhe_request_review 回调。

        审稿的模型失败按修订要求终止整晚：记录 fatal，给主 agent 返回说明，
        并拒绝后续提交。
        """
        try:
            return await reviewer.review(run_id, focus)
        except NightAgentError as exc:
            self._fatal = f"审稿模型请求失败: {exc}"
            return f"审稿失败：{exc}。本次运行将被终止，请不要提交。"

    async def _on_commit(self, committer: DraftCommitter, summary: str, dry: bool) -> str:
        """主 agent 的 astrhe_commit 回调。"""
        if self._fatal:
            return f"提交被拒绝：本次运行已因模型失败而终止（{self._fatal}）"
        try:
            await committer.validate()
        except CommitError as exc:
            return f"提交被拒绝：{exc}"
        if dry:
            self._commit_state["committed"] = True
            return f"演练模式：草稿校验通过，不写入正式数据。总结：{summary}"
        try:
            stats = await committer.commit_db()
        except Exception as exc:  # noqa: BLE001
            return f"提交时数据库出错: {exc}"
        self._commit_state["committed"] = True
        return f"已提交。今晚的规划生效了：{summary}（写入：{stats}）"

    def _external_proxied_tools(self, exclude_names: set[str]) -> list:
        """外部工具代理列表：从全局工具表取，按黑名单过滤。"""
        from .tool_proxy import ProxiedTool, get_external_tool_timeout, is_blacklisted

        timeout = get_external_tool_timeout(self._astrbot_config())
        result = []
        manager = getattr(self.context, "provider_manager", None)
        func_list = getattr(getattr(manager, "llm_tools", None), "func_list", []) or []
        for tool in func_list:
            name = getattr(tool, "name", "")
            if not name or name in exclude_names or is_blacklisted(name):
                continue
            result.append(ProxiedTool(inner=tool, timeout=timeout))
        return result

    def _astrbot_config(self) -> Any:
        try:
            return self.context.get_config()
        except Exception:  # noqa: BLE001
            return {}
