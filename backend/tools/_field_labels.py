"""Chinese display labels for API column names, stats metric keys, and chart identifiers.

Provides a single source of truth for translating raw API field names (e.g. ``qty``,
``finishQty``, ``mean``) to human-readable Chinese labels used in chart legends,
table headers, and KPI cards.

Usage::

    from backend.tools._field_labels import col_label, metric_label

    col_label("qty")        # → "吨吞吐量"
    col_label("unknown")    # → "unknown"   (passthrough fallback)
    metric_label("mean")    # → "均值"
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Column name → Chinese display label
# Applied in: chart series names, DataFrame table headers
# ---------------------------------------------------------------------------

COLUMN_LABELS: dict[str, str] = {
    # ── Throughput / quantity ──────────────────────────────────────────────
    "qty":                           "吨吞吐量",
    "tonQ":                          "作业吨量",
    "teuQ":                          "TEU量",
    "finishQty":                     "实际完成量(万吨)",
    "targetQty":                     "计划目标量(万吨)",
    "num":                           "数量",
    "totalQty":                      "总数量",
    "ttlNum":                        "合计数",
    "yoyQty":                        "同比量",
    "momQty":                        "环比量",
    "curMonthThroughput":            "当月吞吐量",
    "throughput":                    "吞吐量",
    "workingAmount":                 "作业量",
    "currentYearTeu":                "当年TEU量",
    "prevYearTeu":                   "上年TEU量",
    "teu":                           "集装箱TEU",
    # ── Rate fields ────────────────────────────────────────────────────────
    "rate":                          "占比(%)",
    "yoyRate":                       "同比增速(%)",
    "momRate":                       "环比增速(%)",
    "contributionRate":              "贡献率(%)",
    "berthOccupancyRate":            "泊位占用率(%)",
    "completionRate":                "目标完成率(%)",
    "revenueShare":                  "收入占比(%)",
    "serviceableRate":               "可用率(%)",
    "usageRate":                     "利用率(%)",
    # ── Operations ────────────────────────────────────────────────────────
    "workTh":                        "作业效率(吨/台时)",
    "berth":                         "泊位数",
    "machineHourRate":               "机时效率",
    # ── Dimension / key fields ────────────────────────────────────────────
    "regionName":                    "港区",
    "zoneName":                      "港区",
    "firstLevelName":                "设备大类",
    "secondLevelName":               "机种",
    "typeName":                      "业务类型",
    "businessType":                  "业务类型",
    "businessSegment":               "业务板块",
    "cargoCategoryName":             "货类名称",
    "clientName":                    "客户名称",
    "companyName":                   "公司名称",
    "displayName":                   "客户简称",
    "displayCode":                   "客户编码",
    "categoryName":                  "货类",
    "clientType":                    "客户类型",
    "indstryFieldName":              "行业领域",
    "statCargoKind":                 "货类",
    "dateMonth":                     "月份",
    "monthStr":                      "月份",
    "monthId":                       "月份",
    "month":                         "月份",
    "yearId":                        "年度",
    "dateYear":                      "年份",
    "ttlDate":                       "统计日期",
    "statType":                      "统计类型",
    "dateType":                      "时间维度",
    # ── Risk ──────────────────────────────────────────────────────────────
    "riskScore":                     "风险评分",
    "riskLevel":                     "风险等级",
    # ── Business / financial ───────────────────────────────────────────────
    "clientCount":                   "客户数量",
    "outPortQty":                    "外贸客户数",
    "strategyClientQty":             "战略客户数",
    "customerFilesNumber":           "客户档案数",
    "cumulativeRevenue":             "累计收入(万元)",
    "cumulativeStrategicThroughput": "战略客户累计吞吐量",
    "strategicThroughput":           "战略吞吐量",
    # ── Asset / investment ────────────────────────────────────────────────
    "ownerZone":                     "所属港区",
    "ownerLgZoneName":               "所属大区",
    "assetTypeName":                 "资产类型",
    "projectQty":                    "项目数量",
    "captProjectQty":                "立项项目数",
    "deliveryCaptProjectQty":        "竣工立项数",
    "investAmt":                     "投资额(万元)",
    "planInvestAmt":                 "计划投资额(万元)",
    "planPayAmt":                    "计划付款额(万元)",
    "finishInvestAmt":               "完成投资额(万元)",
    "finishPayAmt":                  "完成付款额(万元)",
    "realFinishInvestAmt":           "实际完成投资(万元)",
    "realFinishPayAmt":              "实际完成付款(万元)",
    "captPlanPayAmt":                "立项计划付款(万元)",
    "costApplyInvestAmt":            "费用申请投资(万元)",
    "projectCurrentStage":          "项目当前阶段",
    # ── Capital projects list (getCapitalProjectsList) ────────────────────
    "projectName":                   "项目名称",
    "projectNo":                     "项目编号",
    "investProjectType":             "项目类型",
    "investProjectStatus":           "项目状态码",
    "investProjectStatusName":       "项目状态",
    "ownerDept":                     "归口部门",
    "planYear":                      "计划年度",
    "proAmt":                        "立项金额(万元)",
    "captProjectPhysicalProgress":   "物理进度(%)",
    "captProjectPayProgress":        "付款进度",
}

# ---------------------------------------------------------------------------
# Stats metric key → Chinese label
# Applied in: summary_stats table headers (html_gen, _html_tools, _docx_elements)
# ---------------------------------------------------------------------------

METRIC_LABELS: dict[str, str] = {
    "mean":   "均值",
    "median": "中位数",
    "std":    "标准差",
    "min":    "最小值",
    "max":    "最大值",
    "count":  "计数",
    "sum":    "合计",
    "q1":     "25分位",
    "q3":     "75分位",
}

# ---------------------------------------------------------------------------
# ECharts waterfall series identifiers → Chinese
# Applied in: chart_waterfall.py
# ---------------------------------------------------------------------------

WATERFALL_SERIES: dict[str, str] = {
    "base":  "基准",
    "value": "变化量",
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def col_label(col: str) -> str:
    """Return the Chinese display label for an API column name.

    Falls back to the raw column name when no mapping exists — unknown fields
    are still rendered (just untranslated) so nothing silently disappears.
    """
    return COLUMN_LABELS.get(col, col)


def metric_label(metric: str) -> str:
    """Return the Chinese label for a stats metric key (mean, std, …).

    Falls back to the raw key when no mapping exists.
    """
    return METRIC_LABELS.get(metric, metric)


def resolve_col_label(endpoint_name: str | None, col: str) -> str:
    """Endpoint-aware Chinese label resolver (P2.3b).

    Resolution order:
      1. Per-endpoint override — ``endpoint.label_for(col)`` from
         ``api_registry.field_schema``'s 4th element.
      2. Global ``COLUMN_LABELS`` map (backward-compatible default).
      3. The raw column name (passthrough — same behaviour as ``col_label``).

    Pass ``endpoint_name=None`` to skip step 1, matching legacy ``col_label``
    callers that don't yet thread endpoint context.
    """
    if endpoint_name:
        # Imported lazily — api_registry imports this module's siblings only,
        # but importing api_registry at module load would still be a one-way
        # dependency; lazy is safer in case future restructures introduce a
        # cycle.
        from backend.agent.api_registry import BY_NAME

        ep = BY_NAME.get(endpoint_name)
        if ep is not None:
            override = ep.label_for(col)
            if override:
                return override
    return COLUMN_LABELS.get(col, col)
