/** 档案详情：五类档案各自的四格信息、三个页签、主操作与导出文本。排版沿用 RhineLabUI 的结构。 */
import type { ArchiveRecord } from "../data";
import { escapeHtml } from "../html";
import { cronText, dateOnly, dateTime, paragraphs, parseJson, personName, sessionName } from "./format";
import {
  ALARM_STATUS,
  PROMISE_STATUS,
  TODO_STATUS,
  type AlarmEvent,
  type Overview,
  type PlanDetail,
} from "./records";
import { maskedHtml, secretFromAdmin, secretHtml, stripSecrets } from "./secrecy";

type Row = Record<string, unknown>;
const str = (value: unknown) => (typeof value === "string" ? value : value == null ? "" : String(value));

export interface DetailAction {
  action: string;
  en: string;
  cn: string;
  disabled?: boolean;
}

export interface DetailView {
  meta: [label: string, valueHtml: string, status?: boolean][];
  tabs: { label: string; html: string }[];
  action: DetailAction;
  footnote: string;
  /** 导出的纯文本；revealed 为真时包含对管理员保密的内容 */
  exportText: (revealed: boolean) => string;
}

const label = (en: string, cn: string) => `<div class="panel-label">${en} / ${cn}</div>`;
const text = (value: string) => `<p>${secretHtml(value)}</p>`;
const notes = (items: string[]) =>
  items.length
    ? `<ol class="research-notes">${items.map((item, i) => `<li><span>${String(i + 1).padStart(2, "0")}</span><div>${item}</div></li>`).join("")}</ol>`
    : "<p>—</p>";
const masked = (html: string, whole: boolean) => (whole ? maskedHtml(html) : html);

function evidenceItems(value: unknown) {
  return parseJson<unknown[]>(value, []).map((item) => {
    // 出处摘录可能带【保密】段落，同样按保密规则显示
    if (typeof item === "string") return secretHtml(item);
    const row = (item ?? {}) as Row;
    const where = row.umo ? sessionName(str(row.umo)) : "";
    const id = row.message_id ?? row.id;
    return secretHtml([where, id ? `#${id}` : "", str(row.note ?? row.text)].filter(Boolean).join(" · ") || JSON.stringify(item));
  });
}

function statusCell(map: Record<string, [string, string]>, status: string) {
  return escapeHtml(map[status]?.[1] ?? status);
}

function exportLines(record: ArchiveRecord, sections: [string, string][], revealed: boolean) {
  return [
    `AstrHe 档案终端 · ${record.category} · ${record.id}`,
    record.en,
    "",
    ...sections.flatMap(([title, body]) => [`【${title}】`, stripSecrets(body, revealed) || "—", ""]),
  ].join("\n");
}

function planView(record: ArchiveRecord, plan: PlanDetail, latest: boolean): DetailView {
  const sections = Object.entries(plan.sections ?? {});
  return {
    meta: [
      ["PLAN DATE / 规划日", escapeHtml(plan.plan_date)],
      ["SOURCE / 来源", `第 ${plan.run_id} 次夜间复盘`],
      ["SECTIONS / 会话段落", `${sections.length} 个会话`],
      ["STATUS / 状态", latest ? "生效中 · 白天注入" : "已归档", true],
    ],
    tabs: [
      { label: "全文", html: label("FULL TEXT", "规划书全文") + text(plan.full_text) },
      {
        label: "会话段落",
        html: label("SECTIONS", "按会话注入的段落") + notes(sections.map(([umo, body]) => `<b>${escapeHtml(sessionName(umo))}</b><br>${secretHtml(body)}`)),
      },
      {
        label: "反思与提醒",
        html: label("REFLECTION", "自我反思") + text(plan.reflection) + label("DAY REMINDERS", "白天提醒") + text(plan.day_reminders),
      },
    ],
    action: { action: "open-run", en: "↗ NIGHT RUN", cn: "查看当晚复盘" },
    footnote: `写于 ${dateTime(plan.updated_at ?? plan.created_at)}`,
    exportText: (revealed) =>
      exportLines(record, [["规划书全文", plan.full_text], ...sections.map(([umo, body]) => [`段落 · ${sessionName(umo)}`, body] as [string, string]), ["自我反思", plan.reflection], ["白天提醒", plan.day_reminders]], revealed),
  };
}

