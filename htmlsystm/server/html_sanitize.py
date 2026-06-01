# -*- coding: utf-8 -*-
"""公告等富文本 HTML 入库前净化（防 XSS）。"""

from typing import Optional

try:
    import bleach
except ImportError:
    bleach = None  # type: ignore

# 公告编辑器允许的标签与属性
_ALLOWED_TAGS = [
    "p", "br", "div", "span", "strong", "b", "em", "i", "u", "s", "strike",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "img", "blockquote", "pre", "code", "hr", "sub", "sup",
]

_ALLOWED_ATTRIBUTES = {
    "*": ["class", "style"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_announcement_content(html: Optional[str]) -> str:
    """净化公告正文 HTML；无 bleach 时退化为去标签纯文本。"""
    if not html:
        return ""
    text = str(html)
    if bleach is None:
        return bleach_strip_tags_fallback(text)
    return bleach.clean(
        text,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )


def sanitize_announcement_title(title: Optional[str]) -> str:
    """标题不允许 HTML。"""
    if not title:
        return ""
    text = str(title).strip()
    if bleach is None:
        return bleach_strip_tags_fallback(text)
    return bleach.clean(text, tags=[], strip=True)


def bleach_strip_tags_fallback(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text)
