/**
 * 插件页面的静态资源地址。
 *
 * AstrBot 把页面放在 /api/plugin/page/content/<插件>/<页面>/ 下，每个资源都要带
 * asset_token 查询参数；它只改写 HTML/CSS/JS import 里的相对地址，运行时拼出来的
 * 地址（GLTFLoader 等）要我们自己补上。令牌 60 秒过期、资源也不允许缓存，所以模型
 * 在打开页面时一次性下载进内存，之后用 blob 地址读取，不再请求服务器。
 */
import { decompress, initSync } from "brotli-dec-wasm/web";
import decoderWasmUrl from "brotli-dec-wasm/web/bg.wasm?url";

declare const __ASTRHE_ASSETS__: Record<string, string>;
declare const __ASTRHE_ASSET_BYTES__: Record<string, number>;

export const MODEL_PATHS = [
  "assets/archive-cassette.glb",
  "assets/archive-assembly.glb",
] as const;

/** 官方完整可变字体，构建时只做整文件压缩（许可见 public/fonts/MiSans-license.pdf）。 */
export const FONT_PATH = "fonts/MiSansVF.ttf";
// MiSans VF 的轴坐标不是 CSS 字重，按官方命名实例映射，避免把正文和粗体显示得过粗。
const FONT_WEIGHTS = {
  300: 250,
  400: 330,
  600: 450,
  700: 630,
} as const;

const pageUrl = new URL(location.href);
const assetToken = pageUrl.searchParams.get("asset_token");
const preloaded = new Map<string, Promise<string>>();
/** 脚本下载的资源：已收到字节数（总量来自构建时记录的文件大小）。 */
const received = new Map<string, number>();
let decoder: Promise<void> | undefined;

function versioned(path: string) {
  const key = path.replace(/^\//, "");
  if (import.meta.env.PROD) return __ASTRHE_ASSETS__[key] ?? key;
  // 开发服务器直接读源文件：模型放在 models/，不经过 public/
  return key.replace(/^assets\/(archive-[a-z]+\.glb)$/, "models/$1");
}

/** 当前页面作用域内的资源地址（带令牌，供打开页面 60 秒内直接请求）。 */
function remoteUrl(path: string) {
  const url = new URL(versioned(path), new URL(import.meta.env.BASE_URL, pageUrl));
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

function prepareDecoder() {
  if (!decoder) {
    decoder = download(decoderWasmUrl, "high", "application/wasm")
      .then((blob) => blob.arrayBuffer())
      .then((module) => {
        initSync({ module });
      })
      .catch((error) => {
        decoder = undefined;
        throw error;
      });
  }
  return decoder;
}

async function downloadPacked(path: string, priority: RequestPriority, type: string) {
  received.set(path, 0);
  if (!import.meta.env.PROD) return download(path, priority, type);
  // 解码器与资源一起发起请求，避免慢网时等到资源令牌过期才下载解码器。
  const [blob] = await Promise.all([download(path, priority, type), prepareDecoder()]);
  const bytes = decompress(new Uint8Array(await blob.arrayBuffer()));
  return new Blob([bytes as Uint8Array<ArrayBuffer>], { type });
}

/** 打开页面时调用：把资源整个下载进内存；失败后再次调用会重新下载。 */
export function preloadAsset(path: string, priority: RequestPriority = "auto") {
  let pending = preloaded.get(path);
  if (!pending) {
    pending = downloadPacked(path, priority, "model/gltf-binary").then(
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
 * 一次下载完整 MiSans VF，再注册原来的四档字重。不用 CSS @font-face：浏览器自己下载字体时
 * 网页拿不到进度，而加载页的百分比要按实际收到的字节计算。
 */
export async function loadFonts() {
  const data = await (await downloadPacked(FONT_PATH, "high", "font/ttf")).arrayBuffer();
  return Promise.all(Object.entries(FONT_WEIGHTS).map(async ([weight, axis]) => {
    // TypeScript 的 DOM 声明尚未收录这个字体描述符，浏览器按标准支持它。
    const descriptors: FontFaceDescriptors & { variationSettings: string } = {
      weight,
      style: "normal",
      variationSettings: `"wght" ${axis}`,
    };
    const face = new FontFace("MiSans", data, descriptors);
    // 先放进字体集再等解析完成，字体集的 loadingdone 事件照常触发。
    document.fonts.add(face);
    await face.loaded;
    return face;
  }));
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
      /* 预载失败后重新下载；压缩资源必须先解压，不能直接交给 GLTFLoader。 */
    }
  }
  return import.meta.env.PROD ? preloadAsset(path) : remoteUrl(path);
}

/** 同步场景（HTML 链接等）使用的地址。 */
export const assetUrl = (path: string) => remoteUrl(path);
