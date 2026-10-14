"""测试图片描述延迟回写：描述提取、占位符替换与 media 收集。"""

from __future__ import annotations

from dataclasses import dataclass, field

from astrhe.media_caption import (
    build_media_json,
    clean_caption,
    extract_caption,
    extract_image_paths,
    render_described,
    replace_first_placeholder,
)


@dataclass
class Part:
    text: str


@dataclass
class Plain:
    text: str = ""


@dataclass
class FakeImage:
    """字段名刻意与 AstrBot 的 Image 组件一致；模块按类名判断类型。"""

    url: str = ""
    file: str = ""


@dataclass
class FakeReq:
    extra_user_content_parts: list = field(default_factory=list)


# 让 type(comp).__name__ == "Image"
FakeImage.__name__ = "Image"


def test_clean_caption_collapses_whitespace() -> None:
    assert clean_caption("一只猫\n趴在  键盘上 ") == "一只猫 趴在 键盘上"
    assert clean_caption(None) == ""
    assert clean_caption("   ") == ""


def test_render_described_and_empty() -> None:
    assert render_described("一只白猫") == "[图片: 一只白猫]"
    assert render_described("") is None
    assert render_described("  \n ") is None


def test_extract_caption_and_paths() -> None:
    req = FakeReq(
        [
            Part("[Image Attachment: path /tmp/a.jpg]"),
            Part("<image_caption>一只白猫趴在键盘上</image_caption>"),
            Part("=== [IRMIA] 当前状态 ==="),
            "[Image Attachment: path /tmp/b.png]",
        ]
    )
    assert extract_caption(req) == "一只白猫趴在键盘上"
    assert extract_image_paths(req) == ["/tmp/a.jpg", "/tmp/b.png"]


def test_extract_caption_missing() -> None:
    assert extract_caption(FakeReq([Part("普通文本")])) == ""
    assert extract_caption(FakeReq()) == ""
    assert extract_image_paths(FakeReq()) == []


def test_replace_first_placeholder_basic() -> None:
    assert replace_first_placeholder("[图片]", "一只白猫") == "[图片: 一只白猫]"
    assert (
        replace_first_placeholder("[图片][穷鬼]", "一只白猫")
        == "[图片: 一只白猫][穷鬼]"
    )
    assert (
        replace_first_placeholder("[@123] 看看[图片]", "一只白猫")
        == "[@123] 看看[图片: 一只白猫]"
    )


def test_replace_skips_already_described() -> None:
    """已经写过描述的不再改，避免重复进钩子时套娃。"""
    assert replace_first_placeholder("[图片: 上次写的]", "新描述") is None
    assert replace_first_placeholder("[图片：全角冒号]", "新描述") is None
    # 混着来的时候只补还没写的那个
    assert (
        replace_first_placeholder("[图片: 第一张][图片]", "第二张")
        == "[图片: 第一张][图片: 第二张]"
    )


def test_replace_returns_none_for_edge_cases() -> None:
    assert replace_first_placeholder("[图片]", "") is None
    assert replace_first_placeholder("[图片]", "   ") is None
    assert replace_first_placeholder("纯文字消息", "描述") is None
    assert replace_first_placeholder("", "描述") is None


def test_build_media_json_collects_image_refs() -> None:
    msg = [
        Plain("看这个"),
        FakeImage(url="http://x/1.jpg"),
        FakeImage(file="/tmp/2.png"),
        FakeImage(url="http://x/1.jpg"),
    ]
    assert build_media_json(msg) == '["http://x/1.jpg", "/tmp/2.png"]'


def test_build_media_json_without_images() -> None:
    assert build_media_json([Plain("纯文字")]) == ""
    assert build_media_json([]) == ""
    assert build_media_json(None) == ""
