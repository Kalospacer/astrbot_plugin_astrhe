/** 把 AstrHe 总览接口的数据整理成档案阵列的五列档案。 */
import { archiveColumns, COLUMN_LIMIT, type ArchiveKind, type ArchiveRecord } from "../data";
import { parseJson, personName, sessionName, shortTitle } from "./format";
import { hasAdminSecret, secretFromAdmin, stripSecrets } from "./secrecy";

type Row = Record<string, unknown>;

export interface PlanDetail extends Row {
  id: number;
  run_id: number;
  plan_date: string;
  full_text: string;
  reflection: string;
  day_reminders: string;
  created_at: number;
  updated_at: number | null;
  sections: Record<string, string>;
}

export interface AlarmEvent {
  id: number;
  ts: number;
  kind: string;
  detail: string;
}

export interface Overview {
  now: string;
  timezone?: string;
  version?: string;
  admins?: string[];
  runtime?: { running: boolean; stage?: string; elapsed_seconds?: number };
  plan_details?: PlanDetail[];
  todos: Row[];
  alarms: Row[];
  persons: Row[];
  promises: Row[];
  alarm_events?: Record<string, AlarmEvent[]>;
}

export const PREFIX: Record<string, string> = {
  规划书: "P",
  待办: "T",
  闹钟: "A",
  承诺: "V",
  关系本: "R",
};

export const TODO_STATUS: Record<string, [string, string]> = {
  open: ["PENDING", "待办"],
  progress: ["IN PROGRESS", "有进展"],
  done: ["COMPLETED", "已完成"],
  dropped: ["DROPPED", "已放弃"],
  deleted: ["DELETED", "已删除 · 回收站"],
};
export const ALARM_STATUS: Record<string, [string, string]> = {
  scheduled: ["SCHEDULED", "待执行"],
  fired: ["RUNNING", "执行中"],
  done: ["COMPLETED", "已执行"],
  failed: ["FAILED", "执行失败"],
  missing: ["MISSED", "错过"],
  cancelled: ["CANCELLED", "已取消"],
};
export const PROMISE_STATUS: Record<string, [string, string]> = {
  open: ["OPEN", "未兑现"],
  done: ["KEPT", "已兑现"],
  broken: ["BROKEN", "未守约"],
  waived: ["WAIVED", "已作罢"],
  deleted: ["DELETED", "已删除 · 回收站"],
};

const str = (value: unknown) => (typeof value === "string" ? value : value == null ? "" : String(value));
/** 后端已解析的 JSON 字段（如出处列表）转回文字，用于查找保密段落 */
const jsonText = (value: unknown) => (typeof value === "string" ? value : JSON.stringify(value ?? ""));
const code3 = (code: number) => String(code).padStart(3, "0");

function record(
  category: string,
  kind: ArchiveKind,
  code: number,
  fields: Pick<ArchiveRecord, "title" | "en" | "clearance" | "department" | "secret" | "key" | "raw"> & {
    search: string[];
  },
): ArchiveRecord {
  const prefix = PREFIX[category];
  const id = `${prefix}-${code3(code)}`;
  const { search, ...rest } = fields;
  return {
    id,
    prefix,
    code,
    kind,
    category,
    ...rest,
    searchText: [id, fields.title, fields.en, fields.department, ...search].join(" ").toLowerCase(),
  };
}

function placeholder(category: string): ArchiveRecord {
  return record(category, "empty", 0, {
    title: "暂无记录",
    en: "NO RECORD",
    clearance: "EMPTY",
    department: "—",
    secret: false,
    key: "",
    raw: {},
    search: [],
  });
}

function planRecords(plans: PlanDetail[]) {
  return plans.slice(0, COLUMN_LIMIT).map((plan, index) => {
    const [, month = "", day = ""] = plan.plan_date.split("-");
    const texts = [plan.full_text, plan.reflection, plan.day_reminders, ...Object.values(plan.sections ?? {})];
    return record("规划书", "plan", plan.id, {
      title: `${Number(month)} 月 ${Number(day)} 日规划`,
      en: `NIGHT PLAN ${month}.${day}`,
      clearance: index === 0 ? "IN EFFECT" : "ARCHIVED",
      department: `${Object.keys(plan.sections ?? {}).length} 个会话段落`,
      secret: texts.some(hasAdminSecret),
      key: plan.id,
      raw: plan,
      search: [plan.plan_date, ...texts.map((t) => stripSecrets(t))],
    });
  });
}

