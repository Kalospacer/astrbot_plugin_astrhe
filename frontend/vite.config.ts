import { defineConfig } from "vite";
import { readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";

// 模型文件名带内容哈希，换模型后不会读到旧文件；源文件保持 Blender 导出的固定路径。
const models = ["archive-cassette", "archive-assembly"].map((name) => {
  const source = readFileSync(`models/${name}.glb`);
  const hash = createHash("sha256").update(source).digest("hex").slice(0, 16);
  return { key: `assets/${name}.glb`, fileName: `assets/${name}.${hash}.glb`, source };
});

// 开场期间后台下载的资源大小，用于显示同步进度。
const backgroundAssets = {
  "assets/archive-cassette.glb": statSync("models/archive-cassette.glb").size,
  "assets/archive-assembly.glb": statSync("models/archive-assembly.glb").size,
  "fonts/MiSans-Light.woff2": statSync("public/fonts/MiSans-Light.woff2").size,
};

// 产物直接写进插件的 pages/dashboard/，由 AstrBot 插件页面托管。
// base 用相对路径：页面挂在 /api/plugin/page/content/<插件>/<页面>/ 下。
// 不拆动态 chunk：运行时拼出的地址会丢掉 AstrBot 的 asset_token。
export default defineConfig({
  base: "./",
  define: {
    __ASTRHE_MODELS__: JSON.stringify(
      Object.fromEntries(models.map((model) => [model.key, model.fileName])),
    ),
    __ASTRHE_ASSET_BYTES__: JSON.stringify(backgroundAssets),
  },
  build: {
    outDir: "../pages/dashboard",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    copyPublicDir: true,
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
  },
  plugins: [
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
