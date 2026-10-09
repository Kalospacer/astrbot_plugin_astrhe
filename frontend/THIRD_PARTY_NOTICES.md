# 第三方声明

AstrHe 档案终端（`frontend/`，构建产物在 `pages/dashboard/`）基于以下作品制作。

## RhineLabUI

- 作者：LBEILC，<https://github.com/LBEILC/RhineLabUI>
- 许可：MIT，全文见 [`LICENSE-RhineLabUI`](LICENSE-RhineLabUI)（Copyright (c) 2026 LBEILC）
- 使用范围：界面代码、动效时间轴、三维场景与查看器、建模脚本。声音、壁纸、工作台、手柄与 PWA 部分未移植。
- 三维模型：`models/*.glb` 由 `art/*.py`（改编自原作者的 Blender 建模脚本）用 Blender 4.5 重新生成，侧面立体字与标签文字已换成 AstrHe，未分发原仓库的 `.blend` 工程与模型文件。重新生成：`blender -b --factory-startup --python art/build_archive.py`，再以同样方式运行 `art/build_assembly.py`。
- 原作者说明：RhineLabUI 是对《明日方舟》特别映像「莱茵生命：访问」终端界面的非官方复刻；相关名称、标志、设定与原作视觉设计的权利归各自权利人，MIT 授权不覆盖这些权利，也不覆盖原仓库中未另行声明为 MIT 的模型、图像等非代码资产。本项目已替换全部莱茵文字与标志。

## MiSans

- 作者：小米科技有限责任公司（Beijing Xiaomi Mobile Software Co., Ltd.）
- 许可：《MiSans 字体知识产权许可协议》，见 [`public/fonts/MiSans-license.pdf`](public/fonts/MiSans-license.pdf)
- 官方字体文件原样分发，未修改；界面设置页注明使用 MiSans 并提供许可入口。

## Novecento Sans Wide

- 作者：Jan Tonellato / Synthview Type Design，<https://typography.synthview.com/novecento-sans-font-family.php>
- 开场固定英文与左上角品牌字为预先描好的图形轮廓（`src/boot-lettering-art.json`），不分发字体文件。
- Normal、DemiBold：DaFont 免费桌面许可，允许将字母转换为图形对象。
- Bold：MyFonts / Monotype 桌面许可；欢迎页三行各合成一整块静态图形，不按单个字形调用。
- 重新生成轮廓需要自行取得字体并在本地运行 `scripts/make-boot-lettering.py`。

## 其他依赖

- three.js：MIT，<https://github.com/mrdoob/three.js>
- @kitlangton/rolling-number：MIT，见 [`public/licenses/rolling-number.txt`](public/licenses/rolling-number.txt)
