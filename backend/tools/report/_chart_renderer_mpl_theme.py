"""matplotlib 主题注入 — 辽港数据期刊 PR-1。

为 ``_chart_renderer.render_chart_to_png`` 提供统一的 matplotlib
rcParams 配置，使 DOCX 内嵌图表与报告其余部分的视觉一致。

调用方式::

    from backend.tools.report._chart_renderer_mpl_theme import apply_mpl_theme
    apply_mpl_theme(theme)
"""
from __future__ import annotations

from cycler import cycler

from backend.tools.report._theme import Theme


def apply_mpl_theme(theme: Theme) -> None:
    """将 Theme 对象映射到 matplotlib rcParams，全局生效。

    应在 ``render_chart_to_png`` 内每次调用前执行，确保多线程
    环境下不同报告的图表不会交叉污染 rcParams。
    """
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": theme.css_bg_light,
        "axes.facecolor": theme.css_bg_light,
        "axes.edgecolor": theme.css_neutral,
        "axes.labelcolor": theme.css_text_dark,
        "axes.titlecolor": theme.css_text_dark,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.spines.bottom": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": "#1F1A1219",
        "grid.linewidth": 0.5,
        "ytick.color": theme.css_text_dark,
        "xtick.color": theme.css_text_dark,
        "ytick.major.size": 0,
        "xtick.major.size": 0,
        "font.family": [theme.font_ui] + list(theme.font_ui_fallbacks),
        "font.size": 9,
        "axes.prop_cycle": cycler(
            "color", ["#" + c for c in theme.chart_colors]
        ),
        "legend.frameon": False,
        "legend.fontsize": 9,
    })
