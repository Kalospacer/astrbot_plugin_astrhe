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

/** MiSans 官方整包 woff2，原样分发（许可见 public/fonts/MiSans-license.pdf）。 */
export const FONT_PATHS = {
  300: "fonts/MiSans-Light.woff2",
  400: "fonts/MiSans-Regular.woff2",
  600: "fonts/MiSans-Demibold.woff2",
  700: "fonts/MiSans-Bold.woff2",
} as const;

const pageUrl = new URL(location.href);
const assetToken = pageUrl.searchParams.get("asset_token");
const preloaded = new Map<string, Promise<string>>();
/** 脚本下载的资源：已收到字节数（总量来自构建时记录的文件大小）。 */
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

async function download(path: string, priority: RequestPriority, type: string) {
  const response = await fetch(remoteUrl(path), { priority });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  const reader = response.body?.getReader();
  if (!reader) {
    const blob = await response.blob();
    received.set(path, blob.size);
    return blob;
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
  return new Blob(chunks, { type });
}

/** 打开页面时调用：把资源整个下载进内存；失败后再次调用会重新下载。 */
export function preloadAsset(path: string, priority: RequestPriority = "auto") {
  let pending = preloaded.get(path);
  if (!pending) {
    received.set(path, 0);
    pending = download(path, priority, "model/gltf-binary").then(
      (blob) => URL.createObjectURL(blob),
      (error) => {
        preloaded.delete(path);
        throw error;
      },
    );
    preloaded.set(path, pending);
  }
  return pending;
}

/**
 * 下载一档 MiSans 字重并交给浏览器。不用 CSS @font-face：浏览器自己下载字体时
 * 网页拿不到进度，而加载页的百分比要按实际收到的字节计算。
 */
export async function loadFont(weight: keyof typeof FONT_PATHS, priority: RequestPriority = "high") {
  const path = FONT_PATHS[weight];
  received.set(path, 0);
  const data = await (await download(path, priority, "font/woff2")).arrayBuffer();
  const face = new FontFace("MiSans", data, { weight: String(weight), style: "normal" });
  // 先放进字体集再等解析完成，字体集的 loadingdone 事件照常触发
  document.fonts.add(face);
  await face.loaded;
  return face;
}

/** 指定资源的整体下载进度（0–1）；还没开始下载的按 0 计。 */
export function downloadProgress(paths: readonly string[]) {
  let done = 0;
  let total = 0;
  for (const path of paths) {
    const bytes = received.get(path) ?? 0;
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
