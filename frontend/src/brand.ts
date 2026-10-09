// AstrHe 的氦原子标志（双轨）：两条倾斜的电子轨道、带两个质子「+」的原子核、两颗电子。
// 画布与 RhineLabUI 的标志相同（310 × 145，带字时 310 × 185），替换后排版不用动。

const CX = 155;
const CY = 72.5;
const RX = 126;
const RY = 30;
const TILT = 22;
/** 轨道线宽；开场线宽轨迹按原版 26 的比例缩放到这里 */
export const MARK_STROKE = 17;
const NUCLEUS_R = 25;
const ELECTRON_R = 10;
const ELECTRON_GAP = 5;

function ellipsePoint(rot: number, degrees: number) {
  const r = (rot * Math.PI) / 180;
  const t = (degrees * Math.PI) / 180;
  const x = RX * Math.cos(t);
  const y = RY * Math.sin(t);
  return [CX + x * Math.cos(r) - y * Math.sin(r), CY + x * Math.sin(r) + y * Math.cos(r)];
}

// 两颗电子各自的轨道倾角与停靠角度
const ELECTRON_ORBITS = [
  [TILT, 150],
  [-TILT, 330],
] as const;

/** 第 i 颗电子沿自己的轨道（与描线同向）前进 advance 度后的位置 */
export function electronAt(i: number, advance = 0) {
  const [tilt, angle] = ELECTRON_ORBITS[i];
  const [x, y] = ellipsePoint(tilt, angle + advance);
  return { x, y };
}

/** 两颗电子停在各自轨道上的位置 */
export const electrons = ELECTRON_ORBITS.map((_, i) => {
  const { x, y } = electronAt(i);
  return { x: +x.toFixed(2), y: +y.toFixed(2) };
});

// 两条轨道关于水平轴对称，交点落在水平线上：从左交点出发先绕完第一条轨道，
// 再绕第二条回到起点，就是开场「一笔画」需要的连续轮廓。
const cross = 1 / Math.sqrt(Math.cos((TILT * Math.PI) / 180) ** 2 / RX ** 2 + Math.sin((TILT * Math.PI) / 180) ** 2 / RY ** 2);
const left = `${(CX - cross).toFixed(2)} ${CY}`;
const right = `${(CX + cross).toFixed(2)} ${CY}`;
export const bootMarkContour =
  `M${left}A${RX} ${RY} ${TILT} 1 1 ${right}A${RX} ${RY} ${TILT} 1 1 ${left}` +
  `A${RX} ${RY} ${-TILT} 1 1 ${right}A${RX} ${RY} ${-TILT} 1 1 ${left}Z`;

let instance = 0;

/** 标志图形本体。每个实例的遮罩 id 唯一，避免页面里多处标志互相引用。 */
function markShapes(fill: string) {
  const id = `astrhe-mark-${++instance}`;
  const plus = (x: number) => `M${x - 7} ${CY}h14M${x} ${CY - 7}v14`;
  return `<defs>
<mask id="${id}-gap" maskUnits="userSpaceOnUse" x="0" y="0" width="310" height="145"><rect width="310" height="145" fill="#fff"/>${electrons.map((e) => `<circle class="astrhe-electron-gap" cx="${e.x}" cy="${e.y}" r="${ELECTRON_R + ELECTRON_GAP}" fill="#000"/>`).join("")}</mask>
<mask id="${id}-core" maskUnits="userSpaceOnUse" x="0" y="0" width="310" height="145"><rect width="310" height="145" fill="#fff"/><path d="${plus(CX - 9.5)}${plus(CX + 9.5)}" stroke="#000" stroke-width="5" fill="none"/></mask>
</defs>
<path class="astrhe-orbits" d="${bootMarkContour}" fill="none" stroke="currentColor" stroke-width="${MARK_STROKE}" mask="url(#${id}-gap)"/>
<g class="astrhe-nucleus" fill="${fill}"><circle cx="${CX}" cy="${CY}" r="${NUCLEUS_R}" mask="url(#${id}-core)"/></g>
${electrons.map((e) => `<circle class="astrhe-electron" cx="${e.x}" cy="${e.y}" r="${ELECTRON_R}" fill="${fill}"/>`).join("")}`;
}

/** 档案盒标签上印的小标志（Canvas 绘制，颜色固定）。 */
export const labelMarkSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 310 145" color="#171713">${markShapes("#171713")}</svg>`;

/** 界面里带字的完整标志。 */
export function logoMarkup() {
  return `<svg viewBox="0 0 310 185" aria-label="AstrHe" role="img">${markShapes("currentColor")}<text x="165" y="174" text-anchor="middle" font-family="MiSans,sans-serif" font-size="16" font-weight="700" letter-spacing="22">ASTR·HE</text></svg>`;
}

// 左上角品牌字第三行逐字母位置（35px MiSans 实测字宽 S20.79/O27.16/U24.67/L19.74，字间距 17.6px）。
// 品牌字块收窄到 240px，三行两端对齐，OS 与 SOUL 之间留出比字间距更宽的空隙。
const soulPositions = [2, 40.4, 85.2, 127.4];
export const brandHeading = `<h1>ASTR HE</h1><div>SYNTHESIZE MEMORIES</div><p><span class="brand-analysis" role="img" aria-label="SOUL">${[..."SOUL"].map((letter, i) => `<span aria-hidden="true" style="left:${soulPositions[i]}px">${letter}</span>`).join("")}</span> <b>OS</b></p>`;
