/** MD3 对话框与提示条：操作确认、编辑关系层（compact 下全屏）、关于。沙盒里不能用浏览器自带的 confirm / alert。 */
import type { Dialog } from "mdui/components/dialog.js";
import { snackbar } from "mdui/functions/snackbar.js";
import { escapeHtml } from "../html";
import { apiPost } from "../astrhe/bridge";
import { personFormValues, readPersonForm } from "../astrhe/forms";
import { state } from "./store";

export interface Confirm {
  title: string;
  message: string;
  /** 确认按钮上的字 */
  confirm: string;
  run: () => Promise<void>;
}

export interface PersonPayload {
  qq: string;
  aliases: string[];
  relation_text: string;
  anniversaries: { name: string; date: string }[];
}

export const notify = (message: string) => snackbar({ message, autoCloseDelay: 3000 });

function openDialog(html: string, fullscreen = false): Dialog {
  const dialog = document.createElement("mdui-dialog");
  dialog.innerHTML = html;
  if (fullscreen) dialog.setAttribute("fullscreen", "");
  dialog.addEventListener("closed", (event) => {
    if (event.target === dialog) dialog.remove();
  });
  document.querySelector("#dialog-root")!.append(dialog);
  dialog.open = true;
  return dialog;
}

const close = (dialog: Dialog) => {
  dialog.open = false;
};

function showError(dialog: Dialog, message: string) {
  const box = dialog.querySelector<HTMLElement>(".dialog-error")!;
  box.hidden = false;
  box.textContent = message;
}

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function confirmDialog(pending: Confirm) {
  const dialog = openDialog(`
    <span slot="headline">${escapeHtml(pending.title)}</span>
    <span slot="description">${escapeHtml(pending.message)}</span>
    <p class="dialog-error" role="alert" hidden></p>
    <mdui-button slot="action" variant="text" data-role="cancel">取消</mdui-button>
    <mdui-button slot="action" variant="filled" data-role="confirm">${escapeHtml(pending.confirm)}</mdui-button>`);
  dialog.querySelector('[data-role="cancel"]')!.addEventListener("click", () => close(dialog));
  const confirm = dialog.querySelector<HTMLElement>('[data-role="confirm"]')!;
  confirm.addEventListener("click", () => {
    confirm.setAttribute("disabled", "");
    pending
      .run()
      .then(() => close(dialog))
      .catch((error) => {
        confirm.removeAttribute("disabled");
        showError(dialog, `操作失败：${errorText(error)}`);
      });
  });
}

/** 编辑关系层：保存成功后回调，由调用方原位更新档案。 */
export function personDialog(person: Record<string, unknown>, saved: (payload: PersonPayload) => void) {
  const values = personFormValues(person);
  const dialog = openDialog(
    `
    <span slot="headline">编辑关系层</span>
    <span slot="description">QQ ${escapeHtml(values.qq)} · 近况层由夜间复盘自动维护，这里不改；保存后夜间复盘会读到新的关系层。</span>
    <form class="person-form" data-person="${escapeHtml(values.qq)}">
      <mdui-text-field name="aliases" label="别名" helper="多个别名用顿号或逗号分隔" autocomplete="off"></mdui-text-field>
      <mdui-text-field name="relation_text" label="关系层" helper="是谁、和 bot 是什么关系、怎么称呼" rows="6"></mdui-text-field>
      <mdui-text-field name="anniversaries" label="纪念日" helper="每行一条，例如：生日 10-11" rows="3"></mdui-text-field>
      <p class="dialog-error" role="alert" hidden></p>
    </form>
    <mdui-button slot="action" variant="text" data-role="cancel">取消</mdui-button>
    <mdui-button slot="action" variant="filled" data-role="save">保存</mdui-button>`,
    state.size === "compact",
  );
  const fields = dialog.querySelectorAll<HTMLElement & { value: string }>("mdui-text-field");
  [values.aliases, values.relation, values.anniversaries].forEach((text, i) => (fields[i].value = text));
  const form = dialog.querySelector<HTMLFormElement>("form")!;
  const save = dialog.querySelector<HTMLElement>('[data-role="save"]')!;
  dialog.querySelector('[data-role="cancel"]')!.addEventListener("click", () => close(dialog));
  save.addEventListener("click", () => form.requestSubmit());
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const parsed = readPersonForm(form);
    if ("error" in parsed) return showError(dialog, parsed.error ?? "");
    save.setAttribute("disabled", "");
    apiPost("person/save", parsed.payload)
      .then(() => {
        saved(parsed.payload);
        close(dialog);
      })
      .catch((error) => {
        save.removeAttribute("disabled");
        showError(dialog, `保存失败：${errorText(error)}`);
      });
  });
}
export function aboutDialog() {
  const dialog = openDialog(`
    <span slot="headline">AstrHe 档案终端</span>
    <span slot="description">NORMAL · Material Design 3 普通版</span>
    <ul class="about-list">
      <li><b>版本</b><span>${escapeHtml(state.overview?.version ?? "未知")}</span></li>
      <li><b>服务器时区</b><span>${escapeHtml(state.overview?.timezone ?? "未知")}</span></li>
      <li><b>说明</b><span>只在本次打开期间保存界面状态；解密的保密内容刷新页面后会重新打码。</span></li>
    </ul>
    <p class="about-notice">界面组件 <a href="https://www.mdui.org/" target="_blank" rel="noreferrer noopener">mdui</a> 2.1.5（MIT）；图标 @mdui/icons 1.0.4（MIT，图形取自 Google Material Icons，Apache-2.0）；动态配色 Material Color Utilities（Apache-2.0）。完整声明见 frontend/THIRD_PARTY_NOTICES.md。</p>
    <mdui-button slot="action" variant="text" data-role="cancel">关闭</mdui-button>`);
  dialog.querySelector('[data-role="cancel"]')!.addEventListener("click", () => close(dialog));
}
