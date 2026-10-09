/**
 * AstrBot 插件页面桥接：页面在沙盒 iframe 里，只能通过父页面转发调用插件 Web API。
 * endpoint 相对插件名（例如 "overview" → /astrbot_plugin_astrhe/overview）。
 */
interface PluginPageBridge {
  ready(): Promise<unknown>;
  apiGet(endpoint: string, params?: Record<string, unknown>): Promise<unknown>;
  apiPost(endpoint: string, body?: unknown): Promise<unknown>;
}

declare global {
  interface Window {
    AstrBotPluginPage?: PluginPageBridge;
  }
}

const TIMEOUT_MS = 20000;

function bridge() {
  const instance = window.AstrBotPluginPage;
  if (!instance) throw new Error("请在 AstrBot 面板的插件页面里打开 AstrHe 档案终端");
  return instance;
}

function withTimeout<T>(pending: Promise<T>, what: string) {
  let timer: ReturnType<typeof setTimeout>;
  return Promise.race([
    pending,
    new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${what}超时，请检查 AstrBot 是否在运行`)), TIMEOUT_MS);
    }),
  ]).finally(() => clearTimeout(timer));
}

export function apiGet<T>(endpoint: string, params?: Record<string, unknown>) {
  return withTimeout(bridge().apiGet(endpoint, params) as Promise<T>, "读取档案");
}

export function apiPost<T>(endpoint: string, body?: unknown) {
  return withTimeout(bridge().apiPost(endpoint, body) as Promise<T>, "提交操作");
}
