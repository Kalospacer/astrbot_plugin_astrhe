/**
 * NORMAL：Material Design 3 普通版前端（mdui）。
 * 不用三维和字体，系统字体即可；功能与 SOUL OS 对齐。由 launcher.ts 动态导入。
 */
import "./components";
import { loadLocale } from "mdui/functions/loadLocale.js";
import { setLocale } from "mdui/functions/setLocale.js";
import * as zhCn from "mdui/locales/zh-cn.js";
import { handleClick, handleKey, handleSearchInput } from "./actions";
import { currentSize, watchSize } from "./layout";
import { mountSearch } from "./search";
import { shellMarkup } from "./shell";
import { injectStyles } from "./styles";
import { state } from "./store";
import { initTheme } from "./theme";
import { applyChrome, boot } from "./views";

export function startNormal() {
  injectStyles();
  // mdui 自带的少量提示文字改成中文（语言包是静态引入的，不会在运行时再去请求）
  loadLocale(async () => zhCn);
  void setLocale("zh-cn");
  initTheme();

  const root = document.createElement("div");
  root.id = "normal-root";
  root.innerHTML = shellMarkup();
  document.body.append(root);
  document.title = "AstrHe 档案终端";
  state.size = currentSize();
  mountSearch();
  applyChrome();

  root.addEventListener("click", handleClick);
  root.addEventListener("input", handleSearchInput);
  document.addEventListener("keydown", handleKey);
  watchSize((size) => {
    state.size = size;
    applyChrome();
  });
  void boot();
}
