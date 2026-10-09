/**
 * NORMAL 的样式：mdui 的 MD3 样式表加上自己的几份 CSS，都用 ?inline 取成字符串后注入一个 <style>。
 * 不能让构建工具把它们拆成独立 CSS 文件：动态加载的 CSS 是运行时拼出来的 <link>，
 * 地址没有 AstrBot 的 asset_token，会被拒绝。只有选中 NORMAL 时这个模块才会被加载。
 */
import mdui from "mdui/mdui.css?inline";
import base from "./css/base.css?inline";
import layout from "./css/layout.css?inline";
import list from "./css/list.css?inline";
import detail from "./css/detail.css?inline";
import search from "./css/search.css?inline";
import dialog from "./css/dialog.css?inline";
import secret from "./css/secret.css?inline";
import motion from "./css/motion.css?inline";

export function injectStyles() {
  const style = document.createElement("style");
  style.id = "normal-styles";
  style.textContent = [mdui, base, layout, list, detail, search, dialog, secret, motion].join("\n");
  document.head.append(style);
}
