/**
 * 检索视图（MD3 Search）：compact 下全屏，其余尺寸是居中的浮层。
 * 命中规则与 SOUL OS 相同：编号、标题、会话、QQ 号和内容，保密内容已在 record.searchText 里排除。
 */
import { categories, records } from "../data";
import { escapeHtml } from "../html";
import { emptyState, recordItem } from "./list";
import { enter, leave } from "./motion";
import { icon } from "./shell";
import { state } from "./store";

let filter = "全部档案";
let query = "";

const root = () => document.querySelector<HTMLElement>("#search-view")!;
const input = () => document.querySelector<HTMLInputElement>("#search-input")!;

export function mountSearch() {
  document.querySelector("#search-root")!.innerHTML = `
  <div id="search-view" class="search-view" hidden>
    <div class="search-scrim" data-action="search-close"></div>
    <div class="search-panel" role="dialog" aria-modal="true" aria-label="检索档案">
      <div class="search-bar">
        <mdui-button-icon data-action="search-close" aria-label="关闭检索">${icon("arrow-back--outlined")}</mdui-button-icon>
        <input id="search-input" type="search" autocomplete="off" enterkeyhint="search" placeholder="输入编号、内容、会话或 QQ 号" aria-label="检索档案" />
        <mdui-button-icon id="search-clear" data-action="search-clear" aria-label="清空" hidden>${icon("close--outlined")}</mdui-button-icon>
      </div>
      <div class="search-filters" role="group" aria-label="按列筛选">${categories
        .map(
          (name, i) =>
            `<mdui-chip variant="filter" selectable data-filter="${escapeHtml(name)}"${i === 0 ? " selected" : ""}>${escapeHtml(name)}</mdui-chip>`,
        )
        .join("")}</div>
      <p id="search-count" class="search-count"></p>
      <div id="search-results" class="search-results"></div>
    </div>
  </div>`;
}

export function renderResults() {
  const text = query.trim().toLowerCase();
  const results = records.filter(
    (r) => r.kind !== "empty" && (filter === "全部档案" || r.category === filter) && r.searchText.includes(text),
  );
  document.querySelector("#search-results")!.innerHTML = results.length
    ? `<mdui-list>${results.map((r) => recordItem(r, false)).join("")}</mdui-list>`
    : emptyState(
        "manage-search--outlined",
        "没有匹配的档案",
        "尝试其他编号、内容、会话或 QQ 号，或切换分类。",
        `<mdui-button variant="tonal" data-action="search-reset">重置检索</mdui-button>`,
      );
  document.querySelector("#search-count")!.textContent = `${results.length} 份档案`;
  document.querySelector<HTMLElement>("#search-clear")!.hidden = !query;
}

export function setQuery(value: string) {
  query = value;
  renderResults();
}

export function setFilter(name: string) {
  filter = name;
  document
    .querySelectorAll<HTMLElement & { selected: boolean }>("#search-view [data-filter]")
    .forEach((chip) => (chip.selected = chip.dataset.filter === filter));
  renderResults();
}

export function resetSearch() {
  query = "";
  input().value = "";
  setFilter("全部档案");
}

export async function openSearch() {
  if (state.searchOpen) return;
  state.searchOpen = true;
  const view = root();
  view.hidden = false;
  renderResults();
  const panel = view.querySelector<HTMLElement>(".search-panel")!;
  input().focus({ preventScroll: true });
  await Promise.all([
    enter(view.querySelector<HTMLElement>(".search-scrim")!, [{ opacity: 0 }, { opacity: 1 }], 200),
    enter(
      panel,
      [
        { opacity: 0, transform: "translateY(-12px) scale(0.96)" },
        { opacity: 1, transform: "translateY(0) scale(1)" },
      ],
      300,
    ),
  ]);
}

export async function closeSearch() {
  if (!state.searchOpen) return;
  state.searchOpen = false;
  const view = root();
  await Promise.all([
    leave(view.querySelector<HTMLElement>(".search-scrim")!, [{ opacity: 1 }, { opacity: 0 }], 150),
    leave(
      view.querySelector<HTMLElement>(".search-panel")!,
      [
        { opacity: 1, transform: "translateY(0) scale(1)" },
        { opacity: 0, transform: "translateY(-12px) scale(0.96)" },
      ],
      200,
    ),
  ]);
  // 关闭动画期间又被打开时不要藏起来
  if (!state.searchOpen) {
    view.hidden = true;
    view.querySelectorAll("*").forEach((node) => (node as HTMLElement).getAnimations?.().forEach((a) => a.cancel()));
  }
}
