/**
 * 档案阵列的数据层。三维场景与循环位置只通过这里的 records / columnFiles /
 * fileLocation / fileAtSlot 取档案；AstrHe 数据在启动时由 setRecords 填入。
 */

export type ArchiveKind = "plan" | "todo" | "alarm" | "promise" | "person" | "empty";

export interface ArchiveRecord {
  /** 显示编号，如 A-005 */
  id: string;
  /** 编号前缀（P/T/A/V/R），滚动数字只滚后面的三位 */
  prefix: string;
  /** 三位编号的数值，阵列标题与档案盒标签使用 */
  code: number;
  kind: ArchiveKind;
  /** 所在列名 */
  category: string;
  /** 阵列标题、检索结果使用的中文名（保密档案已替换为中性名称） */
  title: string;
  /** 详情页大标题 */
  en: string;
  /** 阵列右侧的小标签（状态） */
  clearance: string;
  /** 检索结果第二列：会话或对象 */
  department: string;
  /** 含对管理员保密的内容 */
  secret: boolean;
  /** 检索文本，不含保密内容 */
  searchText: string;
  /** 后端主键：操作接口使用 */
  key: number | string;
  /** 后端原始数据 */
  raw: Record<string, unknown>;
}

/** 五列固定顺序（哥哥 10-09 选定）。 */
export const archiveColumns = ["规划书", "待办", "闹钟", "承诺", "关系本"];
export const categories = ["全部档案", ...archiveColumns];
/** 阵列每列 32 行，档案占第 12–31 行，所以每列最多 20 份。 */
export const COLUMN_LIMIT = 20;
export const records: ArchiveRecord[] = [];

/** 启动时替换全部档案；每列至少一份（空列由调用方补占位档案）。 */
export function setRecords(next: ArchiveRecord[]) {
  records.splice(0, records.length, ...next);
}

export function columnFiles(lane: number) {
  return records
    .map((record, index) => ({ record, index }))
    .filter(({ record }) => record.category === archiveColumns[lane])
    .map(({ index }) => index);
}
export function fileLocation(index: number) {
  const lane = archiveColumns.indexOf(records[index].category);
  const row = 12 + columnFiles(lane).indexOf(index);
  return { lane, row, slot: lane * 32 + row };
}
export function fileAtSlot(slot: number) {
  const files = columnFiles(Math.floor(slot / 32));
  return files[Math.max(0, Math.min(files.length - 1, (slot % 32) - 12))];
}
