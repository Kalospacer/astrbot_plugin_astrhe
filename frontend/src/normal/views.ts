/** 把状态画到界面上：导航、标题栏、两个窗格，以及各种导航动作（切列、开档案、开运行记录、返回）。 */
import { realCount, byId, loadArchive, state } from "./store";
import { closeSearch } from "./search";
import { markActive, renderList, renderListError, renderListLoading } from "./list";
import { renderDetail, renderEmptyDetail, renderRunDetail } from "./detail-pane";
import { containerTransform, fadeThrough } from "./motion";
import { archiveColumns } from "../data";

const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;

/** compact / medium 下处在详情页，或处在 NIGHT RUNS 时，顶部应用栏显示返回键。 */
export const canGoBack = () => state.mode === "runs" || (state.size !== "expanded" && state.pane === "detail");

/** 根据状态刷新导航与标题栏（不重绘列表和详情）。 */
export function applyChrome() {
  const panes = $("#panes");
  panes.dataset.size = state.size;
  panes.dataset.pane = state.pane;
  document.documentElement.dataset.size = state.size;

  const runs = state.mode === "runs";
  const inDetail = state.size !== "expanded" && state.pane === "detail";
  let title = "AstrHe";
  if (runs) title = inDetail && state.runId ? `运行 #${String(state.runId).padStart(3, "0")}` : "NIGHT RUNS";
  else if (inDetail) title = byId(state.selectedId)?.title ?? title;
  $("#app-title").textContent = title;
  $("#back-slot").hidden = !canGoBack();

  // 导航选中项：NIGHT RUNS 不属于五列，此时把选中态清掉（mdui 的导航组件没有「无选中」的接口，直接改 active）
  for (const nav of document.querySelectorAll<HTMLElement & { value: string; updateComplete: Promise<unknown> }>("#nav-bar, #nav-rail")) {
    if (nav.value !== state.category) nav.value = state.category;
    void nav.updateComplete.then(() =>
      requestAnimationFrame(() =>
        nav.querySelectorAll<HTMLElement & { active: boolean }>("[value]").forEach((item) => {
          item.active = !runs && item.getAttribute("value") === state.category;
        }),
      ),
    );
  }
  // 手机竖屏上，档案详情和运行记录是二级页面，不显示底部导航栏。
  // 用 display:none 而不是 mdui 的 hide（它只做位移，布局仍会给导航栏留位置）
  const hidden = state.size === "compact" && (runs || state.pane === "detail");
  $("#nav-bar").toggleAttribute("data-hidden", hidden);
  document.documentElement.toggleAttribute("data-nav-bar", state.size === "compact" && !hidden);
}

/** 导航栏上每列的档案数量。 */
function updateBadges() {
  for (const item of document.querySelectorAll<HTMLElement>("#nav-bar > [value], #nav-rail > [value]")) {
    const count = realCount(item.getAttribute("value")!);
    item.querySelector("mdui-badge")?.remove();
    if (count) item.insertAdjacentHTML("beforeend", `<mdui-badge slot="badge" variant="large">${count}</mdui-badge>`);
  }
}

/** 数据读完后的第一次完整绘制。 */
export function renderAll() {
  updateBadges();
  renderList();
  renderEmptyDetail(state.mode === "runs");
  applyChrome();
}

/** 读取档案；失败时给出可重试的错误状态。 */
export async function boot() {
  renderListLoading();
  try {
    await loadArchive();
  } catch (error) {
    console.error(error);
    renderListError(error instanceof Error ? error.message : String(error));
    return;
  }
  document.querySelector("#loading")?.remove();
  renderAll();
}

/** 切换导航目的地（五列之一）：fade through。 */
export async function showCategory(category: string) {
  if (!archiveColumns.includes(category)) return;
  if (state.mode === "records" && state.category === category && (state.size === "expanded" || state.pane === "list")) return;
  await fadeThrough($("#panes"), () => {
    state.mode = "records";
    state.category = category;
    state.selectedId = null;
    state.pane = "list";
    renderList();
    renderEmptyDetail();
    applyChrome();
  });
}

/** 打开一份档案：compact / medium 是 container transform 进全屏详情，expanded 是右栏内容 fade through。 */
export async function showRecord(id: string, source: HTMLElement | null) {
  const record = byId(id);
  if (!record || record.kind === "empty") return;
  if (state.searchOpen) {
    void closeSearch();
    source = null;
  }
  const update = () => {
    const sameList = state.mode === "records" && state.category === record.category;
    state.mode = "records";
    state.category = record.category;
    state.selectedId = id;
    state.pane = "detail";
    if (sameList) markActive();
    else renderList();
    renderDetail(record);
    applyChrome();
  };
  if (state.size === "expanded") await fadeThrough($("#detail-scroll"), update);
  else await containerTransform(source, update, () => $("#pane-detail"), $("#panes"));
}

/** 进入 NIGHT RUNS；带 runId 时直接打开那一次运行。 */
export async function showRuns(runId: number | null = null, source: HTMLElement | null = null) {
  if (state.searchOpen) void closeSearch();
  const update = () => {
    const sameList = state.mode === "runs";
    state.mode = "runs";
    state.runId = runId;
    state.pane = runId ? "detail" : "list";
    if (sameList) markActive();
    else renderList();
    if (runId) void renderRunDetail(runId);
    else renderEmptyDetail(true);
    applyChrome();
  };
  if (state.size === "expanded" || !runId) await fadeThrough($("#panes"), update);
  else await containerTransform(source, update, () => $("#pane-detail"), $("#panes"));
}

/** 在 NIGHT RUNS 里打开一次运行：compact / medium 是 container transform，expanded 是右栏 fade through。 */
export async function showRun(runId: number, source: HTMLElement | null) {
  const update = () => {
    state.runId = runId;
    state.pane = "detail";
    markActive();
    void renderRunDetail(runId);
    applyChrome();
  };
  if (state.size === "expanded") await fadeThrough($("#detail-scroll"), update);
  else await containerTransform(source, update, () => $("#pane-detail"), $("#panes"));
}

/** 返回：详情 → 列表；NIGHT RUNS → 档案列表。 */
export async function goBack() {
  if (!canGoBack()) return;
  if (state.mode === "runs" && !(state.size !== "expanded" && state.pane === "detail")) {
    await fadeThrough($("#panes"), () => {
      state.mode = "records";
      state.runId = null;
      state.pane = "list";
      renderList();
      state.selectedId ? renderDetail(byId(state.selectedId)!) : renderEmptyDetail();
      applyChrome();
    });
    return;
  }
  const runs = state.mode === "runs";
  const back = () => {
    state.pane = "list";
    if (runs) state.runId = null;
    markActive();
    applyChrome();
  };
  const key = runs ? `[data-run="${state.runId}"]` : `[data-record="${state.selectedId}"]`;
  await containerTransform($("#pane-detail"), back, () => document.querySelector<HTMLElement>(`#list-scroll ${key}`), $("#panes"));
}
