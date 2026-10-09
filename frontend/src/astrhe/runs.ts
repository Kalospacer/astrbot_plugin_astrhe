/** 夜间运行记录弹窗（替代原版右上角的 SAVED 收藏）：列表与单次运行的会话汇报、审稿意见。 */
import { escapeHtml } from "../html";
import { apiGet } from "./bridge";
import { dateTime, parseJson, sessionName } from "./format";
import { decryptButton, secretHtml } from "./secrecy";

type Row = Record<string, unknown>;
const str = (value: unknown) => (typeof value === "string" ? value : value == null ? "" : String(value));

export interface RunRow extends Row {
  id: number;
  started_at: number;
  ended_at: number | null;
  plan_date: string;
  mode: string;
  status: string;
  error: string;
  stats_json: string;
}

const STATUS: Record<string, [string, string]> = {
  running: ["RUNNING", "进行中"],
  committed: ["COMMITTED", "已提交"],
  dry_done: ["DRY RUN", "演练完成"],
  failed: ["FAILED", "失败"],
};
const MODE: Record<string, string> = { auto: "定时", manual: "手动", dry: "演练", dryrun: "演练" };
const STAGES: Record<string, string> = {
  init: "准备",
  cleanup: "清理",
  backfill: "补拉",
  reconcile: "对账",
  report: "汇报",
  plan: "规划",
  review: "审稿",
  commit: "提交",
  external: "外部收尾",
};
const REVIEW_STATUS: Record<string, string> = { ok: "有效", invalid: "格式无效" };

function seconds(value: unknown) {
  const total = Math.round(Number(value) || 0);
  return total >= 60 ? `${Math.floor(total / 60)} 分 ${total % 60} 秒` : `${total} 秒`;
}

/** 运行统计翻译成中文；不认识的字段原样显示。 */
function statsFacts(stats: Row): [string, string][] {
  return Object.entries(stats).map(([key, value]) => {
    if (key === "stages" && value && typeof value === "object")
      return ["各阶段", Object.entries(value as Row).map(([stage, s]) => `${STAGES[stage] ?? stage} ${seconds(s)}`).join(" · ") || "—"];
    if (key === "elapsed_seconds") return ["总耗时", seconds(value)];
    if (key === "sessions") return ["会话数", str(value)];
    if (key === "reports") return ["汇报数", str(value)];
    if (key === "reports_failed")
      return ["汇报失败", Array.isArray(value) && value.length ? value.map((u) => sessionName(String(u))).join("、") : "无"];
    if (key === "external_results") return ["外部动作", Array.isArray(value) ? `${value.length} 项` : str(value)];
    if (key === "backfill") return ["补拉", typeof value === "object" ? JSON.stringify(value) : str(value)];
    return [key, typeof value === "object" ? JSON.stringify(value) : str(value)];
  });
}

const REPORT_FIELDS: [string, string][] = [
  ["big_events", "大事"],
  ["interesting", "有趣的事"],
  ["self_interest", "自己感兴趣的事"],
  ["promises", "承诺"],
  ["plan_candidates", "可能的计划"],
  ["person_updates", "关系本更新"],
  ["reflection_hints", "反思线索"],
];

let runs: RunRow[] = [];

export async function loadRuns() {
  const data = await apiGet<{ runs: RunRow[] }>("runs");
  runs = data?.runs ?? [];
  return runs;
}

export const runCount = () => runs.length;

function duration(run: RunRow) {
  if (!run.ended_at) return "—";
  const seconds = Math.max(0, Math.round(run.ended_at - run.started_at));
  return seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}

/** 列表：沿用检索弹窗的行样式（档案 / 科室 / 访问三列）。 */
export function runListMarkup() {
  if (!runs.length)
    return `<div class="empty-results"><span>∅</span><strong>还没有夜间运行记录</strong><p>每天零点会自动复盘；也可以在聊天里用 /astrhe run 手动运行。</p></div>`;
  return runs
    .map((run) => {
      const [en, cn] = STATUS[run.status] ?? [run.status.toUpperCase(), run.status];
      return `<button class="result-row" data-run="${run.id}"><span class="result-name"><b>#${String(run.id).padStart(3, "0")}</b><span>${escapeHtml(run.plan_date || "—")} 规划日<small>${escapeHtml(MODE[run.mode] ?? run.mode)} · ${dateTime(run.started_at)}</small></span></span><span>${escapeHtml(cn)} · ${escapeHtml(duration(run))}</span><span>${escapeHtml(en)} <i>↗</i></span></button>`;
    })
    .join("");
}

