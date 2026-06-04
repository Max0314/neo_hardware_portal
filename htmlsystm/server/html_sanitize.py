# -*- coding: utf-8 -*-
"""公告等富文本 HTML 入库前净化（防 XSS）。"""

import re
from html import escape
from html.parser import HTMLParser
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
    "*": {"class", "style"},
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]
_SAFE_IMAGE_DATA_URL_RE = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp|bmp);base64,[A-Za-z0-9+/]+={0,2}$",
    re.IGNORECASE,
)


def _is_safe_image_data_url(value: str) -> bool:
    """Allow pasted inline bitmap images while blocking SVG/scriptable data URLs."""
    src = (value or "").strip()
    return bool(_SAFE_IMAGE_DATA_URL_RE.match(src))


def _allow_attribute(tag: str, name: str, value: str) -> bool:
    allowed_for_tag = _ALLOWED_ATTRIBUTES.get(tag, set())
    allowed_for_all = _ALLOWED_ATTRIBUTES.get("*", set())
    if name not in allowed_for_tag and name not in allowed_for_all:
        return False
    if str(value or "").strip().lower().startswith("data:"):
        return tag == "img" and name == "src" and _is_safe_image_data_url(value)
    return True


def _has_disallowed_protocol(value: str) -> bool:
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", (value or "").strip())
    return bool(match and match.group(1).lower() not in _ALLOWED_PROTOCOLS)


class _FallbackSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        self._append_start_tag(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[override]
        self._append_start_tag(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in _ALLOWED_TAGS and tag not in {"br", "hr", "img"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def _append_start_tag(self, tag: str, attrs, self_closing: bool) -> None:
        if tag not in _ALLOWED_TAGS:
            return
        cleaned_attrs = []
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            value = raw_value or ""
            if not _allow_attribute(tag, name, value):
                continue
            if name in {"href", "src"} and _has_disallowed_protocol(value):
                continue
            if name == "style" and re.search(r"(expression\s*\(|url\s*\()", value, re.IGNORECASE):
                continue
            cleaned_attrs.append(f'{name}="{escape(value, quote=True)}"')
        attr_text = (" " + " ".join(cleaned_attrs)) if cleaned_attrs else ""
        if self_closing or tag in {"br", "hr", "img"}:
            self.parts.append(f"<{tag}{attr_text}>")
        else:
            self.parts.append(f"<{tag}{attr_text}>")


def sanitize_html_fallback(text: str) -> str:
    parser = _FallbackSanitizer()
    parser.feed(text)
    parser.close()
    return "".join(parser.parts)


def sanitize_announcement_content(html: Optional[str]) -> str:
    """净化公告正文 HTML；无 bleach 时退化为去标签纯文本。"""
    if not html:
        return ""
    text = str(html)
    if bleach is None:
        return sanitize_html_fallback(text)
    return bleach.clean(
        text,
        tags=_ALLOWED_TAGS,
        attributes=_allow_attribute,
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
