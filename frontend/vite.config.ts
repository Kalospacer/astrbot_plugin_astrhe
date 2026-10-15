import { defineConfig } from "vite";
import { readdirSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { posix } from "node:path";
import { brotliCompressSync, constants as zlib } from "node:zlib";
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS, EXTMeshoptCompression } from "@gltf-transform/extensions";
import { MeshoptDecoder, MeshoptEncoder } from "meshoptimizer";

const PRELOAD_HELPER = "\0vite/preload-helper.js";

// 打包时用 meshopt 无损压缩模型（EXT_meshopt_compression，不量化、不加滤波）：
// 解码后的顶点数据逐位不变，只有三角形的起点可能轮换（朝向不变），体积约为原来的六成。
// 不能量化：scene.ts 会把节点矩阵烘进顶点，量化后的归一化整数在烘焙时会被截断。
// 开发服务器直接读 models/ 下的源文件（见 asset-url.ts），所以只在打包时压缩。
const isBuild = process.argv.includes("build");
await Promise.all([MeshoptEncoder.ready, MeshoptDecoder.ready]);
const gltfIO = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ "meshopt.encoder": MeshoptEncoder, "meshopt.decoder": MeshoptDecoder });
async function compressModel(path: string) {
  const document = await gltfIO.read(path);
  document
    .createExtension(EXTMeshoptCompression)
    .setRequired(true)
    .setEncoderOptions({ method: EXTMeshoptCompression.EncoderMethod.QUANTIZE });
  return gltfIO.writeBinary(document);
}

// 整文件 Brotli 只改变存储形式：解压后仍是原始字体或 meshopt 模型，不裁字、不改几何。
function packedAsset(key: string, original: Uint8Array) {
  const source = isBuild
    ? brotliCompressSync(original, { params: { [zlib.BROTLI_PARAM_QUALITY]: 11 } })
    : original;
  const hash = createHash("sha256").update(source).digest("hex").slice(0, 16);
  const { dir, name, ext } = posix.parse(key);
  return {
    key,
    fileName: `${dir}/${name}.${hash}${ext}${isBuild ? ".br" : ""}`,
    source,
  };
}

// 文件名带内容哈希；开发时直接读取原文件，不需要先构建或解压。
const assets = await Promise.all(
  ["archive-cassette", "archive-assembly"].map(async (name) => {
    const path = `models/${name}.glb`;
    const source = isBuild ? await compressModel(path) : readFileSync(path);
    return packedAsset(`assets/${name}.glb`, source);
  }),
);
assets.push(packedAsset("fonts/MiSansVF.ttf", readFileSync("fonts/MiSansVF.ttf")));

// 脚本下载的资源大小，用于加载页与开场等待点按字节显示进度。
const assetBytes = Object.fromEntries(assets.map((asset) => [asset.key, asset.source.byteLength]));

