/**
 * MD3 动效：只用规范里的 emphasized / standard 曲线与时长。
 * - 档案列表 → 详情：container transform（支持 View Transitions API 时用它，否则退化成 fade through）
 * - 切换导航目的地：fade through
 * - 详情页签切换：shared axis X
 * 系统设置了「减少动态效果」时一律不播放，直接更新。
 */
const EMPHASIZED_DECELERATE = "cubic-bezier(0.05, 0.7, 0.1, 1)";
const EMPHASIZED_ACCELERATE = "cubic-bezier(0.3, 0, 0.8, 0.15)";

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const canViewTransition = () => "startViewTransition" in document && !reducedMotion();

const finish = (animation: Animation) => animation.finished.catch(() => undefined);

/** fade through：旧内容 90ms 淡出，新内容 210ms 淡入并从 92% 放大到 100%。 */
export async function fadeThrough(element: HTMLElement, update: () => void) {
  if (reducedMotion()) return update();
  await finish(element.animate({ opacity: [1, 0] }, { duration: 90, easing: "linear", fill: "forwards" }));
  update();
  await finish(
    element.animate(
      [
        { opacity: 0, transform: "scale(0.92)" },
        { opacity: 1, transform: "scale(1)" },
      ],
      { duration: 210, easing: EMPHASIZED_DECELERATE },
    ),
  );
  element.getAnimations().forEach((animation) => animation.cancel());
}

/** shared axis X：direction 为 1 表示向前（新内容从右侧滑入），-1 相反。 */
export async function sharedAxisX(element: HTMLElement, direction: 1 | -1, update: () => void) {
  if (reducedMotion()) return update();
  const shift = 30;
  await finish(
    element.animate(
      [
        { opacity: 1, transform: "translateX(0)" },
        { opacity: 0, transform: `translateX(${-direction * shift}px)` },
      ],
      { duration: 90, easing: EMPHASIZED_ACCELERATE, fill: "forwards" },
    ),
  );
  update();
  await finish(
    element.animate(
      [
        { opacity: 0, transform: `translateX(${direction * shift}px)` },
        { opacity: 1, transform: "translateX(0)" },
      ],
      { duration: 210, easing: EMPHASIZED_DECELERATE },
    ),
  );
  element.getAnimations().forEach((animation) => animation.cancel());
}

/**
 * container transform：from 是被点击的列表项，update 里完成界面切换，to 返回切换后的详情容器。
 * 不支持 View Transitions API 时退化为 fade through（对 fallback 元素）。
 */
export async function containerTransform(
  from: HTMLElement | null,
  update: () => void,
  to: () => HTMLElement | null,
  fallback: HTMLElement,
) {
  if (!from || !canViewTransition()) return fadeThrough(fallback, update);
  from.style.viewTransitionName = "container";
  const transition = document.startViewTransition(() => {
    from.style.viewTransitionName = "";
    update();
    const target = to();
    if (target) target.style.viewTransitionName = "container";
  });
  await transition.finished.catch(() => undefined);
  const target = to();
  if (target) target.style.viewTransitionName = "";
}

/** 搜索视图等浮层的进入 / 退出：emphasized decelerate 进，accelerate 出。 */
export function enter(element: HTMLElement, keyframes: Keyframe[], duration = 300) {
  if (reducedMotion()) return Promise.resolve();
  return finish(element.animate(keyframes, { duration, easing: EMPHASIZED_DECELERATE }));
}
export function leave(element: HTMLElement, keyframes: Keyframe[], duration = 200) {
  if (reducedMotion()) return Promise.resolve();
  return finish(element.animate(keyframes, { duration, easing: EMPHASIZED_ACCELERATE, fill: "forwards" }));
}
