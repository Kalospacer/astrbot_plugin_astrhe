"""AstrHe 常量集中定义。

本文件集中存放第一版的所有默认值（对应计划 2.4 节）与工具黑名单。
这些值刻意不做成设置项；调整时改这里并补测试。

夜间不设时长、步数、复盘窗口数据量上限；连续三次模型请求失败才终止。
模型与外部工具的单次超时使用 AstrBot 自己的设置。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 调度与日期
# ---------------------------------------------------------------------------

#: 夜间复盘运行时刻（本地时间，时区取 AstrBot 配置 timezone，取不到用系统时区）
NIGHT_RUN_HOUR = 0
NIGHT_RUN_MINUTE = 0

#: 启动后多少秒检查漏跑
MISSED_RUN_CHECK_DELAY_SECONDS = 120

#: 冷启动（尚未成功提交过）时回溯秒数
COLD_START_SECONDS = 72 * 3600

#: 补拉单页大小
BACKFILL_PAGE_SIZE = 200

#: 复盘窗口超过这么久（正常每晚约 24 小时）视为有空档，补拉时额外回溯全部近期私聊
BACKFILL_FULL_SCAN_GAP_SECONDS = 36 * 3600

# ---------------------------------------------------------------------------
# 夜间流程
# ---------------------------------------------------------------------------

#: 汇报分块：每块最多消息条数
REPORT_CHUNK_SIZE = 300

#: 汇报子代理并发上限
REPORT_CONCURRENCY = 3


#: 成功完成的审稿次数：至少 / 至多
REVIEW_MIN_OK = 1
REVIEW_MAX_OK = 2

#: 审稿人没按格式给出意见（例如回了一句闲聊）累计这么多次后不再重试，
#: 允许主 agent 自查后提交，免得整晚卡在审稿上
REVIEW_MAX_INVALID = 2

#: 夜间 agent 的 max_steps：tool_loop_agent 要求整数，这里传实际不可能达到
#: 的极大值，表示「不设步数上限，做到做完为止」。runner 在 max_steps >= 16 时
#: 按百分比插步数提醒（tool_loop_agent_runner.py:1041-1068），取极大值时不会触发。
UNLIMITED_STEPS = 10**9

#: 夜间 agent 的 tool_call_timeout：ContextWrapper.tool_call_timeout 是 pydantic
#: 校验的 int（core/agent/run_context.py:19），不能传 None，故用极大值表示
#: 「AstrHe 内部工具不设超时」。唯一的停止条件是模型请求失败。
UNLIMITED_SECONDS = 10**9

#: 外部工具代理的默认超时（秒）：实际取 AstrBot 配置
#: agent_runner.config.misc.tool_call_timeout，取不到配置时用该值。
#: 外部工具超时只返回文字说明给模型，不终止当晚运行。
EXTERNAL_TOOL_TIMEOUT_DEFAULT = 120

#: 连续模型请求失败达到三次才放弃；成功过一轮即重新计数。
NIGHT_MAX_CONSECUTIVE_FAILURES = 3
NIGHT_RETRY_DELAY_SECONDS = 30

#: 纪念日前瞻天数
ANNIVERSARY_LOOKAHEAD_DAYS = 14

#: 预期联系人默认有效秒数（3 天）；每晚最多新增人数
EXPECTED_FRIEND_TTL_SECONDS = 3 * 24 * 3600
EXPECTED_FRIEND_MAX_PER_NIGHT = 3

#: 闹钟 run_at 必须晚于「现在 + 该秒数」
ALARM_MIN_LEAD_SECONDS = 5 * 60

# ---------------------------------------------------------------------------
# 频率上限
# ---------------------------------------------------------------------------

#: 贴表情：每会话每小时次数
RATE_REACT_PER_SESSION_PER_HOUR = 6
#: 戳一戳：每人每天 / 全局每天
RATE_POKE_PER_USER_PER_DAY = 3
RATE_POKE_GLOBAL_PER_DAY = 20
#: 点赞：每人每天（times 上限）/ 全局每天人数
RATE_LIKE_PER_USER_PER_DAY = 1
RATE_LIKE_MAX_TIMES = 10
RATE_LIKE_GLOBAL_PER_DAY = 20
#: 改签名：白天夜里共用，这么多天内最多换一次（签名所有人可见，换太勤不像真人）
RATE_SIGNATURE_INTERVAL_DAYS = 7
#: 改在线状态：每小时
RATE_STATUS_PER_HOUR = 2
#: 夜间新建主动闹钟：每晚 / 同一目标每天
RATE_ALARM_NIGHT_PER_RUN = 10
RATE_ALARM_SAME_TARGET_PER_DAY = 2
#: 白天新建闹钟：每会话每天 / 全局每天
RATE_ALARM_DAY_PER_SESSION = 5
RATE_ALARM_DAY_GLOBAL_PER_DAY = 20

#: 深夜免打扰时段（本地时间）：[start, end)，00:30-08:00
QUIET_HOURS_START_MINUTES = 30  # 00:30
QUIET_HOURS_END_MINUTES = 8 * 60  # 08:00

# ---------------------------------------------------------------------------
# 账本与缓存
# ---------------------------------------------------------------------------

#: 聊天账本与过程记录的保留秒数（30 天）；没复盘过的消息与闹钟结果不受此限
LEDGER_RETENTION_SECONDS = 30 * 24 * 3600

#: 一次性闹钟过了原定时间多久仍无执行记录，判为错过（AstrBot 宽限只有 5 分钟）
ALARM_LOST_GRACE_SECONDS = 3600

#: 夜间材料只列这么多天内结束的闹钟，更早的用 astrhe_read_alarms 翻页
NIGHT_FINISHED_ALARM_DAYS = 7

#: SQLite WAL 文件的大小上限，避免一次大批量清理后长期占着空间
SQLITE_JOURNAL_SIZE_LIMIT = 64 * 1024 * 1024

ALARM_HISTORY_PAGE_SIZE = 50
MEMORY_SEARCH_PAGE_SIZE = 30
MEMORY_PLAN_PAGE_SIZE = 60
MEMORY_ITEM_PAGE_SIZE = 100
MEMORY_ADMIN_PAGE_SIZE = 50

#: 群成员缓存有效期（秒），每晚刷新
GROUP_MEMBER_CACHE_TTL = 24 * 3600

#: 保密「在场」判定：近 N 天在该会话发过言
SECRET_PRESENT_SPEAK_DAYS = 7

#: 只读工具单次读消息上限
READ_MESSAGES_PAGE_LIMIT = 200


# ---------------------------------------------------------------------------
# 工具黑名单（夜间 agent 不可用）
# ---------------------------------------------------------------------------

#: 精确名称黑名单
NIGHT_TOOL_BLACKLIST_EXACT = frozenset({"future_task", "send_message_to_user"})

#: 夜间可用的 AstrHe 白天只读工具（astrhe_ 前缀的例外）
NIGHT_ASTRHE_TOOL_WHITELIST = frozenset({"astrhe_qq_lookup", "astrhe_read_plan"})

#: 夜间新建闹钟的发起人标识（payload.sender_id / origin）
NIGHT_ALARM_SENDER_ID = "astrhe"
NIGHT_ALARM_ORIGIN = "tool"

#: 需要保密的内容标记
SECRET_MARK_OPEN_PREFIX = "【保密:"
SECRET_MARK_CLOSE = "【/保密】"

#: 数据库文件名
DB_FILENAME = "astrhe.db"
