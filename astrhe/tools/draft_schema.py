"""夜间草稿工具的参数声明。"""

from .base import AstrHeFunctionTool


def build_draft_tools(owner):
    tools = [
        AstrHeFunctionTool(
            name="astrhe_draft_plan",
            description=(
                "写规划书草稿。参数：full_text（规划书全文，保密内容用"
                "【保密:QQ号】…【/保密】包裹）、reflection（自我反思）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "full_text": {"type": "string"},
                    "reflection": {"type": "string"},
                    "day_reminders": {
                        "type": "string",
                        "description": "白天自我提醒，建议一两句",
                    },
                },
                "required": ["full_text"],
            },
            fn=owner._draft_plan,
        ),
        AstrHeFunctionTool(
            name="astrhe_draft_sections",
            description=(
                "按会话切分规划段落（白天注入用，每段要短）。"
                "参数：sections_json（JSON 对象，键是会话 UMO，值是段落文本）。"
            ),
            parameters={
                "type": "object",
                "properties": {"sections_json": {"type": "string"}},
                "required": ["sections_json"],
            },
            fn=owner._draft_sections,
        ),
        AstrHeFunctionTool(
            name="astrhe_draft_todo",
            description=(
                "新增待办草稿。参数：content；visible_umos（JSON 数组，可见会话）；"
                "secret_from（JSON 数组，对谁保密）；due_kind（today/future/deadline）；"
                "due_date（YYYY-MM-DD）；show_from（从哪天开始贴出，deadline 默认从规划日起显示）；"
                "evidence（JSON 数组，依据）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "visible_umos": {"type": "string"},
                    "secret_from": {"type": "string"},
                    "due_kind": {"type": "string"},
                    "due_date": {"type": "string"},
                    "show_from": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["content", "visible_umos"],
            },
            fn=owner._draft_todo,
        ),
        AstrHeFunctionTool(
            name="astrhe_draft_todo_drop",
            description="删除已无必要的旧待办。参数：todo_id、reason（理由）。",
            parameters={
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["todo_id", "reason"],
            },
            fn=owner._draft_todo_drop,
        ),
        AstrHeFunctionTool(
            name="astrhe_draft_alarm",
            description=(
                "新增闹钟卡片草稿。参数：target_umo（目标会话）；run_at（执行时间，"
                "如 2026-10-11 00:00）；background、purpose、how（必填，来龙去脉）；"
                "involved、mentions、secret_from（JSON 数组）；taboo；"
                "落在深夜（00:30-08:00）的必须 agreed=true 并写 agreed_reason。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target_umo": {"type": "string"},
                    "run_at": {"type": "string"},
                    "cron_expression": {"type": "string"},
                    "background": {"type": "string"},
                    "purpose": {"type": "string"},
                    "how": {"type": "string"},
                    "involved": {"type": "string"},
                    "mentions": {"type": "string"},
                    "secret_from": {"type": "string"},
                    "taboo": {"type": "string"},
                    "agreed": {"type": "boolean"},
                    "agreed_reason": {"type": "string"},
                },
                "required": ["target_umo", "background", "purpose", "how"],
            },
            fn=owner._draft_alarm,
        ),
        AstrHeFunctionTool(
            name="astrhe_draft_person",
            description=(
                "更新关系本草稿。参数：qq；aliases（JSON 数组）；relation_text"
                "（关系层，只在确有变化时给）；recent_text（近况层）；"
                'anniversaries（JSON 数组，如 [{"name":"生日","date":"10-11"}]）；'
                "expected_friend（true 时标为预期联系人，配合 expected_reason）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "qq": {"type": "string"},
                    "aliases": {"type": "string"},
                    "relation_text": {"type": "string"},
                    "recent_text": {"type": "string"},
                    "anniversaries": {"type": "string"},
                    "expected_friend": {"type": "boolean"},
                    "expected_reason": {"type": "string"},
                },
                "required": ["qq"],
            },
            fn=owner._draft_person,
        ),
        AstrHeFunctionTool(
            name="astrhe_draft_promise",
            description=(
                "承诺账本变更草稿。参数：action（add/update）；add 时给 from_id、"
                "to_id、content、due_date；update 时给 promise_id、status"
                "（done/broken/waived）、reason。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "from_id": {"type": "string"},
                    "to_id": {"type": "string"},
                    "content": {"type": "string"},
                    "due_date": {"type": "string"},
                    "promise_id": {"type": "integer"},
                    "status": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action"],
            },
            fn=owner._draft_promise,
        ),
        AstrHeFunctionTool(
            name="astrhe_draft_appearance",
            description=(
                "自我形象动作草稿（可选，受频率上限约束）。参数：signature"
                "（规划日的个性签名）；status_preset（在线/离开/忙碌/请勿打扰/Q我吧）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "signature": {"type": "string"},
                    "status_preset": {"type": "string"},
                },
            },
            fn=owner._draft_appearance,
        ),
        AstrHeFunctionTool(
            name="astrhe_request_review",
            description=(
                "请审稿子代理复盘当前草稿。参数：focus（审稿重点，可空）。"
                "至少要成功审稿 1 次、至多 2 次才能提交。"
            ),
            parameters={
                "type": "object",
                "properties": {"focus": {"type": "string"}},
            },
            fn=owner._request_review,
        ),
        AstrHeFunctionTool(
            name="astrhe_commit",
            description=(
                "提交今晚的全部草稿（规划书、待办、闹钟、关系本、承诺）。"
                "参数：summary（一句话总结今晚的决定）。"
                "没有规划书或没经过审稿会被拒绝。"
            ),
            parameters={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
            fn=owner._commit,
        ),
        AstrHeFunctionTool(
            name="astrhe_read_drafts",
            description="读当前草稿箱（审稿时用）。",
            fn=owner._read_drafts,
        ),
    ]

    tools.insert(
        8,
        AstrHeFunctionTool(
            name="astrhe_draft_discard",
            description="撤回 active 草稿，必须写理由。提交后不能再改。",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["draft_id", "reason"],
            },
            fn=owner._discard,
        ),
    )
    for tool in tools:
        if (
            tool.name.startswith("astrhe_draft_")
            and tool.name != "astrhe_draft_discard"
        ):
            tool.parameters.setdefault("properties", {})["replace_draft_id"] = {
                "type": "integer",
                "description": "替换同类旧草稿编号（可选）",
            }
        tool.fn = owner.guard(tool.fn, tool.name)
    return tools
