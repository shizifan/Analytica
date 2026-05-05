"""辽港数据期刊 PR-2 — ECharts 主题 "liangang-journal"。

在 HTML 模板中通过 ``<script>`` 标签注入到页面头部。
``HtmlBlockRenderer`` 使用 ``echarts.init(el, "liangang-journal")``
注册此主题。
"""
from __future__ import annotations

import json


def liangang_journal_echarts_theme_js() -> str:
    """返回 ECharts 主题注册的 JS 代码段。

    注入到 HTML ``<head>`` 中，确保在 echarts CDN 之后执行。
    """
    theme = {
        "color": [
            "#004889", "#AC916B", "#80A4C2",
            "#CFAB79", "#336EA4", "#8B4A2B",
        ],
        "backgroundColor": "transparent",
        "textStyle": {
            "fontFamily": "'Noto Sans SC', 'PingFang SC', sans-serif",
            "color": "#1F1A12",
        },
        "title": {"show": False},
        "grid": {
            "top": 24, "right": 24, "bottom": 32, "left": 8,
            "containLabel": True,
        },
        "xAxis": {
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
            "axisLabel": {"color": "#5E5648", "fontSize": 11},
        },
        "yAxis": {
            "position": "right",
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "splitLine": {
                "show": True,
                "lineStyle": {"color": "rgba(31,26,18,0.10)"},
            },
            "axisLabel": {
                "color": "#5E5648", "fontSize": 11,
                "align": "left", "margin": 8,
            },
        },
        "legend": {"show": False},
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": "#FBF6EE",
            "borderColor": "#004889",
            "borderWidth": 1,
            "textStyle": {"color": "#1F1A12"},
        },
    }
    theme_json = json.dumps(theme, ensure_ascii=False)
    return (
        "<script>"
        "echarts.registerTheme('liangang-journal', " + theme_json + ");"
        "</script>"
    )
