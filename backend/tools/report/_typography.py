"""辽港数据期刊 PR-2 — 中英自动加空格。

在中文和拉丁字符之间插入一个空格，提升混合排版的
可读性。跳过 ``<code>`` / ``<pre>`` / ``<script>`` / ``<style>`` 块，
避免破坏代码内容。
"""
from __future__ import annotations

import re


_CJK_LATIN = re.compile(r"([\u4e00-\u9fff\u3400-\u4dbf])([A-Za-z0-9])")
_LATIN_CJK = re.compile(r"([A-Za-z0-9])([\u4e00-\u9fff\u3400-\u4dbf])")
_SKIP_BLOCK = re.compile(
    r"<(?:code|pre|script|style)[^>]*>.*?</(?:code|pre|script|style)>",
    re.DOTALL | re.IGNORECASE,
)


def cn_latin_spacing(html: str) -> str:
    """中英之间自动加空格，跳过 code/pre/script/style 块。"""
    placeholders: list[str] = []

    def stash(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00{len(placeholders) - 1}\x00"

    masked = _SKIP_BLOCK.sub(stash, html)
    masked = _CJK_LATIN.sub(r"\1 \2", masked)
    masked = _LATIN_CJK.sub(r"\1 \2", masked)
    return re.sub(
        r"\x00(\d+)\x00",
        lambda m: placeholders[int(m.group(1))],
        masked,
    )
