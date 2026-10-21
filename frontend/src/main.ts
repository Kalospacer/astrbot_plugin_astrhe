import { createRollingClock } from "./rolling-clock";
import { InspectionOverlay } from "./inspection-overlay";
import { DocumentDecryption } from "./document-decryption";
import { escapeHtml } from "./html";
import {
  normalizeQuality,
  qualityPresets,
  superPerformanceQuality,
  type QualityPreset,
  type RenderQuality,
} from "./render-quality";
import { qualityMarkup, syncQualityUI } from "./quality-settings";
import { viewportLayout, openingLayout } from "./viewport-layout";
import { assetUrl, downloadProgress, FONT_PATHS, loadFont, MODEL_PATHS, preloadAsset } from "./asset-url";
import {
  createRollingNumber,
  createRollingText,
} from "@kitlangton/rolling-number";
import { ArchiveScene } from "./scene";
import { ModelViewer } from "./model-viewer";
import { ContentTransition, SurfaceTransition } from "./ui-transitions";
import { BootSequence } from "./boot";
import { wrap, type ArchiveNavigation } from "./archive-loop";
import {
  records,
  categories,
  archiveColumns,
  columnFiles,
  fileLocation,
  setRecords,
} from "./data";
import { apiGet, apiPost } from "./astrhe/bridge";
import { configureFormat, parseJson } from "./astrhe/format";
import { buildRecords, type Overview } from "./astrhe/records";
import { configureSecrecy, decryptButton, isRevealed, reveal } from "./astrhe/secrecy";
import { detailView, type DetailView } from "./astrhe/detail";
import { loadRuns, runCount, runDetailMarkup, runListMarkup } from "./astrhe/runs";
import {
  confirmMarkup,
  downloadText,
  personEditorMarkup,
  readPersonForm,
  type PendingConfirm,
} from "./astrhe/forms";
import {
  createMotionPreferences,
  fullMotion,
  motionEnabled,
  motionPresetFor,
  motionSettingsMarkup,
  motionSummary,
  reducedMotion,
  type MotionKey,
  type MotionPreset,
  type StoredMotion,
} from "./motion-preferences";
import { paintTheme, themeSettingsMarkup } from "./theme-ui";
const $ = <T extends HTMLElement = HTMLElement>(selector: string) =>
  document.querySelector<T>(selector)!;
import { logoMarkup, brandHeading } from "./brand";

$("#stage").innerHTML = `
  <div id="three-scene" class="three-scene"></div>
  <div class="scene-atmosphere archive-atmosphere"></div>
  <div id="boot-background" class="boot-background"><svg viewBox="0 0 1920 1080" preserveAspectRatio="none"><g fill="none" stroke="#fff" stroke-width="3"><path d="M-210 705C-45 705 182 704 247 567C337 377 99 306 4 435S27 680 169 631C309 584 227 314 279 111S568-113 568-113"/><path d="M1560-80C1374 114 1671 168 1601 323S1371 367 1431 480S1692 666 1559 787S1329 886 1498 1130"/><circle cx="1450" cy="648" r="346"/><circle cx="1450" cy="648" r="348"/></g></svg></div>
  <header class="brand">${brandHeading}</header>
  <nav class="system-nav" aria-label="系统导航">
    <button data-action="search"><span class="nav-glyph">⌕</span> ARCHIVE INDEX <span class="key">/</span></button>
    <button data-action="runs" aria-label="夜间运行记录" title="夜间运行记录">＋ NIGHT RUNS <span id="saved-count">00</span></button>
    <button class="settings-button" data-action="settings" aria-label="系统设置" title="系统设置"><span class="settings-glyph" aria-hidden="true">◷</span><span class="settings-label">设置</span></button>
  </nav>
  <button id="skip" class="skip" data-action="skip">ENTER SYSTEM <span>↗</span></button>
  <section id="boot" class="boot" aria-label="系统启动">
    <div class="access-text">ACCESS</div>
    <div class="boot-logo">${logoMarkup()}</div>
    <div class="auth-status"><span>▪</span> <span id="auth-message"></span><i></i></div>
    <div id="boot-sync" class="boot-sync" role="status" hidden><span>SYNCHRONIZING ARCHIVE</span><i><b></b></i><span id="boot-sync-value">00%</span></div>
    <div class="scan"><svg viewBox="0 0 1920 1080" aria-hidden="true"><g fill="none" stroke="#080a08" stroke-width="2" stroke-linecap="round"><path/><path stroke="#fff"/><path/><path/><path/><path/><circle class="orbit-dot" r="8" fill="#ed821b" stroke="none"/><circle class="orbit-dot" r="8" fill="#ed821b" stroke="none"/><circle class="scan-core" cx="960" cy="540" r="5" fill="#080a08" stroke="none"/></g></svg><span>PERMISSION AUTHORIZED</span></div>
    <div class="welcome"><div class="welcome-panel"></div><div class="welcome-heading">WELCOME TO</div><div class="welcome-company"><strong>ASTRHE.SOUL.</strong><strong class="welcome-highlight" aria-hidden="true">ASTRHE.SOUL.</strong></div><div class="welcome-database">NIGHTLY DATABASE</div><div class="welcome-logo">${logoMarkup()}</div></div>
  </section>
  <svg id="inspection-marks" viewBox="0 0 1920 1080" aria-hidden="true"><path id="inspection-lines"/><g id="inspection-corners"></g><circle id="inspection-point" r="1.8"/></svg>
  <div id="inspection-text" aria-hidden="true">CONFIDENTIALITY:<strong>GENERAL BUSINESS USE</strong></div>
  <section id="archive-ui" class="archive-ui" aria-label="档案选择">
    <div class="archive-callout"><div class="eyebrow">NIGHTLY DATABASE <span>／</span> <span id="archive-category">规划书</span></div><button class="file-title" data-action="open">FILE NUMBER: <span id="selected-id"><span id="selected-prefix">P</span>-<span id="selected-code">001</span></span><span class="file-open">↗</span></button><div class="callout-rule"><i></i></div><div class="file-summary"><span id="selected-title"></span><span id="selected-clearance"></span></div><button class="read-file" data-action="open">ACCESS FILE <span>→</span></button></div>
    <div id="hover-label" class="hover-label" hidden><span id="hover-prefix">P</span>-<span id="hover-code">001</span> / <span id="hover-title"></span></div>
    <div class="archive-counter"><span class="tiny-label">ARCHIVE / SELECT</span><div><span id="selected-number">01</span><i>/</i><span class="count-total">12</span></div></div>
    <div class="archive-navigation"><button data-action="prev" aria-label="上一个档案">↑</button><div id="file-ticks" class="file-ticks"></div><button data-action="next" aria-label="下一个档案">↓</button></div>
    <div class="column-navigation"><button data-action="column-prev" aria-label="上一列">←</button><div><span id="column-number">COLUMN <span id="column-index">03</span> / 05</span><strong id="column-name">机构档案</strong></div><button data-action="column-next" aria-label="下一列">→</button></div>
    <div class="archive-hint"><kbd>←</kbd> <kbd>→</kbd> 切换列 <span>／</span> <kbd>↑</kbd> <kbd>↓</kbd> 前后档案 <span>／</span> <kbd>ENTER</kbd> 读取</div>
  </section>
  <section id="detail-ui" class="detail-ui" aria-label="档案内容" hidden>
    <button class="back-button" data-action="back">← <span>ARCHIVE OVERVIEW</span><small>ESC</small></button>
    <div class="object-caption"><span id="object-id">NO.001</span><div>NIGHTLY DATABASE</div><small>DRAG TO INSPECT <span>↔</span></small><button class="viewer-open" data-action="model-viewer">360° 查看文档模型 <span>↗</span></button></div>
    <article id="detail-content" class="detail-content"></article>
  </section>
  <div class="powered">POWERED BY <b>ASTRHE</b><i></i></div>
  <footer class="system-footer"><span><i class="status-light"></i> SESSION AUTHORIZED</span><span>ADMINISTRATOR <i>／</i> <span id="clock">00:00:00</span></span><button data-action="replay" title="重播启动流程">REINITIALIZE ↗</button></footer>
  <div id="modal-root"></div><div id="toast" class="toast" role="status"></div>
  <div id="loading" class="loading"><div class="loading-mark">${logoMarkup()}</div><span>CONNECTING TO NIGHTLY DATABASE</span><div class="loading-progress" role="progressbar" aria-label="加载进度"><i></i><span id="loading-value">00%</span></div></div>
`;

