# 第三方声明

AstrHe 档案终端（`frontend/`，构建产物在 `pages/dashboard/`）基于以下作品制作。档案终端有两套前端：SOUL OS（三维版，基于 RhineLabUI、three.js、MiSans 等）和 NORMAL（Material Design 3 普通版，基于 mdui）。

打包进构建产物的第三方代码，许可原文在构建时自动汇总到 `pages/dashboard/licenses/third-party.txt`。插件安装包（GitHub 生成的源码压缩包）里的 `frontend/` 只有本文件和 `LICENSE-RhineLabUI`：下文提到的 `public/…` 文件在安装包里位于 `pages/dashboard/` 下的同名位置（如 `pages/dashboard/fonts/MiSans-license.pdf`、`pages/dashboard/licenses/rolling-number.txt`），`fonts/`、`models/`、`art/`、`src/`、`scripts/` 只在仓库里。

## RhineLabUI

- 作者：LBEILC，<https://github.com/LBEILC/RhineLabUI>
- 许可：MIT，全文见 [`LICENSE-RhineLabUI`](LICENSE-RhineLabUI)（Copyright (c) 2026 LBEILC）
- 使用范围：界面代码、动效时间轴、三维场景与查看器、建模脚本。声音、壁纸、工作台、手柄与 PWA 部分未移植。
- 三维模型：`models/*.glb` 由 `art/*.py`（改编自原作者的 Blender 建模脚本）用 Blender 4.5 重新生成，侧面立体字与标签文字已换成 AstrHe，未分发原仓库的 `.blend` 工程与模型文件。重新生成：`blender -b --factory-startup --python art/build_archive.py`，再以同样方式运行 `art/build_assembly.py`。打包时 `vite.config.ts` 用 meshopt 无损压缩这两个模型，再做整文件 Brotli 无损压缩，输出到 `pages/dashboard/assets/`；浏览器还原 GLB 后交给 meshopt 解码器。
- 原作者说明：RhineLabUI 是对《明日方舟》特别映像「莱茵生命：访问」终端界面的非官方复刻；相关名称、标志、设定与原作视觉设计的权利归各自权利人，MIT 授权不覆盖这些权利，也不覆盖原仓库中未另行声明为 MIT 的模型、图像等非代码资产。本项目已替换全部莱茵文字与标志。

## MiSans

- 作者：小米科技有限责任公司（Beijing Xiaomi Mobile Software Co., Ltd.）
- 许可：《MiSans 字体知识产权许可协议》，见 [`public/fonts/MiSans-license.pdf`](public/fonts/MiSans-license.pdf)
- 使用 `fonts/MiSansVF.ttf`（Version 4.009）官方完整可变字体，保留原有 29,571 个字符；打包时只做整文件 Brotli 无损压缩，不裁字、不改字体表，浏览器还原后与官方文件逐字节一致。原来的四份静态 WOFF2 保留在 `fonts/static/`，不进入安装包。来源、SHA-256 和四档字重的轴坐标对应见 `fonts/README.md`。
- 界面设置页注明使用 MiSans 并提供许可入口；字体文件与字体许可均随插件分发，页面不需要访问外部字体 CDN。

## Novecento Sans Wide

- 作者：Jan Tonellato / Synthview Type Design，<https://typography.synthview.com/novecento-sans-font-family.php>
- 开场固定英文与左上角品牌字为预先描好的图形轮廓（`src/boot-lettering-art.json`），不分发字体文件。
- Normal、DemiBold：DaFont 免费桌面许可，允许将字母转换为图形对象。
- Bold：MyFonts / Monotype 桌面许可；欢迎页三行各合成一整块静态图形，不按单个字形调用。
- 重新生成轮廓需要自行取得字体并在本地运行 `scripts/make-boot-lettering.py`。

## mdui（NORMAL 前端）

- 作者：zdhxiong，<https://github.com/zdhxiong/mdui>，版本 2.1.5（精确锁定）
- 许可：MIT（Copyright (c) 2016-present zdhxiong@gmail.com），以包内 `LICENSE` 为准
- 使用范围：NORMAL 的全部界面组件（顶部应用栏、导航栏 / 导航轨道、列表、标签页、对话框、输入框、提示条等）与 MD3 设计令牌样式；按需引入，不使用其图标字体。
- mdui 自带的运行时依赖也一并打包进 NORMAL：`@mdui/jq`、`@mdui/shared`、`@mdui/icons-shared`、`@floating-ui/utils`、`classcat`、`ssr-window`、`is-promise`（MIT）；`lit`、`lit-html`、`lit-element`、`@lit/reactive-element`、`@lit/localize`、`@lit-labs/ssr-dom-shim`（BSD-3-Clause，Google LLC）；`@material/material-color-utilities`（Apache-2.0，Material Eng，用于动态配色）；`tslib`（0BSD，Microsoft Corp.）。

## @mdui/icons（NORMAL 前端的图标）

- 作者：zdhxiong，版本 1.0.4（精确锁定）
- 许可：包内 `LICENSE` 为 MIT（Copyright (c) 2021-present zdhxiong@gmail.com）
- 图标图形来自 Google 的 Material Icons，据其 README 以 Apache License 2.0 提供（<https://github.com/google/material-design-icons>，Apache License 2.0 全文与 `@material/material-color-utilities` 相同，见 `licenses/third-party.txt`）。每个图标是独立的 SVG Web Component，NORMAL 只引入用到的几十个；不使用图标字体。
- NORMAL 使用系统字体，不下载 MiSans，也不请求三维模型。

## 其他依赖


- three.js：MIT，<https://github.com/mrdoob/three.js>
- meshoptimizer 解码器（three.js 附带的 `examples/jsm/libs/meshopt_decoder.module.js`，打包进 SOUL OS，用于读取压缩后的模型）：MIT，Copyright (C) 2016-2025 Arseny Kapoulkine，<https://github.com/zeux/meshoptimizer>
- brotli-dec-wasm 2.3.2（SOUL OS 随包的 WebAssembly 解压器，用于完整字体与 GLB 的整文件解压）：MIT OR Apache-2.0，Copyright (c) 2026 Yulong Ming，<https://github.com/ustclug-dev/brotli-dec-wasm>；包内两份许可原文均收录到 `licenses/third-party.txt`。NORMAL 不加载该解压器。
- @kitlangton/rolling-number：MIT，见 [`public/licenses/rolling-number.txt`](public/licenses/rolling-number.txt)