function todoRecords(todos: Row[]) {
  const rank = (row: Row) => (["open", "progress"].includes(str(row.status)) ? 0 : 1);
  return [...todos]
    .sort((a, b) => rank(a) - rank(b))
    .slice(0, COLUMN_LIMIT)
    .map((todo) => {
      const secretWhole = secretFromAdmin(todo.secret_from_json);
      const content = str(todo.content);
      const secret = secretWhole || [content, str(todo.note), jsonText(todo.evidence_json)].some(hasAdminSecret);
      const umos = parseJson<string[]>(todo.visible_umos_json, []);
      const status = TODO_STATUS[str(todo.status)] ?? [str(todo.status).toUpperCase(), str(todo.status)];
      return record("待办", "todo", Number(todo.id), {
        title: secretWhole ? "保密待办" : shortTitle(stripSecrets(content)),
        en: `TODO T-${code3(Number(todo.id))}`,
        clearance: secret ? "CONFIDENTIAL" : status[0],
        department: umos.map(sessionName).join("、") || "—",
        secret,
        key: Number(todo.id),
        raw: todo,
        search: secretWhole ? [] : [stripSecrets(content), stripSecrets(str(todo.note))],
      });
    });
}

function alarmRecords(alarms: Row[]) {
  const live = (row: Row) => (["scheduled", "fired"].includes(str(row.status)) ? 0 : 1);
  return [...alarms]
    .sort((a, b) => live(a) - live(b))
    .slice(0, COLUMN_LIMIT)
    .map((alarm) => {
      const card = parseJson<Row>(alarm.card_json, {});
      const secretWhole = secretFromAdmin(card.secret_from);
      const cardTexts = Object.values(card).filter((v): v is string => typeof v === "string");
      const secret = secretWhole || [...cardTexts, str(alarm.result_note)].some(hasAdminSecret);
      const status = ALARM_STATUS[str(alarm.status)] ?? [str(alarm.status).toUpperCase(), str(alarm.status)];
      return record("闹钟", "alarm", Number(alarm.id), {
        title: secretWhole ? "保密闹钟" : shortTitle(stripSecrets(str(card.purpose) || "（未写目的）")),
        en: `ALARM A-${code3(Number(alarm.id))}`,
        clearance: secret ? "CONFIDENTIAL" : status[0],
        department: sessionName(str(alarm.target_umo)),
        secret,
        key: Number(alarm.id),
        raw: alarm,
        search: secretWhole ? [] : cardTexts.map((t) => stripSecrets(t)),
      });
    });
}

function promiseRecords(promises: Row[]) {
  const rank = (row: Row) => (str(row.status) === "open" ? 0 : 1);
  return [...promises]
    .sort((a, b) => rank(a) - rank(b))
    .slice(0, COLUMN_LIMIT)
    .map((promise) => {
      const content = str(promise.content);
      const secret = [content, str(promise.note), jsonText(promise.evidence_json)].some(hasAdminSecret);
      const status = PROMISE_STATUS[str(promise.status)] ?? [str(promise.status).toUpperCase(), str(promise.status)];
      return record("承诺", "promise", Number(promise.id), {
        title: shortTitle(stripSecrets(content)),
        en: `PROMISE V-${code3(Number(promise.id))}`,
        clearance: secret ? "CONFIDENTIAL" : status[0],
        department: `${personName(str(promise.from_id))} → ${personName(str(promise.to_id))}`,
        secret,
        key: Number(promise.id),
        raw: promise,
        search: [stripSecrets(content), stripSecrets(str(promise.note))],
      });
    });
}

function personRecords(persons: Row[], admins: Set<string>) {
  return [...persons]
    .sort((a, b) => Number(admins.has(str(b.qq))) - Number(admins.has(str(a.qq))))
    .slice(0, COLUMN_LIMIT)
    .map((person, index) => {
      const qq = str(person.qq);
      const aliases = parseJson<string[]>(person.aliases_json, []);
      const texts = [str(person.relation_text), str(person.recent_text)];
      const secret = texts.some(hasAdminSecret);
      return record("关系本", "person", index + 1, {
        title: aliases[0] || qq,
        en: `QQ ${qq}`,
        clearance: admins.has(qq) ? "ADMINISTRATOR" : secret ? "CONFIDENTIAL" : "RELATION",
        department: aliases.join("、") || "—",
        secret,
        key: qq,
        raw: person,
        search: [qq, ...aliases, ...texts.map((t) => stripSecrets(t))],
      });
    });
}

/** 按列顺序排好的全部档案；空列补一份占位档案。 */
export function buildRecords(overview: Overview): ArchiveRecord[] {
  const byColumn: Record<string, ArchiveRecord[]> = {
    规划书: planRecords(overview.plan_details ?? []),
    待办: todoRecords(overview.todos ?? []),
    闹钟: alarmRecords(overview.alarms ?? []),
    承诺: promiseRecords(overview.promises ?? []),
    关系本: personRecords(overview.persons ?? [], new Set((overview.admins ?? []).map(String))),
  };
  return archiveColumns.flatMap((column) => (byColumn[column].length ? byColumn[column] : [placeholder(column)]));
}