$("#boot-background").insertAdjacentHTML(
  "beforeend",
  '<div class="boot-white"></div>',
);
const bootSequence = new BootSequence($("#stage"));
$("#viewport").insertAdjacentHTML(
  "beforeend",
  '<button class="mobile-entry" data-action="skip">进入档案 <span>→</span></button>',
);

type Mode = "boot" | "archive" | "detail";
let mode: Mode = "boot",
  selected = 0,
  bootStart = 0,
  lastStep = "",
  ready = false;
let modal: "search" | "runs" | "settings" | "person" | "confirm" | null = null,
  searchQuery = "",
  filter = "全部档案";
let activeTab = "overview";
const reviewParams = new URLSearchParams(location.search);
let frozenTime =
  reviewParams.get("freeze") === "1"
    ? Number(reviewParams.get("time") ?? 0)
    : null;
if (reviewParams.get("review") === "1") {
  $("#stage").dataset.review = "true";
  window.addEventListener("message", (event) => {
    if (
      event.origin !== location.origin ||
      event.source !== window.parent ||
      event.data?.type !== "rhine-review-frame"
    )
      return;
    const t = Number(event.data.time);
    if (!Number.isFinite(t) || t < 0 || t >= 35) return;
    frozenTime = t;
    if (ready && mode !== "boot") setMode("boot");
  });
}
let toastTimer: ReturnType<typeof setTimeout>;
let previousFocus: HTMLElement | null = null;
const detailTransition = new SurfaceTransition(
  $("#detail-ui"),
  undefined,
  180,
  180,
);
const tabTransition = new ContentTransition();
let modalTransition: SurfaceTransition | undefined;
let modalClosing = false;
let modalSiblings: { node: HTMLElement; inert: boolean }[] = [];
let pendingDetailFocus = false;
function readLocal<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "null") ?? fallback;
  } catch {
    return fallback;
  }
}
// AstrHe 数据：启动时经 Bridge 读取一次；之后的删除、取消、编辑只在原位更新对应档案。
let overview: Overview | undefined;
let currentView: DetailView | undefined;
let pendingConfirm: PendingConfirm | undefined;
let editingPerson: Record<string, unknown> | undefined;
let runDetailHtml: string | null = null;
const storedPrefs = readLocal<
  Partial<{
    reduced: boolean;
    quality: boolean;
    rendering: RenderQuality;
    superPerformance: boolean;
    colorTheme: "light" | "dark";
    motion: StoredMotion;
    motionPreset: MotionPreset;
  }>
>("rhine-settings", {});
const initialMotion = createMotionPreferences(
  storedPrefs.motion,
  storedPrefs.reduced ??
    (storedPrefs.motion === undefined
      ? matchMedia("(prefers-reduced-motion: reduce)").matches
      : undefined),
);
const initialMotionPreset = motionPresetFor(initialMotion);
const prefs = {
  motion: initialMotion,
  motionPreset: initialMotionPreset,
  quality: storedPrefs.quality ?? true,
  superPerformance: storedPrefs.superPerformance ?? false,
  rendering: normalizeQuality(
    storedPrefs.rendering,
    storedPrefs.quality !== false,
  ),
  colorTheme: storedPrefs.colorTheme === "dark" ? "dark" : "light",
};
const motionActive = (key: MotionKey) => motionEnabled(prefs.motion, key);
const motionIsReduced = () =>
  Object.values(prefs.motion).every((value) => !value);
