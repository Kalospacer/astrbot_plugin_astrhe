/** 应用外壳：MD3 规范布局（顶部应用栏 + 底部导航栏 / 导航轨道 + 列表与详情两个窗格）。 */
import { archiveColumns } from "../data";

/** 每列档案的图标：[未选中, 选中] */
const ICONS: Record<string, [string, string]> = {
  规划书: ["description--outlined", "description"],
  待办: ["checklist--outlined", "checklist"],
  闹钟: ["alarm--outlined", "alarm"],
  承诺: ["handshake--outlined", "handshake"],
  关系本: ["people--outlined", "people"],
};

export const icon = (name: string, slot = "") =>
  `<mdui-icon-${name}${slot ? ` slot="${slot}"` : ""}></mdui-icon-${name}>`;

export const categoryIcon = (category: string, active = false) => icon(ICONS[category][active ? 1 : 0]);

function navItems(tag: "navigation-bar-item" | "navigation-rail-item") {
  return archiveColumns
    .map((category) => {
      const [normal, active] = ICONS[category];
      return `<mdui-${tag} value="${category}">${icon(normal, "icon")}${icon(active, "active-icon")}${category}</mdui-${tag}>`;
    })
    .join("");
}

export const iconButton = (action: string, label: string, glyph: string) =>
  `<mdui-button-icon data-action="${action}" aria-label="${label}" title="${label}">${icon(glyph)}</mdui-button-icon>`;

export function shellMarkup() {
  return `
  <mdui-layout id="app" full-height>
    <mdui-navigation-rail id="nav-rail" order="1" value="${archiveColumns[0]}" divider>${navItems("navigation-rail-item")}</mdui-navigation-rail>
    <mdui-top-app-bar id="app-bar" order="2" variant="small">
      <span id="back-slot">${iconButton("back", "返回", "arrow-back--outlined")}</span>
      <mdui-top-app-bar-title id="app-title">AstrHe</mdui-top-app-bar-title>
      ${iconButton("search", "检索档案", "search--outlined")}
      ${iconButton("runs", "夜间运行记录 NIGHT RUNS", "bedtime--outlined")}
      ${iconButton("about", "关于", "info--outlined")}
    </mdui-top-app-bar>
    <mdui-navigation-bar id="nav-bar" order="3" label-visibility="labeled" value="${archiveColumns[0]}">${navItems("navigation-bar-item")}</mdui-navigation-bar>
    <mdui-layout-main id="main">
      <mdui-linear-progress id="loading" aria-label="正在读取档案"></mdui-linear-progress>
      <div id="panes" class="panes" data-pane="list">
        <section id="pane-list" class="pane pane-list" aria-label="档案列表"><div id="list-scroll" class="scroll"></div></section>
        <section id="pane-detail" class="pane pane-detail" aria-label="档案详情"><div id="detail-scroll" class="scroll"></div></section>
      </div>
    </mdui-layout-main>
  </mdui-layout>
  <div id="search-root"></div>
  <div id="dialog-root"></div>`;
}
