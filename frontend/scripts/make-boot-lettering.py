"""把开场固定英文与左上角品牌字导出为预先描好的图形轮廓（改编自 RhineLabUI 同名脚本，MIT）。

需要 Pillow 与 fontTools。字体文件由使用者自行取得、放在项目外，输出里不含字体文件，
也不含可复用的字符表：
- Normal、DemiBold：Novecento Sans Wide 的 DaFont 免费桌面包，许可允许把字母转成图形。
- Bold：MyFonts / Monotype 桌面授权。其许可只允许「不对应被单独调用的字形」的静态图形，
  所以用 Bold 的欢迎三行各合成一整块路径，不按字母拆分（开场里这三行本来就是整句显示）。

用法：
  python3 scripts/make-boot-lettering.py --fonts <DaFont 字体目录> <MyFonts Bold 字体目录>
"""

import argparse
import hashlib
import json
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]

# (键, 文字, 字重)。键与 src/boot.ts 中 BootLettering 的用法一一对应。
PHRASES = [
    ("brand", "ASTR HE", "DemiBold"),
    ("access", "ACCESS PERMISSION REQUIRED", "Normal"),
    ("identity", "ID CONFIRMED : ADMINISTRATOR", "Normal"),
    ("request", "REQUEST RECEIVED", "Normal"),
    ("processing", "START PROCESSING...", "Normal"),
    ("processingGlitch", "              SING...", "Normal"),
    ("permission", "PERMISSION AUTHORIZED", "Normal"),
    ("welcome", "WELCOME TO", "Bold"),
    ("company", "ASTRHE.SOUL.", "Bold"),
    ("database", "NIGHTLY DATABASE", "Bold"),
]
# 合成整块路径、不按字母拆分的句子（Monotype 桌面许可）
WHOLE = {"welcome", "company", "database"}


def find_font(dirs: list[Path], weight: str) -> Path:
    for directory in dirs:
        path = directory / f"Novecentosanswide-{weight}.otf"
        if path.exists():
            return path
    raise SystemExit(
        f"找不到 Novecentosanswide-{weight}.otf，请用 --fonts 指定字体目录"
    )


def advances(layout: ImageFont.FreeTypeFont, text: str) -> list[float]:
    """每个字母占的宽度，含与下一个字母之间的字距微调。"""
    result = []
    for i, char in enumerate(text):
        advance = layout.getlength(char)
        if i + 1 < len(text):
            advance += (
                layout.getlength(text[i : i + 2])
                - layout.getlength(char)
                - layout.getlength(text[i + 1])
            )
        result.append(advance)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonts", required=True, type=Path, nargs="+")
    args = parser.parse_args()
    art, sources = {}, {}
    for weight in ("Normal", "DemiBold", "Bold"):
        path = find_font(args.fonts, weight)
        font = TTFont(path)
        units = font["head"].unitsPerEm
        glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
        # 基础排版（不做 GPOS 字距微调），与原作者导出的开场字形字距一致
        layout = ImageFont.truetype(
            str(path), units, layout_engine=ImageFont.Layout.BASIC
        )
        sources[weight] = {
            "filename": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "version": font["name"].getDebugName(5),
        }
        for key, text, phrase_weight in PHRASES:
            if weight != phrase_weight:
                continue
            widths = advances(layout, text)
            if key in WHOLE:
                # 整句一块：每个字母按累计宽度平移后画进同一条路径
                pen, x = SVGPathPen(glyphs), 0.0
                for char, width in zip(text, widths):
                    glyphs[cmap[ord(char)]].draw(
                        TransformPen(pen, (1, 0, 0, -1, x, units * 0.8))
                    )
                    x += width
                letters = [{"width": round(x / units, 6), "path": pen.getCommands()}]
            else:
                letters = []
                for char, width in zip(text, widths):
                    pen = SVGPathPen(glyphs)
                    # 固定的图形格子，基线在距顶部 0.8 em 处
                    glyphs[cmap[ord(char)]].draw(
                        TransformPen(pen, (1, 0, 0, -1, 0, units * 0.8))
                    )
                    letters.append(
                        {"width": round(width / units, 6), "path": pen.getCommands()}
                    )
            art[key] = {
                "text": text,
                "weight": weight,
                "units": units,
                "letters": letters,
            }
        font.close()
    target = ROOT / "src/boot-lettering-art.json"
    ordered = {key: art[key] for key, _, _ in PHRASES}
    target.write_text(
        json.dumps(ordered, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (ROOT / "scripts/boot-lettering-sources.json").write_text(
        json.dumps(sources, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(art)} 句固定文字：{target.stat().st_size} 字节，未输出任何字体文件。")


if __name__ == "__main__":
    main()