paintTheme(prefs.colorTheme === "dark" ? 1 : 0);
const rollingMotion = {
  duration: 460,
  motionBlur: true,
  animated: motionActive("rollingNumbers"),
};
const updateFooterClock = createRollingClock($("#clock"));
const numberOptions = {
  ...rollingMotion,
  locales: "en-US",
  format: { minimumIntegerDigits: 2, useGrouping: false },
};
const fileCounter = createRollingNumber($("#selected-number"), {
  ...numberOptions,
  value: 1,
});
const columnCounter = createRollingNumber($("#column-index"), {
  ...numberOptions,
  value: 3,
});
const codeOptions = {
  ...numberOptions,
  format: { minimumIntegerDigits: 3, useGrouping: false },
  value: 1,
};
const textOptions = {
  ...rollingMotion,
  animated: motionActive("rollingText"),
  transition: "direct" as const,
  stagger: "none" as const,
};
const selectionTitle = createRollingText($("#selected-title"), {
  ...textOptions,
  text: $("#selected-title").textContent ?? "",
});
const columnTitle = createRollingText($("#column-name"), {
  ...textOptions,
  text: $("#column-name").textContent ?? "",
});
const hoverTitle = createRollingText($("#hover-title"), {
  ...textOptions,
  text: "",
});
const categoryTitle = createRollingText($("#archive-category"), {
  ...textOptions,
  text: $("#archive-category").textContent ?? "",
});
const clearanceTitle = createRollingText($("#selected-clearance"), {
  ...textOptions,
  text: $("#selected-clearance").textContent ?? "",
});
const rollingTitles = [
  selectionTitle,
  columnTitle,
  hoverTitle,
  categoryTitle,
  clearanceTitle,
];
const selectedCode = createRollingNumber($("#selected-code"), codeOptions);
const hoverCode = createRollingNumber($("#hover-code"), codeOptions);
let started = false;
const loading = $("#loading");
// The entry screen uses the actual viewport, including portrait phones; the
// reference animation still uses its calibrated 1920 x 1080 stage.
$("#viewport").append(loading);
$("#stage").inert = true;
$(".mobile-entry").inert = true;
let scene: ArchiveScene | undefined;
let viewer: ModelViewer | undefined;
let columnMemory: number[] = [];
function superPerformanceEnabled() {
  return prefs.superPerformance;
}
function effectiveRenderQuality() {
  return superPerformanceEnabled() ? superPerformanceQuality : prefs.rendering;
}
function savePrefs() {
  // 插件页面运行在不透明源沙盒里，localStorage 会抛错；偏好只在本次打开内有效。
  try {
    localStorage.setItem("rhine-settings", JSON.stringify(prefs));
  } catch {}
  if (!motionActive("rollingText"))
    rollingTitles.forEach((title) => title.finish());
  if (!motionActive("rollingNumbers"))
    [fileCounter, columnCounter, selectedCode, hoverCode].forEach((counter) =>
      counter.finish(),
    );
  if (!motionActive("surfaceTransitions")) {
    detailTransition.finish();
    modalTransition?.finish();
    tabTransition.finish();
  }
  scene?.setMotion(prefs.motion);
  scene?.setTheme(
    prefs.colorTheme === "dark",
    !motionActive("surfaceTransitions") || !started,
  );
  document
    .querySelectorAll<HTMLElement>("[data-color-theme]")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.colorTheme === prefs.colorTheme),
      ),
    );
  scene?.setSuperPerformance(superPerformanceEnabled());
  viewer?.setSuperPerformance(superPerformanceEnabled());
  scene?.setQuality(effectiveRenderQuality());
  viewer?.setQuality(effectiveRenderQuality());
  viewer?.setMotion(prefs.motion);
  syncQualityUI(prefs.rendering);
  updateQualitySummary();
  fileCounter.update({
    animated: motionActive("rollingNumbers") && mode === "archive",
  });
  rollingTitles.forEach((title) =>
    title.update({
      animated: motionActive("rollingText") && mode === "archive",
    }),
  );
  columnCounter.update({
    animated: motionActive("rollingNumbers") && mode === "archive",
  });
  selectedCode.update({
    animated: motionActive("rollingNumbers") && mode === "archive",
  });
  hoverCode.update({
    animated: motionActive("rollingNumbers") && mode === "archive",
  });
  $("#stage").classList.toggle("reduce-motion", motionIsReduced());
  $("#stage").classList.toggle(
    "reduce-surfaces",
    !motionActive("surfaceTransitions"),
  );
  updateFooterClock(new Date(), motionActive("rollingNumbers"));
}
let previousLayout = "";
function fit() {
  const stage = $("#stage");
  const viewport = $("#viewport");
  const coarse = matchMedia("(pointer: coarse)").matches;
  const reference =
    reviewParams.has("time") || reviewParams.get("review") === "1";
  const { width, height, scale, kind } =
    mode === "boot" && !reference
      ? openingLayout(viewport.clientWidth, viewport.clientHeight)
      : viewportLayout(
          viewport.clientWidth,
          viewport.clientHeight,
          coarse,
          mode === "boot",
        );
  stage.style.width = `${width}px`;
  stage.style.height = `${height}px`;
  stage.style.transform = `translate(-50%, -50%) scale(${scale})`;
  stage.dataset.layout = kind;
  stage.dataset.touch = String(coarse);
  viewport.dataset.mobileBoot = String(
    mode === "boot" && (coarse || viewport.clientWidth < 1100),
  );
  stage.style.setProperty("--stage-scale", String(scale));
  stage.style.setProperty("--opening-width", `${width}px`);
  stage.style.setProperty("--opening-height", `${height}px`);
  stage.style.setProperty(
    "--opening-scan-scale",
    String(Math.min(1, width / 1920)),
  );
  stage.dataset.openingPortrait = String(width < height);
  // The software keyboard resizes dialogs without recomposing the 3D scene.
  const visible = window.visualViewport;
  const stageTop = (viewport.clientHeight - height * scale) / 2;
  stage.style.setProperty(
    "--modal-top",
    `${Math.max(0, (visible?.offsetTop ?? 0) - stageTop) / scale}px`,
  );
  stage.style.setProperty(
    "--modal-height",
    `${Math.min(height, (visible?.height ?? viewport.clientHeight) / scale)}px`,
  );
  $("#viewport").style.setProperty("--scale", String(scale));
  const marks = document.querySelector("#inspection-marks");
  marks?.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const layoutKey = JSON.stringify([
    width,
    height,
    scale,
    kind,
    devicePixelRatio,
  ]);
  if (layoutKey !== previousLayout) {
    previousLayout = layoutKey;
    scene?.resize();
    viewer?.resize();
  }
  updateQualitySummary();
  // Re-measure line covers and tab underline after wrapping changes.
  requestAnimationFrame(() => {
    documentDecryption.refresh();
    const tab = document.querySelector<HTMLElement>(
      ".detail-tabs button.active",
    );
    const indicator = document.querySelector<HTMLElement>(".tab-indicator");
    if (tab && indicator)
      indicator.style.transform = `translateX(${tab.offsetLeft}px) scaleX(${tab.offsetWidth})`;
  });
}
window.addEventListener("resize", fit);
window.visualViewport?.addEventListener("resize", fit);
window.visualViewport?.addEventListener("scroll", fit);
matchMedia("(pointer: coarse)").addEventListener("change", fit);
fit();
let tickLane = -1;
/** 档案刻度随所在列重建：AstrHe 各列档案数量不同（原版每列固定 8 份）。 */
function renderTicks(lane: number, files: number[]) {
  const ticks = $("#file-ticks");
  if (lane === tickLane && ticks.childElementCount === files.length) return;
  tickLane = lane;
  ticks.innerHTML = files.map((index) => `<button data-select="${index}"></button>`).join("");
  ticks.toggleAttribute("data-dense", files.length > 8);
  ticks.style.setProperty("--ticks", String(files.length));
}

