/**
 * 详情窗格：档案详情（四格信息 + 三个页签 + 主操作）和 NIGHT RUNS 的单次运行详情。
 * 内容与保密规则全部来自 astrhe/detail.ts、astrhe/runs.ts：这里只负责把它们重新排成 MD3 的样子。
 */
import type { ArchiveRecord } from "../data";
import { escapeHtml } from "../html";
import { detailView, type DetailView } from "../astrhe/detail";
import { decryptButton, isRevealed } from "../astrhe/secrecy";
import { runDetailMarkup } from "../astrhe/runs";
import { emptyState } from "./list";
import { sharedAxisX } from "./motion";
import { icon } from "./shell";
import { state } from "./store";
import { statusChip } from "./status";

let view: DetailView | null = null;
let tabIndex = 0;

const scroll = () => document.querySelector<HTMLElement>("#detail-scroll")!;
/** 双语标签 "PLAN DATE / 规划日" 只留中文部分 */
const chinese = (label: string) => label.split(" / ").pop() ?? label;

/** 详情 HTML 里的 .panel-label 也是双语标签，同样只留中文。 */
function localizeLabels(root: ParentNode) {
  root.querySelectorAll(".panel-label").forEach((node) => (node.textContent = chinese(node.textContent ?? "")));
}

/** 把保密区域的「解密」按钮换成 MD3 assist chip；已经解密的显示为禁用状态。 */
export function upgradeDecrypt(root: ParentNode, revealed: boolean) {
  root.querySelectorAll<HTMLElement>("button.astrhe-decrypt").forEach((button) => {
    const chip = document.createElement("mdui-chip");
    chip.className = "astrhe-decrypt";
    chip.setAttribute("variant", "assist");
    chip.dataset.action = "decrypt";
    chip.innerHTML = revealed
      ? `${icon("lock-open--outlined", "icon")}已解密`
      : `${icon("lock--outlined", "icon")}解密保密内容`;
    if (revealed) chip.setAttribute("disabled", "");
    button.replaceWith(chip);
  });
}

/** 运行详情里的小标题（REVIEWS / 审稿意见、RUN #001）改成中文。 */
function localizeRunHeadings(root: ParentNode) {
  root.querySelectorAll(".astrhe-run-detail h3").forEach((heading) => {
    const label = heading.firstChild;
    if (label?.nodeType === Node.TEXT_NODE) label.textContent = chinese(label.textContent ?? "");
  });
  root.querySelectorAll(".astrhe-run-block h4").forEach((heading) => {
    const label = heading.firstChild;
    if (label?.nodeType === Node.TEXT_NODE) label.textContent = (label.textContent ?? "").replace(/^RUN #/, "运行 #");
  });
}

const ACTIONS: Record<string, { glyph: string; variant: string; danger?: boolean }> = {
  "open-run": { glyph: "history--outlined", variant: "filled" },
  "edit-person": { glyph: "edit--outlined", variant: "filled" },
  "delete-todo": { glyph: "delete--outlined", variant: "tonal", danger: true },
  "delete-promise": { glyph: "delete--outlined", variant: "tonal", danger: true },
  "cancel-alarm": { glyph: "close--outlined", variant: "tonal", danger: true },
};

function actionsMarkup(record: ArchiveRecord, current: DetailView) {
  const { action, cn, disabled } = current.action;
  const style = ACTIONS[action] ?? { glyph: "info--outlined", variant: "tonal" };
  const primary = `<mdui-button data-action="${action}" variant="${style.variant}"${style.danger ? " data-danger" : ""}${disabled ? " disabled" : ""}>${icon(style.glyph, "icon")}${escapeHtml(cn)}</mdui-button>`;
  const exporter = `<mdui-tooltip content="导出文本"><mdui-button-icon data-action="export" aria-label="导出 ${record.id} 档案">${icon("download--outlined")}</mdui-button-icon></mdui-tooltip>`;
  return `<div class="detail-actions">${primary}<span class="grow"></span>${exporter}</div>`;
}

export function renderEmptyDetail(runs = false) {
  view = null;
  scroll().innerHTML = runs
    ? emptyState("bedtime--outlined", "选择一次运行", "从左侧列表里选一次夜间复盘，查看会话汇报与审稿意见。")
    : emptyState("manage-search--outlined", "选择一份档案", "从左侧列表里选一份，查看它的详细内容。");
}

export function renderDetail(record: ArchiveRecord, keepTab = false) {
  view = detailView(record, state.overview!);
  if (!keepTab) tabIndex = 0;
  const current = view;
  const revealed = isRevealed(record.id);
  scroll().innerHTML = `
  <article class="detail astrhe-decryptable${revealed ? " astrhe-revealed" : ""}">
    <header class="detail-head">
      <div class="overline">${record.id} · ${escapeHtml(record.category)}</div>
      <h1>${escapeHtml(record.title)}</h1>
      <p class="subtitle">${escapeHtml(record.en)}</p>
      <div class="detail-chips">${statusChip(record)}${record.secret ? decryptButton() : ""}</div>
    </header>
    <dl class="meta-grid">${current.meta
      .map(
        ([label, value, status]) =>
          `<div class="meta-cell"${status ? " data-status" : ""}><dt>${escapeHtml(chinese(label))}</dt><dd>${value}</dd></div>`,
      )
      .join("")}</dl>
    <mdui-tabs id="detail-tabs" variant="secondary" full-width value="${tabIndex}">${current.tabs
      .map((tab, i) => `<mdui-tab value="${i}">${escapeHtml(tab.label)}</mdui-tab>`)
      .join("")}</mdui-tabs>
    <div id="tab-panel" class="tab-panel" role="tabpanel"></div>
    <p class="detail-foot">${escapeHtml(current.footnote)}</p>
    ${actionsMarkup(record, current)}
  </article>`;
  upgradeDecrypt(scroll(), revealed);
  fillPanel();
  scroll().scrollTop = 0;
  const tabs = document.querySelector<HTMLElement & { value?: string }>("#detail-tabs")!;
  tabs.addEventListener("change", () => {
    const next = Number(tabs.value);
    if (Number.isNaN(next) || next === tabIndex) return;
    const direction = next > tabIndex ? 1 : -1;
    tabIndex = next;
    void sharedAxisX(document.querySelector<HTMLElement>("#tab-panel")!, direction, fillPanel);
  });
}

function fillPanel() {
  const panel = document.querySelector<HTMLElement>("#tab-panel");
  if (!panel || !view) return;
  panel.innerHTML = view.tabs[tabIndex]?.html ?? "";
  localizeLabels(panel);
  // 解密只对当前这份档案生效：容器上的 astrhe-revealed 已经覆盖页签内容
}

/** 导出文本：未解密的保密内容写成「（保密内容）」，由 exportText 决定。 */
export const exportText = (record: ArchiveRecord) => view?.exportText(isRevealed(record.id)) ?? "";

/** 单次运行的详情（会话汇报、审稿意见）。 */
export async function renderRunDetail(runId: number) {
  scroll().innerHTML = `<div class="loading-block"><mdui-circular-progress></mdui-circular-progress></div>`;
  let html: string;
  try {
    html = await runDetailMarkup(runId);
  } catch (error) {
    html = emptyState("error--outlined", "读取运行记录失败", error instanceof Error ? error.message : String(error));
  }
  if (state.mode !== "runs" || state.runId !== runId) return;
  scroll().innerHTML = `<article class="detail run-detail">${html}</article>`;
  localizeRunHeadings(scroll());
  upgradeDecrypt(scroll(), false);
  scroll().scrollTop = 0;
}
