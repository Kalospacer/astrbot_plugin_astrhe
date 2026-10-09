/**
 * MD3 窗口尺寸等级，按 iframe 视口宽度划分：
 * Compact <600px（手机竖屏），Medium 600–839px，Expanded ≥840px。
 * 这里只决定 NORMAL 自己的布局；用哪套前端在打开页面那一刻就定了，之后不会切换。
 */
export type Size = "compact" | "medium" | "expanded";

const medium = matchMedia("(min-width: 600px)");
const expanded = matchMedia("(min-width: 840px)");

export const currentSize = (): Size => (expanded.matches ? "expanded" : medium.matches ? "medium" : "compact");

export function watchSize(handler: (size: Size) => void) {
  const notify = () => handler(currentSize());
  medium.addEventListener("change", notify);
  expanded.addEventListener("change", notify);
}