function setMode(next: Mode) {
  const previousMode = mode;
  rollingTitles.forEach((title) =>
    title.update({
      animated: motionActive("rollingText") && next === "archive",
    }),
  );
  if (next !== "archive") {
    rollingTitles.forEach((title) => title.finish());
    hoverCode.finish();
    $("#hover-label").hidden = true;
  }
  mode = next;
  $("#stage").dataset.mode = next;
  if (previousMode !== next) fit();
  $("#boot").inert = next !== "boot";
  $("#boot").setAttribute("aria-hidden", String(next !== "boot"));
  $("#archive-ui").inert = next !== "archive" || Boolean(modal);
  $("#archive-ui").setAttribute("aria-hidden", String(next !== "archive"));
  $(".system-nav").inert = next === "boot" || Boolean(modal);
  $(".system-footer").inert = next === "boot" || Boolean(modal);
  if (next === "detail") {
    if (previousMode !== "detail")
      detailTransition.show(!motionActive("surfaceTransitions"));
  } else if (
    previousMode === "detail" ||
    (next === "boot" && !$("#detail-ui").hidden)
  ) {
    pendingDetailFocus = false;
    tabTransition.cancel();
    detailTransition.hide(
      !motionActive("surfaceTransitions") || next === "boot",
    );
    if (!modal && next === "archive")
      $(".read-file").focus({ preventScroll: true });
  }
  $("#detail-ui").inert = next !== "detail" || Boolean(modal);
  scene?.setMode(next === "boot" ? "hidden" : next);
  if (next !== "boot") {
    bootSequence.reset();
    $(".file-title").firstChild!.textContent = "FILE NUMBER: ";
    $("#stage").dataset.boot = "done";
  }
  if (next === "detail" && previousMode !== "detail") {
    renderDetail();
    pendingDetailFocus = true;
    if (!scene) {
      $("#detail-content").style.opacity = "1";
      $("#detail-content").style.translate = "0 0";
      $("#detail-content").inert = false;
    }
  }
}
function select(index: number, navigation?: ArchiveNavigation) {
  selected = (index + records.length) % records.length;
  columnMemory[fileLocation(selected).lane] = selected;
  if (mode === "detail") setMode("archive");
  activeTab = "overview";
  scene?.select(selected, navigation);
  updateSelection(navigation);
}
function stepFile(direction: number) {
  const files = columnFiles(fileLocation(selected).lane);
  if (files.length < 2) return;
  select(
    files[(files.indexOf(selected) + direction + files.length) % files.length],
    { axis: "row", direction },
  );
}
function stepColumn(direction: number) {
  const lane = fileLocation(selected).lane;
  const next = wrap(lane + direction, archiveColumns.length);
  select(columnMemory[next], { axis: "lane", direction });
}
function updateSelection(navigation?: ArchiveNavigation) {
  const r = records[selected];
  const { lane } = fileLocation(selected);
  const files = columnFiles(lane);
  $("#selected-prefix").textContent = r.prefix;
  $("#inspection-text strong").textContent = r.secret ? "ADMINISTRATOR RESTRICTED" : "GENERAL ARCHIVE USE";
  selectionTitle.update({
    text: r.title,
    animated: motionActive("rollingText") && mode === "archive",
  });
  clearanceTitle.update({
    text: r.clearance,
    animated: motionActive("rollingText") && mode === "archive",
  });
  categoryTitle.update({
    text: r.category,
    animated: motionActive("rollingText") && mode === "archive",
  });
  const direction =
    navigation && "axis" in navigation
      ? navigation.direction > 0
        ? "up"
        : "down"
      : "auto";
  selectedCode.update({
    value: r.code,
    animated: motionActive("rollingNumbers") && mode === "archive",
    direction,
  });
  fileCounter.update({
    value: files.indexOf(selected) + 1,
    animated: motionActive("rollingNumbers") && mode === "archive",
    direction:
      navigation && "axis" in navigation && navigation.axis === "row"
        ? direction
        : "auto",
  });
  $(".count-total").textContent = String(files.length).padStart(2, "0");
  columnCounter.update({
    value: lane + 1,
    animated: motionActive("rollingNumbers") && mode === "archive",
    direction:
      navigation && "axis" in navigation && navigation.axis === "lane"
        ? direction
        : "auto",
  });
  columnTitle.update({
    text: archiveColumns[lane],
    animated: motionActive("rollingText") && mode === "archive",
  });
  $<HTMLButtonElement>('[data-action="column-prev"]').disabled = false;
  $<HTMLButtonElement>('[data-action="column-next"]').disabled = false;
  renderTicks(lane, files);
  $("#file-ticks").querySelectorAll<HTMLButtonElement>("button").forEach((button, slot) => {
    const index = files[slot],
      record = records[index];
    button.dataset.select = String(index);
    button.setAttribute("aria-label", `选择档案 ${record.id} ${record.title}`);
    button.title = `${record.id} · ${record.title}`;
    button.classList.toggle("selected", index === selected);
    button.setAttribute("aria-pressed", String(index === selected));
  });
  $("#saved-count").textContent = String(runCount()).padStart(2, "0");
}
function replayBoot() {
  if (!ready) return;
  closeModal(() => replayBootAfterModal());
}
function replayBootAfterModal() {
  bootStart = performance.now() / 1000 - 1.76;
  frozenTime = null;
  lastStep = "";
  setMode(!motionActive("boot") ? "archive" : "boot");
  scene?.select(0);
  selected = 0;
  updateSelection();
}
function openFile() {
  if (!ready) return;
  closeModal(() => {
    setMode("detail");
  });
}
function renderDetail() {
  tabTransition.cancel();
  const r = records[selected];
  const view = (currentView = detailView(r, overview!));
  const tabs = ["overview", "notes", "history"];
  const action = view.action;
  $("#object-id").textContent = `NO.${String(r.code).padStart(3, "0")}`;
  $("#detail-content").innerHTML = `
  <div class="detail-kicker"><span>FILE ${r.id}</span>${r.secret ? decryptButton() : `<span>${escapeHtml(r.clearance)}</span>`}</div>
  <h2>${escapeHtml(r.en)}</h2><div class="detail-title-cn">${escapeHtml(r.title)}<span>${escapeHtml(r.category)}</span></div>
  <div class="detail-rule"></div>
  <dl class="metadata">${view.meta.map(([label, value, status]) => `<div><dt>${label}</dt><dd>${status ? "<i></i>" : ""}${value}</dd></div>`).join("")}</dl>
  <div class="detail-tabs" role="tablist">${view.tabs.map((tab, i) => `<button id="tab-${tabs[i]}"${i === 0 ? ' class="active"' : ""} role="tab" aria-controls="tab-panel" aria-selected="${i === 0}" data-tab="${tabs[i]}">${String(i + 1).padStart(2, "0")} <span>${escapeHtml(tab.label)}</span></button>`).join("")}<i class="tab-indicator" aria-hidden="true"></i></div>
  <div id="tab-panel" class="tab-panel" role="tabpanel">${view.tabs[0].html}</div>
  <div class="detail-actions"><button class="solid-button" data-action="${action.action}"${action.disabled ? " disabled" : ""}>${escapeHtml(action.en)}<span>${escapeHtml(action.cn)}</span></button><button class="export-button" data-action="export" aria-label="导出 ${r.id} 档案">EXPORT <span>↓</span></button></div>
  <div class="detail-footnote"><span>${escapeHtml(view.footnote)}</span><span>${String(selected + 1).padStart(3, "0")} / ${String(records.length).padStart(3, "0")}</span></div>`;
  $("#detail-content").classList.add("astrhe-decryptable");
  $("#detail-content").classList.toggle("astrhe-revealed", isRevealed(r.id));
  $("#detail-content").setAttribute("tabindex", "-1");
  documentDecryption.reset(
    $("#detail-content"),
    !motionActive("documentReveal") ||
      !scene ||
      scene.decryptionFrame.phase === "clear",
  );
  setTab(activeTab, false);
}
function setTab(tab: string, animate = true) {
  if (animate && tab === activeTab) return;
  activeTab = tab;
  document.querySelectorAll("[data-tab]").forEach((b) => {
    const active = (b as HTMLElement).dataset.tab === tab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", String(active));
    b.setAttribute("tabindex", active ? "0" : "-1");
  });
  const tabButton = $<HTMLButtonElement>(`[data-tab="${tab}"]`);
  const indicator = $(".tab-indicator");
  indicator.style.transition =
    animate && motionActive("surfaceTransitions") ? "" : "none";
  indicator.style.transform = `translateX(${tabButton.offsetLeft}px) scaleX(${tabButton.offsetWidth})`;
  $("#tab-panel").setAttribute("aria-labelledby", tabButton.id);
  $("#tab-panel").innerHTML =
    currentView?.tabs[["overview", "notes", "history"].indexOf(tab)]?.html ?? "";
  $("#tab-panel").scrollTop = 0;
  documentDecryption.refresh();
  if (animate)
    tabTransition.reveal($("#tab-panel"), !motionActive("surfaceTransitions"));
}
function notify(message: string) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").classList.add("visible");
  toastTimer = setTimeout(() => $("#toast").classList.remove("visible"), 2600);
}

