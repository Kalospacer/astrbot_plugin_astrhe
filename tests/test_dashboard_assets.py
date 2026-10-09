"""档案终端构建产物（pages/dashboard）的检查：两套前端分开加载，且能通过 AstrBot 插件页面的地址改写。

AstrBot 只给 HTML 的 src/href、CSS 的 url() 和 JS 里写死的 import 地址补 asset_token，
运行时拼出来的请求（预加载 <link>、动态 chunk 自带的 CSS）没有令牌，会被拒绝；
所以产物必须满足这些条件，改前端构建配置后要重新构建并过这几项。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

DASHBOARD = Path(__file__).resolve().parents[1] / "pages" / "dashboard"
ASSETS = DASHBOARD / "assets"
# 所有写死的相对模块地址（含动态 import("./x.js")）；STATIC_ONLY 只含静态引用
ANY_IMPORT = re.compile(r"""(?:\bfrom|\bimport)\s*\(?\s*["'](\.{1,2}/[^"']+)["']""")
STATIC_ONLY = re.compile(r"""(?:\bfrom|\bimport)\s+["'](\.{1,2}/[^"']+)["']""")


def _chunks() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in ASSETS.glob("*.js")}


def test_entry_has_single_stylesheet_and_no_runtime_preload():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    assert len(re.findall(r'<link rel="stylesheet"', html)) == 1
    assert len(re.findall(r'<script type="module"', html)) == 1
    # 动态 chunk 不能带独立 CSS，否则运行时拼 <link> 加载会丢令牌
    assert len(list(ASSETS.glob("*.css"))) == 1
    for name, code in _chunks().items():
        assert "modulepreload" not in code, name
        assert 'createElement("link")' not in code, name
        assert 'createElement("script")' not in code, name


def test_normal_frontend_does_not_pull_soul_assets():
    chunks = _chunks()
    normal = next(n for n, c in chunks.items() if "normal-styles" in c)
    soul = next(n for n, c in chunks.items() if "WebGLRenderer" in c)
    seen: set[str] = set()
    todo = [normal]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo += [s.rsplit("/", 1)[-1] for s in STATIC_ONLY.findall(chunks[name])]
    assert soul not in seen
    for name in seen:
        code = chunks[name]
        assert "WebGLRenderer" not in code and ".glb" not in code, name
        assert "fonts/MiSans" not in code, name


ASTRBOT_SOURCE = os.environ.get("ASTRBOT_SOURCE_PATH")


@pytest.mark.skipif(
    not ASTRBOT_SOURCE or not Path(ASTRBOT_SOURCE).is_dir(),
    reason="需要 ASTRBOT_SOURCE_PATH 指向 AstrBot 源码",
)
def test_every_relative_import_gets_asset_token_from_real_rewriter():
    if str(ASTRBOT_SOURCE) not in sys.path:
        sys.path.insert(0, str(ASTRBOT_SOURCE))
    from astrbot.dashboard.services.plugin_page_service import PluginPageService

    service = PluginPageService.__new__(PluginPageService)
    total = 0
    for path in ASSETS.glob("*.js"):
        code = path.read_text(encoding="utf-8")
        rewritten = service.rewrite_plugin_page_js(
            code,
            "astrbot_plugin_astrhe",
            "dashboard",
            f"assets/{path.name}",
            {"asset_token": "TESTTOKEN"},
        )
        for spec in ANY_IMPORT.findall(code):
            total += 1
            name = re.escape(spec.rsplit("/", 1)[-1])
            assert re.search(name + r"\?[^\"']*asset_token=TESTTOKEN", rewritten), (
                path.name,
                spec,
            )
    # 入口、两套前端和它们的共享 chunk 之间至少有这些静态 / 动态引用
    assert total >= 4
