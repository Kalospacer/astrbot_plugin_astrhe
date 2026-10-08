"""夜间日记草稿；复用草稿编号、替换、撤回和提交后拒写机制。"""

from .base import AstrHeFunctionTool


def build_memory_tool(owner):
    async def draft_memory(event, **kw):
        payload = {
            key: str(kw.get(key, "") or "").strip()
            if key != "content"
            else str(kw.get(key, "") or "")
            for key in ("kind", "target", "action", "field", "content", "reason")
        }
        run = await owner.storage.runs.get_run(owner.run_id)
        await owner.storage.memory.validate_edit(payload, run["plan_date"])
        return await owner._add("memory_edit", payload, kw.get("replace_draft_id", 0))

    return AstrHeFunctionTool(
        name="astrhe_draft_memory_edit",
        description=(
            "整理日记草稿：kind=plan/todo/promise，target=规划书 YYYY-MM-DD 或条目编号；"
            "action=append/replace/delete/restore，reason 必填。只可修改往日规划书、"
            "已了结待办或承诺。append 给规划书选定字段补后记，待办/承诺补到 note；"
            "replace 替换整个字段。删除进入回收站，30 天内可恢复。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["plan", "todo", "promise"]},
                "target": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["append", "replace", "delete", "restore"],
                },
                "field": {
                    "type": "string",
                    "description": "plan:full_text/reflection；其他:content/note",
                },
                "content": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["kind", "target", "action", "reason"],
        },
        fn=draft_memory,
    )