function openModal(kind: NonNullable<typeof modal>) {
  if (!ready) return;
  if (!modal) {
    previousFocus = document.activeElement as HTMLElement;
    modalSiblings = [...$("#stage").children]
      .filter(
        (node): node is HTMLElement =>
          node instanceof HTMLElement && node.id !== "modal-root",
      )
      .map((node) => ({ node, inert: node.inert }));
    modalSiblings.forEach(({ node }) => (node.inert = true));
  }
  modalClosing = false;
  modal = kind;
  searchQuery = "";
  filter = "全部档案";
  renderModal();
}
function closeModal(afterClose?: () => void) {
  if (!modal) {
    afterClose?.();
    return;
  }
  if (modalClosing) return;
  modalClosing = true;
  modalTransition!.hide(!motionActive("surfaceTransitions"), () => {
    modal = null;
    modalClosing = false;
    $("#modal-root").replaceChildren();
    modalTransition = undefined;
    modalSiblings.forEach(({ node, inert }) => (node.inert = inert));
    modalSiblings = [];
    $("#archive-ui").inert = mode !== "archive";
    $("#detail-ui").inert = mode !== "detail";
    previousFocus?.focus({ preventScroll: true });
    afterClose?.();
  });
}
const MODAL_TITLES = {
  search: ["档案检索", "ARCHIVE DIRECTORY"],
  runs: ["夜间运行记录", "NIGHT RUNS"],
  settings: ["系统设置", "SYSTEM PREFERENCES"],
  person: ["编辑关系层", "RELATION EDITOR"],
  confirm: ["确认操作", "CONFIRMATION"],
} as const;
function runPanelMarkup() {
  return (
    runDetailHtml ??
    `<div class="result-header"><span>RUN / 运行</span><span>RESULT / 结果</span><span>STATUS</span></div><div class="search-results">${runListMarkup()}</div>`
  );
}
function modalBody() {
  switch (modal) {
    case "settings":
      return settingsMarkup();
    case "person":
      return personEditorMarkup(editingPerson ?? {});
    case "confirm":
      return pendingConfirm ? confirmMarkup(pendingConfirm) : "";
    case "runs":
      return `<h2>NIGHT RUNS<small>夜间运行记录</small></h2><div id="run-panel">${runPanelMarkup()}</div><div class="modal-bottom"><span>${String(runCount()).padStart(2, "0")} RUNS RECORDED</span><span>NIGHTLY DATABASE <i>●</i> CONNECTED</span></div>`;
    default:
      return `<h2>ARCHIVE INDEX<small>档案检索</small></h2><div class="search-field"><span>⌕</span><input id="archive-search" type="search" autocomplete="off" placeholder="输入编号、内容、会话或 QQ 号" aria-label="检索档案"/><span class="key">ESC</span></div><div class="category-filters">${categories.map((c, i) => `<button data-filter="${escapeHtml(c)}" class="${i === 0 ? "active" : ""}">${escapeHtml(c)}</button>`).join("")}</div><div class="result-header"><span>FILE / 档案</span><span>SESSION / 会话与对象</span><span>STATUS</span></div><div id="search-results" class="search-results"></div><div class="modal-bottom"><span id="result-count"></span><span>NIGHTLY DATABASE <i>●</i> CONNECTED</span></div>`;
  }
}
function renderModal() {
  if (!modal) return;
  modalTransition?.dispose();
  const [label, top] = MODAL_TITLES[modal];
  const size = modal === "settings" ? "settings-modal" : modal === "person" || modal === "confirm" ? "astrhe-compact" : "";
  $("#modal-root").innerHTML =
    `<div class="modal-backdrop"><section class="terminal-modal ${size}" role="dialog" aria-modal="true" aria-label="${label}"><div class="modal-top"><span>ASTRHE / ${top}</span><button data-action="close-modal" aria-label="关闭窗口">CLOSE <span>×</span></button></div>${modalBody()}</section></div>`;
  const backdrop = $(".modal-backdrop");
  backdrop.hidden = true;
  modalTransition = new SurfaceTransition(backdrop, $(".terminal-modal"));
  modalTransition.show(!motionActive("surfaceTransitions"));
  if (modal === "settings") updateQualitySummary();
  if (modal === "search") renderResults();
  const focusTarget =
    modal === "search"
      ? "#archive-search"
      : modal === "person"
        ? ".astrhe-form input"
        : modal === "confirm"
          ? '[data-action="confirm-yes"]'
          : '[data-action="close-modal"]';
  requestAnimationFrame(() => {
    if (backdrop.isConnected && !modalClosing)
      document.querySelector<HTMLElement>(focusTarget)?.focus();
  });
  $("#modal-root")
    .querySelector(".modal-backdrop")
    ?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeModal();
    });
}
function renderResults() {
  const query = searchQuery.trim().toLowerCase();
  const results = records
    .map((r, i) => ({ r, i }))
    .filter(
      ({ r }) =>
        r.kind !== "empty" &&
        (filter === "全部档案" || r.category === filter) &&
        r.searchText.includes(query),
    );
  $("#search-results").innerHTML = results.length
    ? results
        .map(
          ({ r, i }) =>
            `<button class="result-row" data-result="${i}"><span class="result-name"><b>${r.id}</b><span>${escapeHtml(r.title)}<small>${escapeHtml(r.en)}</small></span>${r.secret ? "<i>◆</i>" : ""}</span><span>${escapeHtml(r.department)}</span><span>${escapeHtml(r.clearance)} <i>↗</i></span></button>`,
        )
        .join("")
    : `<div class="empty-results"><span>∅</span><strong>没有匹配的档案</strong><p>尝试其他编号、内容、会话或 QQ 号，或切换分类。</p><button data-action="reset-search">重置检索 →</button></div>`;
  $("#result-count").textContent =
    `${String(results.length).padStart(2, "0")} RECORDS FOUND`;
}
function updateQualitySummary() {
  const summary = document.querySelector("#quality-summary");
  if (!summary) return;
  if (!scene) {
    summary.textContent = "3D 已关闭 · 三维模型与渲染资源已释放";
    return;
  }
  const canvas = scene.renderer.domElement;
  const metrics = JSON.parse(
    canvas.parentElement?.dataset.renderQuality ?? "{}",
  );
  summary.textContent = `${superPerformanceEnabled() ? "超级性能模式已启用 · 画质设置暂被覆盖，关闭后恢复 · " : ""}实际渲染 ${canvas.width} × ${canvas.height} · ${effectiveRenderQuality().antialias === "smaa" ? "SMAA" : "原始抗锯齿"} · 纹理 ${metrics.anisotropy ?? 1}×${metrics.limited ? " · 已达到缓冲上限" : ""}`;
}
function motionPreferenceNoteMarkup() {
  const preset = prefs.motionPreset;
  const allEnabled = Object.values(prefs.motion).every(Boolean);
  return `<div id="motion-preference-note" class="motion-preference-note"><p>${motionSummary(prefs.motion)}</p><span>预设：${preset === "full" ? "完整动画" : preset === "reduced" ? "减少动画" : "自定义"} · 仅本次打开有效</span>${allEnabled ? "" : '<button data-action="enable-motion">启用完整动画并重播 ↻</button>'}</div>`;
}
function settingsMarkup() {
  return `<h2>SYSTEM SETTINGS<small>终端偏好设置</small></h2><p class="settings-intro">ADMINISTRATOR <span>·</span> SESSION AUTHORIZED</p><div class="settings-list">${themeSettingsMarkup(prefs.colorTheme === "dark")}<label><div><strong>SUPER PERFORMANCE</strong><span>降低三维画质和渲染分辨率，保留完整动效；关闭后恢复原画质</span></div><input type="checkbox" data-pref="superPerformance" ${prefs.superPerformance ? "checked" : ""}/><i class="toggle"></i></label></div>${motionPreferenceNoteMarkup()}${motionSettingsMarkup(prefs.motion, prefs.motionPreset)}${qualityMarkup(prefs.rendering)}<div class="settings-shortcuts"><span>KEYBOARD CONTROLS</span><p><kbd>←</kbd><kbd>→</kbd> 切列 <kbd>↑</kbd><kbd>↓</kbd> 选档 <kbd>ENTER</kbd> 读取 <kbd>/</kbd> 检索 <kbd>ESC</kbd> 返回</p></div><div class="settings-bottom"><button data-action="restart">REINITIALIZE SYSTEM <span>↻</span></button></div><div class="modal-bottom"><span>SOUL OS / ${escapeHtml(overview?.version ?? "")} · 使用 MiSans 字体（小米） <a href="${assetUrl("fonts/MiSans-license.pdf")}" download="MiSans-license.pdf">字体许可</a> · 界面基于 RhineLabUI（MIT）</span><span>POWERED BY ASTRHE</span></div>`;
}