function todoView(record: ArchiveRecord, todo: Row): DetailView {
  const whole = secretFromAdmin(todo.secret_from_json);
  const secretFrom = parseJson<string[]>(todo.secret_from_json, []);
  const due =
    str(todo.due_kind) === "today" ? "当天" : [str(todo.due_kind) === "future" ? "未来" : "", str(todo.due_date)].filter(Boolean).join(" · ") || "—";
  const content = whole ? maskedHtml(paragraphs(str(todo.content))) : secretHtml(str(todo.content));
  return {
    meta: [
      ["SESSIONS / 挂载会话", escapeHtml(record.department)],
      ["DUE / 日期", escapeHtml(due)],
      ["SECRET FROM / 保密对象", escapeHtml(secretFrom.map(personName).join("、") || "无")],
      ["STATUS / 状态", statusCell(TODO_STATUS, str(todo.status)), true],
    ],
    tabs: [
      { label: "内容", html: label("CONTENT", "待办内容") + `<p>${content}</p>` + label("NOTE", "备注与进展") + `<p>${masked(secretHtml(str(todo.note)), whole)}</p>` },
      { label: "出处", html: label("EVIDENCE", "出处") + notes(evidenceItems(todo.evidence_json).map((item) => masked(item, whole))) },
      {
        label: "关联",
        html:
          label("LINKS", "关联") +
          notes([
            todo.alarm_id ? `关联闹钟 A-${String(todo.alarm_id).padStart(3, "0")}` : "未关联闹钟",
            todo.created_run_id ? `来自第 ${todo.created_run_id} 次夜间复盘` : "白天或手动添加",
            str(todo.show_from) ? `从 ${escapeHtml(str(todo.show_from))} 起显示` : "立即显示",
            `最近更新 ${dateTime(Number(todo.updated_at))}`,
          ]),
      },
    ],
    action:
      str(todo.status) === "deleted"
        ? { action: "", en: "DELETED", cn: "已在回收站", disabled: true }
        : { action: "delete-todo", en: "− DELETE TODO", cn: "删除待办" },
    footnote: "删除后进入回收站，30 天内可恢复",
    exportText: (revealed) => exportLines(record, [["待办内容", whole && !revealed ? "（保密内容）" : str(todo.content)], ["备注", whole && !revealed ? "（保密内容）" : str(todo.note)]], revealed),
  };
}

const CARD_FIELDS: [string, string][] = [
  ["background", "背景"],
  ["purpose", "目的"],
  ["how", "怎么做"],
  ["involved", "牵涉的人"],
  ["mentions", "需要 @ 的人"],
  ["secret_from", "对谁保密"],
  ["taboo", "禁忌"],
  ["agreed_reason", "约定时刻的理由"],
  ["plan_date", "关联规划日"],
];
const EVENT_LABELS: Record<string, string> = {
  fired: "到点执行",
  manual_run: "面板立即执行",
  send_ok: "消息已发出",
  send_failed: "发送失败",
  done: "执行完成",
  cancelled: "已取消",
};

function cardValue(key: string, value: unknown) {
  if (Array.isArray(value)) return value.map((v) => (["involved", "mentions", "secret_from"].includes(key) ? personName(String(v)) : String(v))).join("、");
  return str(value);
}

function alarmView(record: ArchiveRecord, alarm: Row, events: AlarmEvent[]): DetailView {
  const card = parseJson<Row>(alarm.card_json, {});
  const whole = secretFromAdmin(card.secret_from);
  const fields = CARD_FIELDS.filter(([key]) => card[key] != null && cardValue(key, card[key]) !== "");
  const runAt = alarm.cron_expression ? cronText(str(alarm.cron_expression)) : dateTime(alarm.run_at as number | null);
  const live = ["scheduled", "fired"].includes(str(alarm.status));
  return {
    meta: [
      ["TARGET / 目标会话", escapeHtml(sessionName(str(alarm.target_umo)))],
      ["RUN AT / 执行时间", escapeHtml(runAt)],
      ["CREATOR / 创建者", escapeHtml(str(alarm.origin) === "night" ? "夜间复盘" : `白天 · ${personName(str(alarm.creator_id))}`)],
      ["STATUS / 状态", statusCell(ALARM_STATUS, str(alarm.status)), true],
    ],
    tabs: [
      {
        label: "来龙去脉",
        html: label("CARD", "闹钟卡片") + notes(fields.map(([key, name]) => `<b>${name}</b><br>${masked(secretHtml(cardValue(key, card[key])), whole)}`)),
      },
      {
        label: "执行记录",
        html:
          label("EVENTS", "执行记录") +
          (events.length
            ? events
                .map((e) => `<div class="log-row"><span>${dateTime(e.ts)}</span><span>${escapeHtml(EVENT_LABELS[e.kind] ?? e.kind)}</span><b>${masked(escapeHtml(e.detail ? e.detail.slice(0, 80) : "—"), whole)}</b></div>`)
                .join("")
            : "<p>还没有执行记录。</p>"),
      },
      {
        label: "结果",
        html:
          label("RESULT", "结果") +
          `<p>${masked(secretHtml(str(alarm.result_note) || "未记录"), whole)}</p>` +
          notes([`平台任务 ${escapeHtml(str(alarm.cron_job_id) || "未建立")}`, `创建于 ${dateTime(Number(alarm.created_at))}`, alarm.finished_at ? `结束于 ${dateTime(Number(alarm.finished_at))}` : "仍在生效"]),
      },
    ],
    action: live ? { action: "cancel-alarm", en: "× CANCEL ALARM", cn: "取消闹钟" } : { action: "", en: "ALARM CLOSED", cn: "已结束", disabled: true },
    footnote: live ? "取消会同时删除 AstrBot 定时任务" : `状态：${ALARM_STATUS[str(alarm.status)]?.[1] ?? str(alarm.status)}`,
    exportText: (revealed) =>
      exportLines(record, fields.map(([key, name]) => [name, whole && !revealed ? "（保密内容）" : cardValue(key, card[key])] as [string, string]), revealed),
  };
}

