"""演练动作清单：按正式执行顺序展示，不修改业务数据。"""

import json


def describe_dry_actions(drafts):
    actions = [
        {"kind": d["kind"], **json.loads(d["payload_json"])}
        for d in sorted(drafts, key=lambda d: d["kind"] != "alarm_cancel")
        if d["kind"] in ("alarm", "alarm_cancel", "appearance", "person", "memory_edit")
    ]
    return "演练通过，不写入正式数据。将执行：" + json.dumps(
        actions, ensure_ascii=False
    )