document.addEventListener("input", (e) => {
  const slider = e.target as HTMLInputElement;
  if (slider.dataset.quality) {
    const output = document.querySelector<HTMLOutputElement>(
      `[data-quality-output="${slider.dataset.quality}"]`,
    );
    if (output) output.value = `${slider.value}%`;
  }
  if ((e.target as HTMLElement).id === "archive-search") {
    searchQuery = (e.target as HTMLInputElement).value;
    renderResults();
  }
});
document.addEventListener("change", (e) => {
  const el = e.target as HTMLInputElement;
  if (el.id === "quality-preset" && Object.hasOwn(qualityPresets, el.value)) {
    prefs.rendering = { ...qualityPresets[el.value as QualityPreset] };
    savePrefs();
  } else if (el.dataset.quality) {
    const key = el.dataset.quality as keyof RenderQuality;
    prefs.rendering = normalizeQuality({
      ...prefs.rendering,
      [key]: key === "antialias" ? el.value : Number(el.value),
    });
    savePrefs();
  }
  if (el.dataset.pref) {
    const key = el.dataset.pref;
    if (key === "quality" || key === "superPerformance") prefs[key] = el.checked;
    savePrefs();
  }
  if (el.dataset.motion) {
    const key = el.dataset.motion as MotionKey;
    prefs.motion[key] = el.checked;
    prefs.motionPreset = motionPresetFor(prefs.motion);
    savePrefs();
    const motionRoot = $("#motion-settings");
    const advancedOpen =
      motionRoot.querySelector<HTMLDetailsElement>(".motion-advanced")?.open ??
      false;
    const settingsPanel = motionRoot.closest<HTMLElement>(".settings-modal");
    const scrollTop = settingsPanel?.scrollTop ?? 0;
    motionRoot.outerHTML = motionSettingsMarkup(
      prefs.motion,
      prefs.motionPreset,
    );
    $("#motion-preference-note").outerHTML = motionPreferenceNoteMarkup();
    $("#motion-settings").querySelector<HTMLDetailsElement>(
      ".motion-advanced",
    )!.open = advancedOpen;
    requestAnimationFrame(() => {
      if (settingsPanel) settingsPanel.scrollTop = scrollTop;
      document
        .querySelector<HTMLInputElement>(`[data-motion="${key}"]`)
        ?.focus({ preventScroll: true });
    });
    notify(
      key === "boot"
        ? "开场设置将在下次重播时生效"
        : el.checked
          ? "已启用此动画"
          : "已关闭此动画",
    );
  }
});
document.addEventListener("click", (e) => {
  const themeButton = (e.target as Element).closest<HTMLElement>(
    "[data-color-theme]",
  );
  if (themeButton) {
    prefs.colorTheme =
      themeButton.dataset.colorTheme === "dark" ? "dark" : "light";
    savePrefs();
    return;
  }
  if (!started) return;
  if (modalClosing) return;
  const el = (e.target as Element).closest<HTMLElement>("button");
  if (!el) return;
  if (el.dataset.action === "motion-preset") {
    const preset = el.dataset.preset;
    if (preset !== "full" && preset !== "reduced") return;
    prefs.motionPreset = preset;
    prefs.motion = preset === "full" ? fullMotion() : reducedMotion();
    savePrefs();
    renderModal();
    requestAnimationFrame(() =>
      document
        .querySelector<HTMLButtonElement>(
          `[data-action="motion-preset"][data-preset="${prefs.motionPreset}"]`,
        )
        ?.focus({ preventScroll: true }),
    );
    return;
  }
  if (el.dataset.select) {
    select(Number(el.dataset.select));
    return;
  }
  if (el.dataset.run) {
    void showRun(Number(el.dataset.run));
    return;
  }
  if (el.dataset.result) {
    const index = Number(el.dataset.result);
    closeModal(() => {
      select(index);
      openFile();
    });
    return;
  }
  if (el.dataset.filter) {
    filter = el.dataset.filter;
    document
      .querySelectorAll("[data-filter]")
      .forEach((b) =>
        b.classList.toggle(
          "active",
          (b as HTMLElement).dataset.filter === filter,
        ),
      );
    renderResults();
    return;
  }
  if (el.dataset.tab) {
    setTab(el.dataset.tab);
    return;
  }
  const action = el.dataset.action;
  if (action === "skip") skipOpening();
  if (action === "prev") stepFile(-1);
  if (action === "next") stepFile(1);
  if (action === "column-prev") stepColumn(-1);
  if (action === "column-next") stepColumn(1);
  if (action === "open") openFile();
  if (action === "model-viewer" && mode === "detail" && scene) {
    const activeScene = scene;
    // Safari does not always focus a button when it is tapped. Capture the
    // actual opener so closing the modal reliably restores the right control.
    el.focus({ preventScroll: true });
    viewer ??= new ModelViewer($("#stage"), () => {});
    viewer.setSuperPerformance(superPerformanceEnabled());
    viewer.setQuality(effectiveRenderQuality());
    viewer.setMotion(prefs.motion);
    scene.finishDecryption();
    viewer.open(
      records[selected].id,
      records[selected].title,
      () => activeScene.createAssemblyModel(),
      !motionActive("viewerNavigation"),
    );
  }
  if (action === "back") {
    setMode("archive");
  }
  if (action === "search" || action === "runs" || action === "settings") {
    el.focus({ preventScroll: true });
    if (action === "runs") runDetailHtml = null;
    openModal(action);
  }
  if (action === "close-modal") closeModal();
  if (action) handleAstrheAction(action, el);
  if (action === "reset-search") {
    modal = "search";
    searchQuery = "";
    filter = "全部档案";
    renderModal();
  }
  if (action === "replay" || action === "restart") {
    replayBoot();
  }
  if (action === "enable-motion") {
    prefs.motion = fullMotion();
    prefs.motionPreset = "full";
    savePrefs();
    replayBoot();
  }

});
document.addEventListener("keydown", (e) => {
  if (!started) return;
  if (viewer?.isOpen) return;
  if (modalClosing) {
    e.preventDefault();
    return;
  }
  const typing = e.target instanceof HTMLInputElement;
  if (e.key === "Escape") {
    if (modal) closeModal();
    else if (mode === "detail") setMode("archive");
    else if (mode === "boot") skipOpening();
    return;
  }
  if (modal && e.key === "Tab") {
    const focusables = [
      ...$("#modal-root").querySelectorAll<HTMLElement>(
        'a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,[tabindex="0"]',
      ),
    ];
    const visible = focusables.filter(
      (el) =>
        el.tabIndex >= 0 &&
        !el.matches(":disabled") &&
        el.getClientRects().length > 0,
    );
    const first = visible[0],
      last = visible.at(-1);
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last?.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first?.focus();
    }
    return;
  }
  if (!ready && !typing && !modal && mode === "boot" && e.key === "Enter") {
    e.preventDefault();
    skipOpening();
    return;
  }
  if (typing || modal || !ready) return;
  if (
    (e.target as HTMLElement).dataset.tab &&
    ["ArrowLeft", "ArrowRight"].includes(e.key)
  ) {
    e.preventDefault();
    const tabs = ["overview", "notes", "history"];
    setTab(
      tabs[(tabs.indexOf(activeTab) + (e.key === "ArrowRight" ? 1 : 2)) % 3],
    );
    $<HTMLButtonElement>(`[data-tab="${activeTab}"]`).focus();
    return;
  }
  if (e.key === "/") {
    e.preventDefault();
    if (mode === "boot") setMode("archive");
    openModal("search");
  }
  if (e.key === "ArrowLeft" && mode !== "boot") {
    e.preventDefault();
    stepColumn(-1);
  }
  if (e.key === "ArrowRight" && mode !== "boot") {
    e.preventDefault();
    stepColumn(1);
  }
  if (["ArrowUp", "ArrowDown"].includes(e.key) && mode !== "boot") {
    e.preventDefault();
    stepFile(e.key === "ArrowUp" ? -1 : 1);
  }
  if (
    e.key === "Enter" &&
    (document.activeElement === document.body ||
      document.activeElement?.id === "detail-content" ||
      ["prev", "next", "column-prev", "column-next"].includes(
        (document.activeElement as HTMLElement)?.dataset.action ?? "",
      ) ||
      (document.activeElement as HTMLElement)?.dataset.select)
  ) {
    e.preventDefault();
    if (mode === "boot") setMode("archive");
    else if (mode === "archive") openFile();
  }
});

const ease = (t: number) => {
  t = Math.max(0, Math.min(1, t));
  return t * t * (3 - 2 * t);
};
function bootFrame(t: number) {
  const motion = bootSequence.update(t);
  let step: string = motion.step;
  if (t >= 22) {
    step = "array";
  }
  if (t >= 25.68) {
    step = "select";
  }
  if (t >= 28.3) {
    step = "inspect";
  }
  if (step !== lastStep) {
    $("#stage").dataset.boot = step;
    lastStep = step;
  }
  $(".file-title").firstChild!.textContent =
    step === "array"
      ? "SELECTING FILES...".slice(0, Math.max(0, Math.floor((t - 21.94) * 18)))
      : "FILE NUMBER: ";
  $("#stage").style.setProperty(
    "--entry-opacity",
    String(ease((t - 21.9) / 0.13)),
  );
  $(".callout-rule").style.transform = `scaleX(${ease((t - 22.08) / 0.9)})`;
  const reveal = ease((t - 22) / 0.4),
    lift = ease((t - 26) / 1.8),
    zoom = 0.55 * ease((t - 27.3) / 1.65) + 0.45 * ease((t - 29.0) / 5.0);
  if (t >= 35) {
    setMode("detail");
    return undefined;
  }
  return { reveal, lift, zoom, time: t };
}

