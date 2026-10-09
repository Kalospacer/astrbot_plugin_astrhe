/** 列表窗格：五列档案的列表、NIGHT RUNS 的运行列表，以及加载中 / 出错 / 空列的 MD3 空状态。 */
import type { ArchiveRecord } from "../data";
import { escapeHtml } from "../html";
import { runCount, runSummaries } from "../astrhe/runs";
import { categoryRecords, realCount, state } from "./store";
import { categoryIcon, icon } from "./shell";
import { statusChip } from "./status";

const HINTS: Record<string, string> = {
  规划书: "每晚复盘后写下的第二天计划，最近 20 份，生效中的排在最前。",
  待办: "挂在各个会话里的待办，进行中的排在前面，最近 20 条。",
  闹钟: "AstrHe 安排的定时任务，待执行的排在前面，最近 20 个。",
  承诺: "谁答应了谁什么，未兑现的排在前面，最近 20 条。",
  关系本: "按 QQ 号记录的人物关系，管理员排在最前，最近 20 位。",
};

export function emptyState(glyph: string, title: string, text: string, action = "") {
  return `<div class="empty-state">${icon(glyph)}<h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p>${action}</div>`;
}

export function recordItem(record: ArchiveRecord, active: boolean) {
  const secret = record.secret ? icon("lock--outlined") : "";
  return `<mdui-list-item rounded data-record="${record.id}"${active ? " active" : ""} description-line="1">
    <span slot="icon" class="leading-icon">${categoryIcon(record.category)}</span>
    ${escapeHtml(record.title)}
    <span slot="description">${record.id} · ${escapeHtml(record.department)}</span>
    <span slot="end-icon" class="trailing">${secret}${statusChip(record)}</span>
  </mdui-list-item>`;
}

function recordsMarkup() {
  const items = categoryRecords(state.category);
  const real = items.filter((r) => r.kind !== "empty");
  const heading = `<header class="list-heading"><h2>${state.category}</h2><p>${realCount(state.category)} 份 · ${HINTS[state.category]}</p></header>`;
  if (!real.length)
    return (
      heading +
      emptyState(
        "inbox--outlined",
        "这一列还没有档案",
        `每天零点的夜间复盘提交后，新的${state.category}会出现在这里。`,
      )
    );
  return (
    heading +
    `<mdui-list>${real.map((r) => recordItem(r, r.id === state.selectedId)).join("")}</mdui-list>` +
    footerMarkup()
  );
}

function runsMarkup() {
  const runs = runSummaries();
  const heading = `<header class="list-heading"><h2>NIGHT RUNS</h2><p>${runCount()} 次夜间复盘 · 点开查看会话汇报与审稿意见。</p></header>`;
  if (!runs.length)
    return (
      heading +
      emptyState("bedtime--outlined", "还没有夜间运行记录", "每天零点会自动复盘；也可以在聊天里用 /astrhe run 手动运行。")
    );
  const items = runs
    .map(
      (run) => `<mdui-list-item rounded data-run="${run.id}"${run.id === state.runId ? " active" : ""} description-line="1">
        <span slot="icon" class="leading-icon">${icon("bedtime--outlined")}</span>
        ${escapeHtml(run.planDate)} 规划日
        <span slot="description">#${String(run.id).padStart(3, "0")} · ${escapeHtml(run.mode)} · ${run.startedAt} · ${escapeHtml(run.duration)}</span>
        <span slot="end-icon" class="trailing"><span class="status-chip" data-tone="${run.status === "committed" ? "done" : run.status === "failed" ? "bad" : run.status === "running" ? "active" : "muted"}">${escapeHtml(run.statusCn)}</span></span>
      </mdui-list-item>`,
    )
    .join("");
  return heading + `<mdui-list>${items}</mdui-list>` + footerMarkup();
}

/** 页面底部：版本号与第三方许可（点开「关于」看详情）。 */
function footerMarkup() {
  return `<footer class="list-footer"><button type="button" data-action="about">AstrHe ${escapeHtml(state.overview?.version ?? "")} · NORMAL · mdui（MIT）</button></footer>`;
}

export function renderList() {
  const scroll = document.querySelector<HTMLElement>("#list-scroll")!;
  scroll.innerHTML = state.mode === "runs" ? runsMarkup() : recordsMarkup();
  scroll.scrollTop = 0;
}

/** 只切换选中项的高亮，不重绘列表（保持滚动位置）。 */
export function markActive() {
  document.querySelectorAll<HTMLElement>("#list-scroll [data-record], #list-scroll [data-run]").forEach((item) => {
    const active =
      state.mode === "runs" ? Number(item.dataset.run) === state.runId : item.dataset.record === state.selectedId;
    item.toggleAttribute("active", active);
  });
}

/** 单个档案变化后，只重绘它那一行。 */
export function refreshItem(record: ArchiveRecord) {
  const item = document.querySelector<HTMLElement>(`#list-scroll [data-record="${record.id}"]`);
  if (item) item.outerHTML = recordItem(record, record.id === state.selectedId);
}

export function renderListLoading() {
  document.querySelector("#list-scroll")!.innerHTML = `<div class="loading-block"><mdui-circular-progress></mdui-circular-progress></div>`;
}

export function renderListError(message: string) {
  document.querySelector("#list-scroll")!.innerHTML = emptyState(
    "error--outlined",
    "读取档案失败",
    message,
    `<mdui-button data-action="retry" variant="tonal">${icon("refresh--outlined", "icon")}重试</mdui-button>`,
  );
}
