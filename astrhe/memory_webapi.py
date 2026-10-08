"""管理员日记接口；沿用查看页的路由注册和面板登录权限。"""

from . import constants as C


class MemoryWebApi:
    def __init__(self, storage, web_getter, body_reader):
        self.storage = storage
        self._web = web_getter
        self._body = body_reader

    def routes(self):
        return [
            ("/memory/trash", self.trash, ["GET"], "日记回收站"),
            ("/memory/restore", self.restore, ["POST"], "恢复回收站日记"),
            ("/memory/revisions", self.revisions, ["GET"], "日记修订记录"),
            ("/memory/revert", self.revert, ["POST"], "回退日记修订"),
        ]

    def _offset(self):
        return max(0, int(self._web().request.query.get("offset", 0)))

    def _page(self, key, rows, total, offset):
        return self._web().json_response(
            {
                key: rows,
                "total": total,
                "offset": offset,
                "next_offset": offset + len(rows)
                if offset + len(rows) < total
                else None,
                "page_size": C.MEMORY_ADMIN_PAGE_SIZE,
            }
        )

    async def trash(self):
        try:
            offset = self._offset()
            rows, total = await self.storage.memory.trash(offset)
            return self._page("trash", rows, total, offset)
        except (ValueError, TypeError) as exc:
            return self._web().error_response(str(exc), status_code=400)

    async def revisions(self):
        try:
            offset = self._offset()
            rows, total = await self.storage.memory.revisions(offset)
            return self._page("revisions", rows, total, offset)
        except (ValueError, TypeError) as exc:
            return self._web().error_response(str(exc), status_code=400)

    async def restore(self):
        payload = await self._body()
        try:
            row = await self.storage.memory.restore(
                payload.get("kind"),
                payload.get("target", ""),
                str(payload.get("reason") or "管理员从回收站恢复"),
            )
            return self._web().json_response({"ok": True, "entry": row})
        except (ValueError, TypeError) as exc:
            return self._web().error_response(str(exc), status_code=400)

    async def revert(self):
        payload = await self._body()
        try:
            row = await self.storage.memory.revert(
                payload.get("revision_id", 0), str(payload.get("reason", "") or "")
            )
            return self._web().json_response({"ok": True, "entry": row})
        except (ValueError, TypeError) as exc:
            return self._web().error_response(str(exc), status_code=400)
