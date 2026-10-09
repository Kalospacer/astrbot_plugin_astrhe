import { bootMotion, POWERED_TEXT } from "./boot-motion";
import { bootMarkContour, electronAt, electrons, MARK_STROKE } from "./brand";
import { themeAmount } from "./theme-ui";
import { BootLettering } from "./boot-lettering";

const ns = "http://www.w3.org/2000/svg";
// 开场标志描线的关键值，取自 boot-logo-tracks 的原版轨迹
const LOGO_CLOSED = 0.9725; // 描完后的线长（原版留一道缺口）
const LOGO_REST_START = 0.211; // 描完后线头停靠的位置
const LOGO_CUT_FRAME = 420; // 缺口开始绕轮廓移动的帧
const arc = (r: number, start: number, sweep: number, x = 960, y = 540) => {
  const point = (a: number) => `${x + Math.cos(a) * r},${y + Math.sin(a) * r}`;
  if (sweep >= Math.PI * 1.999)
    return `M${point(start)}A${r},${r} 0 1 1 ${point(start + Math.PI)}A${r},${r} 0 1 1 ${point(start + Math.PI * 2)}`;
  return `M${point(start)}A${r},${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${point(start + sweep)}`;
};

export class BootSequence {
  private nodes: Map<string, HTMLElement> = new Map();
  private contour: SVGPathElement;
  private letters: SVGTextElement;
  private nucleus: SVGGElement;
  private electronDots: SVGCircleElement[];
  private electronGaps: SVGCircleElement[];
  private brandLines: HTMLElement[];
  private scanPaths: SVGPathElement[];
  private orbitDots: SVGCircleElement[];
  private core: SVGCircleElement;
  private satellites: SVGCircleElement[];
  private caps: SVGCircleElement[];
  private companyInk: HTMLElement[];
  private poweredHTML: string;
  private accessLettering: BootLettering;
  private authLettering: BootLettering;
  constructor(private stage: HTMLElement) {
    [
      ".access-text",
      ".boot-logo",
      ".auth-status",
      "#auth-message",
      ".scan",
      ".scan > span",
      ".welcome",
      ".welcome-heading",
      ".welcome-panel",
      ".welcome-company",
      ".welcome-highlight",
      ".welcome-database",
      ".welcome-logo",
      ".brand",
      ".powered",
      "#boot-background",
      ".boot-background svg",
      ".boot-white",
    ].forEach((s) => this.nodes.set(s, stage.querySelector<HTMLElement>(s)!));
    const mark = stage.querySelector<SVGSVGElement>(".boot-logo svg")!;
    // 氦原子标志：两条轨道是一条连续轮廓（原版 ∞ 的画法），原子核与两颗电子
    // 沿用原版「+」「−」出场的缩放与飞出轨迹。
    this.contour = mark.querySelector<SVGPathElement>(".astrhe-orbits")!;
    this.contour.setAttribute("d", bootMarkContour);
    this.contour.setAttribute("pathLength", "1");
    this.nucleus = mark.querySelector<SVGGElement>(".astrhe-nucleus")!;
    this.electronDots = Array.from(mark.querySelectorAll<SVGCircleElement>(".astrhe-electron"));
    this.electronGaps = Array.from(mark.querySelectorAll<SVGCircleElement>(".astrhe-electron-gap"));
    this.letters = mark.querySelector("text")!;
    this.letters.setAttribute("text-anchor", "start");
    this.letters.setAttribute("x", "20");
    this.brandLines = Array.from(
      stage.querySelector(".brand")!.children,
    ) as HTMLElement[];
    this.scanPaths = Array.from(
      stage.querySelectorAll<SVGPathElement>(".scan path"),
    );
    this.orbitDots = Array.from(
      stage.querySelectorAll<SVGCircleElement>(".scan .orbit-dot"),
    );
    this.core = stage.querySelector(".scan .scan-core")!;
    this.core.setAttribute("cx", "959.5");
    this.core.setAttribute("cy", "539.5");
    this.satellites = Array.from({ length: 6 }, () => {
      const dot = document.createElementNS(ns, "circle");
      dot.classList.add("satellite-dot");
      dot.setAttribute("fill", "#080a08");
      dot.setAttribute("stroke", "none");
      // Draw beneath the core so its large flashes naturally cover the orbit.
      this.core.parentElement!.insertBefore(dot, this.core);
      return dot;
    });
    this.caps = ["#080a08", "#fff"].map((fill) => {
      const cap = document.createElementNS(ns, "circle");
      cap.setAttribute("fill", fill);
      cap.setAttribute("stroke", "none");
      this.core.parentElement!.appendChild(cap);
      return cap;
    });
    this.companyInk = Array.from(
      stage.querySelectorAll<HTMLElement>(".welcome-company strong"),
    );
    this.companyInk.forEach((el) => {
      const ink = document.createElement("span");
      ink.textContent = el.textContent;
      el.replaceChildren(ink);
    });
    this.poweredHTML = this.el(".powered").innerHTML;
    new BootLettering(this.brandLines[0], ["brand"]).setText("ASTR HE");
    // Bind after collecting the original ring paths. Phrase artwork also has
    // SVG paths, and must never be included in the scan's animated geometry.
    this.accessLettering = new BootLettering(this.el(".access-text"), ["access"]);
    this.authLettering = new BootLettering(this.el("#auth-message"), [
      "identity", "request", "processing", "processingGlitch",
    ]);
    for (const [selector, key, text] of [
      [".scan > span", "permission", "PERMISSION AUTHORIZED"],
      [".welcome-heading", "welcome", "WELCOME TO"],
      [".welcome-database", "database", "NIGHTLY DATABASE"],
    ] as const) new BootLettering(this.el(selector), [key]).setText(text);
    this.companyInk.forEach((el) =>
      new BootLettering(el.querySelector("span")!, ["company"]).setText("ASTRHE.SOUL."),
    );
  }
  private el(selector: string) {
    return this.nodes.get(selector)!;
  }
  private opacity(selector: string, value: number | boolean) {
    this.el(selector).style.opacity = String(Number(value));
  }
  update(time: number) {
    const s = bootMotion(time),
      t = s.t;
    this.stage.dataset.bootFrame = String(s.f);
    this.accessLettering.setText(s.access);
    this.opacity(".access-text", s.accessOpacity);
    this.opacity(".boot-logo", s.logoOpacity);
    this.el(".boot-logo").style.transform =
      `translate(${s.logo.offsetX}px, 1px)`;
    // 原版标志是留一道缺口的单线轮廓，描线停在 0.9725 圈；原子轨道要闭合，所以按比例描满整圈，
    // 后段「缺口绕轮廓移动」也随之闭合，改由两颗电子沿轨道绕行来呈现（见下方 orbit）。
    const length = Math.min(1, s.logo.length / LOGO_CLOSED);
    this.contour.style.strokeDasharray = length >= 0.999 ? "none" : `${length} ${1 - length}`;
    this.contour.style.strokeDashoffset = String(-s.logo.start);
    this.contour.setAttribute("stroke-width", String((s.logo.strokeWidth * MARK_STROKE) / 26));
    // Preserve the SVG text node once each revealed letter is in place. Replacing
    // it every frame invalidates glyph rasterization under the moving HUD.
    if (this.letters.textContent !== s.logoLetters)
      this.letters.textContent = s.logoLetters;
    const scale = s.logo.symbolScale;
    this.nucleus.style.opacity = scale > 0 ? "1" : "0";
    // 原子核在中心放大，借原版「+」到位后的 90° 旋转收尾；两个质子要转半圈才回到横排，所以角度加倍
    this.nucleus.setAttribute(
      "transform",
      `translate(155 72.5) rotate(${s.logo.plusAngle * 2}) scale(${scale}) translate(-155 -72.5)`,
    );
    // 两颗电子沿原版「+」「−」从中心飞出的进度飞到各自轨道
    const flight = [
      (155 - s.logo.plusX) / (155 - 72.6),
      (s.logo.minusX - 155) / (237.1 - 155),
    ];
    // 原版缺口绕轮廓移动的进度（整条轮廓 = 两圈轨道，所以 1 = 720°）换成电子沿轨道前进的角度
    const orbit = s.f >= LOGO_CUT_FRAME ? (s.logo.start - LOGO_REST_START) * 720 : 0;
    electrons.forEach((_, i) => {
      const p = Math.max(0, Math.min(1, flight[i]));
      const electron = electronAt(i, orbit);
      const x = String(155 + (electron.x - 155) * p);
      const y = String(72.5 + (electron.y - 72.5) * p);
      for (const [node, radius] of [[this.electronDots[i], 10], [this.electronGaps[i], 15]] as const) {
        node.setAttribute("cx", x);
        node.setAttribute("cy", y);
        node.setAttribute("r", String(radius * scale));
      }
    });
    this.opacity(".auth-status", s.authOpacity);
    this.authLettering.setText(s.auth);
    this.opacity(".brand", 1);
    this.el(".brand").style.transform = "none";
    this.brandLines.forEach((node, i) => {
      node.style.opacity = String(s.brand[i].opacity);
      node.style.transform = `translateX(${s.brand[i].x}px)`;
    });
    this.opacity(".powered", s.poweredLetters > 0);
    this.el(".powered").style.clipPath =
      `inset(0 ${100 * (1 - s.poweredLetters / (POWERED_TEXT.length - 1))}% 0 0)`;
    this.opacity(".scan", s.scanVisible);
    if (s.scanVisible) this.renderScan(s);
    this.opacity(".welcome", s.welcomeVisible ? s.welcomeOpacity : 0);
    this.el(".welcome").style.transform = `scale(${s.welcomeScale})`;
    this.el(".welcome").style.filter =
      `blur(${s.exitBlur}px) invert(${s.exit * 0.22}) sepia(${s.exit}) saturate(${1 + s.exit * 5}) hue-rotate(${s.exit * 115}deg)`;
    this.opacity(".welcome-panel", s.welcomePanel);
    this.opacity(".welcome-heading", 1);
    this.el(".welcome-heading").style.color =
      themeAmount > .0001 ? "var(--theme-ink)" : `rgb(${255 * (1 - s.welcomeInk)} ${255 * (1 - s.welcomeInk)} ${255 * (1 - s.welcomeInk)})`;
    this.opacity(".welcome-company", s.companyVisible);
    this.el(".welcome-company").style.opacity = String(
      s.companyVisible ? (s.companyMask ? 0.65 : 1) : 0,
    );
    this.companyInk[1].querySelector("span")!.style.opacity = s.companyMask
      ? ".06"
      : "1";
    this.el(".welcome-highlight").style.clipPath =
      `inset(0 ${100 * (1 - s.highlight)}% 0 0)`;
    this.opacity(".welcome-database", s.databaseOpacity);
    this.opacity(".welcome-logo", s.welcomeLogo);
    this.opacity("#boot-background", s.backgroundOpacity);
    this.opacity(".boot-white", s.white);
    this.el(".boot-background svg").style.transform =
      `translate(${Math.sin(t * 0.16) * 18}px, ${-(t - 6) * 5}px) scale(1.08)`;
    return s;
  }
  private renderScan(s: ReturnType<typeof bootMotion>) {
    const { scan } = s,
      r = scan.radius;
    const group = this.scanPaths[0].parentElement!;
    group.setAttribute(
      "transform",
      `translate(960 540) scale(${s.ringScale}) translate(-960 -540)`,
    );
    group.style.opacity = String(s.ringOpacity);
    group.style.filter = `blur(${s.ringBlur}px)`;
    this.scanPaths[0].setAttribute(
      "d",
      arc(r, scan.outerStart, scan.outerSweep),
    );
    this.scanPaths[0].setAttribute("stroke-width", "2.4");
    this.scanPaths[1].setAttribute(
      "d",
      arc(scan.whiteRadius, scan.whiteStart, scan.whiteSweep),
    );
    this.scanPaths[1].setAttribute("stroke-width", "4");
    const inner = scan.innerStart;
    this.scanPaths[2].setAttribute(
      "d",
      arc(scan.innerRadius, inner, scan.innerSweep),
    );
    this.scanPaths[3].setAttribute(
      "d",
      arc(scan.innerRadius, inner + Math.PI, scan.innerSweep),
    );
    s.scanOrbit.sides.forEach((side, i) => {
      this.scanPaths[i + 4].setAttribute(
        "d",
        arc(side.radius, side.start, side.sweep, side.x, side.y),
      );
      this.scanPaths[i + 4].style.opacity = s.scanOrbit.sideVisible ? "1" : "0";
    });
    s.scanOrbit.satellites.forEach((point, i) => {
      const dot = this.satellites[i];
      dot.setAttribute("cx", String(point.x));
      dot.setAttribute("cy", String(point.y));
      dot.setAttribute("r", String(point.radius));
    });
    this.core.style.opacity = s.ornament ? "1" : "0";
    this.core.setAttribute("r", String(s.coreRadius));
    const orbit = scan.orbit;
    this.orbitDots.forEach((dot, i) => {
      dot.setAttribute(
        "cx",
        String(960 + Math.cos(orbit + i * Math.PI) * scan.orbitRadius),
      );
      dot.setAttribute(
        "cy",
        String(540 + Math.sin(orbit + i * Math.PI) * scan.orbitRadius),
      );
      dot.setAttribute("r", String(scan.dotRadius));
    });
    this.caps.forEach((cap, i) => {
      const angle = i ? scan.whiteStart : scan.outerStart + scan.outerSweep;
      const radius = i ? scan.whiteRadius : r;
      cap.setAttribute("cx", String(960 + Math.cos(angle) * radius));
      cap.setAttribute("cy", String(540 + Math.sin(angle) * radius));
      cap.setAttribute("r", String(i ? scan.whiteCap : scan.blackCap));
    });
    this.opacity(".scan > span", s.permissionOpacity);
    this.el(".scan > span").style.letterSpacing = `${s.scanTracking}px`;
    this.el(".scan > span").style.setProperty("--boot-phrase-tracking", `${s.scanTracking}px`);
    this.el(".scan > span").style.fontSize = `${s.scanFont}px`;
  }
  reset() {
    // Restore shared corner branding when skipping at any intermediate frame.
    [".brand", ".powered"].forEach((key) =>
      this.el(key).removeAttribute("style"),
    );
    this.brandLines.forEach((node) => node.removeAttribute("style"));
    this.el(".powered").innerHTML = this.poweredHTML;
    this.opacity("#boot-background", 0);
  }
}
