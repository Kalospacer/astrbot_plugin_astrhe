/** 点击、键盘与检索输入的处理，以及档案上的各种操作（导出、删除、取消闹钟、编辑关系层、解密）。 */
import { archiveColumns, type ArchiveRecord } from "../data";
import { apiPost } from "../astrhe/bridge";
import { downloadText } from "../astrhe/forms";
import { reveal } from "../astrhe/secrecy";
import { aboutDialog, confirmDialog, notify, personDialog } from "./dialogs";
import { exportText, renderDetail } from "./detail-pane";
import { refreshItem } from "./list";
import { icon } from "./shell";
import { closeSearch, openSearch, resetSearch, setFilter, setQuery } from "./search";
import { selectedRecord, state, patchRecord } from "./store";
import { applyChrome, boot, canGoBack, goBack, showCategory, showRecord, showRun, showRuns } from "./views";

const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.matches("input, textarea, mdui-text-field") || target.isContentEditable);

/** 操作成功后原位更新当前档案（不重新排序），并刷新详情、列表行和标题栏。 */
function refreshCurrent(record: ArchiveRecord, patch: Record<string, unknown>, clearance?: string) {
  patchRecord(record, patch, clearance);
  refreshItem(record);
  renderDetail(record, true);
  applyChrome();
}

function decrypt(button: HTMLElement) {
  const box = button.closest(".astrhe-decryptable");
  box?.classList.add("astrhe-revealed");
  button.setAttribute("disabled", "");
  button.innerHTML = `${icon("lock-open--outlined", "icon")}已解密`;
  // 档案详情的解密只对当前这份生效；运行记录没有编号，只揭开眼前这一页
  if (box?.matches("article.detail")) reveal(state.selectedId!);
  notify("已解密保密内容（仅本次打开有效）");
}

function removeRecord(record: ArchiveRecord, todo: boolean) {
  confirmDialog({
    title: todo ? "删除待办" : "删除承诺",
    message: `删除 ${record.id}「${record.title}」？删除后进入回收站，30 天内可以恢复。`,
    confirm: "删除",
    run: async () => {
      await apiPost(todo ? "todo/delete" : "promise/delete", todo ? { todo_id: record.key } : { promise_id: record.key });
      refreshCurrent(record, { status: "deleted" }, "DELETED");
      notify(todo ? "待办已移入回收站" : "承诺已移入回收站");
    },
  });
}

function cancelAlarm(record: ArchiveRecord) {
  confirmDialog({
    title: "取消闹钟",
    message: `取消 ${record.id}「${record.title}」？AstrBot 里对应的定时任务会一起删除，到点不会再执行。`,
    confirm: "取消闹钟",
    run: async () => {
      await apiPost("alarm/cancel", { alarm_id: record.key });
      refreshCurrent(record, { status: "cancelled" }, "CANCELLED");
      notify("闹钟已取消");
    },
  });
}

function editPerson(record: ArchiveRecord) {
  personDialog(record.raw, (payload) => {
    record.title = payload.aliases[0] || payload.qq;
    record.department = payload.aliases.join("、") || "—";
    refreshCurrent(record, {
      aliases_json: payload.aliases,
      relation_text: payload.relation_text,
      anniversaries_json: payload.anniversaries,
    });
    notify("关系层已保存");
  });
}

function recordAction(action: string, button: HTMLElement) {
  const record = selectedRecord();
  if (!record) return;
  switch (action) {
    case "decrypt":
      return decrypt(button);
    case "export":
      downloadText(`AstrHe-${record.id}.txt`, exportText(record));
      return notify("档案文本已导出");
    case "open-run":
      return void showRuns(Number(record.raw.run_id));
    case "edit-person":
      return editPerson(record);
    case "delete-todo":
    case "delete-promise":
      return removeRecord(record, action === "delete-todo");
    case "cancel-alarm":
      return cancelAlarm(record);
  }
}

export function handleClick(event: Event) {
  const target = event.target as HTMLElement;
  // 导航项：直接认点击（mdui 的 change 事件在程序改选中项时也会触发，不可靠）
  const navItem = target.closest<HTMLElement>("mdui-navigation-bar-item, mdui-navigation-rail-item");
  if (navItem) return void showCategory(navItem.getAttribute("value") ?? "");
  const chip = target.closest<HTMLElement>("[data-filter]");
  if (chip) return setFilter(chip.dataset.filter!);
  const actionEl = target.closest<HTMLElement>("[data-action]");
  if (actionEl) {
    if (actionEl.hasAttribute("disabled")) return;
    const action = actionEl.dataset.action!;
    switch (action) {
      case "back":
        return void goBack();
      case "search":
        return void openSearch();
      case "search-close":
        return void closeSearch();
      case "search-clear":
        setQuery("");
        document.querySelector<HTMLInputElement>("#search-input")!.value = "";
        return document.querySelector<HTMLInputElement>("#search-input")!.focus();
      case "search-reset":
        return resetSearch();
      case "runs":
        return void showRuns();
      case "about":
        return aboutDialog();
      case "retry":
        return void boot();
      default:
        return recordAction(action, actionEl);
    }
  }
  const record = target.closest<HTMLElement>("[data-record]");
  if (record) return void showRecord(record.dataset.record!, record);
  const run = target.closest<HTMLElement>("[data-run]");
  if (run) void showRun(Number(run.dataset.run), run);
}

export function handleSearchInput(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.id === "search-input") setQuery(input.value);
}

export function handleKey(event: KeyboardEvent) {
  if (event.key === "Escape") {
    // 对话框自己处理 Esc；检索视图先关，其次才是返回
    if (document.querySelector("mdui-dialog[open]")) return;
    if (state.searchOpen) void closeSearch();
    else if (canGoBack()) void goBack();
  } else if (event.key === "/" && !typing(event.target) && !event.ctrlKey && !event.metaKey && !document.querySelector("mdui-dialog[open]")) {
    event.preventDefault();
    void openSearch();
  }
}