const inspectionOverlay = new InspectionOverlay();
const documentDecryption = new DocumentDecryption();
// A newly opened archive can introduce another font shard. Re-measure its
// redaction lines after font swap while retaining the current reveal progress.
document.fonts.addEventListener("loadingdone", () =>
  documentDecryption.refresh(),
);

let lastTime = 0,
  frameCount = 0,
  frameStart = performance.now(),
  fps = 0;
function frame(ms: number) {
  if (document.hidden) {
    requestAnimationFrame(frame);
    return;
  }
  const time = ms / 1000;
  const theme = scene?.themeAmount ?? (prefs.colorTheme === "dark" ? 1 : 0);
  paintTheme(theme);
  viewer?.setTheme(theme);
  let cinema: ReturnType<typeof bootFrame>;
  if (mode === "boot" && started) {
    let t = frozenTime ?? time - bootStart;
    const holding = !ready && frozenTime === null && t >= BOOT_HOLD;
    if (holding) {
      bootStart = time - BOOT_HOLD;
      t = BOOT_HOLD;
    }
    showSync(holding);
    cinema = bootFrame(t);
  }
  // The calibrated 2D opening fully covers the scene until array entry.
  if (!viewer?.isOpen && (!cinema || cinema.time >= 21.9))
    scene?.update(time, cinema);
  viewer?.update(time);
  if (scene && mode === "detail") {
    documentDecryption.update(
      time,
      scene.decryptionFrame,
      !motionActive("documentReveal"),
    );
    $("#detail-content").style.opacity = String(scene.detailVisibility);
    $("#detail-content").style.translate =
      `0 ${(1 - scene.detailVisibility) * 18}px`;
    $("#detail-content").inert = scene.detailVisibility < 0.1;
    if (
      pendingDetailFocus &&
      scene.detailVisibility >= 0.1 &&
      !modal &&
      !viewer?.isOpen
    ) {
      $("#detail-content").focus({ preventScroll: true });
      pendingDetailFocus = false;
    }
  }
  $("#stage").style.setProperty(
    "--detail-shade",
    String(mode === "boot" ? 0 : (scene?.detailVisibility ?? 0)),
  );
  const currentScene = scene;
  if (currentScene)
    inspectionOverlay.render(
      currentScene.decryptionFrame,
      (x, y) => currentScene.projectCard(x, y),
      Boolean(cinema),
      motionActive("modelDecryption"),
    );
  if (Math.floor(time) !== lastTime) {
    lastTime = Math.floor(time);
    updateFooterClock(new Date(), motionActive("rollingNumbers"));
  }
  frameCount++;
  if (ms - frameStart > 1000) {
    fps = (frameCount * 1000) / (ms - frameStart);
    frameStart = ms;
    frameCount = 0;
    $("#three-scene").dataset.fps = String(Math.round(fps));
    $("#three-scene").dataset.renderStats = JSON.stringify(
      scene?.getStats() ?? { loaded: false, drawCalls: 0, triangles: 0 },
    );
  }
  requestAnimationFrame(frame);
}
function bindScene(scene: ArchiveScene, cell?: { lane: number; row: number }) {
  scene.select(selected, cell ? { cell } : undefined);
  scene.onSelect = (i, cell) => {
    if (mode !== "archive" || modal || viewer?.isOpen) return;
    select(i, cell ? { cell } : undefined);
  };
  scene.onNavigate = (axis, direction) => {
    if (mode !== "archive" || modal || viewer?.isOpen) return;
    if (axis === "lane") stepColumn(direction);
    else stepFile(direction);
  };
  scene.onHover = (i) => {
    const label = $("#hover-label");
    if (i === null) {
      label.hidden = true;
      hoverCode.finish();
      hoverTitle.finish();
      return;
    }
    const animated = motionActive("rollingText") && mode === "archive";
    const numbersAnimated =
      motionActive("rollingNumbers") && mode === "archive";
    $("#hover-prefix").textContent = records[i].prefix;
    hoverCode.update({
      value: records[i].code,
      animated: !label.hidden && numbersAnimated,
    });
    hoverTitle.update({
      text: records[i].title,
      animated: !label.hidden && animated,
    });
    label.hidden = false;
    // Prepare the first visible value so the next hover can animate immediately.
    hoverCode.update({ animated: numbersAnimated });
    hoverTitle.update({ animated });
  };
}
// 开场「START PROCESSING...」三个点出全的那一帧（原片第 476 帧）：资源未到齐时在这里等。
const BOOT_HOLD = 476 / 25 - 5;
// 加载页只等开场要用的三档字重；细体与模型在开场期间后台下载（等待点显示它们的进度）。
const OPENING_WEIGHTS = [400, 600, 700] as const;
const BACKGROUND_ASSETS = [...MODEL_PATHS, FONT_PATHS[300]];
let skipRequested = false;
let syncVisible = false;

function showSync(visible: boolean) {
  if (visible === syncVisible && !visible) return;
  syncVisible = visible;
  const sync = $("#boot-sync");
  sync.hidden = !visible;
  if (!visible) return;
  const value = Math.round(downloadProgress(BACKGROUND_ASSETS) * 100);
  sync.style.setProperty("--sync", String(value / 100));
  $("#boot-sync-value").textContent = `${String(value).padStart(2, "0")}%`;
}

/** 资源没到齐时按下跳过：先跳到等待点，到齐后直接进入阵列。 */
function skipOpening() {
  if (ready) {
    setMode("archive");
    return;
  }
  skipRequested = true;
  if (mode === "boot" && frozenTime === null)
    bootStart = Math.min(bootStart, performance.now() / 1000 - BOOT_HOLD);
}

function showFatal(message = "三维档案资源未能载入。请确认浏览器已启用硬件加速，然后在 AstrBot 面板里重新打开本页。") {
  const error = document.createElement("div");
  error.className = "loading";
  // 沙盒里重新加载会带着已过期的资源令牌，所以提示从面板重新打开，而不是原版的刷新按钮
  error.innerHTML = `<div class="error-state"><strong>CONNECTION INTERRUPTED</strong><p>${escapeHtml(message)}</p></div>`;
  loading.remove();
  $("#viewport").append(error);
}

/** 经 Bridge 读取 AstrHe 总览与运行记录，整理成五列档案。 */
async function loadArchive() {
  const [data] = await Promise.all([
    apiGet<Overview>("overview"),
    loadRuns().catch((error) => {
      console.warn("运行记录读取失败", error);
      return [];
    }),
  ]);
  overview = data;
  configureFormat({
    timezone: data.timezone,
    persons: (data.persons ?? []).map((p) => ({
      qq: String(p.qq),
      aliases: parseJson<string[]>(p.aliases_json, []),
    })),
  });
  configureSecrecy(data.admins ?? []);
  setRecords(buildRecords(data));
  columnMemory = archiveColumns.map((_, lane) => columnFiles(lane)[0]);
  selected = 0;
  updateSelection();
}

/** 档案操作后原位更新：不重排档案，三维阵列的位置不会跳。 */
function refreshCurrent(patch: Record<string, unknown>, clearance?: string) {
  const r = records[selected];
  Object.assign(r.raw, patch);
  if (clearance) r.clearance = clearance;
  updateSelection();
  if (mode === "detail") renderDetail();
}

function askConfirm(pending: PendingConfirm) {
  pendingConfirm = pending;
  openModal("confirm");
}

async function showRun(runId: number) {
  runDetailHtml = '<p class="astrhe-run-empty">正在读取运行记录…</p>';
  const panel = document.querySelector("#run-panel");
  if (panel) panel.innerHTML = runPanelMarkup();
  try {
    runDetailHtml = await runDetailMarkup(runId);
  } catch (error) {
    runDetailHtml = `<p class="astrhe-run-empty">读取失败：${escapeHtml(error instanceof Error ? error.message : String(error))}</p>`;
  }
  const target = document.querySelector("#run-panel");
  if (target) target.innerHTML = runPanelMarkup();
}