function listItems(value: unknown) {
  const items = Array.isArray(value) ? value : value ? [value] : [];
  return items.map((item) => (typeof item === "string" ? item : JSON.stringify(item)));
}

function reportMarkup(report: Row) {
  const content = parseJson<Row>(report.content_json, {});
  const summary = str(content.summary);
  const parts = REPORT_FIELDS.flatMap(([key, name]) => {
    const items = listItems(content[key]);
    return items.length ? [`<dt>${name}</dt>${items.map((i) => `<dd>${secretHtml(i)}</dd>`).join("")}`] : [];
  });
  const failed = !summary;
  return `<section class="astrhe-run-block"><h4>${escapeHtml(sessionName(str(report.umo)))}${failed ? '<em>汇报失败</em>' : ""}</h4>${
    failed
      ? `<p>${secretHtml(str(report.raw_text) || "没有保存到原文")}</p>`
      : `<p>${secretHtml(summary)}</p>${parts.length ? `<dl>${parts.join("")}</dl>` : ""}`
  }</section>`;
}

/** 单次运行详情：基本信息、会话汇报、审稿意见。 */
export async function runDetailMarkup(runId: number) {
  const run = runs.find((r) => r.id === runId);
  const detail = await apiGet<{ reports: Row[]; reviews: Row[] }>("run_detail", { run_id: runId });
  const stats = parseJson<Row>(run?.stats_json, {});
  const [en, cn] = STATUS[run?.status ?? ""] ?? ["—", run?.status ?? "—"];
  const facts = [
    ["规划日", run?.plan_date || "—"],
    ["模式", MODE[run?.mode ?? ""] ?? run?.mode ?? "—"],
    ["状态", `${cn} · ${en}`],
    ["开始", dateTime(run?.started_at)],
    ["耗时", run ? duration(run) : "—"],
    ...statsFacts(stats),
  ];
  const reviews = detail?.reviews ?? [];
  const reports = detail?.reports ?? [];
  const body = `
    <section class="astrhe-run-block"><h4>RUN #${String(runId).padStart(3, "0")}</h4><dl class="astrhe-run-facts">${facts.map(([k, v]) => `<dt>${escapeHtml(String(k))}</dt><dd>${escapeHtml(String(v))}</dd>`).join("")}</dl>${run?.error ? `<p class="astrhe-run-error">${escapeHtml(run.error)}</p>` : ""}</section>
    <h3>REVIEWS / 审稿意见 <small>${reviews.length}</small></h3>
    ${reviews.length ? reviews.map((r) => `<section class="astrhe-run-block"><h4>${escapeHtml(str(r.focus) || "审稿")}<em${str(r.status) === "ok" ? ' class="ok"' : ""}>${escapeHtml(REVIEW_STATUS[str(r.status)] ?? str(r.status))}</em></h4><p>${secretHtml(str(r.result_text))}</p></section>`).join("") : "<p class=\"astrhe-run-empty\">这次没有审稿记录。</p>"}
    <h3>REPORTS / 会话汇报 <small>${reports.length}</small></h3>
    ${reports.length ? reports.map(reportMarkup).join("") : "<p class=\"astrhe-run-empty\">这次没有会话汇报（可能没有新消息，或演练提前结束）。</p>"}`;
  const secret = body.includes("astrhe-secret\"");
  // 解密按钮与内容放在同一个 .astrhe-decryptable 容器里，点击时才能找到要揭开的区域
  return `<div class="astrhe-decryptable"><div class="astrhe-run-top"><button class="astrhe-run-back" data-action="runs-back">← ALL RUNS <span>全部运行</span></button>${secret ? decryptButton() : ""}</div>
  <div class="astrhe-run-detail">${body}</div></div>`;
}
