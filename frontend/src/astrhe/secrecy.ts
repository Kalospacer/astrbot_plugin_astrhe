/**
 * 保密内容：规划书等文字里的【保密:QQ…】…【/保密】段落，以及待办 / 闹钟卡片的 secret_from。
 * 只有保密对象包含 AstrBot 管理员时才算「对你保密」：默认打码，点「解密」后揭开（只在本次打开有效）。
 */
import { escapeHtml } from "../html";
import { personName } from "./format";

const BLOCK = /【保密[:：]\s*([^】]*)】([\s\S]*?)【\/保密】/g;
let admins = new Set<string>();
const revealed = new Set<string>();

export function configureSecrecy(adminIds: string[]) {
  admins = new Set(adminIds.map(String));
}

function idsOf(mark: string) {
  return mark.split(/[,，、\s]+/).filter((id) => /^\d+$/.test(id));
}

/** 保密对象名单里有管理员。 */
export function secretFromAdmin(ids: unknown) {
  return Array.isArray(ids) && ids.some((id) => admins.has(String(id)));
}

export function hasAdminSecret(text: string | null | undefined) {
  for (const match of (text ?? "").matchAll(BLOCK)) if (secretFromAdmin(idsOf(match[1]))) return true;
  return false;
}

/** 检索、标题、导出用：对管理员保密的段落换成占位，其余去掉标记保留内容。 */
export function stripSecrets(text: string | null | undefined, keepAdminSecrets = false) {
  return (text ?? "").replace(BLOCK, (_, mark: string, body: string) =>
    secretFromAdmin(idsOf(mark)) && !keepAdminSecrets ? "（保密内容）" : body,
  );
}

function plain(text: string) {
  return escapeHtml(text).replace(/\n/g, "<br>");
}

/** 显示用 HTML：对管理员保密的段落包成遮挡块，对别人保密的段落加一个说明。 */
export function secretHtml(text: string | null | undefined) {
  const value = text ?? "";
  if (!value.trim()) return "—";
  let html = "";
  let last = 0;
  for (const match of value.matchAll(BLOCK)) {
    html += plain(value.slice(last, match.index));
    const ids = idsOf(match[1]);
    if (secretFromAdmin(ids)) html += maskedHtml(plain(match[2]));
    else {
      const names = ids.map(personName).join("、") || "未知对象";
      html += `<span class="astrhe-secret-note" title="${escapeHtml(`对 ${names} 保密`)}">${plain(match[2])}</span>`;
    }
    last = (match.index ?? 0) + match[0].length;
  }
  return html + plain(value.slice(last));
}

/** 整段打码（保密对象含管理员的待办、闹钟卡片）。参数已经是安全的 HTML。 */
export function maskedHtml(html: string) {
  return `<span class="astrhe-secret" data-label="CONFIDENTIAL">${html}</span>`;
}

export const isRevealed = (id: string) => revealed.has(id);
export function reveal(id: string) {
  revealed.add(id);
}

/** 区域里有对管理员保密的内容时显示的解密按钮；点击后给最近的 .astrhe-decryptable 加 astrhe-revealed。 */
export function decryptButton() {
  return `<button class="astrhe-decrypt" data-action="decrypt"><i></i>CONFIDENTIAL <span>解密</span></button>`;
}
