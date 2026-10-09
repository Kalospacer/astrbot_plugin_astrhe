/**
 * 页面入口：按插件设置里的「横屏 / 竖屏使用的前端」，只加载一套前端。
 *
 * - 只看打开页面那一刻 iframe 的横竖屏（宽高相等算竖屏），选定后不再切换；
 * - 读不到设置（插件未启用、接口报错、超时）时用默认值：横屏 SOUL OS，竖屏 NORMAL；
 * - 两套前端都是被动态导入的模块。它们里面写死的 import 地址会被 AstrBot 补上令牌，
 *   所以这里不能用运行时拼出来的地址或 <link>（见 soul-styles.ts、normal/styles.ts）。
 */
import "./soul-styles";
import { apiGet } from "./astrhe/bridge";

type Frontend = "SOUL OS" | "NORMAL";
const CHOICES: readonly string[] = ["SOUL OS", "NORMAL"];
const DEFAULTS: Record<"landscape" | "portrait", Frontend> = { landscape: "SOUL OS", portrait: "NORMAL" };
/** 读设置不能让页面等太久：超时就用默认值 */
const SETTING_TIMEOUT_MS = 3000;

async function chooseFrontend(): Promise<Frontend> {
  const orientation = matchMedia("(orientation: portrait)").matches ? "portrait" : "landscape";
  try {
    const setting = await apiGet<Record<string, string>>("frontend", undefined, SETTING_TIMEOUT_MS);
    const value = setting?.[orientation];
    return CHOICES.includes(value) ? (value as Frontend) : DEFAULTS[orientation];
  } catch {
    return DEFAULTS[orientation];
  }
}

async function launch() {
  const frontend = await chooseFrontend();
  if (frontend === "NORMAL") {
    // SOUL OS 的全局样式（*、body、button 等）会污染 MD3 页面，选中 NORMAL 时先摘掉
    document.querySelectorAll('link[rel="stylesheet"], style[data-vite-dev-id]').forEach((node) => node.remove());
    document.querySelector("#viewport")?.remove();
    const { startNormal } = await import("./normal/app");
    startNormal();
  } else {
    await import("./main");
  }
  // 选定的前端已经有了自己的底色，撤掉分流期间的中性底
  document.documentElement.removeAttribute("data-launching");
}

launch().catch((error) => {
  console.error(error);
  document.documentElement.removeAttribute("data-launching");
  document.body.textContent = `档案终端加载失败：${error instanceof Error ? error.message : error}`;
});
