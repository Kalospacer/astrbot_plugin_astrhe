import { defineConfig } from "vite";
import { readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";

const PRELOAD_HELPER = "\0vite/preload-helper.js";

// 模型文件名带内容哈希，换模型后不会读到旧文件；源文件保持 Blender 导出的固定路径。
const models = ["archive-cassette", "archive-assembly"].map((name) => {
  const source = readFileSync(`models/${name}.glb`);
  const hash = createHash("sha256").update(source).digest("hex").slice(0, 16);
  return { key: `assets/${name}.glb`, fileName: `assets/${name}.${hash}.glb`, source };
});

// 脚本下载的资源大小，用于加载页与开场等待点按字节显示进度。
const assetBytes = {
  "assets/archive-cassette.glb": statSync("models/archive-cassette.glb").size,
  "assets/archive-assembly.glb": statSync("models/archive-assembly.glb").size,
  ...Object.fromEntries(
    ["Light", "Regular", "Demibold", "Bold"].map((name) => {
      const path = `fonts/MiSans-${name}.woff2`;
      return [path, statSync(`public/${path}`).size];
    }),
  ),
};

// 产物直接写进插件的 pages/dashboard/，由 AstrBot 插件页面托管。
// base 用相对路径：页面挂在 /api/plugin/page/content/<插件>/<页面>/ 下。
// 两套前端按设置分开加载，所以允许拆动态 chunk：AstrBot 会给 JS 里写死的 import("./x.js")
// 补令牌，但运行时拼出的地址（预加载 <link>、动态 chunk 自带的 CSS）会丢掉 asset_token。
// 因此关掉 modulePreload；SOUL OS 样式进入口 CSS（soul-styles.ts），NORMAL 的样式用 ?inline 注入。
export default defineConfig({
  base: "./",
  define: {
    __ASTRHE_MODELS__: JSON.stringify(
      Object.fromEntries(models.map((model) => [model.key, model.fileName])),
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
      name: "versioned-model-assets",
      apply: "build",
      buildStart() {
        for (const model of models)
          this.emitFile({ type: "asset", fileName: model.fileName, source: model.source });
      },
    },
  ],
});
