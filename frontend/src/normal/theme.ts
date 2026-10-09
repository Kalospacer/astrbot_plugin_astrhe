/**
 * MD3 动态配色：种子色为绿色（Material Green 500）；亮暗跟随 AstrBot 面板，面板切换时实时跟着变。
 * 页面加载时 AstrBot 已经把 data-theme 写在 <html> 上，之后的切换由桥接对象推送 isDark。
 *
 * 配色用 MD3 标准的 Tonal Spot 方案生成（主色色度 36）。mdui 自带的 setColorScheme 用的是旧版
 * 算法，主色色度至少 48，绿色会很扎眼；这里按 mdui 同样的 CSS 变量格式自己写入。
 */
import {
  argbFromHex,
  blueFromArgb,
  type DynamicColor,
  greenFromArgb,
  Hct,
  MaterialDynamicColors as C,
  redFromArgb,
  SchemeTonalSpot,
} from "@material/material-color-utilities";
import { setTheme } from "mdui/functions/setTheme.js";
import { onPanelContext } from "../astrhe/bridge";

const SEED_COLOR = "#4caf50";
const SCHEME_CLASS = "astrhe-color-scheme";

/** mdui 用到的颜色变量（--mdui-color-*）与 MD3 颜色角色的对应关系 */
const ROLES: Record<string, DynamicColor> = {
  primary: C.primary,
  "on-primary": C.onPrimary,
  "primary-container": C.primaryContainer,
  "on-primary-container": C.onPrimaryContainer,
  "inverse-primary": C.inversePrimary,
  secondary: C.secondary,
  "on-secondary": C.onSecondary,
  "secondary-container": C.secondaryContainer,
  "on-secondary-container": C.onSecondaryContainer,
  tertiary: C.tertiary,
  "on-tertiary": C.onTertiary,
  "tertiary-container": C.tertiaryContainer,
  "on-tertiary-container": C.onTertiaryContainer,
  error: C.error,
  "on-error": C.onError,
  "error-container": C.errorContainer,
  "on-error-container": C.onErrorContainer,
  background: C.background,
  "on-background": C.onBackground,
  surface: C.surface,
  "on-surface": C.onSurface,
  "surface-variant": C.surfaceVariant,
  "on-surface-variant": C.onSurfaceVariant,
  "surface-dim": C.surfaceDim,
  "surface-bright": C.surfaceBright,
  "surface-container-lowest": C.surfaceContainerLowest,
  "surface-container-low": C.surfaceContainerLow,
  "surface-container": C.surfaceContainer,
  "surface-container-high": C.surfaceContainerHigh,
  "surface-container-highest": C.surfaceContainerHighest,
  "surface-tint-color": C.surfaceTint,
  "inverse-surface": C.inverseSurface,
  "inverse-on-surface": C.inverseOnSurface,
  outline: C.outline,
  "outline-variant": C.outlineVariant,
  shadow: C.shadow,
  scrim: C.scrim,
};

const rgb = (argb: number) => `${redFromArgb(argb)}, ${greenFromArgb(argb)}, ${blueFromArgb(argb)}`;

/** 生成亮、暗两套变量并挂到 <html> 上（变量格式与 mdui 的 setColorScheme 相同）。 */
function installColorScheme(hex: string) {
  const source = Hct.fromInt(argbFromHex(hex));
  const schemes = { light: new SchemeTonalSpot(source, false, 0), dark: new SchemeTonalSpot(source, true, 0) };
  const vars = (theme: "light" | "dark") =>
    Object.entries(ROLES)
      .map(([token, role]) => `--mdui-color-${token}-${theme}: ${rgb(role.getArgb(schemes[theme]))};`)
      .join("");
  const use = (theme: "light" | "dark") =>
    Object.keys(ROLES)
      .map((token) => `--mdui-color-${token}: var(--mdui-color-${token}-${theme});`)
      .join("");
  const style = document.createElement("style");
  style.id = SCHEME_CLASS;
  style.textContent = `.${SCHEME_CLASS}{${vars("light")}${vars("dark")}${use("light")}color:rgb(var(--mdui-color-on-background));background-color:rgb(var(--mdui-color-background))}
.mdui-theme-dark.${SCHEME_CLASS},.mdui-theme-dark .${SCHEME_CLASS}{${use("dark")}}`;
  document.head.append(style);
  document.documentElement.classList.add(SCHEME_CLASS);
}

function apply(dark: boolean) {
  setTheme(dark ? "dark" : "light");
  // 浏览器地址栏 / 系统控件的明暗也一起跟着
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function initTheme() {
  installColorScheme(SEED_COLOR);
  apply(document.documentElement.getAttribute("data-theme") === "dark");
  onPanelContext((context) => {
    if (typeof context?.isDark === "boolean") apply(context.isDark);
  });
}
