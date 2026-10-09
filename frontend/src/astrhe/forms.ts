/** 小弹窗：关系本编辑表单与操作确认（沙盒没有 allow-modals，不能用浏览器自带的 confirm）。 */
import { escapeHtml } from "../html";
import { parseJson } from "./format";

type Row = Record<string, unknown>;

/** 编辑表单里各字段的初始文字（别名用顿号连接，纪念日每行一条）。 */
export function personFormValues(person: Row) {
  const qq = String(person.qq ?? "");
  const aliases = parseJson<string[]>(person.aliases_json, []).join("、");
  const anniversaries = parseJson<Row[]>(person.anniversaries_json, [])
    .map((a) => `${a.name ?? ""} ${a.date ?? ""}`.trim())
    .join("\n");
  return { qq, aliases, relation: String(person.relation_text ?? ""), anniversaries };
}

export function personEditorMarkup(person: Row) {
  const { qq, aliases, relation, anniversaries } = personFormValues(person);
  return `<h2>EDIT RELATION<small>编辑关系层 · QQ ${escapeHtml(qq)}</small></h2>
  <form class="astrhe-form" data-person="${escapeHtml(qq)}">
    <label><span>ALIASES / 别名</span><input name="aliases" autocomplete="off" value="${escapeHtml(aliases)}" placeholder="多个别名用顿号或逗号分隔"/></label>
    <label><span>RELATION / 关系层</span><textarea name="relation_text" rows="7" placeholder="是谁、和 bot 是什么关系、怎么称呼">${escapeHtml(relation)}</textarea></label>
    <label><span>ANNIVERSARIES / 纪念日</span><textarea name="anniversaries" rows="3" placeholder="每行一条，例如：生日 10-11">${escapeHtml(anniversaries)}</textarea></label>
    <p class="astrhe-form-note">近况层由夜间复盘自动维护，这里不改。保存后夜间复盘会读到新的关系层。</p>
    <p class="astrhe-form-error" role="alert" hidden></p>
    <div class="detail-actions"><button type="submit" class="solid-button">SAVE RELATION<span>保存</span></button><button type="button" class="export-button" data-action="close-modal">CANCEL <span>×</span></button></div>
  </form>`;
}

/** 读取表单；纪念日格式不对时返回错误文字。 */
export function readPersonForm(form: HTMLFormElement) {
  const data = new FormData(form);
  const aliases = String(data.get("aliases") ?? "")
    .split(/[、,，\n]+/)
    .map((a) => a.trim())
    .filter(Boolean);
  const anniversaries: { name: string; date: string }[] = [];
  for (const line of String(data.get("anniversaries") ?? "").split("\n")) {
    const value = line.trim();
    if (!value) continue;
    const match = value.match(/^(.+?)\s+(\d{2}-\d{2})$/);
    if (!match) return { error: `纪念日「${value}」格式不对，请写成「名称 月-日」，例如：生日 10-11` };
    anniversaries.push({ name: match[1].trim(), date: match[2] });
  }
  return {
    payload: {
      qq: form.dataset.person ?? "",
      aliases,
      relation_text: String(data.get("relation_text") ?? ""),
      anniversaries,
    },
  };
}

export interface PendingConfirm {
  title: string;
  message: string;
  confirm: string;
  run: () => Promise<void>;
}

export function confirmMarkup(pending: PendingConfirm) {
  return `<h2>CONFIRM<small>${escapeHtml(pending.title)}</small></h2>
  <p class="astrhe-confirm-text">${escapeHtml(pending.message)}</p>
  <p class="astrhe-form-error" role="alert" hidden></p>
  <div class="detail-actions"><button class="solid-button" data-action="confirm-yes">${escapeHtml(pending.confirm)}<span>确认</span></button><button class="export-button" data-action="close-modal">CANCEL <span>×</span></button></div>`;
}

/** 下载 UTF-8 文本（沙盒允许 allow-downloads）。 */
export function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
