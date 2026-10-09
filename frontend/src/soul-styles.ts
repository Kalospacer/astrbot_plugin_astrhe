/**
 * SOUL OS 的全部样式集中在这里，只由页面入口 launcher.ts 静态引入。
 *
 * 这样它们会进入「入口 CSS」，由 index.html 的 <link> 引用，AstrBot 才会给地址补上
 * asset_token；放进被动态导入的模块里，Vite 会在运行时拼 <link> 加载，那个地址没有令牌，
 * 会被 401 拒绝。
 *
 * 顺序必须与改造前各模块首次引入这些样式的顺序一致（main.ts → boot.ts 的依赖），
 * 层叠顺序一变，样式就可能变。
 */
import "./document-decryption.css";
import "./decryption.css";
import "@kitlangton/rolling-number/styles.css";
import "./style.css";
import "./quality-settings.css";
import "./responsive.css";
import "./boot-sync.css";
import "./theme.css";
import "./boot-lettering.css";
import "./astrhe/astrhe.css";
