/** 显示格式：时间按插件所在服务器的时区，会话编码转成人能看懂的名字。 */
import { escapeHtml } from "../html";

let timeZone: string | undefined;
let personNames = new Map<string, string>();

export function configureFormat(options: { timezone?: string; persons: { qq: string; aliases: string[] }[] }) {
  timeZone = options.timezone || undefined;
  personNames = new Map(options.persons.filter((p) => p.aliases.length).map((p) => [p.qq, p.aliases[0]]));
}

function parts(ts: number) {
  const date = new Date(ts * 1000);
  const fields = new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type: string) => fields.find((f) => f.type === type)?.value ?? "";
  return { y: get("year"), m: get("month"), d: get("day"), hh: get("hour"), mm: get("minute") };
}

/** 2026-10-10 21:00 */
export function dateTime(ts: number | null | undefined) {
  if (!ts) return "—";
  const p = parts(ts);
  return `${p.y}-${p.m}-${p.d} ${p.hh}:${p.mm}`;
}

/** 2026-10-10 */
export function dateOnly(ts: number | null | undefined) {
  if (!ts) return "—";
  const p = parts(ts);
  return `${p.y}-${p.m}-${p.d}`;
}

export function personName(qq: string) {
  const name = personNames.get(qq);
  return name ? `${name}（${qq}）` : qq || "未知";
}

/** default:FriendMessage:10002 → 私聊 · 小雨（10002）；群聊 → 群聊 20001 */
export function sessionName(umo: string) {
  const [, kind = "", id = umo] = umo.split(":");
  if (kind === "FriendMessage") return `私聊 · ${personName(id)}`;
  if (kind === "GroupMessage") return `群聊 ${id}`;
  return umo;
}

/** 多段文字：保留换行，空内容给一个破折号。 */
export function paragraphs(text: string | null | undefined) {
  const value = (text ?? "").trim();
  return value ? escapeHtml(value).replace(/\n/g, "<br>") : "—";
}

export function parseJson<T>(value: unknown, fallback: T): T {
  if (typeof value !== "string") return (value as T) ?? fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

/** 截短用于阵列标题（详情页显示全文）。 */
export function shortTitle(text: string, limit = 16) {
  const value = text.replace(/\s+/g, " ").trim();
  return value.length > limit ? `${value.slice(0, limit)}…` : value || "（空）";
}

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六", "日"];

/** 常见的重复规则写成中文（每天 / 每周几 / 每月几号），其余照原样显示。 */
export function cronText(expression: string) {
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) return `重复 · ${expression}`;
  const [minute, hour, dom, month, dow] = fields;
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour) || month !== "*")
    return `重复 · ${expression}`;
  const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  if (dom === "*" && dow === "*") return `每天 ${time}`;
  if (dom === "*" && /^[0-7](,[0-7])*$/.test(dow))
    return `每周${dow.split(",").map((d) => WEEKDAYS[Number(d)]).join("、")} ${time}`;
  if (dow === "*" && /^\d+$/.test(dom)) return `每月 ${dom} 日 ${time}`;
  return `重复 · ${expression}`;
}

