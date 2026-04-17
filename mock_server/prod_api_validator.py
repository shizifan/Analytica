#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
prod_api_validator.py
=====================
港口司南生产环境 API 验证脚本
- 以 mock_server_all.py 为唯一权威来源
- Python 3.7.9 兼容 | 仅依赖 requests + stdlib
- 验证: 路径可达、Token 认证、入参、出参结构、数据样例
- 同步: 自动解析 mock_server_all.py 补全缺失 API 定义
- 校验: 入参签名交叉校验（与 mock 函数参数对比）
- 对照: 生产 vs Mock 响应数据结构对照报告
- 输出: JSON 报告文件

用法:
    # 基础验证
    python prod_api_validator.py [--base-url URL] [--output FILE] [--timeout SEC]
                                 [--domain D1|D2|..] [--fail-fast]
    # 自动补全 + 验证
    python prod_api_validator.py --sync-mock ./mock_server_all.py
    # 仅查看差异（不实际调用）
    python prod_api_validator.py --sync-mock ./mock_server_all.py --dry-run-sync
    # 对照模式（需 mock 服务运行）
    python prod_api_validator.py --sync-mock ./mock_server_all.py --compare-mock
"""
from __future__ import print_function

import sys
import json
import time
import datetime
import argparse
import os
import re
import ast

try:
    import requests
except ImportError:
    print("[FATAL] requests not installed. pip install requests")
    sys.exit(1)

# Suppress SSL warnings for self-signed certificates
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "https://10.29.212.24:81"
DEFAULT_TIMEOUT = 15
DEFAULT_OUTPUT = "api_validation_report_{ts}.json"

# ---------------------------------------------------------------------------
# Known categorical/enum field names for business semantics comparison
# ---------------------------------------------------------------------------
KNOWN_CATEGORICAL_FIELDS = {
    "regionName", "businessType", "cargoType", "companyName",
    "shipType", "shipStatus", "controlType", "status",
    "assetType", "assetTypeName", "ownerZone", "zoneName",
    "cooperationLevel", "creditLevel", "customerType",
    "meetingType", "motionStatus", "businessSegment",
    "changeType", "position", "withdrawalType",
    "businessScope", "renewalStatus", "riskLevel",
    "cargoCategoryName", "projectCurrentStage", "investProjectType",
    "investProjectStatus", "yianZt", "orgName",
}

# Patterns that indicate a field is NOT categorical (IDs, timestamps, etc.)
_SKIP_FIELD_PATTERNS = (
    "Id", "Code", "Time", "Date", "Stamp", "traceId", "UUID",
    "uuid", "No", "Serial", "Hash",
)

# ---------------------------------------------------------------------------
# Multi-variant parameter enrichment
# Two mechanisms:
#   1) PARAM_VARIANTS  – single-key alternatives (one param changes at a time)
#   2) LINKED_VARIANTS – multi-key groups that change together (date ranges, etc.)
# Each API keeps its base params as variant 0, then extra variants follow.
# ---------------------------------------------------------------------------

# ── Single-key alternatives ──
PARAM_VARIANTS = {
    # -- Annual --
    "dateYear":  ["2025", "2024", "2023"],
    "currYear":  ["2025", "2024", "2023"],
    # -- Monthly --
    "dateMonth": [
        "2026-01", "2026-02", "2025-12", "2025-06", "2025-03", "2025-01",
    ],
    "preDateMonth": ["2025-06", "2024-12"],
    # -- date (format-dependent) --
    "date": {
        "YYYY":       ["2025", "2024"],
        "YYYY-MM":    [
            "2026-01", "2026-02", "2025-12", "2025-09", "2025-06", "2025-03",
        ],
        "YYYY-MM-DD": [
            "2026-03-15", "2026-02-15", "2026-01-15",
            "2025-12-15", "2025-09-15", "2025-06-15",
        ],
    },
    # -- Equipment / asset --
    "secondLevelClassName": ["岸桥", "门机"],
    "type":   ["1", "2"],
    "flag":   ["0"],
    # -- Region / org --
    "ownerZone":       ["全港"],
    "ownerLgZoneName": ["全港"],
    "assetOwnerZone":  ["全港"],
    # -- Pagination --
    "pageNo": ["2"],
    # -- Business type --
    "businessSegment": ["集装箱", "散杂货", "油化品", "商品车"],
    "businessType":    ["集装箱", "散杂货"],
}

# ── Linked-key groups (all specified keys must exist in api params) ──
# Each group is: { trigger_keys: [...], variants: [ {k: v, ...}, ... ] }
LINKED_VARIANTS = [
    # --- startDate + endDate ranges ---
    {
        "trigger_keys": ["startDate", "endDate"],
        "variants": [
            # 2026 quarters
            {"startDate": "2026-01-01", "endDate": "2026-01-31"},
            {"startDate": "2026-01-01", "endDate": "2026-02-28"},
            {"startDate": "2026-02-01", "endDate": "2026-03-31"},
            # 2025 full year & halves
            {"startDate": "2025-01-01", "endDate": "2025-12-31"},
            {"startDate": "2025-01-01", "endDate": "2025-06-30"},
            {"startDate": "2025-07-01", "endDate": "2025-12-31"},
            # 2025 quarters
            {"startDate": "2025-01-01", "endDate": "2025-03-31"},
            {"startDate": "2025-04-01", "endDate": "2025-06-30"},
            {"startDate": "2025-07-01", "endDate": "2025-09-30"},
            {"startDate": "2025-10-01", "endDate": "2025-12-31"},
            # 2024
            {"startDate": "2024-01-01", "endDate": "2024-12-31"},
            {"startDate": "2024-01-01", "endDate": "2024-06-30"},
        ],
    },
    # --- startMonth + endMonth ranges ---
    {
        "trigger_keys": ["startMonth", "endMonth"],
        "variants": [
            {"startMonth": "2025-01", "endMonth": "2025-12"},
            {"startMonth": "2025-01", "endMonth": "2025-06"},
            {"startMonth": "2025-07", "endMonth": "2025-12"},
            {"startMonth": "2025-01", "endMonth": "2025-03"},
            {"startMonth": "2024-01", "endMonth": "2024-12"},
            {"startMonth": "2026-01", "endMonth": "2026-01"},
            {"startMonth": "2026-01", "endMonth": "2026-02"},
        ],
    },
    # --- curDateYear + yearDateYear pairs ---
    {
        "trigger_keys": ["curDateYear", "yearDateYear"],
        "variants": [
            {"curDateYear": "2025", "yearDateYear": "2024"},
            {"curDateYear": "2024", "yearDateYear": "2023"},
        ],
    },
    # --- currYear + preYear pairs ---
    {
        "trigger_keys": ["currYear", "preYear"],
        "variants": [
            {"currYear": "2025", "preYear": "2024"},
            {"currYear": 2025,   "preYear": 2024},
            {"currYear": "2024", "preYear": "2023"},
            {"currYear": 2024,   "preYear": 2023},
        ],
    },
    # --- curDateMonth + yearDateMonth pairs ---
    {
        "trigger_keys": ["curDateMonth", "yearDateMonth"],
        "variants": [
            {"curDateMonth": "2026-01", "yearDateMonth": "2025-01"},
            {"curDateMonth": "2026-02", "yearDateMonth": "2025-02"},
            {"curDateMonth": "2025-12", "yearDateMonth": "2024-12"},
            {"curDateMonth": "2025-06", "yearDateMonth": "2024-06"},
            {"curDateMonth": "2025-03", "yearDateMonth": "2024-03"},
        ],
    },
    # --- dateYear + preYear pairs ---
    {
        "trigger_keys": ["dateYear", "preYear"],
        "variants": [
            {"dateYear": "2025", "preYear": "2024"},
            {"dateYear": "2024", "preYear": "2023"},
        ],
    },
    # --- dateMonth + preDateMonth pairs ---
    {
        "trigger_keys": ["dateMonth", "preDateMonth"],
        "variants": [
            {"dateMonth": "2026-01", "preDateMonth": "2025-01"},
            {"dateMonth": "2026-02", "preDateMonth": "2025-02"},
            {"dateMonth": "2025-12", "preDateMonth": "2024-12"},
            {"dateMonth": "2025-06", "preDateMonth": "2024-06"},
        ],
    },
    # --- PersonalCenter: date + yoyDate + momDate ---
    {
        "trigger_keys": ["date", "yoyDate", "momDate"],
        "variants": [
            {"date": "2026-03-15", "yoyDate": "2025-03-15", "momDate": "2026-03-14"},
            {"date": "2026-02-15", "yoyDate": "2025-02-15", "momDate": "2026-02-14"},
            {"date": "2026-01-15", "yoyDate": "2025-01-15", "momDate": "2026-01-14"},
            {"date": "2025-12-15", "yoyDate": "2024-12-15", "momDate": "2025-12-14"},
            {"date": "2025-06-15", "yoyDate": "2024-06-15", "momDate": "2025-06-14"},
        ],
    },
    # --- PersonalCenter month: startDate + endDate + yoy + mom 6-key ---
    {
        "trigger_keys": ["startDate", "endDate", "yoyStartDate", "yoyEndDate",
                         "momStartDate", "momEndDate"],
        "variants": [
            {
                "startDate": "2026-02-01", "endDate": "2026-02-28",
                "yoyStartDate": "2025-02-01", "yoyEndDate": "2025-02-28",
                "momStartDate": "2026-01-01", "momEndDate": "2026-01-31",
            },
            {
                "startDate": "2026-01-01", "endDate": "2026-01-31",
                "yoyStartDate": "2025-01-01", "yoyEndDate": "2025-01-31",
                "momStartDate": "2025-12-01", "momEndDate": "2025-12-31",
            },
            {
                "startDate": "2025-12-01", "endDate": "2025-12-31",
                "yoyStartDate": "2024-12-01", "yoyEndDate": "2024-12-31",
                "momStartDate": "2025-11-01", "momEndDate": "2025-11-30",
            },
            {
                "startDate": "2025-06-01", "endDate": "2025-06-30",
                "yoyStartDate": "2024-06-01", "yoyEndDate": "2024-06-30",
                "momStartDate": "2025-05-01", "momEndDate": "2025-05-31",
            },
        ],
    },
    # --- PersonalCenter year: startDate + endDate + yoy 4-key ---
    {
        "trigger_keys": ["startDate", "endDate", "yoyStartDate", "yoyEndDate"],
        "variants": [
            {
                "startDate": "2025-01-01", "endDate": "2025-12-31",
                "yoyStartDate": "2024-01-01", "yoyEndDate": "2024-12-31",
            },
            {
                "startDate": "2025-01-01", "endDate": "2025-06-30",
                "yoyStartDate": "2024-01-01", "yoyEndDate": "2024-06-30",
            },
            {
                "startDate": "2024-01-01", "endDate": "2024-12-31",
                "yoyStartDate": "2023-01-01", "yoyEndDate": "2023-12-31",
            },
        ],
    },
    # --- statDate + endDate (泊位占用率) ---
    {
        "trigger_keys": ["statDate", "endDate"],
        "variants": [
            {"statDate": "2026-01-01", "endDate": "2026-01-31"},
            {"statDate": "2026-02-01", "endDate": "2026-02-28"},
            {"statDate": "2025-01-01", "endDate": "2025-12-31"},
            {"statDate": "2025-01-01", "endDate": "2025-06-30"},
            {"statDate": "2025-07-01", "endDate": "2025-12-31"},
            {"statDate": "2025-01-01", "endDate": "2025-03-31"},
        ],
    },
]


def _detect_date_format(val):
    """Detect the date format pattern for 'date' param variants."""
    if val is None:
        return None
    s = str(val)
    if len(s) == 4 and s.isdigit():
        return "YYYY"
    if len(s) == 7 and s[4:5] == "-":
        return "YYYY-MM"
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        return "YYYY-MM-DD"
    return None


def _combo_key(params):
    """Hashable key for de-duplication of param combinations."""
    return tuple(sorted(
        (k, str(v)) for k, v in params.items() if v is not None
    ))


def generate_param_variants(api_def):
    """
    Generate parameter variant combinations for an API definition.
    Returns list of (variant_tag, params_dict) tuples.
    Variant 0 ("v0") is always the base params.

    Two-pass generation:
      Pass 1 – LINKED_VARIANTS: multi-key groups that change together.
               Longer trigger lists are matched first (most specific wins).
      Pass 2 – PARAM_VARIANTS:  single-key alternatives, skipping keys
               already covered by a linked group.
    """
    base_params = api_def.get("params", {})
    base_keys = set(base_params.keys())
    variants = [("v0", dict(base_params))]

    seen = set()
    seen.add(_combo_key(base_params))

    vid = 1
    covered_keys = set()  # keys handled by linked groups

    # ── Pass 1: linked groups (sorted longest trigger first) ──
    for group in sorted(LINKED_VARIANTS,
                        key=lambda g: len(g["trigger_keys"]), reverse=True):
        tkeys = group["trigger_keys"]
        if not all(k in base_keys for k in tkeys):
            continue
        # Check this isn't a subset already covered by a longer group
        tset = set(tkeys)
        if tset <= covered_keys:
            continue
        covered_keys |= tset

        for gvar in group["variants"]:
            new_params = dict(base_params)
            skip = False
            for gk, gv in gvar.items():
                if gk not in base_keys:
                    skip = True
                    break
                new_params[gk] = gv
            if skip:
                continue
            ck = _combo_key(new_params)
            if ck in seen:
                continue
            seen.add(ck)
            variants.append(("v%d" % vid, new_params))
            vid += 1

    # ── Pass 2: single-key alternatives ──
    for param_key, alt_values in PARAM_VARIANTS.items():
        if param_key not in base_keys:
            continue
        if param_key in covered_keys:
            continue  # already handled by linked group
        base_val = base_params[param_key]

        # Handle 'date' with format-dependent alternatives
        if isinstance(alt_values, dict):
            fmt = _detect_date_format(base_val)
            if fmt and fmt in alt_values:
                alt_values = alt_values[fmt]
            else:
                continue

        for alt_val in alt_values:
            if str(alt_val) == str(base_val):
                continue
            new_params = dict(base_params)
            new_params[param_key] = alt_val

            # Coherent paired adjustments for unpaired year/month params
            if param_key == "dateYear" and "preYear" in new_params \
                    and "preYear" not in covered_keys:
                try:
                    new_params["preYear"] = str(int(alt_val) - 1)
                except (ValueError, TypeError):
                    pass
            elif param_key == "currYear" and "preYear" in new_params \
                    and "preYear" not in covered_keys:
                try:
                    new_params["preYear"] = type(new_params["preYear"])(
                        int(alt_val) - 1)
                except (ValueError, TypeError):
                    pass

            ck = _combo_key(new_params)
            if ck in seen:
                continue
            seen.add(ck)
            variants.append(("v%d" % vid, new_params))
            vid += 1

    return variants

# ---------------------------------------------------------------------------
# 214 Business API Definitions
# Extracted from mock_server/mock_server_all.py
# Each entry: path, token, domain, intent, params (sample values for required)
# params value=None means optional (will be omitted)
# ---------------------------------------------------------------------------
API_DEFS = [
    {
        "path": "/api/gateway/getWeatherForecast",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF74113C28A028CE867EA8B03F4C4ADC66",
        "domain": "D1",
        "intent": "查询各港区未来5天天气预报（天气/温度/风速/湿度）",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getRealTimeWeather",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFF04C3E3A6F4A442C0DA5C671950A3663",
        "domain": "D1",
        "intent": "查询各港区当前实时气象（温度/风速/能见度/浪高）",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getTrafficControl",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF071FCB360EEA8B8BF13A1D6EC27DC9A8",
        "domain": "D1",
        "intent": "查询当前航道交通管制信息（大风封航/浓雾限航/演习管制）",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getKeyVesselList",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF9008019B7EA43A0E286EF594A6902FA8",
        "domain": "D1",
        "intent": "查询重点船舶列表（在泊/锚地状态，含船名/货类/到港时间）",
        "params": {
            "shipStatus": "D",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getThroughputAndTargetThroughputTon",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF36EF1D63A0571DAB2FB2D987C65E04E7",
        "domain": "D1",
        "intent": "查询年度吞吐量实际完成值与目标值对比（万吨，含完成率）",
        "params": {
            "dateYear": "2026",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getThroughputAndTargetThroughputTeu",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFE3E2DE79ACFC2153E38AEDAD344AFDFB",
        "domain": "D1",
        "intent": "查询年度集装箱吞吐量实际值与目标值对比（TEU）",
        "params": {
            "dateYear": "2026",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getSingleShipRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF6B02A46F686CB9500CA7DFA7B4097951",
        "domain": "D1",
        "intent": "查询各公司单船效率（作业/小时），按时间段统计",
        "params": {
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getBerthOccupancyRateByRegion",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF14F290450E6728284578455D84402F3C",
        "domain": "D1",
        "intent": "按港区查询泊位占用率及在泊时间统计",
        "params": {
            "startDate": "2026-01-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getBerthOccupancyRateByBusinessType",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFBAF2339B3F17E898B14DD223DF827FFA",
        "domain": "D1",
        "intent": "按业务类型查询泊位占用率",
        "params": {
            "startDate": "2026-01-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getImportantCargoPortInventoryByRegion",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFC22EE6D962755C19E8F936DF84C8E461",
        "domain": "D1",
        "intent": "查询各港区主要货物港存量（铁矿石/煤/粮食/石油/集装箱/商品车）",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getContainerAndVehicleTrade",
        "token": "46F4717D4D36AA272FFC710A28B050F7197F90A4B013C5DDF454DAD5F5842FAD",
        "domain": "D1",
        "intent": "查询港区集装箱（内外贸）和商品车（进出口）数量",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getThroughputAnalysisNonContainer",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFAAC07F3B25F0739AFBC9750B349B64BB",
        "domain": "D1",
        "intent": "查询年度非集装箱吞吐量（干散/液散/件杂/滚装）",
        "params": {
            "dateYear": 2026,
        },
    },
    {
        "path": "/api/gateway/getThroughputAnalysisContainer",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF339A4372C3D4155FF9DEFEE3F271D3A2",
        "domain": "D1",
        "intent": "查询年度集装箱吞吐量（内外贸/空重箱）",
        "params": {
            "dateYear": 2026,
        },
    },
    {
        "path": "/api/gateway/getThroughputAnalysisByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF055A39AC6F90C5B49F83A45D1536137F",
        "domain": "D1",
        "intent": "查询年度各月吞吐量趋势（当年vs上年同期月度对比）",
        "params": {
            "dateYear": "2026",
            "preYear": "2025",
        },
    },
    {
        "path": "/api/gateway/getContainerThroughputAnalysisByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFFE95E6F21D4B554F35E3DA30CBBB7771",
        "domain": "D1",
        "intent": "查询集装箱吞吐量年度月趋势（当年vs上年，TEU）",
        "params": {
            "dateYear": "2026",
            "preYear": "2025",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getOilsChemBreakBulkByBusinessType",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF099C3B4FC01B72ABA3B25B0D1AB7F49F",
        "domain": "D1",
        "intent": "查询各港区油化品和散杂货吞吐量（按月，支持同比/环比切换）",
        "params": {
            "flag": "0",
            "dateMonth": "2026-03",
            "businessType": "\u96c6\u88c5\u7bb1",
        },
    },
    {
        "path": "/api/gateway/getRoroByBusinessType",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFB6563F3278BD411C6FF7824AC68DDD9D",
        "domain": "D1",
        "intent": "查询各港区滚装（商品车）吞吐量",
        "params": {
            "flag": "0",
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getContainerByBusinessType",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF901ACDCAFE6E39A5B2519571CE335EE2",
        "domain": "D1",
        "intent": "查询各港区集装箱吞吐量（TEU，按月）",
        "params": {
            "flag": "0",
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getCompanyStatisticsBusinessType",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF54218CCBF43E144BA0FD29243A60A4CA",
        "domain": "D1",
        "intent": "按公司查询各业务类型吞吐量（集装箱/散货/油化/滚装）",
        "params": {
            "flag": "0",
            "dateMonth": "2026-03",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getThroughputAnalysisYoyMomByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFCCFD062E9BF3D205BD4FE8F36D552458",
        "domain": "D1",
        "intent": "查询指定年份吞吐量同比/环比（年度层面）",
        "params": {
            "date": "2026-01-01",
        },
    },
    {
        "path": "/api/gateway/getContainerAnalysisYoyMomByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFA57695EE933FCD13AF102D89D33E4546",
        "domain": "D1",
        "intent": "查询集装箱吞吐量同比/环比（年度）",
        "params": {
            "date": "2026-01-01",
        },
    },
    {
        "path": "/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFCE58B93530572AEDA522A3E39860C4F8",
        "domain": "D1",
        "intent": "查询各业务类型吞吐量同比/环比（年度，可按港区筛选）",
        "params": {
            "date": "2026-01-01",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getThroughputAnalysisYoyMomByMonth",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF9FA01B2532CBBBDE2833EFD9268DE42C",
        "domain": "D1",
        "intent": "查询指定月份吞吐量同比/环比（月度层面）",
        "params": {
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getThroughputAnalysisYoyMomByDay",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFEC7D5A5AD631828C8B77B30B67B15CE2",
        "domain": "D1",
        "intent": "查询指定日期吞吐量同比/环比（日层面）",
        "params": {
            "date": "2026-04-15",
        },
    },
    {
        "path": "/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByMonth",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF84AB2801AC63E68CC044D558E8412210",
        "domain": "D1",
        "intent": "查询各业务类型吞吐量同比/环比（月度）",
        "params": {
            "dateMonth": "2026-03",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByDay",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF77D88A6BCD6377AA90CC5B8BDEA25AD0",
        "domain": "D1",
        "intent": "查询各业务类型吞吐量同比/环比（日度）",
        "params": {
            "date": "2026-04-15",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getShipStatisticsByRegion",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFFB38B32DAB37592AD95AD094ED5A90D2",
        "domain": "D1",
        "intent": "按港区+船舶类型统计在港船舶数量（集装箱船/散货船/油轮等）",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getShipStatisticsByBusinessType",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF5EC914F6A0930D2E03425B1A2E395C62",
        "domain": "D1",
        "intent": "按业务类型统计在港船舶数量（集装箱/散杂货/油化品/商品车）",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getBusinessSegmentBranch",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF53B6F4D6E5DE6A9E5DB7280DD9A39963",
        "domain": "D1",
        "intent": "查询港区下各公司的业务分支组织关系",
        "params": {
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getPortCompanyThroughput",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFE6226DDFF0D4D31756D2324E991704F2",
        "domain": "D1",
        "intent": "查询各公司指定月份吞吐量及同比",
        "params": {
            "date": "2026-04-15",
            "cmpName": "全部",
        },
    },
    {
        "path": "/api/gateway/getThroughputMonthlyTrend",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF40FE291B51D21D9EF1A45133EEA048DD",
        "domain": "D1",
        "intent": "查询公司全年月度吞吐量趋势（含同比）",
        "params": {
            "dateYear": "2026",
            "cmpName": "全部",
        },
    },
    {
        "path": "/api/gateway/getDailyPortInventoryData",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFC98145473E3E0E9DCCC35CF41858A94A",
        "domain": "D1",
        "intent": "查询指定公司指定日期的港存快照（各货类汇总+库容率）",
        "params": {
            "dateCur": "2026-04-15",
            "cmpName": "全部",
        },
    },
    {
        "path": "/api/gateway/getPortInventoryTrend",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF1268DD9BBE8AD8EE8690A057B3095C80",
        "domain": "D1",
        "intent": "查询公司全年各月港存趋势（平均/最高/最低）",
        "params": {
            "dateYear": "2026",
            "cmpName": "全部",
        },
    },
    {
        "path": "/api/gateway/getVesselOperationEfficiency",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF5A358CFC3EEB6EBB46FEA5F1A7326954",
        "domain": "D1",
        "intent": "查询公司船舶作业效率（单船效率平均/最高/最低，按月区间）",
        "params": {
            "cmpName": "全部",
            "startMonth": "2026-01",
            "endMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getVesselOperationEfficiencyTrend",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF6D9A32EEE331EDA3FE12D12154C2B6BB",
        "domain": "D1",
        "intent": "查询月度船舶作业效率趋势（集装箱/散货/油品效率曲线）",
        "params": {
            "startMonth": "2026-01",
            "endMonth": "2026-03",
            "cmpName": "全部",
        },
    },
    {
        "path": "/api/gateway/getBerthOccupancyRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF745694A576CFB5803246AB4FDB7B6D77",
        "domain": "D1",
        "intent": "查询指定公司在时间段内的泊位占用率",
        "params": {
            "mainOrgCode": None,
            "statDate": "2026-03-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getTotalBerthDuration",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFA89C371E602AA48399CB5B88AF6FB552",
        "domain": "D1",
        "intent": "查询机构靠泊总时长和占用率（指定时间段）",
        "params": {
            "orgName": None,
            "statDate": "2026-03-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getBerthList",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF0A1FAF0E78BC80A3EEA53AE7523963AF",
        "domain": "D1",
        "intent": "查询公司泊位列表及当前状态（在泊/离泊/计划）",
        "params": {
            "cmpName": "全部",
        },
    },
    {
        "path": "/api/gateway/getProductViewShipOperationRateAvg",
        "token": "46F4717D4D36AA272FFC710A28B050F7F26B1CD4A48F4BC77D559E004AC44F3E",
        "domain": "D1",
        "intent": "查询港口平均船舶作业效率（集装箱/散货/油品/滚装各业务类型）",
        "params": {
            "startDate": "2026-01-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getProductViewShipOperationRateTrend",
        "token": "46F4717D4D36AA272FFC710A28B050F78B6A6E23774631F0FD52320E8B2AD34F",
        "domain": "D1",
        "intent": "查询船舶作业效率月度趋势（集装箱/散货/油品曲线）",
        "params": {
            "startDate": "2026-01-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getPersonalCenterCargoThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F729E244CB2588799EEFED149F923B1AA3",
        "domain": "D1",
        "intent": "查询指定日期吞吐量及与环比日的对比（个人中心首页）",
        "params": {
            "date": "2026-04-15",
            "momDate": "2026-04-14",
            "yoyDate": "2025-04-15",
        },
    },
    {
        "path": "/api/gateway/getPersonalCenterMonthCargoThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F72A7E607144CC523844CF35636EA6D3EF",
        "domain": "D1",
        "intent": "查询截至某日当月累计吞吐量及与环比月的对比",
        "params": {
            "endDate": "2026-03-31",
            "momEndDate": "2026-02-28",
            "yoyEndDate": "2025-03-31",
            "momStartDate": "2026-02-01",
            "startDate": "2026-03-01",
            "yoyStartDate": "2025-03-01",
        },
    },
    {
        "path": "/api/gateway/getPersonalCenterYearCargoThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F7CE804B7E281864F71D561333523DCD53",
        "domain": "D1",
        "intent": "查询截至某日年累计吞吐量及同比",
        "params": {
            "endDate": "2026-03-31",
            "yoyEndDate": "2025-03-31",
            "startDate": "2026-01-01",
            "yoyStartDate": "2025-01-01",
        },
    },
    {
        "path": "/api/gateway/getPersonalCenterYearCargoThroughputTrend",
        "token": "46F4717D4D36AA272FFC710A28B050F7652D8F58597E2197013B0FBA6CBE077D",
        "domain": "D1",
        "intent": "查询年度各月吞吐量趋势（含累计）",
        "params": {
            "startDate": "2026-01-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getProdShipDynNum",
        "token": "46F4717D4D36AA272FFC710A28B050F781005CF409233C481A18A5158427C8B2",
        "domain": "D1",
        "intent": "查询全港船舶动态数量汇总（在泊/锚地/进港/出港总数）",
        "params": {},
    },
    {
        "path": "/api/gateway/getProdShipDesc",
        "token": "46F4717D4D36AA272FFC710A28B050F79973F08D1DE81B74C87D892E1EAA2388",
        "domain": "D1",
        "intent": "查询重点船舶和锚地船舶的描述性摘要（驾驶舱展示用）",
        "params": {},
    },
    {
        "path": "/api/gateway/getMonthlyThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F7236C5F6DA2419BC3DC2C09B797335E03",
        "domain": "D2",
        "intent": "查询当月吞吐量及与去年同期对比（市场商务驾驶舱，可按港区筛选）",
        "params": {
            "curDateMonth": "2026-03",
            "yearDateMonth": "2025-03",
            "zoneName": None,
        },
    },
    {
        "path": "/api/gateway/getMonthlyZoneThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F790AA48728EC03C7F4E244B3EC6A9734F",
        "domain": "D2",
        "intent": "查询各港区当月吞吐量分布及占比",
        "params": {
            "curDateMonth": "2026-03",
            "yearDateMonth": "2025-03",
            "zoneName": None,
        },
    },
    {
        "path": "/api/gateway/getCumulativeThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F716A59EFC96F1CC26836124CCAB3FFDE5",
        "domain": "D2",
        "intent": "查询年累计吞吐量及同比（内外贸分拆）",
        "params": {
            "curDateYear": "2026",
            "yearDateYear": "2025",
            "zoneName": None,
        },
    },
    {
        "path": "/api/gateway/getCumulativeZoneThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F7369902D9AF69FB5D32520C0CC19E1B08",
        "domain": "D2",
        "intent": "查询各港区年累计吞吐量及占比",
        "params": {
            "curDateYear": "2026",
            "yearDateYear": "2025",
            "zoneName": None,
        },
    },
    {
        "path": "/api/gateway/getCurrentBusinessSegmentThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F7D29D3FBE29DBF8A3C8D41CD705FBDFED",
        "domain": "D2",
        "intent": "查询当月各业务板块（集装箱/散杂货/油化品/商品车）吞吐量",
        "params": {
            "curDateMonth": "2026-03",
            "yearDateMonth": "2025-03",
            "zoneName": None,
        },
    },
    {
        "path": "/api/gateway/getCumulativeBusinessSegmentThroughput",
        "token": "46F4717D4D36AA272FFC710A28B050F7C476705DD6A00BEAAEC8B80621EE652B",
        "domain": "D2",
        "intent": "查询年累计各业务板块吞吐量",
        "params": {
            "curDateYear": "2026",
            "yearDateYear": "2025",
            "zoneName": None,
        },
    },
    {
        "path": "/api/gateway/getTrendChart",
        "token": "46F4717D4D36AA272FFC710A28B050F7E5BF0B16C7D1935D19088A3C037AEB7C",
        "domain": "D2",
        "intent": "查询指定业务板块月度吞吐量趋势图数据（市场商务版）",
        "params": {
            "businessSegment": "集装箱",
            "startDate": "2026-01-01",
            "endDate": "2026-03-31",
        },
    },
    {
        "path": "/api/gateway/getCumulativeTrendChart",
        "token": "46F4717D4D36AA272FFC710A28B050F7469D084A0B2C03C0DE08C40AB0D97613",
        "domain": "D2",
        "intent": "查询业务板块年累计吞吐量趋势（含月度/累计双序列）",
        "params": {
            "businessSegment": "集装箱",
            "curDateYear": "2026",
            "yearDateYear": "2025",
        },
    },
    {
        "path": "/api/gateway/getKeyEnterprise",
        "token": "46F4717D4D36AA272FFC710A28B050F776F1B162E6335D64AAAFA9740C64210E",
        "domain": "D2",
        "intent": "查询当月重点企业吞吐量排名（Top10，按业务板块）",
        "params": {
            "businessSegment": "集装箱",
            "curDateMonth": "2026-03",
            "yearDateMonth": "2025-03",
        },
    },
    {
        "path": "/api/gateway/getCumulativeKeyEnterprise",
        "token": "46F4717D4D36AA272FFC710A28B050F7EE44F1CBC29FAB99EBB5F9D67BBE9B94",
        "domain": "D2",
        "intent": "查询年累计重点企业吞吐量排名",
        "params": {
            "businessSegment": "集装箱",
            "curDateYear": "2026",
            "yearDateYear": "2025",
        },
    },
    {
        "path": "/api/gateway/getActualPerformance",
        "token": "C2B8184E822306ABE43FE46C608F0A100DD0662687EC7F01E315BA2FD5BAF570",
        "domain": "D1",
        "intent": "查询昨日吞吐量实际完成情况及环比（驾驶舱首页）",
        "params": {
            "yesterday": "2026-04-15",
            "lastMonthDay": "2026-03-15",
        },
    },
    {
        "path": "/api/gateway/getMonthlyTrendThroughput",
        "token": "C2B8184E822306ABE43FE46C608F0A1031CDB2DF4DE82B40F2051E64EBD4EE95",
        "domain": "D1",
        "intent": "查询指定时间段月度吞吐量趋势序列",
        "params": {
            "endDate": "2026-03-31",
            "startDate": "2026-01-01",
        },
    },
    {
        "path": "/api/gateway/getlnportDispatchPort",
        "token": "C2B8184E822306ABE43FE46C608F0A106510CE9F3DBA05F4AAFD73B85D74BF23",
        "domain": "D1",
        "intent": "查询指定日期各港区日班/夜班吞吐量调度数据",
        "params": {
            "dispatchDate": "2026-04-15",
        },
    },
    {
        "path": "/api/gateway/getlnportDispatchWharf",
        "token": "C2B8184E822306ABE43FE46C608F0A10AC420D5E03301DDC11D20A94F5966410",
        "domain": "D1",
        "intent": "查询指定日期各码头日班/夜班吞吐量调度数据",
        "params": {
            "dispatchDate": "2026-04-15",
        },
    },
    {
        "path": "/api/gateway/getNetValueDistribution",
        "token": "C2B8184E822306ABE43FE46C608F0A10189E6C3733DC809B27C37A77AD204DFD",
        "domain": "D5",
        "intent": "查询各港区资产净值区间分布",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getCustomerQty",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9AC22EE6D962755C19E8F936DF84C8E461",
        "domain": "D3",
        "intent": "查询客户总数量（含活跃/战略/新增统计）",
        "params": {},
    },
    {
        "path": "/api/gateway/getCustomerTypeAnalysis",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A1CEC8408C1DEDF31B103C4E5F6577301",
        "domain": "D3",
        "intent": "查询客户类型结构分析（货主/船公司/代理等分类及占比）",
        "params": {},
    },
    {
        "path": "/api/gateway/getCustomerFieldAnalysis",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A530A3BCF31FF78888C4F204FADA7A5D6",
        "domain": "D3",
        "intent": "查询客户所属行业分析（钢铁/能源/汽车/粮食等）",
        "params": {},
    },
    {
        "path": "/api/gateway/getStrategicCustomers",
        "token": "B1DCE83DF425C3E5A76104B5E481F535C9A2EA179B615575BEE438A7D07C5CEC",
        "domain": "D3",
        "intent": "查询战略客户名单及合作信息（级别/年份/合同状态）",
        "params": {},
    },
    {
        "path": "/api/gateway/getStrategicClientsEnterprises",
        "token": "B1DCE83DF425C3E5A76104B5E481F535AAB30E46CDBA45A3C274179EBA957318",
        "domain": "D3",
        "intent": "查询指定战略客户的关联企业及合作方式",
        "params": {
            "displayoCde": None,
        },
    },
    {
        "path": "/api/gateway/getCustomerCredit",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A55E1815EBCE44F65464E7163245AB1AD",
        "domain": "D3",
        "intent": "查询客户信用级别和授信额度（已用/可用）",
        "params": {
            "orgName": None,
            "customerName": None,
            "gradeResult": None,
        },
    },
    {
        "path": "/api/gateway/getCumulativeContributionTrend",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A1268DD9BBE8AD8EE8690A057B3095C80",
        "domain": "D3",
        "intent": "查询多年战略客户累计贡献趋势（历年对比）",
        "params": {
            "startYear": "2022",
            "endYear": "2026",
            "contributionType": "吞吐量",
        },
    },
    {
        "path": "/api/gateway/investCorpShareholdingProp",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A84AB2801AC63E68CC044D558E8412210",
        "domain": "D4",
        "intent": "查询投资企业持股比例分布（0-20%/20-50%/50%以上/全资）",
        "params": {},
    },
    {
        "path": "/api/gateway/getMeetingInfo",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A77D88A6BCD6377AA90CC5B8BDEA25AD0",
        "domain": "D4",
        "intent": "查询指定月份董事会/监事会/股东大会召开数量及待处理议案",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getMeetDetail",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9AFB38B32DAB37592AD95AD094ED5A90D2",
        "domain": "D4",
        "intent": "查询指定月份会议议案明细（按议案状态筛选）",
        "params": {
            "date": "2026-03",
            "yianZt": None,
        },
    },
    {
        "path": "/api/gateway/getNewEnterprise",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A5EC914F6A0930D2E03425B1A2E395C62",
        "domain": "D4",
        "intent": "查询年内新设企业信息（注册时间/注册资本/业务范围）",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getWithdrawalInfo",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9AE6226DDFF0D4D31756D2324E991704F2",
        "domain": "D4",
        "intent": "查询年内退出/注销企业信息",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getBusinessExpirationInfo",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A40FE291B51D21D9EF1A45133EEA048DD",
        "domain": "D4",
        "intent": "查询营业执照即将到期的企业及续期状态",
        "params": {
            "date": "2026-04-15",
        },
    },
    {
        "path": "/api/gateway/getSupervisorIncidentInfo",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9AC98145473E3E0E9DCCC35CF41858A94A",
        "domain": "D4",
        "intent": "查询监管人员变动信息（新任/离任/调任）",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getTotalssets",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A5A358CFC3EEB6EBB46FEA5F1A7326954",
        "domain": "D5",
        "intent": "查询指定港区资产总数量（实物资产+金融资产）",
        "params": {
            "assetOwnerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getAssetValue",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A6D9A32EEE331EDA3FE12D12154C2B6BB",
        "domain": "D5",
        "intent": "查询港区资产原值和净值（含折旧率）",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getMainAssetsInfo",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A745694A576CFB5803246AB4FDB7B6D77",
        "domain": "D5",
        "intent": "查询港区主要资产类别数量（设备/设施/房屋/土地）",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getRealAssetsDistribution",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9AA89C371E602AA48399CB5B88AF6FB552",
        "domain": "D5",
        "intent": "查询实物资产类型分布（设备/设施/房屋/土地数量占比）",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getOriginalValueDistribution",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A0A1FAF0E78BC80A3EEA53AE7523963AF",
        "domain": "D5",
        "intent": "查询各类资产原值分布",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getHistoricalTrends",
        "token": "B1DCE83DF425C3E5A76104B5E481F53514F290450E6728284578455D84402F3C",
        "domain": "D5",
        "intent": "查询港区资产历年变化趋势（2022-2026，数量/原值/净值/新增/报废）",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getRealAssetQty",
        "token": "B1DCE83DF425C3E5A76104B5E481F535894453073A19C32022C1F32E220FBB77",
        "domain": "D5",
        "intent": "查询本年新增实物资产数量和价值",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getMothballingRealAssetQty",
        "token": "B1DCE83DF425C3E5A76104B5E481F535885417B2B988907C1554AC57E7AEB928",
        "domain": "D5",
        "intent": "查询本年报废/封存资产数量和价值",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getTrendNewAssets",
        "token": "B1DCE83DF425C3E5A76104B5E481F5356EAB6B8E302B01A4503C920A330EDA7B",
        "domain": "D5",
        "intent": "查询近5年新增资产趋势（数量+价值）",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getOriginalQuantity",
        "token": "B1DCE83DF425C3E5A76104B5E481F535715518B02C8B5170FC6A012FCC1B91B3",
        "domain": "D5",
        "intent": "查询本年新增资产原始数量和原值",
        "params": {
            "ownerZone": "全港",
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getTrendScrappedAssets",
        "token": "B1DCE83DF425C3E5A76104B5E481F53555E1815EBCE44F65464E7163245AB1AD",
        "domain": "D5",
        "intent": "查询近5年报废资产趋势",
        "params": {
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getOriginalValueScrappedQuantity",
        "token": "B1DCE83DF425C3E5A76104B5E481F535BAF2339B3F17E898B14DD223DF827FFA",
        "domain": "D5",
        "intent": "查询本年报废资产数量及原值",
        "params": {
            "ownerZone": "全港",
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getNewAssetTransparentAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F535C22EE6D962755C19E8F936DF84C8E461",
        "domain": "D5",
        "intent": "查询各公司新增资产穿透分析（数量/价值/主要类别）",
        "params": {
            "ownerZone": "全港",
            "dateYear": "2026",
            "asseTypeName": "设备",
        },
    },
    {
        "path": "/api/gateway/getScrapAssetTransmitAnalysis",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF24FA64F8B0024177D962D5AA1EFD1C83",
        "domain": "D5",
        "intent": "查询各公司报废资产穿透分析",
        "params": {
            "ownerZone": "全港",
            "dateYear": "2026",
            "asseTypeName": "设备",
        },
    },
    {
        "path": "/api/gateway/getPhysicalAssets",
        "token": "B1DCE83DF425C3E5A76104B5E481F5351CEC8408C1DEDF31B103C4E5F6577301",
        "domain": "D5",
        "intent": "查询全港实物资产汇总（总数量/原值/净值）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getRegionalAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F535530A3BCF31FF78888C4F204FADA7A5D6",
        "domain": "D5",
        "intent": "查询各港区资产数量/原值/净值对比",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getCategoryAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F535055A39AC6F90C5B49F83A45D1536137F",
        "domain": "D5",
        "intent": "查询各类别资产数量/原值/净值（设备/设施/房屋/土地）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getRegionalAnalysisTransparentTransmission",
        "token": "B1DCE83DF425C3E5A76104B5E481F5352B73EC54D2B807CC53938F1D2030F126",
        "domain": "D5",
        "intent": "查询指定港区各类型资产穿透详情",
        "params": {
            "dateYear": "2026",
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getCategoryAnalysisTransparentTransmission",
        "token": "B1DCE83DF425C3E5A76104B5E481F5355EF51BDCE7285517034BF1FA3CE96575",
        "domain": "D5",
        "intent": "查询指定类型资产按港区穿透详情",
        "params": {
            "dateYear": "2026",
            "assetTypeName": "设备",
        },
    },
    {
        "path": "/api/gateway/getHousingAssertAnalysisTransparentTransmission",
        "token": "B1DCE83DF425C3E5A76104B5E481F535AAC07F3B25F0739AFBC9750B349B64BB",
        "domain": "D5",
        "intent": "查询房屋资产穿透分析（按港区/用房类型/面积/价值）",
        "params": {
            "dateYear": "2026",
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getEquipmentAnalysisTransparentTransmissionByFirst",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFAA45BE834636728B28CDA8792D27E028",
        "domain": "D5",
        "intent": "查询设备二级子类穿透分析",
        "params": {
            "dateYear": "2026",
            "assetStatus": "正常",
            "firstLevelClassName": "装卸机械",
        },
    },
    {
        "path": "/api/gateway/getLandMaritimeAnalysisTransparentTransmission",
        "token": "B1DCE83DF425C3E5A76104B5E481F535099C3B4FC01B72ABA3B25B0D1AB7F49F",
        "domain": "D5",
        "intent": "查询土地和海域资产穿透分析（面积/价值按港区）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
        },
    },
    {
        "path": "/api/gateway/getEquipmentFacilityAnalysisYoy",
        "token": "B1DCE83DF425C3E5A76104B5E481F535B6563F3278BD411C6FF7824AC68DDD9D",
        "domain": "D5",
        "intent": "查询设备设施数量和净值同比变化",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getEquipmentFacilityAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F5353655F67A1FD1338ADA22C710B90C6C73",
        "domain": "D5",
        "intent": "查询设备或设施分类分析（type=1设备/type=2设施）",
        "params": {
            "dateYear": "2026",
            "type": "1",
        },
    },
    {
        "path": "/api/gateway/getEquipmentFacilityStatusAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F53505D27D351AF0D990995DBAAD2C535C81",
        "domain": "D5",
        "intent": "查询设备/设施按状态分布（正常/维修/超期/闲置等）",
        "params": {
            "dateYear": "2026",
            "type": "1",
        },
    },
    {
        "path": "/api/gateway/getEquipmentFacilityRegionalAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F53513718C2D92D126102BF7B97E2F0C8D5B",
        "domain": "D5",
        "intent": "查询各港区设备/设施数量和净值分布",
        "params": {
            "dateYear": "2026",
            "type": "1",
        },
    },
    {
        "path": "/api/gateway/getEquipmentFacilityWorthAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F5351F7D263469426656C1065802D56D3D33",
        "domain": "D5",
        "intent": "查询设备/设施净值区间分布",
        "params": {
            "dateYear": "2026",
            "type": "设备",
        },
    },
    {
        "path": "/api/gateway/getHousingAnalysisYoy",
        "token": "B1DCE83DF425C3E5A76104B5E481F53584AB2801AC63E68CC044D558E8412210",
        "domain": "D5",
        "intent": "查询房屋资产同比（数量/面积/净值）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getHousingRegionalAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F53577D88A6BCD6377AA90CC5B8BDEA25AD0",
        "domain": "D5",
        "intent": "查询各港区房屋资产（数量/面积/净值）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getHousingWorthAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F535FB38B32DAB37592AD95AD094ED5A90D2",
        "domain": "D5",
        "intent": "查询房屋资产净值区间分布",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getLandMaritimeAnalysisYoy",
        "token": "B1DCE83DF425C3E5A76104B5E481F5355EC914F6A0930D2E03425B1A2E395C62",
        "domain": "D5",
        "intent": "查询土地海域资产同比（面积/净值）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getLandMaritimeRegionalAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F535E6226DDFF0D4D31756D2324E991704F2",
        "domain": "D5",
        "intent": "查询各港区土地海域面积和净值",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getLandMaritimeWorthAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F53540FE291B51D21D9EF1A45133EEA048DD",
        "domain": "D5",
        "intent": "查询土地海域资产类型价值分析（工业/港口/绿化/海域使用权）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getImportAssertAnalysisList",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF72546B309A06922EC39F4BB351A458B6",
        "domain": "D5",
        "intent": "查询重要资产明细列表（支持多条件筛选，分页）",
        "params": {
            "dateYear": "2026",
            "portCode": None,
            "assetTypeId": None,
            "assetTypeName": None,
            "ownerZone": None,
            "pageNo": 1,
            "pageSize": 20,
        },
    },
    {
        "path": "/api/gateway/getImportAssetWorthAnalysisByOwnerZone",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF7CE12AA23200ED963E27AD5585804ACE",
        "domain": "D5",
        "intent": "查询各港区重要资产净值分析（按净值区间筛选）",
        "params": {
            "dateYear": "2026",
            "type": "设备",
            "minNum": "0",
            "maxNum": "5000",
            "typeName": "设备",
        },
    },
    {
        "path": "/api/gateway/getImportAssetWorthAnalysisByCmpName",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF5A93262256382B148DDB2913D5173AF8",
        "domain": "D5",
        "intent": "查询各公司重要资产净值分析",
        "params": {
            "dateYear": "2026",
            "type": "设备",
            "minNum": "0",
            "maxNum": "5000",
            "ownerZone": "全港",
            "typeName": "设备",
        },
    },
    {
        "path": "/api/gateway/getInvestPlanTypeProjectList",
        "token": "B1DCE83DF425C3E5A76104B5E481F5356CAD71075BC804998E32DCBAE705FBAB",
        "domain": "D6",
        "intent": "查询年度投资计划类型汇总（资本性/成本性/计划外项目数和金额）",
        "params": {
            "ownerLgZoneName": None,
            "currYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getPlanProgressByMonth",
        "token": "B1DCE83DF425C3E5A76104B5E481F535E5BF0B16C7D1935D19088A3C037AEB7C",
        "domain": "D6",
        "intent": "查询年度投资计划月度进度（累计计划vs实际完成）",
        "params": {
            "ownerLgZoneName": "全港",
            "startMonth": "2026-01",
            "endMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/planInvestAndPayYoy",
        "token": "B1DCE83DF425C3E5A76104B5E481F53576F1B162E6335D64AAAFA9740C64210E",
        "domain": "D6",
        "intent": "查询年度投资计划和付款额同比",
        "params": {
            "currYear": 2026,
            "preYear": 2025,
            "ownerLgZoneName": None,
        },
    },
    {
        "path": "/api/gateway/getFinishProgressAndDeliveryRate",
        "token": "B1DCE83DF425C3E5A76104B5E481F535469D084A0B2C03C0DE08C40AB0D97613",
        "domain": "D6",
        "intent": "查询年度投资完成进度和资本项目交付率",
        "params": {
            "ownerLgZoneName": None,
            "currYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getInvestPlanByYear",
        "token": "B1DCE83DF425C3E5A76104B5E481F535EE44F1CBC29FAB99EBB5F9D67BBE9B94",
        "domain": "D6",
        "intent": "查询近5年投资计划和完成情况历年对比",
        "params": {
            "ownerLgZoneName": None,
        },
    },
    {
        "path": "/api/gateway/getCostProjectFinishByYear",
        "token": "B1DCE83DF425C3E5A76104B5E481F535C29FACC7DE6072083C98C69DA4F604A1",
        "domain": "D6",
        "intent": "查询近5年成本性项目完成情况",
        "params": {
            "ownerLgZoneName": None,
        },
    },
    {
        "path": "/api/gateway/getCostProjectYoyList",
        "token": "B1DCE83DF425C3E5A76104B5E481F535F547ABF2303BB47B821552314C106673",
        "domain": "D6",
        "intent": "查询成本性项目数量和金额同比",
        "params": {
            "currYear": 2026,
            "preYear": 2025,
        },
    },
    {
        "path": "/api/gateway/getCostProjectQtyList",
        "token": "B1DCE83DF425C3E5A76104B5E481F535D125D4232784DAA4C46168E583218256",
        "domain": "D6",
        "intent": "查询成本性项目分类数量和金额占比",
        "params": {
            "currYear": 2026,
        },
    },
    {
        "path": "/api/gateway/getCostProjectAmtByOwnerLgZoneName",
        "token": "B1DCE83DF425C3E5A76104B5E481F5354D8F5DB7FA6E4AC31499F1F2468C9EBE",
        "domain": "D6",
        "intent": "查询各港区成本性项目金额（批复/完成/招标）",
        "params": {
            "currYear": 2026,
        },
    },
    {
        "path": "/api/gateway/getCostProjectCurrentStageQtyList",
        "token": "B1DCE83DF425C3E5A76104B5E481F535011F834BFA89826B3221537950206E69",
        "domain": "D6",
        "intent": "查询成本性项目当前阶段数量（立项/招标/施工/竣工等）",
        "params": {
            "currYear": 2026,
            "ownerLgZoneName": None,
        },
    },
    {
        "path": "/api/gateway/getCostProjectQtyByProjectCmp",
        "token": "B1DCE83DF425C3E5A76104B5E481F5350FFB47E0BB36A59FB5C78D10A63B0770",
        "domain": "D6",
        "intent": "查询各公司成本性项目数量和完成情况",
        "params": {
            "dateYear": "2026",
            "zoneName": None,
        },
    },
    {
        "path": "/api/gateway/getInvestAmtList",
        "token": "B1DCE83DF425C3E5A76104B5E481F5351466C3B3412388B980BF57D4D183DAB0",
        "domain": "D6",
        "intent": "查询投资项目金额明细列表（分页，支持多条件筛选）",
        "params": {
            "dateYear": "2026",
            "projectCmp": None,
            "projectName": None,
            "projectNo": None,
            "adminName": None,
            "currentStage": None,
            "zoneName": None,
            "pageNo": 1,
            "pageSize": 20,
        },
    },
    {
        "path": "/api/gateway/getOutOfPlanFinishProgressList",
        "token": "B1DCE83DF425C3E5A76104B5E481F5351022A0ACAFBD961B43C0E83CC320F470",
        "domain": "D6",
        "intent": "查询计划外项目完成进度汇总",
        "params": {
            "dateYear": None,
        },
    },
    {
        "path": "/api/gateway/getOutOfPlanProjectQtyYoy",
        "token": "B1DCE83DF425C3E5A76104B5E481F53572546B309A06922EC39F4BB351A458B6",
        "domain": "D6",
        "intent": "查询计划外项目数量和金额同比",
        "params": {
            "currYear": 2026,
            "preYear": 2025,
        },
    },
    {
        "path": "/api/gateway/getOutOfPlanProjectInvestFinishList",
        "token": "B1DCE83DF425C3E5A76104B5E481F535F26B1CD4A48F4BC77D559E004AC44F3E",
        "domain": "D6",
        "intent": "查询计划外项目近5年投资完成历史",
        "params": {},
    },
    {
        "path": "/api/gateway/getOutOfPlanProjectPayFinishList",
        "token": "B1DCE83DF425C3E5A76104B5E481F5358B6A6E23774631F0FD52320E8B2AD34F",
        "domain": "D6",
        "intent": "查询计划外项目近5年付款完成历史",
        "params": {},
    },
    {
        "path": "/api/gateway/getPlanFinishByZone",
        "token": "B1DCE83DF425C3E5A76104B5E481F535CE804B7E281864F71D561333523DCD53",
        "domain": "D6",
        "intent": "查询各港区投资计划完成情况和交付率",
        "params": {
            "currYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getPlanFinishByProjectType",
        "token": "B1DCE83DF425C3E5A76104B5E481F535652D8F58597E2197013B0FBA6CBE077D",
        "domain": "D6",
        "intent": "查询各项目类型完成情况（技改/新建/扩建/维护改造/安全环保）",
        "params": {},
    },
    {
        "path": "/api/gateway/getPlanExcludedProjectPenetrationAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F53524FA64F8B0024177D962D5AA1EFD1C83",
        "domain": "D6",
        "intent": "查询计划外项目按港区/类型的穿透分析",
        "params": {
            "ownerLgZoneName": None,
            "investProjectType": None,
        },
    },
    {
        "path": "/api/gateway/getUnplannedProjectsInquiry",
        "token": "B1DCE83DF425C3E5A76104B5E481F5355A0FFA45E480D71C0B20F14CF34E741E",
        "domain": "D6",
        "intent": "查询计划外项目明细查询（分页）",
        "params": {
            "dateYear": "2026",
            "regionName": None,
            "pageNo": 1,
            "pageSize": 20,
        },
    },
    {
        "path": "/api/gateway/getCapitalApprovalAnalysisLimitInquiry",
        "token": "B1DCE83DF425C3E5A76104B5E481F535B8B116C7E086FB58AE6F9A37F7A2A23A",
        "domain": "D6",
        "intent": "查询资本性项目批复金额/完成/付款汇总分析",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getCapitalApprovalAnalysisProject",
        "token": "B1DCE83DF425C3E5A76104B5E481F535688DD2E5056273E348A6AA208D92D44A",
        "domain": "D6",
        "intent": "查询各项目类型资本性项目批复分析",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getVisualProgressAnalysisAndStatistics",
        "token": "B1DCE83DF425C3E5A76104B5E481F535AA45BE834636728B28CDA8792D27E028",
        "domain": "D6",
        "intent": "查询资本性项目建设阶段分布（前期/施工/竣工验收/交付）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getCompletionStatus",
        "token": "B1DCE83DF425C3E5A76104B5E481F5357CE12AA23200ED963E27AD5585804ACE",
        "domain": "D6",
        "intent": "查询资本性项目年度完成状态（金额完成率+项目完成率）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getDeliveryRate",
        "token": "B1DCE83DF425C3E5A76104B5E481F5355A93262256382B148DDB2913D5173AF8",
        "domain": "D6",
        "intent": "查询资本性项目交付率（已交付/按时交付）",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getNumberCapitalProjectsDelivered",
        "token": "B1DCE83DF425C3E5A76104B5E481F53574113C28A028CE867EA8B03F4C4ADC66",
        "domain": "D6",
        "intent": "查询已交付资本性项目数量和价值",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getNumberCapitalProjectsDeliveredZoneName",
        "token": "B1DCE83DF425C3E5A76104B5E481F535F04C3E3A6F4A442C0DA5C671950A3663",
        "domain": "D6",
        "intent": "查询各港区当月资本性项目交付数量",
        "params": {
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getRegionalInvestmentQuota",
        "token": "B1DCE83DF425C3E5A76104B5E481F535071FCB360EEA8B8BF13A1D6EC27DC9A8",
        "domain": "D6",
        "intent": "查询各港区投资额度使用情况（批复/已用/使用率）",
        "params": {
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getNumberCapitalProjectsDeliveredPlanAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F53533F464E961F5C4D9C26F9102B711BEBA",
        "domain": "D6",
        "intent": "查询各计划类型资本性项目交付率",
        "params": {
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getTypeAnalysisInvestmentAmountQuery",
        "token": "B1DCE83DF425C3E5A76104B5E481F535BDE7D85129632D041BAB244A1404434F",
        "domain": "D6",
        "intent": "查询各项目类型投资金额完成情况（月度）",
        "params": {
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getCapitalProjectsList",
        "token": "B1DCE83DF425C3E5A76104B5E481F53536EF1D63A0571DAB2FB2D987C65E04E7",
        "domain": "D6",
        "intent": "查询资本性项目明细列表（分页，支持多维度筛选）",
        "params": {
            "projectName": None,
            "investProjectType": None,
            "projectCurrentStage": None,
            "investProjectStatus": None,
            "ownerDept": None,
            "dateYear": None,
            "dateMonth": None,
            "ownerLgZoneName": None,
            "pageNo": 1,
            "pageSize": 20,
        },
    },
    {
        "path": "/api/gateway/getEquipmentIndicatorOperationQty",
        "token": "B1DCE83DF425C3E5A76104B5E481F535FE95E6F21D4B554F35E3DA30CBBB7771",
        "domain": "D7",
        "intent": "查询各港区设备作业量指标（集装箱/散货，月度）",
        "params": {
            "dateMonth": "2026-03",
            "ownerZone": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getEquipmentIndicatorUseCost",
        "token": "B1DCE83DF425C3E5A76104B5E481F535A57695EE933FCD13AF102D89D33E4546",
        "domain": "D7",
        "intent": "查询各港区设备使用成本指标（燃油/电力/维修，月度）",
        "params": {
            "dateMonth": "2026-03",
            "ownerZone": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getProductionEquipmentFaultNum",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFAB27C1127D9E9D64D932479D75D5EEE7",
        "domain": "D7",
        "intent": "查询生产设备年度故障次数（重大/一般，含同比）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getProductionEquipmentStatistic",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF90AA48728EC03C7F4E244B3EC6A9734F",
        "domain": "D7",
        "intent": "查询生产设备月度概览（总数/在用/完好率/利用率/平均役龄）",
        "params": {
            "dateMonth": "2026-03",
            "ownerZone": None,
        },
    },
    {
        "path": "/api/gateway/getProductionEquipmentServiceAgeDistribution",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF369902D9AF69FB5D32520C0CC19E1B08",
        "domain": "D7",
        "intent": "查询生产设备役龄分布（0-5年/5-10年/10-15年等）",
        "params": {
            "dateMonth": "2026-03",
            "ownerZone": "全港",
        },
    },
    {
        "path": "/api/gateway/getOverviewQuery",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF236C5F6DA2419BC3DC2C09B797335E03",
        "domain": "D7",
        "intent": "查询单台设备综合概览（完好率/台时效率/单耗/作业量/成本，单据大屏）",
        "params": {
            "date": "2026-04-15",
            "equipmentNo": "EQ001",
            "ownerLgZoneName": "全港",
            "cmpName": "全部",
            "firstLevelClassName": "装卸机械",
        },
    },
    {
        "path": "/api/gateway/getSingleEquipmentIntegrityRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF16A59EFC96F1CC26836124CCAB3FFDE5",
        "domain": "D7",
        "intent": "查询单台设备完好率及月度趋势",
        "params": {
            "equipmentNo": "EQ001",
        },
    },
    {
        "path": "/api/gateway/getUnitHourEfficiency",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFD29D3FBE29DBF8A3C8D41CD705FBDFED",
        "domain": "D7",
        "intent": "查询单台设备台时效率及月度趋势",
        "params": {
            "equipmentNo": "EQ001",
        },
    },
    {
        "path": "/api/gateway/getUnitConsumption",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFC476705DD6A00BEAAEC8B80621EE652B",
        "domain": "D7",
        "intent": "查询单台设备能源单耗及月度趋势（燃油+电力）",
        "params": {
            "equipmentNo": "EQ001",
        },
    },
    {
        "path": "/api/gateway/getSingleMachineUtilization",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFDC1BA33A3D0C89A8AC9C13741BAF7B2A",
        "domain": "D7",
        "intent": "查询单台设备利用率及有效利用率月度趋势",
        "params": {
            "equipmentNo": "EQ001",
        },
    },
    {
        "path": "/api/gateway/getSingleCost",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF9784CEB3FEDE446D84E8D729028A827E",
        "domain": "D7",
        "intent": "查询单台设备年度成本（燃油/电力/维修/其他及单位成本）",
        "params": {
            "equipmentNo": "EQ001",
        },
    },
    {
        "path": "/api/gateway/getEquipmentUsageRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF894453073A19C32022C1F32E220FBB77",
        "domain": "D7",
        "intent": "查询各港区年度设备利用率（含月度分布曲线）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
            "cmpName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getEquipmentServiceableRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF885417B2B988907C1554AC57E7AEB928",
        "domain": "D7",
        "intent": "查询各港区年度设备完好率（含月度分布）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
            "cmpName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getEquipmentFirstLevelClassNameList",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFC9A2EA179B615575BEE438A7D07C5CEC",
        "domain": "D7",
        "intent": "查询设备一级分类列表及数量（装卸/运输/起重/输送/特种）",
        "params": {
            "dateMonth": "2026-03",
            "ownerZone": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getContainerMachineHourRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF7FFD8EB4A3249541CB9694BD4F728C02",
        "domain": "D7",
        "intent": "查询集装箱装卸设备台时效率（岸桥/RTG分项，月度曲线）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
            "cmpName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getEquipmentEnergyConsumptionPerUnit",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFE5BF0B16C7D1935D19088A3C037AEB7C",
        "domain": "D7",
        "intent": "查询各港区年度设备能源单耗（含月度趋势）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
            "cmpName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getEquipmentFuelOilTonCost",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF76F1B162E6335D64AAAFA9740C64210E",
        "domain": "D7",
        "intent": "查询各港区年度燃油吨成本（元/自然箱，月度趋势）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
            "cmpName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getEquipmentElectricityTonCost",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFF547ABF2303BB47B821552314C106673",
        "domain": "D7",
        "intent": "查询各港区年度电量吨成本（元/自然箱，月度趋势）",
        "params": {
            "dateYear": "2026",
            "ownerZone": None,
            "cmpName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getMachineDataDisplayScreenHourlyEfficiency",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF197F90A4B013C5DDF454DAD5F5842FAD",
        "domain": "D7",
        "intent": "查询指定机种当月台时效率及各台设备明细（机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getModelDataDisplayScreenEnergyConsumptionPerUnit",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFE1A990DB594BFE1DB0652AA1C663BE3D",
        "domain": "D7",
        "intent": "查询指定机种当月能耗单耗（机种展示屏）",
        "params": {
            "secondLevelClassName": "门机",
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getFuelTonCostOfAircraftDataDisplay",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF6CAD71075BC804998E32DCBAE705FBAB",
        "domain": "D7",
        "intent": "查询指定机种燃油吨成本（机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getMachineTypeDataDisplayScreenPowerConsumptionCostPerTon",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFF26344A51FADCCC3F43F811700555930",
        "domain": "D7",
        "intent": "查询指定机种电量吨成本（机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getModelDataDisplayScreenUtilization",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF469D084A0B2C03C0DE08C40AB0D97613",
        "domain": "D7",
        "intent": "查询指定机种年度利用率（机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getModelDataDisplayScreenEffectiveUtilization",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFEE44F1CBC29FAB99EBB5F9D67BBE9B94",
        "domain": "D7",
        "intent": "查询指定机种年度有效利用率（机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getMachineDataDisplayScreenEquipmentIntegrityRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFC29FACC7DE6072083C98C69DA4F604A1",
        "domain": "D7",
        "intent": "查询指定机种年度完好率（机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getModelDataDisplayScreenHierarchyRelation",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF6ECEC354462018E2EAF9954609F4D215",
        "domain": "D7",
        "intent": "查询设备二级分类的层级关系（判断是否属于集装箱设备）",
        "params": {
            "secondLevelClassName": "岸桥",
        },
    },
    {
        "path": "/api/gateway/getMachineDataDisplayEquipmentReliability",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFD125D4232784DAA4C46168E583218256",
        "domain": "D7",
        "intent": "查询集装箱设备可靠性指标（MTBF/MTTR/故障次数，机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getNonContainerProductionEquipmentReliability",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF4D8F5DB7FA6E4AC31499F1F2468C9EBE",
        "domain": "D7",
        "intent": "查询非集装箱设备可靠性指标（散货/油化/滚装）",
        "params": {
            "secondLevelClassName": "岸桥",
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "cmpName": None,
        },
    },
    {
        "path": "/api/gateway/getMachineDataDisplaySingleUnitEnergyConsumption",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF011F834BFA89826B3221537950206E69",
        "domain": "D7",
        "intent": "查询指定机种下各单台设备月度能耗（机种展示屏）",
        "params": {
            "secondLevelClassName": "岸桥",
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentUsageRateByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF0FFB47E0BB36A59FB5C78D10A63B0770",
        "domain": "D7",
        "intent": "查询近5年生产设备有效利用率历年对比",
        "params": {
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentUsageRateByMonth",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF1466C3B3412388B980BF57D4D183DAB0",
        "domain": "D7",
        "intent": "查询年度生产设备有效利用率月度分布",
        "params": {
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentRateByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF1022A0ACAFBD961B43C0E83CC320F470",
        "domain": "D7",
        "intent": "查询近5年生产设备利用率历年对比",
        "params": {
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentIntegrityRateByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFF26B1CD4A48F4BC77D559E004AC44F3E",
        "domain": "D7",
        "intent": "查询生产设备年度完好率（当年vs上年同比）",
        "params": {
            "dateYear": "2026",
            "preYear": "2025",
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentIntegrityRateByMonth",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF8B6A6E23774631F0FD52320E8B2AD34F",
        "domain": "D7",
        "intent": "查询生产设备月度完好率（当月vs去年同月同比）",
        "params": {
            "dateMonth": "2026-03",
            "preDateMonth": "2025-03",
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getQuayEquipmentWorkingAmount",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFCE804B7E281864F71D561333523DCD53",
        "domain": "D7",
        "intent": "查询岸边设备月度作业量及同比（集装箱台数）",
        "params": {
            "dateMonth": "2026-03",
            "ownerLgZoneName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentDataAnalysisList",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF652D8F58597E2197013B0FBA6CBE077D",
        "domain": "D7",
        "intent": "查询生产设备数据分析列表（分页，多指标）",
        "params": {
            "dateMonth": "2026-03",
            "pageNo": 1,
            "pageSize": 20,
            "ownerLgZoneName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentWorkingAmountByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF81005CF409233C481A18A5158427C8B2",
        "domain": "D7",
        "intent": "查询近5年生产设备作业量历年对比",
        "params": {
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentWorkingAmountByMonth",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF9973F08D1DE81B74C87D892E1EAA2388",
        "domain": "D7",
        "intent": "查询生产设备当月作业量及同比",
        "params": {
            "dateMonth": "2026-03",
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentReliabilityByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF5738EACC2B682B2D07B21ED843506EB0",
        "domain": "D7",
        "intent": "查询近5年生产设备可靠性（MTBF）历年趋势",
        "params": {
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentReliabilityByMonth",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF2DDCEE357D5087B5FCE15331EF57772A",
        "domain": "D7",
        "intent": "查询年度生产设备可靠性月度趋势",
        "params": {
            "dateYear": "2026",
            "ownerLgZoneName": None,
            "firstLevelClassName": None,
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentUnitConsumptionByYear",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF5A0FFA45E480D71C0B20F14CF34E741E",
        "domain": "D7",
        "intent": "查询近5年生产设备能耗单耗历年对比",
        "params": {
            "dateYear": "2026",
        },
    },
    {
        "path": "/api/gateway/getProductEquipmentUnitConsumptionByMonth",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFB8B116C7E086FB58AE6F9A37F7A2A23A",
        "domain": "D7",
        "intent": "查询生产设备当月能耗单耗及同比/环比",
        "params": {
            "dateMonth": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getCurBusinessDashboardThroughput",
        "token": "B1DCE83DF425C3E5A76104B5E481F535901ACDCAFE6E39A5B2519571CE335EE2",
        "domain": "D2",
        "intent": "查询当月吞吐量及同比（全港汇总，无港区筛选）",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getMonthlyRegionalThroughputAreaBusinessDashboard",
        "token": "B1DCE83DF425C3E5A76104B5E481F535CCFD062E9BF3D205BD4FE8F36D552458",
        "domain": "D2",
        "intent": "查询当月各港区吞吐量及占比（商务驾驶舱版）",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getCurBusinessCockpitTrendChart",
        "token": "B1DCE83DF425C3E5A76104B5E481F535EC7D5A5AD631828C8B77B30B67B15CE2",
        "domain": "D2",
        "intent": "查询全港吞吐量月度趋势（当年各月，商务驾驶舱版）",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getSumBusinessCockpitTrendChart",
        "token": "B1DCE83DF425C3E5A76104B5E481F535CE58B93530572AEDA522A3E39860C4F8",
        "domain": "D2",
        "intent": "查询全港年累计吞吐量趋势（含月度/累计/去年同期三序列）",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getStrategicCustomerContributionCustomerOperatingRevenue",
        "token": "B1DCE83DF425C3E5A76104B5E481F5355A358CFC3EEB6EBB46FEA5F1A7326954",
        "domain": "D3",
        "intent": "查询当月战略客户营业收入贡献（商务驾驶舱版）",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getCurStrategicCustomerContributionByCargoTypeThroughput",
        "token": "B1DCE83DF425C3E5A76104B5E481F535C98145473E3E0E9DCCC35CF41858A94A",
        "domain": "D3",
        "intent": "查询当月战略客户按货类贡献的吞吐量",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getCurContributionRankOfStrategicCustomer",
        "token": "B1DCE83DF425C3E5A76104B5E481F535745694A576CFB5803246AB4FDB7B6D77",
        "domain": "D3",
        "intent": "查询当月战略客户贡献排名（商务驾驶舱版）",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getSumStrategicCustomerContributionCustomerOperatingRevenue",
        "token": "B1DCE83DF425C3E5A76104B5E481F5356D9A32EEE331EDA3FE12D12154C2B6BB",
        "domain": "D3",
        "intent": "查询年累计战略客户营业收入贡献排名",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getSumStrategyCustomerTrendAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F53553B6F4D6E5DE6A9E5DB7280DD9A39963",
        "domain": "D3",
        "intent": "查询战略客户历年累计趋势分析",
        "params": {},
    },
    # ── 以下 21 个 API 原为 mock_server_all.py 中 DELETED/OFFLINE 状态，现补入 ──
    {
        "path": "/api/gateway/getImportantCargoPortInventoryByBusinessType",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF5EF51BDCE7285517034BF1FA3CE96575",
        "domain": "D1",
        "intent": "查询按业务类型划分的重要货种港存",
        "params": {
            "date": "2026-04-15",
            "regionName": None,
        },
    },
    {
        "path": "/api/gateway/getShipOperationDynamic",
        "token": "46F4717D4D36AA272FFC710A28B050F7DC1BA33A3D0C89A8AC9C13741BAF7B2A",
        "domain": "D1",
        "intent": "查询单船作业动态详情",
        "params": {
            "shipRecordId": None,
        },
    },
    {
        "path": "/api/gateway/getThroughputCollect",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A5EF51BDCE7285517034BF1FA3CE96575",
        "domain": "D2",
        "intent": "查询月度吞吐量汇总及同比",
        "params": {
            "date": "2026-03",
            "yoyDate": "2025-03",
        },
    },
    {
        "path": "/api/gateway/getThroughputByCargoCategoryName",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A055A39AC6F90C5B49F83A45D1536137F",
        "domain": "D2",
        "intent": "查询按货种分类的月度吞吐量",
        "params": {
            "date": "2026-03",
            "yoyDate": "2025-03",
        },
    },
    {
        "path": "/api/gateway/getThroughputByZoneName",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A2B73EC54D2B807CC53938F1D2030F126",
        "domain": "D2",
        "intent": "查询按港区分的月度吞吐量",
        "params": {
            "date": "2026-03",
            "yoyDate": "2025-03",
        },
    },
    {
        "path": "/api/gateway/getContributionByCargoCategoryName",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9A099C3B4FC01B72ABA3B25B0D1AB7F49F",
        "domain": "D3",
        "intent": "查询按货种分类的客户贡献度",
        "params": {
            "date": "2026-03",
            "statisticType": "0",
            "contributionType": "吞吐量",
        },
    },
    {
        "path": "/api/gateway/getClientContributionOrder",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9ACCFD062E9BF3D205BD4FE8F36D552458",
        "domain": "D3",
        "intent": "查询客户贡献排名",
        "params": {
            "date": "2026-03",
            "statisticType": "0",
            "contributionType": "吞吐量",
        },
    },
    {
        "path": "/api/gateway/getStrategicCustomerRevenue",
        "token": "B1DCE83DF425C3E5A76104B5E481F535AB27C1127D9E9D64D932479D75D5EEE7",
        "domain": "D3",
        "intent": "查询战略客户收入贡献",
        "params": {
            "curDate": "2026-03",
            "clientName": None,
            "statisticType": "0",
            "yearDate": "2025-03",
        },
    },
    {
        "path": "/api/gateway/getStrategicCustomerThroughput",
        "token": "B1DCE83DF425C3E5A76104B5E481F535197F90A4B013C5DDF454DAD5F5842FAD",
        "domain": "D3",
        "intent": "查询战略客户吞吐量贡献",
        "params": {
            "curDate": "2026-03",
            "clientName": None,
            "cargoCategoryName": "集装箱",
            "statisticType": "0",
            "yearDate": "2025-03",
        },
    },
    {
        "path": "/api/gateway/getContributionTrend",
        "token": "3CA0D8D714570AC8C8A1F950A198BF9ACE58B93530572AEDA522A3E39860C4F8",
        "domain": "D3",
        "intent": "查询客户贡献趋势",
        "params": {
            "year": "2026",
            "lastYear": "2025",
            "statisticType": "0",
            "contributionType": "吞吐量",
        },
    },
    {
        "path": "/api/gateway/getImportantAssetRegionAnalysisPenetrationPage",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF688DD2E5056273E348A6AA208D92D44A",
        "domain": "D5",
        "intent": "查询重要资产分区分析穿透页面",
        "params": {
            "dateYear": "2026",
            "ownerZone": "全港",
            "assetTypeName": "设备",
        },
    },
    {
        "path": "/api/gateway/getEquipmentAnalysisTransparentTransmission",
        "token": "B1DCE83DF425C3E5A76104B5E481F535339A4372C3D4155FF9DEFEE3F271D3A2",
        "domain": "D5",
        "intent": "查询设备分析穿透传输数据",
        "params": {
            "dateYear": "2026",
            "assetStatus": "正常",
            "assetTypeName": "设备",
        },
    },
    {
        "path": "/api/gateway/getEquipmentMachineHourRate",
        "token": "24FBB42E14C17ACC6A25969E25BFBECFAAB30E46CDBA45A3C274179EBA957318",
        "domain": "D7",
        "intent": "查询设备台时费率",
        "params": {
            "dateYear": "2026",
            "ownerZone": "全港",
            "firstLevelClassName": "装卸机械",
        },
    },
    {
        "path": "/api/gateway/getEquipmentUseList",
        "token": "24FBB42E14C17ACC6A25969E25BFBECF2A7E607144CC523844CF35636EA6D3EF",
        "domain": "D7",
        "intent": "查询设备使用清单",
        "params": {
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
            "month": "2026-03",
            "ownerLgZoneName": "全港",
        },
    },
    {
        "path": "/api/gateway/getMonthlyCargoThroughputCategory",
        "token": "B1DCE83DF425C3E5A76104B5E481F535A8AB69FFA2B0364B63F9FE69B6717100",
        "domain": "D2",
        "intent": "查询月度货种吞吐量分类",
        "params": {
            "date": "2026-03",
        },
    },
    {
        "path": "/api/gateway/getSumBusinessDashboardThroughput",
        "token": "B1DCE83DF425C3E5A76104B5E481F5359008019B7EA43A0E286EF594A6902FA8",
        "domain": "D2",
        "intent": "查询累计业务驾驶舱吞吐量",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getBusinessDashboardCumulativeThroughputByCargoType",
        "token": "B1DCE83DF425C3E5A76104B5E481F53554218CCBF43E144BA0FD29243A60A4CA",
        "domain": "D2",
        "intent": "查询驾驶舱按货种累计吞吐量",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getCumulativeRegionalThroughput",
        "token": "B1DCE83DF425C3E5A76104B5E481F5359FA01B2532CBBBDE2833EFD9268DE42C",
        "domain": "D2",
        "intent": "查询区域累计吞吐量",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getCurStrategyCustomerTrendAnalysis",
        "token": "B1DCE83DF425C3E5A76104B5E481F5350A1FAF0E78BC80A3EEA53AE7523963AF",
        "domain": "D3",
        "intent": "查询当期战略客户趋势分析",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getSumStrategicCustomerContributionByCargoTypeThroughput",
        "token": "B1DCE83DF425C3E5A76104B5E481F5351268DD9BBE8AD8EE8690A057B3095C80",
        "domain": "D3",
        "intent": "查询战略客户按货种累计吞吐量贡献",
        "params": {
            "date": "2026",
        },
    },
    {
        "path": "/api/gateway/getSumContributionRankOfStrategicCustomer",
        "token": "B1DCE83DF425C3E5A76104B5E481F535A89C371E602AA48399CB5B88AF6FB552",
        "domain": "D3",
        "intent": "查询战略客户累计贡献排名",
        "params": {
            "date": "2026",
        },
    },
]


# ---------------------------------------------------------------------------
# Mock Server Parser — parse mock_server_all.py to extract route definitions
# ---------------------------------------------------------------------------

def _extract_t_dict(text):
    """Extract the T = {...} token dictionary from mock source text."""
    match = re.search(r'^T\s*=\s*\{', text, re.MULTILINE)
    if not match:
        return {}
    start = match.start()
    # find matching brace
    depth = 0
    i = match.end() - 1  # position of '{'
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                block = text[i:j + 1]
                try:
                    return ast.literal_eval(block)
                except Exception:
                    return {}
    return {}


def _extract_meta_apis(text):
    """Extract _META_APIS list from mock source text. Returns list of dicts."""
    match = re.search(r'^_META_APIS\s*=\s*\[', text, re.MULTILINE)
    if not match:
        return []
    start = match.start()
    # find the variable assignment start
    eq_pos = text.index('=', start)
    bracket_start = text.index('[', eq_pos)
    depth = 0
    for j in range(bracket_start, len(text)):
        if text[j] == '[':
            depth += 1
        elif text[j] == ']':
            depth -= 1
            if depth == 0:
                block = text[bracket_start:j + 1]
                try:
                    return ast.literal_eval(block)
                except Exception:
                    return []
    return []


def _parse_func_params(param_str):
    """
    Parse function parameters string (after 'request: Request').
    Returns list of (name, type_str, default_str_or_None).
    """
    params = []
    if not param_str or not param_str.strip():
        return params
    # split by comma, but be careful about nested structures
    parts = []
    depth = 0
    current = []
    for ch in param_str:
        if ch in ('(', '[', '{'):
            depth += 1
            current.append(ch)
        elif ch in (')', ']', '}'):
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current).strip())

    for part in parts:
        part = part.strip()
        if not part or part.startswith('request'):
            continue
        # pattern: name: type = default  OR  name: type  OR  name = default  OR  name
        m = re.match(r'(\w+)\s*(?::\s*(\w+))?\s*(?:=\s*(.+))?$', part)
        if m:
            name = m.group(1)
            type_str = m.group(2) if m.group(2) else 'str'
            default_str = m.group(3).strip() if m.group(3) else None
            params.append((name, type_str, default_str))
    return params


def parse_mock_server(mock_file_path):
    """
    Parse mock_server_all.py and return:
      {
        "routes": {path: {"token": str, "func_name": str, "params": [...], "token_key": str}},
        "meta_apis": {path: {domain, intent, required, optional, ...}},
        "t_dict": {key: token_value},
      }
    """
    with open(mock_file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    t_dict = _extract_t_dict(text)
    meta_apis_list = _extract_meta_apis(text)
    meta_apis = {}
    for api in meta_apis_list:
        p = api.get("path", "")
        if p:
            meta_apis[p] = api

    # Extract routes: @app.get("...") followed by async def ...
    routes = {}
    # Find all @app.get decorators with their function signatures
    pattern = re.compile(
        r'@app\.get\("(/api/gateway/[^"]+)"\)\s*\n'
        r'async\s+def\s+(\w+)\(([^)]*)\)\s*:',
        re.MULTILINE
    )

    for m in pattern.finditer(text):
        path = m.group(1)
        func_name = m.group(2)
        raw_params = m.group(3)

        # Skip non-business routes
        if path in ('/', '/api/health') or path.startswith('/api/meta/'):
            continue

        # Parse function parameters
        func_params = _parse_func_params(raw_params)

        # Find token in function body (search next ~30 lines)
        body_start = m.end()
        body_end = min(body_start + 2000, len(text))
        body_text = text[body_start:body_end]

        token_key = None
        token_value = None

        # Try T["key"] pattern
        tk_match = re.search(r'check_token\(request,\s*T\["(\w+)"\]\)', body_text)
        if tk_match:
            token_key = tk_match.group(1)
            token_value = t_dict.get(token_key, "")
        else:
            # Try inline hex token
            tk_match = re.search(r'check_token\(request,\s*"([A-F0-9]{64})"\)', body_text)
            if tk_match:
                token_value = tk_match.group(1)

        routes[path] = {
            "token": token_value or "",
            "func_name": func_name,
            "params": func_params,
            "token_key": token_key or "",
        }

    # Also handle @app.get for test routes
    pattern_test = re.compile(
        r'@app\.get\("(/api/gateway/test/[^"]+)"\)\s*\n'
        r'async\s+def\s+(\w+)\(([^)]*)\)\s*:',
        re.MULTILINE
    )
    for m in pattern_test.finditer(text):
        path = m.group(1)
        func_name = m.group(2)
        raw_params = m.group(3)
        func_params = _parse_func_params(raw_params)

        body_start = m.end()
        body_end = min(body_start + 2000, len(text))
        body_text = text[body_start:body_end]

        token_key = None
        token_value = None
        tk_match = re.search(r'check_token\(request,\s*T\["(\w+)"\]\)', body_text)
        if tk_match:
            token_key = tk_match.group(1)
            token_value = t_dict.get(token_key, "")
        else:
            tk_match = re.search(r'check_token\(request,\s*"([A-F0-9]{64})"\)', body_text)
            if tk_match:
                token_value = tk_match.group(1)

        if path not in routes:
            routes[path] = {
                "token": token_value or "",
                "func_name": func_name,
                "params": func_params,
                "token_key": token_key or "",
            }

    # Handle orchestration routes
    pattern_orch = re.compile(
        r'@app\.get\("(/api/gateway/orchestration/[^"]+)"\)\s*\n'
        r'async\s+def\s+(\w+)\(([^)]*)\)\s*:',
        re.MULTILINE
    )
    for m in pattern_orch.finditer(text):
        path = m.group(1)
        func_name = m.group(2)
        raw_params = m.group(3)
        func_params = _parse_func_params(raw_params)

        body_start = m.end()
        body_end = min(body_start + 2000, len(text))
        body_text = text[body_start:body_end]

        token_key = None
        token_value = None
        tk_match = re.search(r'check_token\(request,\s*T\["(\w+)"\]\)', body_text)
        if tk_match:
            token_key = tk_match.group(1)
            token_value = t_dict.get(token_key, "")
        else:
            tk_match = re.search(r'check_token\(request,\s*"([A-F0-9]{64})"\)', body_text)
            if tk_match:
                token_value = tk_match.group(1)

        if path not in routes:
            routes[path] = {
                "token": token_value or "",
                "func_name": func_name,
                "params": func_params,
                "token_key": token_key or "",
            }

    return {
        "routes": routes,
        "meta_apis": meta_apis,
        "t_dict": t_dict,
    }


def _generate_sample_value(param_name, type_str, default_str):
    """Generate a plausible sample value for a parameter based on its name and type."""
    # If there's a non-None default, use it
    if default_str is not None and default_str != 'None':
        # parse literal
        try:
            return ast.literal_eval(default_str)
        except Exception:
            return default_str.strip('"').strip("'")

    # For optional params (default=None), keep None
    if default_str == 'None':
        return None

    # Heuristic by param name patterns
    name_lower = param_name.lower()
    is_int = (type_str == 'int')

    if param_name in ('dateYear', 'curDateYear', 'yearDateYear', 'currYear'):
        return 2026 if is_int else "2026"
    if param_name in ('preYear', 'yearDateYear') and 'pre' in name_lower:
        return 2025 if is_int else "2025"
    if 'preyear' in name_lower or param_name == 'preYear':
        return 2025 if is_int else "2025"
    if 'datemonth' in name_lower or 'curdate' in name_lower and 'month' in name_lower:
        return "2026-03"
    if param_name in ('dateMonth', 'curDateMonth', 'yearDateMonth', 'preDateMonth',
                       'startMonth', 'endMonth'):
        if 'pre' in name_lower or 'year' in name_lower:
            return "2025-03"
        if 'start' in name_lower:
            return "2026-01"
        if 'end' in name_lower:
            return "2026-03"
        return "2026-03"
    if param_name in ('date', 'dispatchDate', 'dateCur', 'yesterday'):
        return "2026-04-15"
    if param_name in ('startDate', 'statDate', 'momStartDate', 'yoyStartDate'):
        return "2026-01-01"
    if param_name in ('endDate', 'momEndDate', 'yoyEndDate'):
        return "2026-03-31"
    if param_name in ('momDate',):
        return "2026-04-14"
    if param_name in ('yoyDate',):
        return "2025-04-15"
    if param_name in ('lastMonthDay',):
        return "2026-03-15"
    if param_name in ('regionName', 'zoneName', 'ownerZone', 'ownerLgZoneName',
                       'assetOwnerZone'):
        return None
    if param_name in ('cmpName', 'companyName', 'orgName', 'projectCmp',
                       'adminName', 'ownerDept', 'customerName'):
        return None
    if param_name in ('businessSegment', 'businessType'):
        return "\u96c6\u88c5\u7bb1"
    if param_name == 'flag':
        return "0"
    if param_name in ('pageNo',):
        return 1
    if param_name in ('pageSize',):
        return 20
    if param_name in ('equipmentNo',):
        return "EQ001"
    if param_name in ('type',):
        return "1"
    if param_name in ('firstLevelClassName',):
        return None
    if param_name in ('secondLevelClassName',):
        return "\u5cb8\u6865"
    if param_name in ('displayCode', 'displayoCde'):
        return "001"
    if param_name in ('statisticType',):
        return 0 if is_int else "0"
    if param_name in ('contributionType',):
        return "\u541e\u5410\u91cf"
    if param_name in ('gradeResult',):
        return "A"
    if param_name in ('shipStatus',):
        return "\u5728\u6cca"
    if param_name in ('shipRecordId',):
        return None
    if param_name in ('mainOrgCode',):
        return "001"
    if param_name in ('asseTypeName', 'assetTypeName'):
        return "\u8bbe\u5907"
    if param_name in ('assetStatus',):
        return None
    if param_name in ('machineName',):
        return None
    if param_name in ('projectName', 'projectNo'):
        return None
    if param_name in ('currentStage', 'projectCurrentStage', 'investProjectStatus',
                       'investProjectType'):
        return None
    if param_name in ('yianZt',):
        return "\u5df2\u5ba1\u8bae"
    if param_name in ('startYear',):
        return "2022"
    if param_name in ('endYear',):
        return "2026"
    if param_name in ('portCode', 'assetTypeId'):
        return None
    if param_name in ('month',):
        return "2026-03"
    if param_name in ('minNum',):
        return "0"
    if param_name in ('maxNum',):
        return "10000"
    if param_name in ('typeName',):
        return "\u8bbe\u5907"
    if param_name in ('year', 'lastYear'):
        if 'last' in name_lower:
            return "2025"
        return "2026"
    if param_name in ('curDate', 'yearDate'):
        return None
    if param_name in ('clientName', 'cargoCategoryName', 'contributionValue'):
        return None
    # Fallback: None for optional, some string for required
    return None


def merge_missing_api_defs(existing_defs, mock_data):
    """
    Find APIs defined in mock_server_all.py but missing from API_DEFS.
    Returns (new_defs_list, warnings_list).
    """
    existing_paths = set(d["path"] for d in existing_defs)
    routes = mock_data["routes"]
    meta_apis = mock_data["meta_apis"]

    new_defs = []
    warnings = []

    for path, route_info in sorted(routes.items()):
        if path in existing_paths:
            continue

        meta = meta_apis.get(path, {})
        domain = meta.get("domain", "")
        intent = meta.get("intent", "")

        # fallback domain inference from path
        if not domain:
            if "Equipment" in path or "Machine" in path or "equipment" in path:
                domain = "D7"
            elif "Customer" in path or "Strategic" in path or "Contribution" in path:
                domain = "D3"
            elif "Asset" in path or "Housing" in path or "Land" in path:
                domain = "D5"
            elif "Invest" in path or "Capital" in path or "Cost" in path or "Plan" in path:
                domain = "D6"
            elif "Meeting" in path or "Enterprise" in path or "Withdrawal" in path:
                domain = "D4"
            else:
                domain = "D1"

        if not intent:
            # Generate from function name
            func_name = route_info.get("func_name", "")
            intent = "mock\u65b0\u589e\u63a5\u53e3: %s" % func_name

        # Build params
        params = {}
        for pname, ptype, pdefault in route_info["params"]:
            params[pname] = _generate_sample_value(pname, ptype, pdefault)

        token = route_info.get("token", "")
        if not token:
            warnings.append("[WARN] %s: no token found in mock" % path)

        new_defs.append({
            "path": path,
            "token": token,
            "domain": domain,
            "intent": intent,
            "params": params,
            "_source": "auto_sync",
        })

    return new_defs, warnings


# ---------------------------------------------------------------------------
# Parameter Signature Cross-Validation
# ---------------------------------------------------------------------------

def validate_param_signatures(api_def, mock_route_info):
    """
    Compare params between api_def and mock route signature.
    Returns dict with missing_params, extra_params, type_warnings.
    """
    if mock_route_info is None:
        return {"mock_defined": False}

    # mock function params (excluding request)
    mock_params = {}
    for pname, ptype, pdefault in mock_route_info.get("params", []):
        mock_params[pname] = {
            "type": ptype,
            "required": pdefault is None,  # no default = required
        }

    # validator params
    api_params = api_def.get("params", {})
    api_param_keys = set(api_params.keys())
    mock_param_keys = set(mock_params.keys())

    missing = []  # in mock but not in validator
    extra = []  # in validator but not in mock
    type_warnings = []

    for mp in sorted(mock_param_keys - api_param_keys):
        info = mock_params[mp]
        missing.append({
            "param": mp,
            "mock_type": info["type"],
            "required_in_mock": info["required"],
        })

    for ep in sorted(api_param_keys - mock_param_keys):
        extra.append({"param": ep})

    # check type consistency for common params
    for cp in sorted(api_param_keys & mock_param_keys):
        val = api_params[cp]
        mock_type = mock_params[cp]["type"]
        if val is not None:
            if mock_type == 'int' and isinstance(val, str):
                type_warnings.append({
                    "param": cp,
                    "mock_type": "int",
                    "api_sends": "str",
                    "value": val,
                })
            elif mock_type == 'float' and isinstance(val, (str, int)):
                type_warnings.append({
                    "param": cp,
                    "mock_type": "float",
                    "api_sends": type(val).__name__,
                    "value": val,
                })

    return {
        "mock_defined": True,
        "missing_params": missing,
        "extra_params": extra,
        "matched_params": sorted(api_param_keys & mock_param_keys),
        "type_warnings": type_warnings,
    }


# ---------------------------------------------------------------------------
# Mock Comparison — call mock server and compare with prod
# ---------------------------------------------------------------------------

def call_mock_api(session, mock_base_url, api_def, timeout):
    """
    Call the mock server for a single API. Returns a simplified result dict.
    """
    path = api_def["path"]
    token = api_def["token"]
    raw_params = api_def["params"]

    url = mock_base_url.rstrip("/") + path
    headers = {"API-TOKEN": token}
    params = build_params(raw_params)

    result = {
        "status": "UNKNOWN",
        "data": None,
        "data_type": None,
        "error": None,
        "latency_ms": None,
    }

    t0 = time.time()
    try:
        resp = session.get(url, headers=headers, params=params, timeout=timeout)
        latency = (time.time() - t0) * 1000
        result["latency_ms"] = round(latency, 1)

        if resp.status_code != 200:
            result["status"] = "HTTP_%d" % resp.status_code
            result["error"] = "Mock returned HTTP %d" % resp.status_code
            return result

        try:
            body = resp.json()
        except ValueError:
            result["status"] = "INVALID_JSON"
            result["error"] = "Mock response is not valid JSON"
            return result

        # Extract data from response
        pattern, data = classify_response(body)
        result["status"] = "OK"
        result["data"] = data
        if isinstance(data, list):
            result["data_type"] = "list"
        elif isinstance(data, dict):
            result["data_type"] = "dict"
        else:
            result["data_type"] = type(data).__name__ if data is not None else "null"

    except requests.exceptions.ConnectionError:
        result["status"] = "UNREACHABLE"
        result["error"] = "Mock server not reachable"
    except requests.exceptions.Timeout:
        result["status"] = "TIMEOUT"
        result["error"] = "Mock request timed out"
    except Exception as e:
        result["status"] = "EXCEPTION"
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])

    return result


def _collect_field_types(data, prefix=""):
    """
    Recursively collect field names and their types from data.
    Returns dict {field_path: type_name}.
    """
    result = {}
    if isinstance(data, dict):
        for k, v in data.items():
            fp = "%s.%s" % (prefix, k) if prefix else k
            result[fp] = type(v).__name__
            if isinstance(v, dict):
                result.update(_collect_field_types(v, fp))
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                result.update(_collect_field_types(v[0], fp + "[]"))
    elif isinstance(data, list) and data:
        if isinstance(data[0], dict):
            result.update(_collect_field_types(data[0], prefix + "[]" if prefix else "[]"))
    return result


def _collect_numeric_ranges(data):
    """
    Collect min/max ranges for numeric fields in data.
    If data is a list of dicts, aggregate across all items.
    Returns dict {field_name: (min_val, max_val)}.
    """
    ranges = {}
    items = data if isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if k not in ranges:
                    ranges[k] = [v, v]
                else:
                    ranges[k][0] = min(ranges[k][0], v)
                    ranges[k][1] = max(ranges[k][1], v)
    return ranges


def _collect_categorical_values(data):
    """
    Collect unique values for categorical/enum string fields in data.
    Returns dict {field_name: set_of_values}.
    Uses KNOWN_CATEGORICAL_FIELDS for precision; applies heuristic for unknown fields.
    """
    result = {}
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    if not items:
        return result

    # First pass: collect all string values per field
    field_vals = {}  # {field: [val, val, ...]}
    for item in items:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if v is None:
                continue
            if not isinstance(v, str):
                continue
            if k not in field_vals:
                field_vals[k] = []
            field_vals[k].append(v)

    # Second pass: decide which fields are categorical
    total_records = len([x for x in items if isinstance(x, dict)])
    for field, vals in field_vals.items():
        # Skip fields that look like IDs/timestamps
        skip = False
        for pat in _SKIP_FIELD_PATTERNS:
            if field.endswith(pat) or field == pat:
                skip = True
                break
        if skip:
            continue

        unique_vals = set(vals)

        # Known categorical: always include
        if field in KNOWN_CATEGORICAL_FIELDS:
            result[field] = unique_vals
            continue

        # Heuristic for unknown fields:
        #   <= 20 unique values, avg length < 30, not all unique (when enough records)
        if len(unique_vals) > 20:
            continue
        avg_len = sum(len(v) for v in vals) / len(vals) if vals else 0
        if avg_len >= 30:
            continue
        # If every record has a unique value and we have enough records, skip (likely an ID)
        if total_records > 5 and len(unique_vals) == total_records:
            continue

        result[field] = unique_vals

    return result


def _compare_enum_coverage(prod_data, mock_data):
    """
    Compare categorical field value sets between prod and mock.
    Returns list of comparison dicts.
    """
    prod_cats = _collect_categorical_values(prod_data)
    mock_cats = _collect_categorical_values(mock_data)

    results = []
    all_fields = sorted(set(prod_cats.keys()) | set(mock_cats.keys()))
    for field in all_fields:
        pv = prod_cats.get(field, set())
        mv = mock_cats.get(field, set())
        if not pv and not mv:
            continue
        prod_only = sorted(pv - mv)
        mock_only = sorted(mv - pv)
        common = pv & mv
        coverage = (len(common) * 100.0 / len(pv)) if pv else 100.0
        results.append({
            "field": field,
            "prod_values": sorted(pv),
            "mock_values": sorted(mv),
            "prod_only": prod_only,
            "mock_only": mock_only,
            "coverage_pct": round(coverage, 1),
        })
    return results


def _compare_data_volume(prod_data, mock_data):
    """
    Compare record counts between prod and mock responses.
    Returns comparison dict with severity.
    """
    def _count(data):
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            # Check if dict contains a primary list
            max_list_len = 0
            for v in data.values():
                if isinstance(v, list):
                    max_list_len = max(max_list_len, len(v))
            return max_list_len if max_list_len > 0 else 1
        return 0

    pc = _count(prod_data)
    mc = _count(mock_data)

    if pc > 0:
        ratio = float(mc) / float(pc)
    elif mc == 0:
        ratio = 1.0
    else:
        ratio = float('inf')

    if 0.5 <= ratio <= 2.0:
        severity = "OK"
    elif 0.2 <= ratio <= 5.0:
        severity = "WARNING"
    else:
        severity = "CRITICAL"

    note = "prod=%d, mock=%d" % (pc, mc)
    if pc > 0 and mc > 0:
        note += " (ratio=%.1f%%)" % (ratio * 100)

    return {
        "prod_count": pc,
        "mock_count": mc,
        "ratio": round(ratio, 3) if ratio != float('inf') else None,
        "severity": severity,
        "note": note,
    }


def _collect_numeric_values(data, max_per_field=1000):
    """
    Collect all numeric values per field (not just min/max).
    Returns {field_name: [val1, val2, ...]}.
    Also tries to parse numeric strings.
    """
    values = {}
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if isinstance(v, bool):
                continue
            num = None
            if isinstance(v, (int, float)):
                num = float(v)
            elif isinstance(v, str):
                try:
                    num = float(v)
                except (ValueError, TypeError):
                    pass
            if num is not None:
                if k not in values:
                    values[k] = []
                if len(values[k]) < max_per_field:
                    values[k].append(num)
    return values


def _compare_numeric_plausibility(prod_data, mock_data):
    """
    Compare numeric field values for plausibility (magnitude, mean, zero-dominance).
    Returns list of per-field comparison dicts.
    """
    import math

    prod_vals = _collect_numeric_values(prod_data)
    mock_vals = _collect_numeric_values(mock_data)

    common_fields = sorted(set(prod_vals.keys()) & set(mock_vals.keys()))
    results = []

    for field in common_fields:
        pv = prod_vals[field]
        mv = mock_vals[field]
        if not pv or not mv:
            continue

        entry = {
            "field": field,
            "prod_range": [min(pv), max(pv)],
            "mock_range": [min(mv), max(mv)],
            "prod_count": len(pv),
            "mock_count": len(mv),
            "severity": "OK",
            "notes": [],
        }

        # Add means
        p_mean = sum(pv) / len(pv)
        m_mean = sum(mv) / len(mv)
        entry["prod_mean"] = round(p_mean, 4)
        entry["mock_mean"] = round(m_mean, 4)

        # Check if field is a rate/ratio/percentage — skip magnitude check
        field_lower = field.lower()
        is_rate = any(kw in field_lower for kw in ("rate", "ratio", "pct", "percent", "proportion"))

        if is_rate:
            # For rates: check range reasonableness
            if max(pv) <= 1.5 and min(mv) > 100:
                entry["severity"] = "SUSPICIOUS"
                entry["notes"].append("prod is 0-1 scale but mock uses 0-100 scale")
            elif max(pv) > 100 and max(mv) <= 1.5:
                entry["severity"] = "SUSPICIOUS"
                entry["notes"].append("prod uses 0-100 scale but mock is 0-1 scale")
        else:
            # Magnitude check: compare log10 of max absolute values
            p_abs_max = max(abs(x) for x in pv)
            m_abs_max = max(abs(x) for x in mv)

            if p_abs_max > 0 and m_abs_max > 0:
                p_mag = math.log10(p_abs_max)
                m_mag = math.log10(m_abs_max)
                mag_diff = abs(p_mag - m_mag)
                entry["magnitude_diff"] = round(mag_diff, 2)

                if mag_diff > 2:
                    entry["severity"] = "IMPLAUSIBLE"
                    entry["notes"].append(
                        "magnitude differs by %.1f orders (prod max=%.2g, mock max=%.2g)"
                        % (mag_diff, p_abs_max, m_abs_max))
                elif mag_diff > 1:
                    entry["severity"] = "SUSPICIOUS"
                    entry["notes"].append(
                        "magnitude differs by %.1f orders" % mag_diff)

            # Mean comparison (need >= 3 data points each)
            if len(pv) >= 3 and len(mv) >= 3 and p_mean != 0:
                mean_ratio = m_mean / p_mean if p_mean != 0 else float('inf')
                if mean_ratio != float('inf') and (mean_ratio < 0.1 or mean_ratio > 10.0):
                    if entry["severity"] == "OK":
                        entry["severity"] = "SUSPICIOUS"
                    entry["notes"].append(
                        "mean ratio=%.2f (prod=%.2g, mock=%.2g)"
                        % (mean_ratio, p_mean, m_mean))

        # Zero-dominance check
        p_nonzero = sum(1 for x in pv if x != 0)
        m_nonzero = sum(1 for x in mv if x != 0)
        p_nonzero_pct = p_nonzero * 100.0 / len(pv)
        m_nonzero_pct = m_nonzero * 100.0 / len(mv)

        if p_nonzero_pct > 50 and m_nonzero_pct == 0:
            entry["severity"] = "IMPLAUSIBLE"
            entry["notes"].append("prod has %.0f%% non-zero but mock is all zeros" % p_nonzero_pct)
        elif m_nonzero_pct > 50 and p_nonzero_pct == 0:
            entry["severity"] = "SUSPICIOUS"
            entry["notes"].append("mock has %.0f%% non-zero but prod is all zeros" % m_nonzero_pct)

        # Only report fields with issues or significant data
        if entry["severity"] != "OK" or len(pv) >= 3:
            results.append(entry)

    return results


def deep_compare_fields(prod_data, mock_data):
    """
    Compare field structures between production and mock response data.
    Returns comparison dict.
    """
    prod_fields = _collect_field_types(prod_data)
    mock_fields = _collect_field_types(mock_data)

    prod_keys = set(prod_fields.keys())
    mock_keys = set(mock_fields.keys())

    prod_only = sorted(prod_keys - mock_keys)
    mock_only = sorted(mock_keys - prod_keys)
    common = sorted(prod_keys & mock_keys)

    type_diff = []
    for field in common:
        pt = prod_fields[field]
        mt = mock_fields[field]
        if pt != mt:
            # Allow int/float mismatch as minor
            if set([pt, mt]) == set(['int', 'float']):
                continue
            type_diff.append({
                "field": field,
                "prod_type": pt,
                "mock_type": mt,
            })

    # Value range comparison for numeric fields
    prod_ranges = _collect_numeric_ranges(prod_data)
    mock_ranges = _collect_numeric_ranges(mock_data)
    value_range_diff = []
    common_numeric = set(prod_ranges.keys()) & set(mock_ranges.keys())
    for field in sorted(common_numeric):
        pr = prod_ranges[field]
        mr = mock_ranges[field]
        # Report if ranges differ significantly
        if pr[0] != 0 or mr[0] != 0 or pr[1] != 0 or mr[1] != 0:
            value_range_diff.append({
                "field": field,
                "prod_range": [pr[0], pr[1]],
                "mock_range": [mr[0], mr[1]],
            })

    return {
        "field_diff": {
            "prod_only": prod_only,
            "mock_only": mock_only,
            "common": common,
        },
        "type_diff": type_diff,
        "value_range_diff": value_range_diff,
        "enum_coverage": _compare_enum_coverage(prod_data, mock_data),
        "data_volume": _compare_data_volume(prod_data, mock_data),
        "numeric_plausibility": _compare_numeric_plausibility(prod_data, mock_data),
    }


# ---------------------------------------------------------------------------
# Quality Scoring
# ---------------------------------------------------------------------------

def _score_api_quality(comparison):
    """
    Score a single API's prod-vs-mock comparison result (0-100).
    Returns {"score": float, "grade": str, "breakdown": {...}, "top_issues": [...]}.
    """
    issues = []

    # --- 1. Field structure score (weight 35%) ---
    fd = comparison.get("field_diff", {})
    prod_only = fd.get("prod_only", [])
    mock_only = fd.get("mock_only", [])
    common = fd.get("common", [])
    type_diff = comparison.get("type_diff", [])

    total_fields = len(prod_only) + len(mock_only) + len(common)
    if total_fields == 0:
        field_score = 100.0
    else:
        matched = len(common) - len(type_diff)
        field_score = max(0, matched * 100.0 / total_fields)

    if prod_only:
        issues.append("prod has %d fields missing in mock: %s"
                       % (len(prod_only), ", ".join(prod_only[:3])))
    if type_diff:
        issues.append("%d fields have type mismatch" % len(type_diff))

    # --- 2. Enum coverage score (weight 25%) ---
    enum_list = comparison.get("enum_coverage", [])
    if enum_list:
        coverages = [e["coverage_pct"] for e in enum_list]
        enum_score = sum(coverages) / len(coverages)
        for e in enum_list:
            if e["coverage_pct"] < 80 and e["prod_only"]:
                issues.append("%s: mock missing values %s (%.0f%% coverage)"
                               % (e["field"], ", ".join(e["prod_only"][:3]),
                                  e["coverage_pct"]))
    else:
        enum_score = 100.0

    # --- 3. Numeric plausibility score (weight 20%) ---
    num_list = comparison.get("numeric_plausibility", [])
    numeric_penalty = 0
    for n in num_list:
        sev = n.get("severity", "OK")
        if sev == "IMPLAUSIBLE":
            numeric_penalty += 25
            if n.get("notes"):
                issues.append("%s: %s" % (n["field"], n["notes"][0]))
        elif sev == "SUSPICIOUS":
            numeric_penalty += 10
            if n.get("notes"):
                issues.append("%s: %s" % (n["field"], n["notes"][0]))
    numeric_score = max(0, 100 - numeric_penalty)

    # --- 4. Data volume score (weight 20%) ---
    vol = comparison.get("data_volume", {})
    vol_sev = vol.get("severity", "OK")
    volume_map = {"OK": 100, "WARNING": 50, "CRITICAL": 0}
    volume_score = volume_map.get(vol_sev, 50)
    if vol_sev != "OK":
        issues.append("data volume: %s" % vol.get("note", "mismatch"))

    # --- Weighted total ---
    total = (field_score * 0.35 + enum_score * 0.25
             + numeric_score * 0.20 + volume_score * 0.20)

    if total >= 85:
        grade = "EXCELLENT"
    elif total >= 70:
        grade = "GOOD"
    elif total >= 50:
        grade = "FAIR"
    else:
        grade = "POOR"

    return {
        "score": round(total, 1),
        "grade": grade,
        "breakdown": {
            "field_structure": round(field_score, 1),
            "enum_coverage": round(enum_score, 1),
            "numeric_plausibility": round(numeric_score, 1),
            "data_volume": round(volume_score, 1),
        },
        "top_issues": issues[:5],
    }


def _score_domain_quality(api_scores):
    """
    Aggregate per-API quality scores into a domain-level score.
    POOR APIs weighted 1.5x to penalize outliers.
    """
    if not api_scores:
        return {"domain_score": 0, "grade": "POOR",
                "api_count": 0, "excellent": 0, "good": 0, "fair": 0, "poor": 0}

    weighted_sum = 0.0
    weight_total = 0.0
    grade_counts = {"EXCELLENT": 0, "GOOD": 0, "FAIR": 0, "POOR": 0}

    for qs in api_scores:
        s = qs["score"]
        g = qs["grade"]
        grade_counts[g] = grade_counts.get(g, 0) + 1
        w = 1.5 if g == "POOR" else 1.0
        weighted_sum += s * w
        weight_total += w

    avg = weighted_sum / weight_total if weight_total > 0 else 0

    if avg >= 85:
        grade = "EXCELLENT"
    elif avg >= 70:
        grade = "GOOD"
    elif avg >= 50:
        grade = "FAIR"
    else:
        grade = "POOR"

    return {
        "domain_score": round(avg, 1),
        "grade": grade,
        "api_count": len(api_scores),
        "excellent": grade_counts.get("EXCELLENT", 0),
        "good": grade_counts.get("GOOD", 0),
        "fair": grade_counts.get("FAIR", 0),
        "poor": grade_counts.get("POOR", 0),
    }


def _generate_action_items(api_comparisons, max_items=20):
    """
    Generate a prioritized list of actionable fix recommendations.
    Each item: {"priority": "HIGH|MEDIUM|LOW", "domain": str, "path": str, "issue": str}.
    """
    items = []
    for api in api_comparisons:
        quality = api.get("quality")
        if quality is None:
            continue
        grade = quality["grade"]
        path = api.get("path", "")
        domain = api.get("domain", "")
        top_issues = quality.get("top_issues", [])

        if grade == "POOR":
            priority = "HIGH"
        elif grade == "FAIR":
            priority = "MEDIUM"
        elif grade == "GOOD" and top_issues:
            priority = "LOW"
        else:
            continue

        for issue in top_issues[:2]:
            items.append({
                "priority": priority,
                "domain": domain,
                "path": path,
                "issue": issue,
            })

    # Sort: HIGH first, then MEDIUM, then LOW
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda x: (priority_order.get(x["priority"], 9), x["domain"], x["path"]))
    return items[:max_items]


def generate_comparison_report(prod_results, mock_results, prod_base_url,
                                mock_base_url, ts):
    """Generate the enhanced prod-vs-mock comparison report (v2)."""
    apis = []
    field_match_count = 0
    field_mismatch_count = 0
    mock_unreachable_count = 0

    for i, prod_r in enumerate(prod_results):
        path = prod_r["path"]
        if prod_r["status"] != "OK":
            continue
        if i >= len(mock_results):
            continue

        mock_r = mock_results[i]
        if mock_r["status"] == "UNREACHABLE":
            mock_unreachable_count += 1
            apis.append({
                "path": path,
                "domain": prod_r.get("domain", ""),
                "prod_status": "OK",
                "mock_status": "UNREACHABLE",
                "quality": None,
                "field_diff": None,
                "type_diff": None,
                "value_range_diff": None,
                "enum_coverage": None,
                "data_volume": None,
                "numeric_plausibility": None,
                "prod_sample": truncate_sample(prod_r.get("data_sample")),
                "mock_sample": None,
            })
            continue

        if mock_r["status"] != "OK":
            apis.append({
                "path": path,
                "domain": prod_r.get("domain", ""),
                "prod_status": "OK",
                "mock_status": mock_r["status"],
                "quality": None,
                "field_diff": None,
                "type_diff": None,
                "value_range_diff": None,
                "enum_coverage": None,
                "data_volume": None,
                "numeric_plausibility": None,
                "prod_sample": truncate_sample(prod_r.get("data_sample")),
                "mock_sample": None,
            })
            continue

        prod_data = prod_r.get("_raw_data") or prod_r.get("data_sample")
        mock_data = mock_r.get("data")
        if prod_data is not None and mock_data is not None:
            comparison = deep_compare_fields(prod_data, mock_data)
            has_diff = (len(comparison["field_diff"]["prod_only"]) > 0 or
                        len(comparison["field_diff"]["mock_only"]) > 0 or
                        len(comparison["type_diff"]) > 0)
            if has_diff:
                field_mismatch_count += 1
            else:
                field_match_count += 1

            quality = _score_api_quality(comparison)

            apis.append({
                "path": path,
                "domain": prod_r.get("domain", ""),
                "prod_status": "OK",
                "mock_status": "OK",
                "quality": quality,
                "field_diff": comparison["field_diff"],
                "type_diff": comparison["type_diff"],
                "value_range_diff": comparison["value_range_diff"],
                "enum_coverage": comparison.get("enum_coverage", []),
                "data_volume": comparison.get("data_volume"),
                "numeric_plausibility": comparison.get("numeric_plausibility", []),
                "prod_sample": truncate_sample(prod_data),
                "mock_sample": truncate_sample(mock_data),
            })
        else:
            field_match_count += 1

    # --- Quality aggregation ---
    # Per-domain quality
    domain_scores = {}  # {domain: [quality_dict, ...]}
    for api in apis:
        q = api.get("quality")
        if q is None:
            continue
        dm = api.get("domain", "")
        if dm not in domain_scores:
            domain_scores[dm] = []
        domain_scores[dm].append(q)

    domain_quality = {}
    for dm in sorted(domain_scores.keys()):
        domain_quality[dm] = _score_domain_quality(domain_scores[dm])

    # Overall quality
    all_scores = []
    for dm_list in domain_scores.values():
        all_scores.extend(dm_list)

    overall_quality = _score_domain_quality(all_scores)
    grade_dist = {
        "EXCELLENT": overall_quality.get("excellent", 0),
        "GOOD": overall_quality.get("good", 0),
        "FAIR": overall_quality.get("fair", 0),
        "POOR": overall_quality.get("poor", 0),
    }

    # Action items
    action_items = _generate_action_items(apis)

    return {
        "report_type": "prod_vs_mock_comparison_v2",
        "timestamp": ts,
        "prod_base_url": prod_base_url,
        "mock_base_url": mock_base_url,
        "overall_quality": {
            "score": overall_quality["domain_score"],
            "grade": overall_quality["grade"],
            "total_compared": len(all_scores),
            "grade_distribution": grade_dist,
        },
        "domain_quality": domain_quality,
        "action_items": action_items,
        "apis": apis,
        "summary": {
            "total_compared": len(apis),
            "field_match": field_match_count,
            "field_mismatch": field_mismatch_count,
            "mock_unreachable": mock_unreachable_count,
        },
    }


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def build_params(raw_params):
    """Build query params dict, skipping None values."""
    result = {}
    for k, v in raw_params.items():
        if v is not None:
            result[k] = v
    return result


def classify_response(body):
    """
    Classify the response format.
    Pattern A: {"code": 200, "msg": "success", "data": ...}
    Pattern B: {"success": true, "data": ..., "errorCode": null}
    Pattern C: other / unknown
    """
    if not isinstance(body, dict):
        return "UNKNOWN", body
    if "code" in body and "data" in body:
        return "PATTERN_A", body.get("data")
    if "success" in body and "data" in body:
        return "PATTERN_B", body.get("data")
    if "data" in body:
        return "HAS_DATA", body.get("data")
    return "UNKNOWN", body


def truncate_sample(data, max_items=3, max_depth=2):
    """Truncate data sample for report readability."""
    if max_depth <= 0:
        if isinstance(data, (dict, list)):
            return "...(truncated)"
        return data
    if isinstance(data, list):
        items = []
        for item in data[:max_items]:
            items.append(truncate_sample(item, max_items, max_depth - 1))
        if len(data) > max_items:
            items.append("...(%d more)" % (len(data) - max_items))
        return items
    if isinstance(data, dict):
        result = {}
        keys = list(data.keys())[:max_items * 2]
        for k in keys:
            result[k] = truncate_sample(data[k], max_items, max_depth - 1)
        if len(data) > len(keys):
            result["__more__"] = "...(%d more keys)" % (len(data) - len(keys))
        return result
    return data


def _load_dump_results(dump_dir, apis):
    """
    Load production data from local JSON dump files.
    Returns a list of result dicts matching validate_single_api() output format.
    """
    results = []
    loaded = 0
    missing = 0
    for api_def in apis:
        path = api_def["path"]
        domain = api_def["domain"]
        api_name = path.rsplit("/", 1)[-1]
        filename = "%s_%s.json" % (domain, api_name)
        filepath = os.path.join(dump_dir, filename)

        if not os.path.isfile(filepath):
            missing += 1
            results.append({
                "path": path,
                "domain": domain,
                "intent": api_def["intent"],
                "url": "(from-dump) " + filepath,
                "token_prefix": api_def["token"][:16] + "...",
                "params_sent": {},
                "status": "NO_DUMP",
                "http_status": None,
                "response_pattern": None,
                "response_fields": None,
                "data_sample": None,
                "data_type": None,
                "data_count": None,
                "error": "Dump file not found: %s" % filename,
                "latency_ms": None,
            })
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                entry = json.load(fh)
            data = entry.get("data")
            result = {
                "path": path,
                "domain": domain,
                "intent": api_def["intent"],
                "url": "(from-dump) " + filepath,
                "token_prefix": api_def["token"][:16] + "...",
                "params_sent": entry.get("params_sent", {}),
                "status": "OK",
                "http_status": 200,
                "response_pattern": entry.get("response_pattern", ""),
                "response_fields": list(data.keys()) if isinstance(data, dict) else None,
                "data_sample": truncate_sample(data),
                "data_type": entry.get("data_type", ""),
                "data_count": entry.get("data_count"),
                "error": None,
                "latency_ms": entry.get("latency_ms"),
                "_raw_data": data,
            }
            loaded += 1
            results.append(result)
        except Exception as e:
            missing += 1
            results.append({
                "path": path,
                "domain": domain,
                "intent": api_def["intent"],
                "url": "(from-dump) " + filepath,
                "token_prefix": api_def["token"][:16] + "...",
                "params_sent": {},
                "status": "LOAD_ERROR",
                "http_status": None,
                "response_pattern": None,
                "response_fields": None,
                "data_sample": None,
                "data_type": None,
                "data_count": None,
                "error": "Failed to load dump: %s" % str(e)[:200],
                "latency_ms": None,
            })

    sys.stderr.write("Loaded %d dump files (%d missing/errors)\n" % (loaded, missing))
    return results


def validate_single_api(session, base_url, api_def, timeout, mock_routes=None,
                        show_signature=False):
    """
    Validate a single API endpoint.
    Returns a result dict with validation details.
    """
    path = api_def["path"]
    token = api_def["token"]
    domain = api_def["domain"]
    intent = api_def["intent"]
    raw_params = api_def["params"]

    url = base_url.rstrip("/") + path
    headers = {"API-TOKEN": token}
    params = build_params(raw_params)

    result = {
        "path": path,
        "domain": domain,
        "intent": intent,
        "url": url,
        "token_prefix": token[:16] + "...",
        "params_sent": params,
        "status": "UNKNOWN",
        "http_status": None,
        "response_pattern": None,
        "response_fields": None,
        "data_sample": None,
        "data_type": None,
        "data_count": None,
        "error": None,
        "latency_ms": None,
    }

    t0 = time.time()
    try:
        resp = session.get(url, headers=headers, params=params, timeout=timeout)
        latency = (time.time() - t0) * 1000
        result["latency_ms"] = round(latency, 1)
        result["http_status"] = resp.status_code

        if resp.status_code == 404:
            result["status"] = "NOT_FOUND"
            result["error"] = "HTTP 404 - path not found"
            return result

        if resp.status_code == 401:
            result["status"] = "AUTH_FAIL"
            result["error"] = "HTTP 401 - token rejected"
            return result

        if resp.status_code == 422:
            result["status"] = "PARAM_ERROR"
            result["error"] = "HTTP 422 - parameter validation failed"
            try:
                result["data_sample"] = resp.json()
            except Exception:
                result["data_sample"] = resp.text[:500]
            return result

        if resp.status_code >= 500:
            result["status"] = "SERVER_ERROR"
            result["error"] = "HTTP %d" % resp.status_code
            try:
                result["data_sample"] = resp.text[:500]
            except Exception:
                pass
            return result

        if resp.status_code != 200:
            result["status"] = "HTTP_%d" % resp.status_code
            result["error"] = "Unexpected HTTP status"
            return result

        # Parse JSON body
        try:
            body = resp.json()
        except ValueError:
            result["status"] = "INVALID_JSON"
            result["error"] = "Response is not valid JSON"
            result["data_sample"] = resp.text[:500]
            return result

        # Classify response pattern
        pattern, data = classify_response(body)
        result["response_pattern"] = pattern

        if isinstance(body, dict):
            result["response_fields"] = list(body.keys())

        # Analyze data
        if data is not None:
            if isinstance(data, list):
                result["data_type"] = "list"
                result["data_count"] = len(data)
            elif isinstance(data, dict):
                result["data_type"] = "dict"
                result["data_count"] = len(data)
            else:
                result["data_type"] = type(data).__name__
            result["data_sample"] = truncate_sample(data)
            result["_raw_data"] = data  # full data for --dump-prod
        else:
            result["data_sample"] = truncate_sample(body)
            result["_raw_data"] = body

        # Determine success
        if pattern == "PATTERN_A":
            code_val = body.get("code")
            if code_val == 200 or str(code_val) == "200":
                result["status"] = "OK"
            else:
                result["status"] = "BIZ_ERROR"
                result["error"] = "code=%s, msg=%s" % (code_val, body.get("msg", ""))
        elif pattern == "PATTERN_B":
            if body.get("success"):
                result["status"] = "OK"
            else:
                result["status"] = "BIZ_ERROR"
                result["error"] = "success=false, errorCode=%s" % body.get("errorCode")
        elif pattern == "HAS_DATA":
            result["status"] = "OK"
        else:
            result["status"] = "OK_UNKNOWN_FORMAT"

    except requests.exceptions.Timeout:
        latency = (time.time() - t0) * 1000
        result["latency_ms"] = round(latency, 1)
        result["status"] = "TIMEOUT"
        result["error"] = "Request timed out after %ds" % timeout
    except requests.exceptions.ConnectionError as e:
        latency = (time.time() - t0) * 1000
        result["latency_ms"] = round(latency, 1)
        result["status"] = "CONN_ERROR"
        result["error"] = str(e)[:200]
    except Exception as e:
        latency = (time.time() - t0) * 1000
        result["latency_ms"] = round(latency, 1)
        result["status"] = "EXCEPTION"
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])

    # Annotate with mock info if available
    if mock_routes is not None:
        route_info = mock_routes.get(path)
        result["mock_defined"] = route_info is not None
        if show_signature:
            result["param_signature"] = validate_param_signatures(api_def, route_info)
        result["_source"] = api_def.get("_source", "manual")

    return result


def print_progress(idx, total, result):
    """Print progress line to stderr."""
    status = result["status"]
    latency = result.get("latency_ms")
    lat_str = "%6.0fms" % latency if latency else "    N/A"

    if status == "OK":
        mark = "PASS"
    elif status in ("NOT_FOUND", "AUTH_FAIL", "PARAM_ERROR", "BIZ_ERROR",
                     "SERVER_ERROR", "TIMEOUT", "CONN_ERROR"):
        mark = "FAIL"
    else:
        mark = "WARN"

    mock_tag = ""
    if "mock_defined" in result:
        mock_tag = " M+" if result["mock_defined"] else " M-"
    source_tag = ""
    if result.get("_source") == "auto_sync":
        source_tag = " [NEW]"

    sys.stderr.write("[%3d/%d] %-4s %s  %s  %s%s%s\n" % (
        idx + 1, total, mark, lat_str, result["domain"], result["path"],
        mock_tag, source_tag
    ))
    sys.stderr.flush()


def generate_summary(results, sync_stats=None):
    """Generate summary statistics."""
    total = len(results)
    by_status = {}
    by_domain = {}
    latencies = []
    sig_issues = 0
    auto_synced = 0

    for r in results:
        st = r["status"]
        by_status[st] = by_status.get(st, 0) + 1

        dm = r["domain"]
        if dm not in by_domain:
            by_domain[dm] = {"total": 0, "ok": 0, "fail": 0}
        by_domain[dm]["total"] += 1
        if st == "OK":
            by_domain[dm]["ok"] += 1
        else:
            by_domain[dm]["fail"] += 1

        if r.get("latency_ms") is not None:
            latencies.append(r["latency_ms"])

        # Count signature issues
        sig = r.get("param_signature", {})
        if sig.get("missing_params") or sig.get("extra_params") or sig.get("type_warnings"):
            sig_issues += 1

        if r.get("_source") == "auto_sync":
            auto_synced += 1

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    p95_latency = 0
    if latencies:
        sorted_lat = sorted(latencies)
        p95_idx = int(len(sorted_lat) * 0.95)
        p95_latency = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]

    ok_count = by_status.get("OK", 0)

    summary = {
        "total_apis": total,
        "ok_count": ok_count,
        "fail_count": total - ok_count,
        "pass_rate": "%.1f%%" % (ok_count * 100.0 / total) if total > 0 else "0%",
        "by_status": dict(sorted(by_status.items())),
        "by_domain": dict(sorted(by_domain.items())),
        "latency": {
            "avg_ms": round(avg_latency, 1),
            "min_ms": round(min_latency, 1),
            "max_ms": round(max_latency, 1),
            "p95_ms": round(p95_latency, 1),
        },
    }

    if sync_stats is not None or auto_synced > 0:
        summary["sync_stats"] = sync_stats or {}
        summary["sync_stats"]["auto_synced_apis"] = auto_synced
        summary["sync_stats"]["signature_issues"] = sig_issues

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Validate production APIs and cross-check with mock_server_all.py"
    )
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help="Production API base URL (default: %s)" % DEFAULT_BASE_URL
    )
    parser.add_argument(
        "--output", default=None,
        help="Output JSON file path (default: auto-generated with timestamp)"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help="Request timeout in seconds (default: %d)" % DEFAULT_TIMEOUT
    )
    parser.add_argument(
        "--domain", default=None,
        help="Only test specific domain (D1-D7), comma-separated"
    )
    parser.add_argument(
        "--fail-fast", action="store_true",
        help="Stop on first connection error"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-API progress output"
    )
    # --- New arguments for mock sync and comparison ---
    parser.add_argument(
        "--sync-mock", default=None, metavar="FILE",
        help="Path to mock_server_all.py; parse and add missing API definitions"
    )
    parser.add_argument(
        "--mock-url", default="http://localhost:8080",
        help="Base URL of running mock server (default: http://localhost:8080)"
    )
    parser.add_argument(
        "--compare-mock", action="store_true",
        help="Enable prod-vs-mock comparison mode (requires mock server running)"
    )
    parser.add_argument(
        "--compare-output", default=None, metavar="FILE",
        help="Output path for comparison report JSON"
    )
    parser.add_argument(
        "--dry-run-sync", action="store_true",
        help="Only show what --sync-mock would add, don't run validation"
    )
    parser.add_argument(
        "--show-signature", action="store_true",
        help="Include param signature cross-validation in report"
    )
    parser.add_argument(
        "--dump-prod", default=None, metavar="DIR",
        help="Download full production response data and save per-API JSON files to DIR"
    )
    parser.add_argument(
        "--from-dump", default=None, metavar="DIR",
        help="Load prod data from local JSON dump files (skip live prod requests)"
    )
    parser.add_argument(
        "--enrich", action="store_true",
        help="Enable multi-variant enrichment: fetch each API with multiple "
             "param combinations (different years, months, equipment types, etc.) "
             "to collect richer data for semantic analysis. Requires --dump-prod."
    )

    args = parser.parse_args()

    if args.enrich and not args.dump_prod:
        sys.stderr.write("[FATAL] --enrich requires --dump-prod DIR\n")
        sys.exit(1)

    # --from-dump implies --compare-mock
    if args.from_dump:
        args.compare_mock = True

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Mock sync phase ──
    mock_data = None
    mock_routes = None
    sync_stats = None
    new_api_defs = []
    sync_warnings = []

    if args.sync_mock:
        if not os.path.isfile(args.sync_mock):
            sys.stderr.write("[FATAL] Mock file not found: %s\n" % args.sync_mock)
            sys.exit(1)

        sys.stderr.write("Parsing mock_server_all.py ... ")
        try:
            mock_data = parse_mock_server(args.sync_mock)
            mock_routes = mock_data["routes"]
            sys.stderr.write("OK (%d routes, %d meta entries)\n" % (
                len(mock_routes), len(mock_data["meta_apis"])
            ))
        except Exception as e:
            sys.stderr.write("FAILED: %s\n" % str(e)[:200])
            sys.stderr.write("Proceeding with existing API_DEFS only.\n")
            mock_data = None
            mock_routes = None

        if mock_data is not None:
            new_api_defs, sync_warnings = merge_missing_api_defs(API_DEFS, mock_data)
            sync_stats = {
                "mock_file": args.sync_mock,
                "total_mock_routes": len(mock_routes),
                "new_apis_found": len(new_api_defs),
            }

            if sync_warnings:
                sys.stderr.write("\nSync Warnings:\n")
                for w in sync_warnings:
                    sys.stderr.write("  %s\n" % w)

    # ── Dry-run mode ──
    if args.dry_run_sync:
        sys.stderr.write("\n" + "=" * 60 + "\n")
        sys.stderr.write("  DRY-RUN SYNC REPORT\n")
        sys.stderr.write("=" * 60 + "\n")

        if not mock_data:
            sys.stderr.write("  No mock data parsed. Use --sync-mock.\n")
            sys.exit(0)

        existing_paths = set(d["path"] for d in API_DEFS)
        mock_only_paths = set(mock_routes.keys()) - existing_paths
        api_only_paths = existing_paths - set(mock_routes.keys())

        sys.stderr.write("\n  Existing API_DEFS : %d\n" % len(API_DEFS))
        sys.stderr.write("  Mock routes       : %d\n" % len(mock_routes))
        sys.stderr.write("  New in mock       : %d\n" % len(new_api_defs))
        sys.stderr.write("  Only in API_DEFS  : %d\n" % len(api_only_paths))

        if new_api_defs:
            sys.stderr.write("\n  New APIs to add:\n")
            for nd in new_api_defs:
                sys.stderr.write("    [%s] %s\n" % (nd["domain"], nd["path"]))
                sys.stderr.write("         intent: %s\n" % nd["intent"])
                sys.stderr.write("         params: %s\n" % json.dumps(
                    nd["params"], ensure_ascii=False))
                if not nd["token"]:
                    sys.stderr.write("         WARNING: no token found!\n")

        if api_only_paths:
            sys.stderr.write("\n  Paths in API_DEFS but NOT in mock:\n")
            for p in sorted(api_only_paths):
                sys.stderr.write("    %s\n" % p)

        # Param signature check for existing APIs
        if args.show_signature or True:  # always show in dry-run
            sig_issues = []
            for api_def in API_DEFS:
                path = api_def["path"]
                route_info = mock_routes.get(path)
                if route_info is None:
                    continue
                sig = validate_param_signatures(api_def, route_info)
                has_issue = (sig.get("missing_params") or
                             sig.get("extra_params") or
                             sig.get("type_warnings"))
                if has_issue:
                    sig_issues.append((path, sig))

            if sig_issues:
                sys.stderr.write("\n  Parameter Signature Issues (%d):\n" % len(sig_issues))
                for path, sig in sig_issues:
                    sys.stderr.write("    %s\n" % path)
                    for mp in sig.get("missing_params", []):
                        sys.stderr.write("      MISSING: %s (mock type: %s, required: %s)\n" % (
                            mp["param"], mp["mock_type"], mp["required_in_mock"]))
                    for ep in sig.get("extra_params", []):
                        sys.stderr.write("      EXTRA: %s (in validator but not in mock)\n" % (
                            ep["param"]))
                    for tw in sig.get("type_warnings", []):
                        sys.stderr.write("      TYPE: %s (mock=%s, sends=%s, val=%s)\n" % (
                            tw["param"], tw["mock_type"], tw["api_sends"], tw["value"]))
            else:
                sys.stderr.write("\n  No parameter signature issues found.\n")

        sys.stderr.write("\n" + "=" * 60 + "\n")
        sys.exit(0)

    # ── Build final API list ──
    apis = list(API_DEFS)
    if new_api_defs:
        apis.extend(new_api_defs)
        sys.stderr.write("Added %d APIs from mock (total: %d)\n\n" % (
            len(new_api_defs), len(apis)))

    # Filter by domain if specified
    if args.domain:
        domains = set(d.strip().upper() for d in args.domain.split(","))
        apis = [a for a in apis if a["domain"] in domains]
        if not apis:
            sys.stderr.write("No APIs found for domain(s): %s\n" % args.domain)
            sys.exit(1)

    total = len(apis)

    if args.output:
        output_path = args.output
    else:
        output_path = DEFAULT_OUTPUT.replace("{ts}", ts)

    sys.stderr.write("=" * 60 + "\n")
    sys.stderr.write("  Port Sinan Production API Validator\n")
    if args.from_dump:
        sys.stderr.write("  Mode     : from-dump (%s)\n" % args.from_dump)
    else:
        sys.stderr.write("  Base URL : %s\n" % args.base_url)
    sys.stderr.write("  APIs     : %d\n" % total)
    sys.stderr.write("  Timeout  : %ds\n" % args.timeout)
    sys.stderr.write("  Output   : %s\n" % output_path)
    sys.stderr.write("  Time     : %s\n" % ts)
    if args.sync_mock:
        sys.stderr.write("  Mock Sync: %s (+%d new)\n" % (
            args.sync_mock, len(new_api_defs)))
    if args.compare_mock:
        sys.stderr.write("  Compare  : %s\n" % args.mock_url)
    if args.dump_prod:
        sys.stderr.write("  Dump Dir : %s\n" % args.dump_prod)
    sys.stderr.write("=" * 60 + "\n\n")

    # Quick connectivity check (skip for --from-dump)
    session = requests.Session()
    session.verify = False
    if not args.from_dump:
        sys.stderr.write("Connectivity check (prod) ... ")
        try:
            r = session.get(args.base_url.rstrip("/") + "/api/health", timeout=5)
            sys.stderr.write("OK (HTTP %d)\n" % r.status_code)
        except Exception as e:
            sys.stderr.write("WARN: %s\n" % str(e)[:100])
            sys.stderr.write("Proceeding anyway ...\n")

    # Check mock connectivity if compare mode
    mock_session = None
    if args.compare_mock:
        sys.stderr.write("Connectivity check (mock) ... ")
        mock_session = requests.Session()
        mock_session.verify = False
        try:
            r = mock_session.get(
                args.mock_url.rstrip("/") + "/api/health", timeout=5)
            sys.stderr.write("OK (HTTP %d)\n" % r.status_code)
        except Exception as e:
            sys.stderr.write("WARN: %s\n" % str(e)[:100])
            sys.stderr.write("Mock comparison will mark unreachable APIs.\n")

    sys.stderr.write("\n")

    # ── Validation loop ──
    results = []
    mock_results = []
    t_start = time.time()

    if args.from_dump:
        # Load prod results from local dump files
        if not os.path.isdir(args.from_dump):
            sys.stderr.write("[FATAL] Dump dir not found: %s\n" % args.from_dump)
            sys.exit(1)
        results = _load_dump_results(args.from_dump, apis)
        # Call mock for each API
        for idx, api_def in enumerate(apis):
            if mock_session is not None:
                mock_r = call_mock_api(mock_session, args.mock_url, api_def,
                                       args.timeout)
                mock_results.append(mock_r)
            else:
                mock_results.append({"status": "UNREACHABLE", "data": None,
                                      "error": "No mock session"})
            if not args.quiet:
                sys.stderr.write("\r  [%d/%d] mock: %s" % (
                    idx + 1, total, api_def["path"].rsplit("/", 1)[-1]))
        sys.stderr.write("\n")
    else:
        for idx, api_def in enumerate(apis):
            result = validate_single_api(
                session, args.base_url, api_def, args.timeout,
                mock_routes=mock_routes,
                show_signature=args.show_signature
            )
            results.append(result)

            # Call mock if in compare mode
            if args.compare_mock and mock_session is not None:
                mock_r = call_mock_api(mock_session, args.mock_url, api_def,
                                       args.timeout)
                mock_results.append(mock_r)
            elif args.compare_mock:
                mock_results.append({"status": "UNREACHABLE", "data": None,
                                      "error": "No mock session"})

            if not args.quiet:
                print_progress(idx, total, result)

            if args.fail_fast and result["status"] == "CONN_ERROR":
                sys.stderr.write("\n[FAIL-FAST] Connection error, stopping.\n")
                break

    elapsed = time.time() - t_start

    # ── Dump production data if requested (skip when using --from-dump) ──
    if args.dump_prod and not args.from_dump:
        dump_dir = args.dump_prod
        if not os.path.isdir(dump_dir):
            os.makedirs(dump_dir, exist_ok=True)
            sys.stderr.write("\nCreated dump directory: %s\n" % dump_dir)

        dump_count = 0
        dump_errors = 0
        dump_fail_count = 0
        for r in results:
            # Derive filename from path: /api/gateway/getFoo -> getFoo.json
            api_name = r["path"].rsplit("/", 1)[-1]
            domain = r.get("domain", "unknown")
            filename = "%s_%s.json" % (domain, api_name)
            filepath = os.path.join(dump_dir, filename)
            try:
                if r["status"] == "OK":
                    raw = r.get("_raw_data")
                    if raw is None:
                        continue
                    entry = {
                        "api": api_name,
                        "path": r["path"],
                        "domain": domain,
                        "intent": r.get("intent", ""),
                        "params_sent": r.get("params_sent", {}),
                        "response_pattern": r.get("response_pattern", ""),
                        "data_type": r.get("data_type", ""),
                        "data_count": r.get("data_count"),
                        "latency_ms": r.get("latency_ms"),
                        "fetched_at": ts,
                        "base_url": args.base_url,
                        "data": raw,
                    }
                    dump_count += 1
                else:
                    entry = {
                        "api": api_name,
                        "path": r["path"],
                        "domain": domain,
                        "intent": r.get("intent", ""),
                        "params_sent": r.get("params_sent", {}),
                        "status": r["status"],
                        "http_status": r.get("http_status"),
                        "error": r.get("error"),
                        "response_pattern": r.get("response_pattern"),
                        "data_sample": r.get("data_sample"),
                        "latency_ms": r.get("latency_ms"),
                        "fetched_at": ts,
                        "base_url": args.base_url,
                        "data": None,
                    }
                    dump_fail_count += 1
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(entry, f, ensure_ascii=False, indent=2)
            except Exception as e:
                dump_errors += 1
                sys.stderr.write("  [DUMP-ERR] %s: %s\n" % (filename, str(e)[:100]))

        sys.stderr.write("\nProd data dump: %d OK + %d FAIL files saved to %s" % (
            dump_count, dump_fail_count, dump_dir))
        if dump_errors:
            sys.stderr.write(" (%d errors)" % dump_errors)
        sys.stderr.write("\n")

    # ── Multi-variant enrichment phase ──
    if args.enrich and args.dump_prod and not args.from_dump:
        enrich_dir = os.path.join(args.dump_prod, "enriched")
        if not os.path.isdir(enrich_dir):
            os.makedirs(enrich_dir, exist_ok=True)

        # Identify APIs that returned data in base run
        ok_apis = {}
        for r, api_def in zip(results, apis):
            if r["status"] == "OK" and r.get("data_count", 0) and r.get("data_count", 0) > 0:
                ok_apis[api_def["path"]] = api_def

        sys.stderr.write("\n" + "=" * 60 + "\n")
        sys.stderr.write("  ENRICHMENT PHASE: %d APIs with data\n" % len(ok_apis))
        sys.stderr.write("=" * 60 + "\n")

        enrich_total = 0
        enrich_ok = 0
        enrich_empty = 0
        enrich_err = 0

        for api_idx, (path, api_def) in enumerate(sorted(ok_apis.items())):
            variants = generate_param_variants(api_def)
            if len(variants) <= 1:
                continue  # no extra variants for this API

            api_name = path.rsplit("/", 1)[-1]
            domain = api_def.get("domain", "unknown")

            for vtag, vparams in variants[1:]:  # skip v0 (already fetched)
                enrich_total += 1
                # Build a temporary api_def with variant params
                variant_def = dict(api_def)
                variant_def["params"] = vparams

                vresult = validate_single_api(
                    session, args.base_url, variant_def, args.timeout
                )

                # Save variant data
                filename = "%s_%s_%s.json" % (domain, api_name, vtag)
                filepath = os.path.join(enrich_dir, filename)

                vparams_sent = build_params(vparams)
                try:
                    if vresult["status"] == "OK":
                        raw = vresult.get("_raw_data")
                        vdata_count = vresult.get("data_count", 0)
                        if raw is not None and vdata_count and vdata_count > 0:
                            enrich_ok += 1
                        else:
                            enrich_empty += 1
                        entry = {
                            "api": api_name,
                            "path": path,
                            "domain": domain,
                            "intent": api_def.get("intent", ""),
                            "variant": vtag,
                            "params_sent": vparams_sent,
                            "response_pattern": vresult.get("response_pattern", ""),
                            "data_type": vresult.get("data_type", ""),
                            "data_count": vdata_count,
                            "latency_ms": vresult.get("latency_ms"),
                            "fetched_at": ts,
                            "base_url": args.base_url,
                            "data": raw,
                        }
                    else:
                        enrich_err += 1
                        entry = {
                            "api": api_name,
                            "path": path,
                            "domain": domain,
                            "intent": api_def.get("intent", ""),
                            "variant": vtag,
                            "params_sent": vparams_sent,
                            "status": vresult["status"],
                            "error": vresult.get("error"),
                            "latency_ms": vresult.get("latency_ms"),
                            "fetched_at": ts,
                            "base_url": args.base_url,
                            "data": None,
                        }
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(entry, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    enrich_err += 1
                    sys.stderr.write("  [ENRICH-ERR] %s: %s\n" % (
                        filename, str(e)[:100]))

                if not args.quiet:
                    dc = vresult.get("data_count", 0) or 0
                    sys.stderr.write(
                        "\r  [%d] %s %s  params=%s  data=%d    " % (
                            enrich_total, api_name, vtag,
                            json.dumps(vparams_sent, ensure_ascii=False)[:60],
                            dc,
                        ))

        sys.stderr.write(
            "\n\nEnrichment done: %d variants fetched "
            "(%d with data, %d empty, %d errors)\n"
            "  Saved to: %s\n" % (
                enrich_total, enrich_ok, enrich_empty, enrich_err, enrich_dir))


    # ── Generate comparison report if requested (before stripping _raw_data) ──
    comp_report = None
    comp_path = None
    if args.compare_mock and mock_results:
        comp_report = generate_comparison_report(
            results, mock_results, args.base_url, args.mock_url, ts
        )
        if args.compare_output:
            comp_path = args.compare_output
        else:
            comp_path = "comparison_report_%s.json" % ts
        with open(comp_path, "w") as f:
            json.dump(comp_report, f, ensure_ascii=False, indent=2)

    # Strip _raw_data from results before writing report (avoid bloating the report)
    for r in results:
        r.pop("_raw_data", None)

    summary = generate_summary(results, sync_stats=sync_stats)
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["base_url"] = args.base_url
    summary["timestamp"] = ts

    report = {
        "summary": summary,
        "results": results,
    }

    # Write validation report
    with open(output_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ── Print summary to stderr ──
    sys.stderr.write("\n" + "=" * 60 + "\n")
    sys.stderr.write("  VALIDATION COMPLETE\n")
    sys.stderr.write("  Total    : %d APIs\n" % summary["total_apis"])
    sys.stderr.write("  Passed   : %d\n" % summary["ok_count"])
    sys.stderr.write("  Failed   : %d\n" % summary["fail_count"])
    sys.stderr.write("  Pass Rate: %s\n" % summary["pass_rate"])
    sys.stderr.write("  Elapsed  : %.1fs\n" % elapsed)
    sys.stderr.write("  Avg Lat  : %.1fms\n" % summary["latency"]["avg_ms"])
    sys.stderr.write("  P95 Lat  : %.1fms\n" % summary["latency"]["p95_ms"])
    sys.stderr.write("  Report   : %s\n" % output_path)

    # Sync stats
    if sync_stats:
        sys.stderr.write("\n  --- Mock Sync ---\n")
        sys.stderr.write("  Mock Routes  : %d\n" % sync_stats.get(
            "total_mock_routes", 0))
        sys.stderr.write("  New APIs     : %d\n" % sync_stats.get(
            "new_apis_found", 0))
        ss = summary.get("sync_stats", {})
        sys.stderr.write("  Sig Issues   : %d\n" % ss.get(
            "signature_issues", 0))

    # Comparison stats
    if args.compare_mock and mock_results:
        cs = comp_report["summary"]
        sys.stderr.write("\n  --- Prod vs Mock ---\n")
        sys.stderr.write("  Compared     : %d\n" % cs["total_compared"])
        sys.stderr.write("  Field Match  : %d\n" % cs["field_match"])
        sys.stderr.write("  Field Diff   : %d\n" % cs["field_mismatch"])
        sys.stderr.write("  Unreachable  : %d\n" % cs["mock_unreachable"])
        sys.stderr.write("  Compare Rpt  : %s\n" % comp_path)

        # Quality assessment
        oq = comp_report.get("overall_quality", {})
        if oq:
            sys.stderr.write("\n  --- Mock Quality Assessment ---\n")
            sys.stderr.write("  Overall      : %.1f (%s)\n" % (
                oq.get("score", 0), oq.get("grade", "N/A")))
            gd = oq.get("grade_distribution", {})
            sys.stderr.write("  Distribution : %dE  %dG  %dF  %dP\n" % (
                gd.get("EXCELLENT", 0), gd.get("GOOD", 0),
                gd.get("FAIR", 0), gd.get("POOR", 0)))

            dq = comp_report.get("domain_quality", {})
            domain_names_q = {
                "D1": "生产运营", "D2": "市场商务", "D3": "客户管理",
                "D4": "投企管理", "D5": "资产管理", "D6": "投资管理",
                "D7": "设备子屏",
            }
            for dm in sorted(dq.keys()):
                di = dq[dm]
                dn = domain_names_q.get(dm, dm)
                sys.stderr.write("  %s %-8s : %.1f (%s)  [%dE %dG %dF %dP]\n" % (
                    dm, dn, di["domain_score"], di["grade"],
                    di.get("excellent", 0), di.get("good", 0),
                    di.get("fair", 0), di.get("poor", 0)))

            ai = comp_report.get("action_items", [])
            if ai:
                show_n = min(5, len(ai))
                sys.stderr.write("\n  Top Action Items (%d of %d):\n" % (show_n, len(ai)))
                for item in ai[:show_n]:
                    sys.stderr.write("    [%s] %s %s - %s\n" % (
                        item["priority"], item["domain"],
                        item["path"].split("/")[-1],
                        item["issue"][:70]))

    sys.stderr.write("=" * 60 + "\n")

    # Domain breakdown
    domain_names = {
        "D1": "生产运营", "D2": "市场商务", "D3": "客户管理",
        "D4": "投企管理", "D5": "资产管理", "D6": "投资管理",
        "D7": "设备子屏",
    }
    sys.stderr.write("\nDomain Breakdown:\n")
    for dm in sorted(summary["by_domain"].keys()):
        info = summary["by_domain"][dm]
        dn = domain_names.get(dm, dm)
        sys.stderr.write("  %s %-8s : %d/%d OK\n" % (
            dm, dn, info["ok"], info["total"]))

    # Failed APIs list
    failed = [r for r in results if r["status"] != "OK"]
    if failed:
        sys.stderr.write("\nFailed APIs (%d):\n" % len(failed))
        for r in failed:
            sys.stderr.write("  [%s] %s %s - %s\n" % (
                r["status"], r["domain"], r["path"],
                (r.get("error") or "")[:80]
            ))

    sys.stderr.write("\n")

    # Exit code: 0 if all passed, 1 if any failed
    if summary["fail_count"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