// 产物直接写进插件的 pages/dashboard/，由 AstrBot 插件页面托管。
// base 用相对路径：页面挂在 /api/plugin/page/content/<插件>/<页面>/ 下。
// 两套前端按设置分开加载，所以允许拆动态 chunk：AstrBot 会给 JS 里写死的 import("./x.js")
// 补令牌，但运行时拼出的地址（预加载 <link>、动态 chunk 自带的 CSS）会丢掉 asset_token。
// 因此关掉 modulePreload；SOUL OS 样式进入口 CSS（soul-styles.ts），NORMAL 的样式用 ?inline 注入。
export default defineConfig({
  base: "./",
  define: {
    __ASTRHE_ASSETS__: JSON.stringify(
      Object.fromEntries(assets.map((asset) => [asset.key, asset.fileName])),
    ),
    __ASTRHE_ASSET_BYTES__: JSON.stringify(assetBytes),
  },
  build: {
    outDir: "../pages/dashboard",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    copyPublicDir: true,
    modulePreload: false,
  },
  plugins: [
    {
      // Vite 自带的 __vitePreload 会在运行时创建 <link> 预加载依赖，拼出的地址没有 asset_token，
      // 会被 AstrBot 拒绝；这里换成直接调用，动态导入只留下写死的 import("./x.js")。
      name: "no-runtime-preload",
      apply: "build",
      enforce: "pre",
      resolveId(id) {
        if (id === PRELOAD_HELPER) return id;
      },
      load(id) {
        if (id === PRELOAD_HELPER)
          return { code: "export const __vitePreload = (load) => load();", moduleSideEffects: false };
      },
    },
    {
      // AstrBot 只认带空白的静态 import（import {a} from "./x.js"），压缩后的
      // import{a}from"./x.js" 认不出来，chunk 之间的静态引用就拿不到令牌。
      // 压缩发生在 renderChunk 的最后，所以等 generateBundle 再补回空白。
      name: "spaced-chunk-imports",
      apply: "build",
      generateBundle(_options, bundle) {
        for (const chunk of Object.values(bundle)) {
          if (chunk.type !== "chunk") continue;
          chunk.code = chunk.code
            .replace(/\b(import|export)(\{[^{}]*\})from"(\.{1,2}\/[^"]+)"/g, '$1 $2 from "$3"')
            .replace(/\bimport"(\.{1,2}\/[^"]+)"/g, 'import "$1"');
        }
      },
    },
    {
      // MIT、BSD、Apache 等许可要求随代码附上许可原文，而压缩后的产物不保留版权注释：
      // 按实际打进产物的模块找出第三方包，把它们的许可原文汇总成 licenses/third-party.txt。
      // meshopt 解码器放在 three 包里，但版权属于 meshoptimizer，单独附上它的许可。
      name: "third-party-licenses",
      apply: "build",
      generateBundle(_options, bundle) {
        const packages = new Map<string, string>();
        for (const chunk of Object.values(bundle)) {
          if (chunk.type !== "chunk") continue;
          for (const [id, info] of Object.entries(chunk.modules)) {
            if (!info.renderedLength) continue; // 整个被摇树去掉的模块不算
            const path = id.replace(/\\/g, "/");
            const match = path.match(/^(.*\/node_modules\/((?:@[^/]+\/)?[^/]+))\//);
            if (match) packages.set(match[2], match[1]);
            if (path.endsWith("/meshopt_decoder.module.js"))
              packages.set("meshoptimizer", "node_modules/meshoptimizer");
          }
        }
        const sections = [...packages].sort(([a], [b]) => a.localeCompare(b)).map(([name, dir]) => {
          const pkg = JSON.parse(readFileSync(`${dir}/package.json`, "utf-8"));
          const files = readdirSync(dir).filter((f) => /^(licen[cs]e|copying)/i.test(f));
          if (!files.length) throw new Error(`${name} 没有许可文件，无法附上许可原文`);
          const text = files.map((file) =>
            readFileSync(`${dir}/${file}`, "utf-8").replace(/\r\n?/g, "\n").trim(),
          ).join("\n\n");
          return `${"=".repeat(72)}\n${name}@${pkg.version}（${pkg.license}）\n${"=".repeat(72)}\n\n${text}\n`;
        });
        this.emitFile({
          type: "asset",
          fileName: "licenses/third-party.txt",
          source:
            "AstrHe 档案终端打包进产物的第三方代码及其许可原文（构建时自动生成）。\n" +
            "RhineLabUI 的许可见插件目录 frontend/LICENSE-RhineLabUI，MiSans 字体许可见 fonts/MiSans-license.pdf。\n\n" +
            sections.join("\n"),
        });
      },
    },
    {
      name: "versioned-packed-assets",
      apply: "build",
      buildStart() {
        for (const asset of assets)
          this.emitFile({ type: "asset", fileName: asset.fileName, source: asset.source });
      },
    },
  ],
});
