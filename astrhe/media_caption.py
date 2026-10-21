"""图片描述延迟回写：把核心管线生成的 `<image_caption>` 补进账本消息的 text。

为什么需要延迟回写
------------------
记账发生在平台适配器钩子（AstrHe 的 recorder，priority=maxsize-3），那个时刻
`build_main_agent` 还没跑，图片描述还不存在，所以账本里的图片只能写成 `[图片]`
占位符，下游（话题概括、read_channel、会话清单）永远看不到图里的内容。

核心管线在 `_ensure_img_caption()` 里生成描述后，会以
`<image_caption>...</image_caption>` 的形式追加进 `req.extra_user_content_parts`。
`OnLLMRequestEvent` 钩子在 `build_main_agent` 返回之后才触发，所以那一刻描述已经
在 req 里了。AstrHe 的钩子优先级（maxsize-3）高于 AstrIRMIA（maxsize-4），会在
IRMIA 清理这些 part 之前先跑，因此这里能拿到完整的描述与图片路径。

回写之后下游全部自动受益，因为它们都只读 messages.text 这一列。

覆盖率说明
----------
只有真正走到过一轮 LLM 请求的消息才会被回写。群里没人点名、没有命中称呼关键词的
图片消息会被 IRMIA 拦进信箱，从不触发 LLM 请求，核心管线也就不会为它们生成描述。
这类消息由记账时的 media 列记录图片引用，留给后续的补拉或识图工具补齐。

安全性
------
整条链路是 best-effort：任何异常都只记 DEBUG 日志，绝不抛回主流程。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .platform import event_umo

#: 账本里的图片占位符，与 recorder._COMPONENT_PLACEHOLDER 保持一致
IMAGE_PLACEHOLDER = "[图片]"

#: 回写后的形态：`[图片: 描述]`，下游读到的就是一句带内容的话
IMAGE_DESCRIBED_TEMPLATE = "[图片: {caption}]"

#: 核心管线随消息附图写入的路径说明（astr_main_agent.py）
_IMAGE_ATTACHMENT_RE = re.compile(r"^\[Image Attachment: path (.+?)\]$")

#: 核心管线写入的图片描述块
_IMAGE_CAPTION_RE = re.compile(r"^<image_caption>([\s\S]*)</image_caption>$")

#: 只匹配「还没写过描述」的占位符：紧跟冒号或已经带上描述的都不再动，避免套娃
_BARE_PLACEHOLDER_RE = re.compile(r"\[图片\](?!\s*[:：])")


def _part_text(part: Any) -> str:
    """取出 extra_user_content_parts 里单个 part 的文本（兼容 str 与 TextPart）。"""
    if isinstance(part, str):
        return part
    return str(getattr(part, "text", "") or "")


def extract_image_paths(req: Any) -> list[str]:
    """取出本轮随消息附图（不含引用消息里的图）的本地路径列表。"""
    paths: list[str] = []
    for part in getattr(req, "extra_user_content_parts", None) or []:
        matched = _IMAGE_ATTACHMENT_RE.match(_part_text(part).strip())
        if matched:
            paths.append(matched.group(1).strip())
    return paths


def extract_caption(req: Any) -> str:
    """取出核心管线本轮生成的图片描述；没有则返回空串。"""
    for part in getattr(req, "extra_user_content_parts", None) or []:
        matched = _IMAGE_CAPTION_RE.match(_part_text(part).strip())
        if matched:
            return matched.group(1).strip()
    return ""


def clean_caption(caption: str) -> str:
    """把描述里的换行与多余空白压成单空格，并去掉首尾空白。"""
    return re.sub(r"\s+", " ", str(caption or "")).strip()


def render_described(caption: str) -> str | None:
    """把描述包成账本里的标准形态 `[图片: 描述]`；描述为空时返回 None。"""
    clean = clean_caption(caption)
    if not clean:
        return None
    return IMAGE_DESCRIBED_TEMPLATE.format(caption=clean)


def replace_first_placeholder(text: str, caption: str) -> str | None:
    """把 text 里第一个还没写描述的 `[图片]` 换成 `[图片: 描述]`。

    Args:
        text: 账本里该条消息的现有文本。
        caption: 核心管线生成的图片描述。

    Returns:
        替换后的文本；描述为空、或没有可替换的占位符时返回 None。
    """
    described = render_described(caption)
    if described is None:
        return None
    original = str(text or "")
    if not _BARE_PLACEHOLDER_RE.search(original):
        return None
    replaced = _BARE_PLACEHOLDER_RE.sub(described, original, count=1)
    return replaced if replaced != original else None


def build_media_json(message: list) -> str:
    """把消息里的图片组件收集成 JSON 数组（只取 url/file 字段，不下载图片）。

    存下来是为了以后能按图片引用回溯补齐描述，不参与展示。
    """
    refs: list[str] = []
    for comp in message or []:
        if type(comp).__name__ != "Image":
            continue
        ref = str(
            getattr(comp, "url", "") or getattr(comp, "file", "") or ""
        ).strip()
        if ref and ref not in refs:
            refs.append(ref)
    return json.dumps(refs, ensure_ascii=False) if refs else ""


async def apply_caption_writeback(
    storage: Any, event: Any, req: Any, logger: Any
) -> bool:
    """把本轮生成的图片描述回写到账本对应消息的 text 上。

    Args:
        storage: AstrHe 的 Storage（提供 ledger 仓库）。
        event: 当前 AstrMessageEvent。
        req: 当前 ProviderRequest，描述已在 extra_user_content_parts 里。
        logger: 插件 logger。

    Returns:
        真的写入了一行返回 True，其余情况返回 False。
    """
    caption = extract_caption(req)
    if not caption:
        return False

    paths = extract_image_paths(req)
    if len(paths) != 1:
        # 核心管线把一次请求里的所有图片合成一段描述，多于一张时无法判断描述对应哪张，
        # 宁可不写，也不要把合并描述硬塞给某一张
        if len(paths) > 1:
            logger.debug(
                f"[AstrHe] 本轮附图 {len(paths)} 张，描述无法归属到单张图片，跳过回写"
            )
        return False

    umo = event_umo(event)
    message_obj = getattr(event, "message_obj", None)
    platform_message_id = str(getattr(message_obj, "message_id", "") or "").strip()
    if not umo or not platform_message_id:
        return False

    row = await storage.ledger.get_message_by_platform_id(platform_message_id)
    if row is None or str(row.get("umo") or "") != umo:
        return False

    old_text = str(row.get("text") or "")
    new_text = replace_first_placeholder(old_text, caption)
    if not new_text:
        return False

    await storage.ledger.update_message_text(int(row["id"]), new_text)
    logger.debug(
        f"[AstrHe] 图片描述已回写 row={row['id']}：{old_text!r} -> {new_text!r}"
    )
    return True
