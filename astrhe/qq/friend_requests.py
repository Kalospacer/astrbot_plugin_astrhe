"""好友申请处理：flag 留存、预期联系人自动同意、可疑申请处理。

维护者授权：只自动同意「计划中预期的联系人」（persons.expected_friend_until
未过期），其他申请一律不动。
"""

from __future__ import annotations

from typing import Any

from ..storage import Storage
from ..timeutil import utc_now
from .client import QQClient


class FriendRequestManager:
    def __init__(self, storage: Storage, qq: QQClient, logger: Any):
        self.storage = storage
        self.qq = qq
        self.logger = logger

    async def handle_incoming(self, user_id: str, flag: str, comment: str) -> bool:
        """request 事件到达时调用；是预期联系人就自动同意，返回是否已同意。"""
        if not user_id or not flag:
            return False
        now = utc_now()
        if not await self.storage.persons.is_expected_friend(user_id, now):
            return False
        try:
            await self.qq.call("set_friend_add_request", flag=flag, approve=True)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"[AstrHe] 自动同意好友申请失败: {exc}")
            return False
        await self.storage.ledger.set_friend_request_status(flag, "approved")
        await self.storage.persons.clear_expected_friend(user_id)
        await self.storage.ledger.log_action("approve_friend", target=user_id)
        return True

    async def nightly_followup(self) -> list[str]:
        """夜间提交后调用（dry 模式不调）。返回动作结果描述列表。

        1. 对仍是 pending、但现在已成为预期联系人的申请补做同意；
        2. 存在预期联系人时查一次可疑申请，命中预期联系人的处理掉。
        """
        results: list[str] = []
        now = utc_now()

        pendings = await self.storage.ledger.pending_friend_requests()
        for req in pendings:
            user_id = req["user_id"]
            if not await self.storage.persons.is_expected_friend(user_id, now):
                continue
            try:
                await self.qq.call(
                    "set_friend_add_request", flag=req["flag"], approve=True
                )
                await self.storage.ledger.set_friend_request_status(
                    req["flag"], "approved"
                )
                await self.storage.persons.clear_expected_friend(user_id)
                await self.storage.ledger.log_action("approve_friend", target=user_id)
                results.append(f"补同意好友申请: {user_id}")
            except Exception as exc:  # noqa: BLE001
                results.append(f"补同意好友申请失败 {user_id}: {exc}")

        expected = await self.storage.persons.expected_friends(now)
        if expected:
            expected_ids = {p["qq"] for p in expected}
            try:
                doubts = await self.qq.call("get_doubt_friends_add_request", count=50)
                for item in doubts if isinstance(doubts, list) else []:
                    uid = str(item.get("user_id", "") or item.get("uin", ""))
                    flag = str(item.get("flag", "") or "")
                    if uid in expected_ids and flag:
                        try:
                            await self.qq.call(
                                "set_doubt_friends_add_request", flag=flag, approve=True
                            )
                            await self.storage.persons.clear_expected_friend(uid)
                            await self.storage.ledger.log_action(
                                "approve_doubt_friend", target=uid
                            )
                            results.append(f"处理可疑好友申请: {uid}")
                        except Exception as exc:  # noqa: BLE001
                            results.append(f"处理可疑好友申请失败 {uid}: {exc}")
            except Exception as exc:  # noqa: BLE001
                results.append(f"查询可疑好友申请失败: {exc}")
        return results
