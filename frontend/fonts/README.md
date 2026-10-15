# MiSans 原始字体

- `MiSansVF.ttf`：小米官方 `https://hyperos.mi.com/font-download/MiSans.zip` 中的完整可变字体，Version 4.009，29,571 个字符，原文件未修改。
- SHA-256：`0ddef90648998900175cfdca9a6f087a2544c182f130b0ad4f7e94a03a115e79`。
- `static/`：此前使用的四份官方 WOFF2，保留作参考；不再复制进安装包。
- 许可与版权声明在 `../public/fonts/`，随构建产物一同分发。字体不适用项目自身的 AGPL 或前端代码的 MIT 许可。

`vite.config.ts` 对完整 TTF 做整文件 Brotli 无损压缩，不裁字、不修改字体表。页面通过随包的 `brotli-dec-wasm` 还原原始字节，再注册原来使用的四档 CSS 字重。MiSans VF 的轴坐标与 CSS 字重并不相同，`asset-url.ts` 按官方命名实例对应：

| CSS 字重 | 官方名称 | VF `wght` 坐标 |
| --- | --- | --- |
| 300 | Light | 250 |
| 400 | Regular | 330 |
| 600 | Demibold | 450 |
| 700 | Bold | 630 |

开发服务器直接读取完整 TTF；生产构建使用带内容哈希的 `.ttf.br`。两者都不在运行时访问外部字体服务。