function promiseView(record: ArchiveRecord, promise: Row): DetailView {
  return {
    meta: [
      ["PARTIES / 谁对谁", escapeHtml(record.department)],
      ["DUE / 期限", escapeHtml(str(promise.due_date) || "未约定")],
      ["RECORDED / 记录于", dateOnly(Number(promise.created_at))],
      ["STATUS / 状态", statusCell(PROMISE_STATUS, str(promise.status)), true],
    ],
    tabs: [
      { label: "内容", html: label("PROMISE", "承诺内容") + text(str(promise.content)) },
      { label: "出处", html: label("EVIDENCE", "出处") + notes(evidenceItems(promise.evidence_json)) },
      { label: "进展", html: label("PROGRESS", "进展") + text(str(promise.note) || "暂无进展记录") + notes([`最近更新 ${dateTime(Number(promise.updated_at))}`]) },
    ],
    action:
      str(promise.status) === "deleted"
        ? { action: "", en: "DELETED", cn: "已在回收站", disabled: true }
        : { action: "delete-promise", en: "− DELETE PROMISE", cn: "删除承诺" },
    footnote: "删除后进入回收站，30 天内可恢复",
    exportText: (revealed) => exportLines(record, [["承诺内容", str(promise.content)], ["进展", str(promise.note)]], revealed),
  };
}

function personView(record: ArchiveRecord, person: Row, isAdmin: boolean): DetailView {
  const aliases = parseJson<string[]>(person.aliases_json, []);
  const anniversaries = parseJson<Row[]>(person.anniversaries_json, []);
  const anniversaryText = anniversaries.map((a) => `${str(a.name)} ${str(a.date)}`).join("、");
  return {
    meta: [
      ["ALIASES / 别名", escapeHtml(aliases.join("、") || "—")],
      ["ANNIVERSARY / 纪念日", escapeHtml(anniversaryText || "—")],
      ["UPDATED / 更新于", dateOnly(Number(person.updated_at))],
      ["ROLE / 身份", isAdmin ? "管理员" : "关系本", true],
    ],
    tabs: [
      { label: "关系层", html: label("RELATION", "关系层 · 长期稳定") + text(str(person.relation_text)) },
      { label: "近况层", html: label("RECENT", "近况层 · 常变") + text(str(person.recent_text)) },
      {
        label: "纪念日与依据",
        html:
          label("ANNIVERSARIES", "纪念日") +
          notes(anniversaries.map((a) => escapeHtml(`${str(a.name)} · ${str(a.date)}`))) +
          label("EVIDENCE", "依据") +
          text(str(person.evidence) || "—") +
          (person.expected_friend_until ? notes([`预期好友申请：${escapeHtml(str(person.expected_reason))}（至 ${dateTime(Number(person.expected_friend_until))}）`]) : ""),
      },
    ],
    action: { action: "edit-person", en: "✎ EDIT RELATION", cn: "编辑关系层" },
    footnote: "关系层与纪念日可以手动修正",
    exportText: (revealed) => exportLines(record, [["关系层", str(person.relation_text)], ["近况层", str(person.recent_text)], ["纪念日", anniversaryText]], revealed),
  };
}

function emptyView(record: ArchiveRecord): DetailView {
  return {
    meta: [
      ["COLUMN / 列", escapeHtml(record.category)],
      ["COUNT / 数量", "0"],
      ["SOURCE / 来源", "夜间复盘"],
      ["STATUS / 状态", "暂无记录", true],
    ],
    tabs: [
      { label: "说明", html: label("NO RECORD", "暂无记录") + `<p>这一列还没有档案。每天零点的夜间复盘提交后，新的${escapeHtml(record.category)}会出现在这里。</p>` },
      { label: "来源", html: label("SOURCE", "来源") + "<p>—</p>" },
      { label: "记录", html: label("LOG", "记录") + "<p>—</p>" },
    ],
    action: { action: "", en: "NO RECORD", cn: "暂无记录", disabled: true },
    footnote: "—",
    exportText: () => exportLines(record, [["说明", "暂无记录"]], false),
  };
}

export function detailView(record: ArchiveRecord, overview: Overview): DetailView {
  const raw = record.raw as Row;
  switch (record.kind) {
    case "plan":
      return planView(record, raw as PlanDetail, record.clearance === "IN EFFECT");
    case "todo":
      return todoView(record, raw);
    case "alarm":
      return alarmView(record, raw, overview.alarm_events?.[String(raw.id)] ?? []);
    case "promise":
      return promiseView(record, raw);
    case "person":
      return personView(record, raw, (overview.admins ?? []).includes(str(raw.qq)));
    default:
      return emptyView(record);
  }
}
