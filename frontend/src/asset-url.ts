/**
 * 插件页面的静态资源地址。
 *
 * AstrBot 把页面放在 /api/plugin/page/content/<插件>/<页面>/ 下，每个资源都要带
 * asset_token 查询参数；它只改写 HTML/CSS/JS import 里的相对地址，运行时拼出来的
 * 地址（GLTFLoader 等）要我们自己补上。令牌 60 秒过期、资源也不允许缓存，所以模型
 * 在打开页面时一次性下载进内存，之后用 blob 地址读取，不再请求服务器。
 */
declare const __ASTRHE_MODELS__: Record<string, string>;
declare const __ASTRHE_ASSET_BYTES__: Record<string, number>;

export const MODEL_PATHS = [
  "assets/archive-cassette.glb",
  "assets/archive-assembly.glb",
] as const;

const pageUrl = new URL(location.href);
const assetToken = pageUrl.searchParams.get("asset_token");
const preloaded = new Map<string, Promise<string>>();
/** 开场期间后台下载的资源：已收到字节数（总量来自构建时记录的文件大小）。 */
const received = new Map<string, number>();

function versioned(path: string) {
  const key = path.replace(/^\//, "");
  if (import.meta.env.PROD) return __ASTRHE_MODELS__[key] ?? key;
  // 开发服务器直接读源文件：模型放在 models/，不经过 public/
  return key.replace(/^assets\/(archive-[a-z]+\.glb)$/, "models/$1");
}

/** 当前页面作用域内的资源地址（带令牌，供打开页面 60 秒内直接请求）。 */
function remoteUrl(path: string) {
  const url = new URL(`${import.meta.env.BASE_URL}${versioned(path)}`, pageUrl);
  if (assetToken) url.searchParams.set("asset_token", assetToken);
  return url.href;
}

async function download(path: string, priority: RequestPriority) {
  const response = await fetch(remoteUrl(path), { priority });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  const reader = response.body?.getReader();
  if (!reader) {
    const blob = await response.blob();
    received.set(path, blob.size);
    return URL.createObjectURL(blob);
  }
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let bytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    bytes += value.byteLength;
    received.set(path, bytes);
  }
  return URL.createObjectURL(new Blob(chunks, { type: "model/gltf-binary" }));
}

/** 打开页面时调用：把资源整个下载进内存；失败后再次调用会重新下载。 */
export function preloadAsset(path: string, priority: RequestPriority = "auto") {
  let pending = preloaded.get(path);
  if (!pending) {
    received.set(path, 0);
    pending = download(path, priority).catch((error) => {
      preloaded.delete(path);
      throw error;
    });
    preloaded.set(path, pending);
  }
  return pending;
}

/** 记录后台加载的字体：完成后整份计入进度。 */
export function trackFont<T>(loading: Promise<T>, path = "fonts/MiSans-Light.woff2") {
  received.set(path, 0);
  return loading.then((value) => {
    received.set(path, __ASTRHE_ASSET_BYTES__[path] ?? 0);
    return value;
  });
}

/** 后台资源的整体下载进度（0–1）。 */
export function downloadProgress() {
  let done = 0;
  let total = 0;
  for (const [path, bytes] of received) {
    const size = __ASTRHE_ASSET_BYTES__[path] ?? bytes;
    total += size;
    done += Math.min(bytes, size);
  }
  return total ? done / total : 1;
}

/** 已预载的资源返回内存地址，否则返回带令牌的服务器地址。 */
export async function assetSource(path: string) {
  const pending = preloaded.get(path);
  if (pending) {
    try {
      return await pending;
    } catch {
      /* 预载失败时退回直接请求 */
    }
  }
  return remoteUrl(path);
}

/** 同步场景（HTML 链接等）使用的地址。 */
export const assetUrl = (path: string) => remoteUrl(path);
