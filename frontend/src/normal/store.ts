/** NORMAL 的界面状态与数据读取。档案的整理、排序、保密规则都复用 astrhe/ 里的实现。 */
import { archiveColumns, records, setRecords, type ArchiveRecord } from "../data";
import { apiGet } from "../astrhe/bridge";
import { configureFormat, parseJson } from "../astrhe/format";
import { buildRecords, type Overview } from "../astrhe/records";
import { configureSecrecy } from "../astrhe/secrecy";
import { loadRuns } from "../astrhe/runs";
import type { Size } from "./layout";

export interface State {
  overview: Overview | null;
  size: Size;
  /** records 是五列档案，runs 是 NIGHT RUNS（夜间运行记录） */
  mode: "records" | "runs";
  category: string;
  selectedId: string | null;
  runId: number | null;
  /** compact / medium 下当前显示列表还是详情；expanded 下两栏并排，此值不起作用 */
  pane: "list" | "detail";
  searchOpen: boolean;
}

export const state: State = {
  overview: null,
  size: "compact",
  mode: "records",
  category: archiveColumns[0],
  selectedId: null,
  runId: null,
  pane: "list",
  searchOpen: false,
};

/** 经 Bridge 读取总览与运行记录，整理成五列档案（与 SOUL OS 同一套整理规则）。 */
export async function loadArchive() {
  const [data] = await Promise.all([
    apiGet<Overview>("overview"),
    loadRuns().catch((error) => {
      console.warn("运行记录读取失败", error);
      return [];
    }),
  ]);
  state.overview = data;
  configureFormat({
    timezone: data.timezone,
    persons: (data.persons ?? []).map((p) => ({
      qq: String(p.qq),
      aliases: parseJson<string[]>(p.aliases_json, []),
    })),
  });
  configureSecrecy(data.admins ?? []);
  setRecords(buildRecords(data));
}

export const byId = (id: string | null) => records.find((r) => r.id === id);
export const selectedRecord = () => byId(state.selectedId);
export const categoryRecords = (category: string) => records.filter((r) => r.category === category);
/** 不含「暂无记录」占位的真实档案数 */
export const realCount = (category: string) => categoryRecords(category).filter((r) => r.kind !== "empty").length;

/** 操作成功后原位更新这份档案（不重新排序，列表位置不跳）。 */
export function patchRecord(record: ArchiveRecord, patch: Record<string, unknown>, clearance?: string) {
  Object.assign(record.raw, patch);
  if (clearance) record.clearance = clearance;
}
