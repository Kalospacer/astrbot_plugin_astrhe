/** 档案状态的中文说明与色调：复用 records.ts 的状态表，列表和详情共用。 */
import type { ArchiveRecord } from "../data";
import { ALARM_STATUS, PROMISE_STATUS, TODO_STATUS } from "../astrhe/records";

/** active 生效 / 进行中，done 已完成，bad 出了问题，muted 已结束或普通 */
export type Tone = "active" | "done" | "bad" | "muted";

const str = (value: unknown) => (typeof value === "string" ? value : value == null ? "" : String(value));

const TONES: Record<string, Tone> = {
  open: "active",
  progress: "active",
  scheduled: "active",
  fired: "active",
  done: "done",
  failed: "bad",
  missing: "bad",
  broken: "bad",
  dropped: "muted",
  deleted: "muted",
  cancelled: "muted",
  waived: "muted",
};

export function statusInfo(record: ArchiveRecord): { label: string; tone: Tone } {
  const status = str((record.raw as Record<string, unknown>).status);
  const tone = TONES[status] ?? "muted";
  switch (record.kind) {
    case "todo":
      return { label: TODO_STATUS[status]?.[1] ?? status, tone };
    case "alarm":
      return { label: ALARM_STATUS[status]?.[1] ?? status, tone };
    case "promise":
      return { label: PROMISE_STATUS[status]?.[1] ?? status, tone };
    case "plan":
      return record.clearance === "IN EFFECT"
        ? { label: "生效中", tone: "active" }
        : { label: "已归档", tone: "muted" };
    case "person":
      return record.clearance === "ADMINISTRATOR"
        ? { label: "管理员", tone: "active" }
        : { label: "关系本", tone: "muted" };
    default:
      return { label: "暂无记录", tone: "muted" };
  }
}

/** 状态小标签：只是显示，不可点击，所以不用 <mdui-chip>（它是一个可聚焦的按钮）。 */
export function statusChip(record: ArchiveRecord) {
  const { label, tone } = statusInfo(record);
  return `<span class="status-chip" data-tone="${tone}">${label}</span>`;
}