function handleAstrheAction(action: string, el: HTMLElement) {
  const r = records[selected];
  if (action === "decrypt") {
    const box = el.closest(".astrhe-decryptable");
    box?.classList.add("astrhe-revealed");
    el.setAttribute("aria-pressed", "true");
    if (box?.id === "detail-content") reveal(r.id);
    notify("已解密保密内容（仅本次打开有效）");
  } else if (action === "runs-back") {
    runDetailHtml = null;
    const panel = document.querySelector("#run-panel");
    if (panel) panel.innerHTML = runPanelMarkup();
  } else if (action === "export" && currentView) {
    downloadText(`AstrHe-${r.id}.txt`, currentView.exportText(isRevealed(r.id)));
    notify("档案文本已导出");
  } else if (action === "open-run") {
    runDetailHtml = null;
    openModal("runs");
    void showRun(Number(r.raw.run_id));
  } else if (action === "edit-person") {
    editingPerson = r.raw;
    openModal("person");
  } else if (action === "delete-todo" || action === "delete-promise") {
    const todo = action === "delete-todo";
    askConfirm({
      title: todo ? "删除待办" : "删除承诺",
      message: `删除 ${r.id}「${r.title}」？删除后进入回收站，30 天内可以恢复。`,
      confirm: todo ? "− DELETE TODO" : "− DELETE PROMISE",
      run: async () => {
        await apiPost(todo ? "todo/delete" : "promise/delete", todo ? { todo_id: r.key } : { promise_id: r.key });
        refreshCurrent({ status: "deleted" }, "DELETED");
        notify(todo ? "待办已移入回收站" : "承诺已移入回收站");
      },
    });
  } else if (action === "cancel-alarm") {
    askConfirm({
      title: "取消闹钟",
      message: `取消 ${r.id}「${r.title}」？AstrBot 里对应的定时任务会一起删除，到点不会再执行。`,
      confirm: "× CANCEL ALARM",
      run: async () => {
        await apiPost("alarm/cancel", { alarm_id: r.key });
        refreshCurrent({ status: "cancelled" }, "CANCELLED");
        notify("闹钟已取消");
      },
    });
  } else if (action === "confirm-yes" && pendingConfirm) {
    const pending = pendingConfirm;
    const button = el as HTMLButtonElement;
    button.disabled = true;
    pending
      .run()
      .then(() => closeModal())
      .catch((error) => {
        button.disabled = false;
        const box = document.querySelector<HTMLElement>(".astrhe-form-error");
        if (box) {
          box.hidden = false;
          box.textContent = `操作失败：${error instanceof Error ? error.message : error}`;
        }
      });
  }
}

document.addEventListener("submit", (e) => {
  const form = e.target as HTMLFormElement;
  if (!form.matches(".astrhe-form")) return;
  e.preventDefault();
  const parsed = readPersonForm(form);
  const error = form.querySelector<HTMLElement>(".astrhe-form-error")!;
  if ("error" in parsed) {
    error.hidden = false;
    error.textContent = parsed.error ?? "";
    return;
  }
  const { payload } = parsed;
  apiPost("person/save", payload)
    .then(() => {
      const r = records[selected];
      r.title = payload.aliases[0] || payload.qq;
      r.department = payload.aliases.join("、") || "—";
      refreshCurrent({
        aliases_json: payload.aliases,
        relation_text: payload.relation_text,
        anniversaries_json: payload.anniversaries,
      });
      closeModal();
      notify("关系层已保存");
    })
    .catch((err) => {
      error.hidden = false;
      error.textContent = `保存失败：${err instanceof Error ? err.message : err}`;
    });
});

async function start() {
  // 插件页面的资源令牌 60 秒过期，且每次打开都要重新下载：所有资源在第一时间一起发起请求。
  // 开场只等它要用的三档字重；模型和细体字（低优先级）在开场播放期间下载。
  const models = MODEL_PATHS.map((path) => preloadAsset(path, "low"));
  models.forEach((model) =>
    model.catch(() => {
      /* 由 scene.load / 查看器负责报错或重试 */
    }),
  );
  const openingFonts = Promise.all(OPENING_WEIGHTS.map((weight) => loadFont(weight)));
  const lightFont = loadFont(300, "low");
  // 开场被关闭或在调试回放时，照原版先等资源全部到齐。
  const streaming =
    motionActive("boot") &&
    !reviewParams.has("time") &&
    !reviewParams.has("scene");
  const archive = loadArchive();
  archive.catch(() => {
    /* 下面 await 时统一报错 */
  });
  trackLoading(
    streaming
      ? OPENING_WEIGHTS.map((weight) => FONT_PATHS[weight])
      : [...Object.values(FONT_PATHS), ...MODEL_PATHS],
  );
  try {
    try {
      await archive;
    } catch (error) {
      console.error(error);
      showFatal(`无法读取 AstrHe 档案：${error instanceof Error ? error.message : error}`);
      return;
    }
    scene = new ArchiveScene($("#three-scene"));
    scene.setTheme(prefs.colorTheme === "dark", true);
    const resources = Promise.all([scene.load(), openingFonts, lightFont]);
    if (streaming) {
      await openingFonts;
      completeStartup();
    }
    await resources;
    bindScene(scene);
    savePrefs();
    ready = true;
    showSync(false);
    if (mode === "boot") select(0);
    if (!started) completeStartup();
    else if (skipRequested && mode === "boot") setMode("archive");
  } catch (error) {
    console.error(error);
    showFatal();
  }
}
/** 加载页进度：按已收到的字节显示，最多到 99%；数据与解析都就绪、真正进入时才到 100%。 */
function trackLoading(paths: readonly string[]) {
  const tick = () => {
    if (started || !loading.isConnected) return;
    showLoadingProgress(Math.floor(Math.min(downloadProgress(paths), 0.99) * 100));
    requestAnimationFrame(tick);
  };
  tick();
}
function showLoadingProgress(value: number) {
  loading.style.setProperty("--progress", String(value / 100));
  $("#loading-value").textContent = `${String(value).padStart(2, "0")}%`;
}
function completeStartup() {
  if (started) return;
  started = true;
  showLoadingProgress(100);
  const fade = motionActive("boot") ? 600 : 0;
  bootStart =
    performance.now() / 1000 -
    (reviewParams.has("time") ? Number(reviewParams.get("time")) : 1.76);
  if (!reviewParams.has("time")) bootStart += fade / 1000;
  setMode("boot");
  if (
    reviewParams.get("scene") === "archive" ||
    (!motionActive("boot") && !reviewParams.has("time"))
  )
    setMode("archive");
  if (reviewParams.get("scene") === "detail") setMode("detail");
  $("#stage").inert = false;
  $(".mobile-entry").inert = false;
  loading.classList.add("loaded");
  loading.inert = true;
  setTimeout(() => loading.remove(), fade);
  requestAnimationFrame(frame);
}
void start();
// Deterministic review controls: the running application, never a video surrogate.
Object.assign(window, {
  rhine: {
    // The review button supplies a real user activation. Preferences stay local to this preview.
    seek: (t: number) => {
      setMode("boot");
      bootStart = performance.now() / 1000 - t;
      lastStep = "";
    },
    archive: () => setMode("archive"),
    detail: () => openFile(),
    select: (i: number) => select(i),
    stats: () => ({
      ...scene?.getStats(),
      fps: Math.round(fps),
      mode,
      ready,
      startup: started ? "started" : "loading",
      motion: { reduced: motionIsReduced(), preset: prefs.motionPreset },
      bootTime:
        mode === "boot"
          ? started
            ? (frozenTime ?? performance.now() / 1000 - bootStart) + 5
            : 6.76
          : null,
      selected: records[selected]?.id,
    }),
  },
});
