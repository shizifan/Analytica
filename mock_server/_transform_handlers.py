#!/usr/bin/env python3
"""
One-shot transformation script: rewrite mock_server_all.py handler return fields
to align with production data, based on field_mapping.json.

Strategy:
- Read mock_server_all.py
- For each handler with prod data, find the return ok(...) block
- Replace it with production-aligned fields
- Write back the modified file
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOCK_FILE = os.path.join(HERE, "mock_server_all.py")
MAPPING_FILE = os.path.join(HERE, "field_mapping.json")
PROD_DIR = os.path.join(HERE, "prod_data")

with open(MAPPING_FILE, "r", encoding="utf-8") as f:
    FIELD_MAP = json.load(f)

with open(MOCK_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

# ── Helper: find handler start/end line indices ──

def find_handler_range(lines, api_path):
    """Find the line range (start_idx, end_idx) for a handler by its route path."""
    route_pattern = '@app.get("%s")' % api_path
    start = None
    for i, line in enumerate(lines):
        if route_pattern in line:
            start = i
            break
    if start is None:
        return None, None
    # Find end: next @app.get or # ─── section divider or end of file
    end = len(lines)
    for i in range(start + 2, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("@app.get(") or stripped.startswith("# ──"):
            end = i
            break
    return start, end


def find_return_ok(lines, start, end):
    """Find the return ok(...) statement within handler range. Returns (line_idx, indent)."""
    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith("return ok("):
            indent = len(lines[i]) - len(lines[i].lstrip())
            return i, indent
    return None, None


def replace_handler_return(lines, api_name, new_return_code):
    """Replace the return ok(...) block of a handler with new code."""
    api_path = "/api/gateway/%s" % api_name
    start, end = find_handler_range(lines, api_path)
    if start is None:
        print("  WARNING: handler not found for %s" % api_name)
        return False

    ret_line, indent = find_return_ok(lines, start, end)
    if ret_line is None:
        print("  WARNING: return ok() not found for %s" % api_name)
        return False

    # Find the extent of the return statement (handles multi-line)
    # Count parentheses to find the matching close
    ret_end = ret_line
    depth = 0
    for i in range(ret_line, end):
        for ch in lines[i]:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
        if depth <= 0:
            ret_end = i
            break

    # Build indented replacement
    prefix = " " * indent
    new_lines = []
    for ln in new_return_code.strip().split("\n"):
        new_lines.append(prefix + ln + "\n")

    lines[ret_line:ret_end + 1] = new_lines
    return True


# ══════════════════════════════════════════════════════════════
# Handler-specific transformations
# Each function modifies `lines` in place.
# ══════════════════════════════════════════════════════════════

changes = 0

# ── D1: 28 APIs ──────────────────────────────────────────────

# getThroughputAndTargetThroughputTon: dict→list[1], fields: finishQty, targetQty
if replace_handler_return(lines, "getThroughputAndTargetThroughputTon",
    '''return ok([{"finishQty": actual, "targetQty": target}])'''):
    changes += 1

# getThroughputAndTargetThroughputTeu: dict→list[1], fields: finishQty, targetQty
if replace_handler_return(lines, "getThroughputAndTargetThroughputTeu",
    '''return ok([{"finishQty": actual_teu, "targetQty": target_teu}])'''):
    changes += 1

# getBerthOccupancyRateByRegion: fields: regionName, dateMonth, rate
# Needs restructure: iterate regions x months
api_path = "/api/gateway/getBerthOccupancyRateByRegion"
start, end = find_handler_range(lines, api_path)
if start is not None:
    ret_line, indent = find_return_ok(lines, start, end)
    if ret_line is not None:
        # Find extent
        ret_end = ret_line
        depth = 0
        for i in range(ret_line, end):
            for ch in lines[i]:
                if ch == '(': depth += 1
                elif ch == ')': depth -= 1
            if depth <= 0: ret_end = i; break
        prefix = " " * indent
        new_code = [
            prefix + 'months = [f"{year}-{m:02d}" for year in [2025, 2026] for m in range(1, 13)][:3]\n',
            prefix + 'return ok([{\n',
            prefix + '    "regionName": reg,\n',
            prefix + '    "dateMonth": mo,\n',
            prefix + '    "rate": round(r.uniform(0.25, 0.65), 4),\n',
            prefix + '} for reg in REGIONS for mo in months])\n',
        ]
        lines[ret_line:ret_end + 1] = new_code
        changes += 1
        print("  OK: getBerthOccupancyRateByRegion (restructured)")

# getBerthOccupancyRateByBusinessType: fields: businessType, dateMonth, rate
if replace_handler_return(lines, "getBerthOccupancyRateByBusinessType",
    '''months = [f"{year}-{m:02d}" for year in [2025, 2026] for m in range(1, 13)][:3]
return ok([{
    "businessType": bt,
    "dateMonth": mo,
    "rate": round(r.uniform(0.05, 0.50), 4),
} for bt in BUSINESS_TYPES for mo in months])'''):
    changes += 1

# getContainerAnalysisYoyMomByYear: fields: dateType, qty, regionName, statType
if replace_handler_return(lines, "getContainerAnalysisYoyMomByYear",
    '''stat_types = ["当期", "同比", "环比"]
return ok([{
    "dateType": "年",
    "qty": round(r.uniform(0.5, 200), 1),
    "regionName": reg,
    "statType": st,
} for reg in REGIONS for st in stat_types])'''):
    changes += 1

# getContainerByBusinessType: fields: finishQty, regionName, targetQty
if replace_handler_return(lines, "getContainerByBusinessType",
    '''return ok([{
    "finishQty": round(r.uniform(10, 200), 1),
    "regionName": reg,
    "targetQty": round(r.uniform(20, 300), 1),
} for reg in REGIONS])'''):
    changes += 1

# getContainerThroughputAnalysisByYear: fields: dateMonth, qty
if replace_handler_return(lines, "getContainerThroughputAnalysisByYear",
    '''return ok([{
    "dateMonth": f"{sy}-{m:02d}" if m <= 12 else f"{sy+1}-{m-12:02d}",
    "qty": round(month_throughput_ton(sy if m <= 12 else sy+1, m if m <= 12 else m-12, None, r) * 0.03, 1),
} for m in range(1, 17)])'''):
    changes += 1

# getOilsChemBreakBulkByBusinessType: fields: finishQty, regionName, targetQty
if replace_handler_return(lines, "getOilsChemBreakBulkByBusinessType",
    '''return ok([{
    "finishQty": round(r.uniform(100, 800), 1),
    "regionName": reg,
    "targetQty": round(r.uniform(200, 1000), 1),
} for reg in REGIONS])'''):
    changes += 1

# getRoroByBusinessType: fields: finishQty, regionName, targetQty
if replace_handler_return(lines, "getRoroByBusinessType",
    '''return ok([{
    "finishQty": round(r.uniform(5, 30), 1),
    "regionName": reg,
    "targetQty": round(r.uniform(10, 40), 1),
} for reg in REGIONS[:1]])'''):
    changes += 1

# getPersonalCenterCargoThroughput: dict→list[5], fields: curTonQ,curTeuQ,momTonQ,momTeuQ,yoyTonQ,yoyTeuQ,regionName
if replace_handler_return(lines, "getPersonalCenterCargoThroughput",
    '''return ok([{
    "regionName": reg,
    "curTonQ": round(r.uniform(1, 50), 1),
    "curTeuQ": round(r.uniform(100, 2000), 0),
    "momTonQ": round(r.uniform(1, 50), 1),
    "momTeuQ": round(r.uniform(100, 2000), 0),
    "yoyTonQ": round(r.uniform(1, 50), 1),
    "yoyTeuQ": round(r.uniform(100, 2000), 0),
} for reg in REGIONS_SHORT])'''):
    changes += 1

# getPersonalCenterMonthCargoThroughput: same fields as above
if replace_handler_return(lines, "getPersonalCenterMonthCargoThroughput",
    '''return ok([{
    "regionName": reg,
    "curTonQ": round(r.uniform(50, 500), 1),
    "curTeuQ": round(r.uniform(1, 50), 1),
    "momTonQ": round(r.uniform(50, 500), 1),
    "momTeuQ": round(r.uniform(1, 50), 1),
    "yoyTonQ": round(r.uniform(50, 500), 1),
    "yoyTeuQ": round(r.uniform(1, 50), 1),
} for reg in REGIONS_SHORT])'''):
    changes += 1

# getPersonalCenterYearCargoThroughput: fields: curTeuQ,curTonQ,regionName,yoyTeuQ,yoyTonQ
if replace_handler_return(lines, "getPersonalCenterYearCargoThroughput",
    '''return ok([{
    "regionName": reg,
    "curTonQ": round(r.uniform(500, 8000), 1),
    "curTeuQ": round(r.uniform(50, 500), 1),
    "yoyTonQ": round(r.uniform(500, 8000), 1),
    "yoyTeuQ": round(r.uniform(50, 500), 1),
} for reg in REGIONS_SHORT])'''):
    changes += 1

# getPersonalCenterYearCargoThroughputTrend: fields: monthId,regionName,teuQ,tonQ,yearId
if replace_handler_return(lines, "getPersonalCenterYearCargoThroughputTrend",
    '''return ok([{
    "monthId": f"{m:02d}月",
    "regionName": reg,
    "teuQ": round(r.uniform(1, 50), 1),
    "tonQ": round(r.uniform(50, 500), 1),
    "yearId": str(year),
} for reg in REGIONS_SHORT for m in range(1, 4)])'''):
    changes += 1

# getPortCompanyThroughput: fields: businessType, dateYear, num
if replace_handler_return(lines, "getPortCompanyThroughput",
    '''return ok([{
    "businessType": bt,
    "dateYear": year,
    "num": round(r.uniform(0, 500), 1),
} for bt in BUSINESS_TYPES[:2]])'''):
    changes += 1

# getProdShipDesc: fields: anchorageVesselDesc, orgType, portVesselDesc
if replace_handler_return(lines, "getProdShipDesc",
    '''return ok([{
    "orgType": reg + "区域",
    "portVesselDesc": "在泊船舶%d艘" % r.randint(5, 25),
    "anchorageVesselDesc": "锚地船舶%d艘" % r.randint(2, 15),
} for reg in REGIONS_SHORT])'''):
    changes += 1

# getProdShipDynNum: fields: num, orgType, typeName
if replace_handler_return(lines, "getProdShipDynNum",
    '''type_names = ["在泊船", "锚泊船", "离泊船", "抵港船"]
return ok([{
    "num": r.randint(1, 30),
    "orgType": reg + "区域",
    "typeName": tn,
} for reg in REGIONS_SHORT for tn in type_names[:4]])'''):
    changes += 1

# getProductViewShipOperationRateAvg: fields: statCargoKind, tonQ, workTh
if replace_handler_return(lines, "getProductViewShipOperationRateAvg",
    '''cargo_kinds = ["矿石", "油品", "散杂货", "集装箱"]
return ok([{
    "statCargoKind": ck,
    "tonQ": round(r.uniform(1000000, 8000000), 1),
    "workTh": round(r.uniform(500, 2000), 1),
} for ck in cargo_kinds])'''):
    changes += 1

# getProductViewShipOperationRateTrend: fields: monthId, monthStr, statCargoKind, tonQ, workTh
if replace_handler_return(lines, "getProductViewShipOperationRateTrend",
    '''cargo_kinds = ["矿石", "油品", "散杂货", "集装箱"]
return ok([{
    "monthId": f"{year}-{m:02d}",
    "monthStr": f"{m:02d}月",
    "statCargoKind": ck,
    "tonQ": round(r.uniform(1000000, 8000000), 1),
    "workTh": round(r.uniform(300, 1500), 1),
} for m in range(1, 4) for ck in cargo_kinds])'''):
    changes += 1

# getRealTimeWeather: fields: createTime, regionName, stationId, stationName, weather
if replace_handler_return(lines, "getRealTimeWeather",
    '''stations = [
    ("L2413", "大连湾港区", "大连"), ("L2414", "大窑湾港区", "大连"),
    ("L2415", "长兴岛港区", "大连"), ("Y2001", "营口港区", "营口"),
    ("D3001", "丹东港区", "丹东"), ("P4001", "盘锦港区", "盘锦"),
    ("S5001", "绥中港区", "绥中"),
]
return ok([{
    "createTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "regionName": st[2],
    "stationId": st[0],
    "stationName": st[1],
    "weather": "当前温度%.1f℃,%s%d级" % (r.uniform(5, 30), r.choice(["东风", "南风", "西风", "北风"]), r.randint(1, 6)),
} for st in stations for _ in range(r.randint(15, 25))])'''):
    changes += 1

# getWeatherForecast: fields: furtherDate, regionCode, regionName, weather
if replace_handler_return(lines, "getWeatherForecast",
    '''region_codes = {"大连": "DL", "营口": "YK", "丹东": "DD", "盘锦": "PJ", "绥中": "SZ"}
from datetime import timedelta
base_date = datetime.now()
return ok([{
    "furtherDate": (base_date + timedelta(days=d)).strftime("%Y-%m-%d"),
    "regionCode": region_codes.get(reg, "XX"),
    "regionName": reg,
    "weather": "%s,%s%d到%d级,%d℃~%d℃" % (
        r.choice(["晴", "多云", "阴", "小雨", "中雨"]),
        r.choice(["偏南风", "偏北风", "东风", "西风"]),
        r.randint(2, 4), r.randint(4, 7),
        r.randint(5, 15), r.randint(16, 28)),
} for reg in REGIONS_SHORT for d in range(1, 4)])'''):
    changes += 1

# getShipStatisticsByBusinessType: fields: anchorageQty, berthQty, businessType, planQty
if replace_handler_return(lines, "getShipStatisticsByBusinessType",
    '''return ok([{
    "anchorageQty": r.randint(0, 10),
    "berthQty": r.randint(3, 20),
    "businessType": bt,
    "planQty": r.randint(5, 30),
} for bt in ["货船", "油轮", "集装箱船", "滚装船"]])'''):
    changes += 1

# getThroughputAnalysisByYear: fields: dateMonth, qty
if replace_handler_return(lines, "getThroughputAnalysisByYear",
    '''return ok([{
    "dateMonth": f"{sy}-{m:02d}" if m <= 12 else f"{sy+1}-{m-12:02d}",
    "qty": round(month_throughput_ton(sy if m <= 12 else sy+1, m if m <= 12 else m-12, None, r), 1),
} for m in range(1, 17)])'''):
    changes += 1

# getThroughputAnalysisContainer: fields: finishQty, regionName, targetQty
if replace_handler_return(lines, "getThroughputAnalysisContainer",
    '''return ok([{
    "finishQty": round(r.uniform(50, 500), 1),
    "regionName": reg,
    "targetQty": round(r.uniform(200, 1000), 1),
} for reg in REGIONS])'''):
    changes += 1

# getThroughputAnalysisNonContainer: fields: finishQty, regionName, targetQty
if replace_handler_return(lines, "getThroughputAnalysisNonContainer",
    '''return ok([{
    "finishQty": round(r.uniform(1000, 8000), 1),
    "regionName": reg,
    "targetQty": round(r.uniform(5000, 25000), 1),
} for reg in REGIONS])'''):
    changes += 1

# getThroughputAnalysisYoyMomByDay: fields: momQty, qty, regionName, yoyQty
if replace_handler_return(lines, "getThroughputAnalysisYoyMomByDay",
    '''return ok([{
    "momQty": round(r.uniform(30, 80), 2),
    "qty": round(r.uniform(30, 80), 2),
    "regionName": reg,
    "yoyQty": round(r.uniform(30, 80), 2),
} for reg in REGIONS + ["辽港"]])'''):
    changes += 1

# getThroughputAnalysisYoyMomByMonth: fields: momQty, qty, regionName, yoyQty
if replace_handler_return(lines, "getThroughputAnalysisYoyMomByMonth",
    '''return ok([{
    "momQty": round(r.uniform(500, 1500), 2),
    "qty": round(r.uniform(500, 1500), 2),
    "regionName": reg,
    "yoyQty": round(r.uniform(500, 1500), 2),
} for reg in REGIONS + ["辽港"]])'''):
    changes += 1

# getThroughputAnalysisYoyMomByYear: fields: dateType, qty, regionName, statType
if replace_handler_return(lines, "getThroughputAnalysisYoyMomByYear",
    '''stat_types = ["当期", "同比", "环比"]
date_types = ["年"]
return ok([{
    "dateType": dt,
    "qty": round(r.uniform(10, 5000), 1),
    "regionName": reg,
    "statType": st,
} for reg in REGIONS + ["辽港"] for st in stat_types for dt in date_types])'''):
    changes += 1

# getVesselOperationEfficiency: dict→list[1], fields: curEfficiency, lastEfficiency
if replace_handler_return(lines, "getVesselOperationEfficiency",
    '''return ok([{"curEfficiency": round(r.uniform(50, 120), 1), "lastEfficiency": round(r.uniform(50, 120), 1)}])'''):
    changes += 1

# ── D2: 9 APIs ──────────────────────────────────────────────

# getCumulativeKeyEnterprise: fields: companyName, dateYear, throughput
if replace_handler_return(lines, "getCumulativeKeyEnterprise",
    '''top_cmp = ["集装箱码头公司", "股份集码", "散杂货码头", "大连港油码头有限公司", "DCT",
    "营口集装箱码头有限公司", "散粮码头", "盘锦集装箱", "散杂货事业部",
    "大连汽车码头有限公司", "大连港散杂货码头分公司", "辽港控股（营口）有限公司粮食分公司",
    "辽港控股（营口）有限公司第一分公司", "大连海嘉汽车码头有限公司"]
return ok([{
    "companyName": cmp,
    "dateYear": str(year),
    "throughput": round(r.uniform(50, 600), 2),
} for cmp in top_cmp])'''):
    changes += 1

# getCumulativeThroughput: fields: dateYear, ioTrade, throughput
if replace_handler_return(lines, "getCumulativeThroughput",
    '''return ok([{
    "dateYear": str(y),
    "ioTrade": trade,
    "throughput": round(r.uniform(1000, 5000), 2),
} for y in [year, year - 1] for trade in ["外贸", "内贸"]])'''):
    changes += 1

# getCumulativeTrendChart: fields: businessSegment, dateYear, throughput
if replace_handler_return(lines, "getCumulativeTrendChart",
    '''return ok([{
    "businessSegment": bt,
    "dateYear": str(year),
    "throughput": round(r.uniform(500, 5000), 1),
} for bt in BUSINESS_TYPES[:2]])'''):
    changes += 1

# getCurBusinessDashboardThroughput: fields: num, typeName
if replace_handler_return(lines, "getCurBusinessDashboardThroughput",
    '''type_names = ["当期吞吐量", "去年同期吞吐量", "同比吞吐量差异",
    "同比增速", "去年全年吞吐量", "今年目标吞吐量", "当期完成进度", "去年同期完成进度"]
return ok([{
    "num": round(r.uniform(-50, 5000), 1) if i < 6 else round(r.uniform(0, 100), 1),
    "typeName": tn,
} for i, tn in enumerate(type_names)])'''):
    changes += 1

# getKeyEnterprise: fields: companyName, dateMonth, throughput
if replace_handler_return(lines, "getKeyEnterprise",
    '''top_cmp = ["股份集码", "散杂货码头", "DCT", "大连港油码头有限公司",
    "营口集装箱码头有限公司", "散粮码头", "大连汽车码头有限公司"]
return ok([{
    "companyName": cmp,
    "dateMonth": f"{year}-{month:02d}",
    "throughput": round(r.uniform(50, 600), 2),
} for cmp in top_cmp])'''):
    changes += 1

# getMonthlyRegionalThroughputAreaBusinessDashboard: fields: num, typeName, zoneName
if replace_handler_return(lines, "getMonthlyRegionalThroughputAreaBusinessDashboard",
    '''type_names = ["计划吞吐量", "当期吞吐量", "去年同期吞吐量",
    "同比增速", "当期完成进度", "去年同期完成进度"]
return ok([{
    "num": round(r.uniform(100, 3000), 1),
    "typeName": tn,
    "zoneName": reg,
} for reg in REGIONS for tn in type_names[:1]])'''):
    changes += 1

# getSumBusinessDashboardThroughput (new API with prod data): fields: num, typeName
# This one is in the 21 new APIs, handle in Step 4

# getTrendChart: fields: businessSegment, dateMonth, throughput
if replace_handler_return(lines, "getTrendChart",
    '''return ok([{
    "businessSegment": bt,
    "dateMonth": f"{year}-{month:02d}",
    "throughput": round(month_throughput_ton(year, month, None, r) * 0.25, 1),
} for bt in BUSINESS_TYPES[:1]])'''):
    changes += 1

# ── D3: 10 APIs ──────────────────────────────────────────────

# getCurContributionRankOfStrategicCustomer: fields: clientName, num
if replace_handler_return(lines, "getCurContributionRankOfStrategicCustomer",
    '''return ok([{
    "clientName": cl,
    "num": round(r.uniform(0, 200), 1),
} for cl in STRATEGIC_CLIENTS + [
    "广州汽车集团股份有限公司", "华能国际电力股份有限公司",
    "中国华电集团有限公司", "国家电力投资集团有限公司",
    "中国铝业集团有限公司", "中粮集团有限公司",
    "国投交通控股有限公司", "中国建筑股份有限公司",
    "中国交通建设集团有限公司", "中国能源建设集团有限公司",
    "宝武钢铁集团有限公司", "首钢集团有限公司",
    "河钢集团有限公司", "太原钢铁集团有限公司",
    "山东钢铁集团有限公司", "湖南钢铁集团有限公司",
    "北京建龙重工集团有限公司", "敬业钢铁有限公司",
    "福建三宝钢铁有限公司", "日照钢铁控股集团有限公司",
    "凌源钢铁集团有限责任公司", "东北特殊钢集团股份有限公司",
]])'''):
    changes += 1

# getCurStrategicCustomerContributionByCargoTypeThroughput: fields: categoryName, num
if replace_handler_return(lines, "getCurStrategicCustomerContributionByCargoTypeThroughput",
    '''return ok([{
    "categoryName": cat,
    "num": round(r.uniform(0, 500), 1),
} for cat in ["散杂货", "集装箱", "油化品", "商品车"]])'''):
    changes += 1

# getCustomerFieldAnalysis: fields: indstryFieldName, qty
if replace_handler_return(lines, "getCustomerFieldAnalysis",
    '''fields = ["煤炭", "矿石", "钢材", "粮食", "石油化工", "集装箱", "汽车", "木材",
    "水泥", "化肥", "机械设备", "日用百货", "建材", "有色金属", "其他", "农副产品", "纸浆"]
return ok([{
    "indstryFieldName": f,
    "qty": r.randint(1, 200),
} for f in fields])'''):
    changes += 1

# getCustomerQty: dict→list[1], fields: customerFilesNumber,outPortQty,strategyClientQty,totalQty
if replace_handler_return(lines, "getCustomerQty",
    '''return ok([{
    "customerFilesNumber": r.randint(8000, 10000),
    "outPortQty": r.randint(5000, 7000),
    "strategyClientQty": r.randint(30, 50),
    "totalQty": r.randint(6000, 7000),
}])'''):
    changes += 1

# getCustomerTypeAnalysis: fields: clientType, qty
if replace_handler_return(lines, "getCustomerTypeAnalysis",
    '''types = ["自然人", "机关团体", "非自然人", "非企业单位", "企业法人", "个体工商户",
    "非法人组织", "外国人", "外国法人", "临时账户", "其他组织", "合伙企业", "个人独资企业"]
return ok([{
    "clientType": t,
    "qty": r.randint(1, 3000),
} for t in types])'''):
    changes += 1

# getStrategicCustomers: fields: displayCode, displayName
if replace_handler_return(lines, "getStrategicCustomers",
    '''return ok([{
    "displayCode": hashlib.md5(cl.encode()).hexdigest()[:24],
    "displayName": cl,
} for cl in STRATEGIC_CLIENTS + [
    "广州汽车集团股份有限公司", "华能国际电力股份有限公司",
    "中国华电集团有限公司", "国家电力投资集团有限公司",
    "中国铝业集团有限公司", "中粮集团有限公司",
    "国投交通控股有限公司", "中国建筑股份有限公司",
    "中国交通建设集团有限公司", "中国能源建设集团有限公司",
    "宝武钢铁集团有限公司", "首钢集团有限公司",
    "河钢集团有限公司", "太原钢铁集团有限公司",
    "山东钢铁集团有限公司", "湖南钢铁集团有限公司",
    "北京建龙重工集团有限公司", "敬业钢铁有限公司",
    "福建三宝钢铁有限公司", "日照钢铁控股集团有限公司",
    "凌源钢铁集团有限责任公司", "东北特殊钢集团股份有限公司",
]])'''):
    changes += 1

# getSumContributionRankOfStrategicCustomer: same as Cur version
# This is in the 21 new APIs, handle in Step 4

# getSumStrategicCustomerContributionByCargoTypeThroughput: same as Cur version
# This is in the 21 new APIs, handle in Step 4

# getSumStrategyCustomerTrendAnalysis: fields: dateYear, num
if replace_handler_return(lines, "getSumStrategyCustomerTrendAnalysis",
    '''return ok([{
    "dateYear": y,
    "num": round(r.uniform(0, 2000), 1),
} for y in [year, year - 1]])'''):
    changes += 1

# ── D4: 1 API ──────────────────────────────────────────────

# investCorpShareholdingProp: fields: num, ratio, ratioName
if replace_handler_return(lines, "investCorpShareholdingProp",
    '''ratio_names = ["绝对控制线", "相对控制线", "安全控制线", "重大决议否决线",
    "临时股东会召开线", "重大决议基本否决线", "资产收益及选任管理者", "提案权", "代位诉讼权"]
ratios = ["67%", "51%", "34%", "34%", "10%", "34%", "10%", "3%", "1%"]
return ok([{
    "num": r.randint(10, 200),
    "ratio": ratios[i],
    "ratioName": rn,
} for i, rn in enumerate(ratio_names)])'''):
    changes += 1

# ── D5: 17 APIs ──────────────────────────────────────────────

# getAssetValue: dict→list[1], fields: netlValue, originalValue, periodNetlValue, periodOriginalValue
if replace_handler_return(lines, "getAssetValue",
    '''return ok([{
    "netlValue": round(r.uniform(10000, 50000), 2),
    "originalValue": round(r.uniform(50000, 150000), 2),
    "periodNetlValue": round(r.uniform(100, 5000), 2),
    "periodOriginalValue": round(r.uniform(100, 5000), 2),
}])'''):
    changes += 1

# getCategoryAnalysis: fields: assetTypeName, num, typeName
if replace_handler_return(lines, "getCategoryAnalysis",
    '''asset_types = ["设备", "设施", "房屋", "土地海域", "林木", "在建工程"]
type_names = ["实物资产数", "资产原值", "资产净值", "面积"]
return ok([{
    "assetTypeName": at,
    "num": round(r.uniform(100, 20000), 1),
    "typeName": tn,
} for at in asset_types for tn in type_names])'''):
    changes += 1

# getCategoryAnalysisTransparentTransmission: fields: num, ownerUnitName, typeName
if replace_handler_return(lines, "getCategoryAnalysisTransparentTransmission",
    '''type_names = ["实物资产数", "资产原值", "资产净值"]
return ok([{
    "num": round(r.uniform(1, 5000), 1),
    "ownerUnitName": cmp,
    "typeName": tn,
} for cmp in COMPANIES for tn in type_names])'''):
    changes += 1

# getEquipmentFacilityAnalysis: fields: assetTypeName, num, typeName
if replace_handler_return(lines, "getEquipmentFacilityAnalysis",
    '''equip_types = ["锅炉设备", "通信设备", "仪器仪表", "电子设备", "交通运输设备",
    "动力设备", "专用机械", "通用机械", "工具器具", "其他设备"]
type_names = ["实物资产数", "资产原值", "资产净值", "面积", "报废数", "处置数"]
return ok([{
    "assetTypeName": et,
    "num": round(r.uniform(1, 5000), 1),
    "typeName": tn,
} for et in equip_types for tn in type_names])'''):
    changes += 1

# getEquipmentFacilityAnalysisYoy: fields: dateYear, num, typeName
if replace_handler_return(lines, "getEquipmentFacilityAnalysisYoy",
    '''type_names = ["实物资产数", "资产原值", "资产净值"]
return ok([{
    "dateYear": float(y),
    "num": round(r.uniform(5000, 30000), 1),
    "typeName": tn,
} for y in [year, year - 1] for tn in type_names])'''):
    changes += 1

# getEquipmentFacilityRegionalAnalysis: fields: num, ownerZone, typeName
if replace_handler_return(lines, "getEquipmentFacilityRegionalAnalysis",
    '''type_names = ["实物资产数", "资产原值"]
return ok([{
    "num": round(r.uniform(500, 10000), 1),
    "ownerZone": reg,
    "typeName": tn,
} for reg in REGIONS_SHORT + ["综合事业部"] for tn in type_names])'''):
    changes += 1

# getEquipmentFacilityStatusAnalysis: fields: assetStatus, num, typeName
if replace_handler_return(lines, "getEquipmentFacilityStatusAnalysis",
    '''statuses = ["报废", "封存", "启用", "在建", "停用", "闲置"]
type_names = ["实物资产数", "资产原值", "资产净值", "面积"]
return ok([{
    "assetStatus": st,
    "num": round(r.uniform(1, 5000), 1),
    "typeName": tn,
} for st in statuses for tn in type_names])'''):
    changes += 1

# getEquipmentFacilityWorthAnalysis: fields: num, rate, typeName
if replace_handler_return(lines, "getEquipmentFacilityWorthAnalysis",
    '''ranges = ["0-50", "50-100", "100-500", "500-1000", "1000以上"]
type_names = ["资产净值", "实物资产数"]
return ok([{
    "num": r.randint(1, 500),
    "rate": rng_val,
    "typeName": tn,
} for rng_val in ranges for tn in type_names])'''):
    changes += 1

# getHousingAnalysisYoy: fields: dateYear, num, typeName
if replace_handler_return(lines, "getHousingAnalysisYoy",
    '''type_names = ["面积", "实物资产数", "资产原值", "资产净值"]
return ok([{
    "dateYear": float(y),
    "num": round(r.uniform(0, 50000), 1),
    "typeName": tn,
} for y in [year, year - 1] for tn in type_names])'''):
    changes += 1

# getImportAssertAnalysisList: fields: assetCode,assetFirstname,assetName,...(15 fields)
if replace_handler_return(lines, "getImportAssertAnalysisList",
    '''return ok([{
    "assetCode": "A%s" % hashlib.md5(str(i).encode()).hexdigest()[:20],
    "assetFirstname": r.choice(["应用系统", "机械设备", "通信设备", "交通设备"]),
    "assetName": "资产项目%d" % i,
    "assetStatus": r.choice(["新增", "启用", "封存"]),
    "assetStatusName": r.choice(["启用", "封存", "报废"]),
    "assetTypeName": r.choice(["设备", "设施", "房屋"]),
    "buyDate": "2025-%02d-01" % r.randint(1, 12),
    "cardId": "C%s" % hashlib.md5(("c" + str(i)).encode()).hexdigest()[:16],
    "netValue": round(r.uniform(0, 1000), 2),
    "originalValue": round(r.uniform(10, 5000), 2),
    "ownerZone": r.choice(REGIONS_SHORT),
    "propertyUnit": r.choice(COMPANIES[:5]),
    "realAssetTypeName": r.choice(["固定资产", "无形资产"]),
    "specModel": "",
    "useUnit": r.choice(COMPANIES[:5]),
} for i in range(20)])'''):
    changes += 1

# getLandMaritimeAnalysisTransparentTransmission: fields: num, ownerUnitName, typeName
if replace_handler_return(lines, "getLandMaritimeAnalysisTransparentTransmission",
    '''type_names = ["实物资产数", "资产原值", "资产净值"]
return ok([{
    "num": round(r.uniform(1, 5000), 1),
    "ownerUnitName": cmp,
    "typeName": tn,
} for cmp in COMPANIES for tn in type_names])'''):
    changes += 1

# getLandMaritimeAnalysisYoy: fields: dateYear, num, typeName
if replace_handler_return(lines, "getLandMaritimeAnalysisYoy",
    '''type_names = ["资产原值", "资产净值", "实物资产数"]
return ok([{
    "dateYear": float(y),
    "num": round(r.uniform(100000, 800000000), 1),
    "typeName": tn,
} for y in [year, year - 1] for tn in type_names])'''):
    changes += 1

# getLandMaritimeRegionalAnalysis: fields: num, ownerZone, typeName
if replace_handler_return(lines, "getLandMaritimeRegionalAnalysis",
    '''type_names = ["实物资产数", "资产原值"]
return ok([{
    "num": round(r.uniform(1, 500), 1),
    "ownerZone": reg,
    "typeName": tn,
} for reg in REGIONS_SHORT + ["综合事业部"] for tn in type_names[:1]])'''):
    changes += 1

# getLandMaritimeWorthAnalysis: fields: num, rate, typeName
if replace_handler_return(lines, "getLandMaritimeWorthAnalysis",
    '''type_names = ["资产净值", "实物资产数"]
return ok([{
    "num": r.randint(1, 50),
    "rate": rng_val,
    "typeName": tn,
} for rng_val in ["0-50", "50-100"] for tn in type_names])'''):
    changes += 1

# getPhysicalAssets: dict→list, fields: dateYear, num, typeName
if replace_handler_return(lines, "getPhysicalAssets",
    '''type_names = ["实物资产数", "资产原值", "资产净值"]
return ok([{
    "dateYear": float(y),
    "num": round(r.uniform(50000, 100000), 1),
    "typeName": tn,
} for y in [year, year - 1] for tn in type_names])'''):
    changes += 1

# getRegionalAnalysis: fields: num, ownerZone, typeName
if replace_handler_return(lines, "getRegionalAnalysis",
    '''type_names = ["实物资产数", "资产原值"]
return ok([{
    "num": round(r.uniform(1000, 20000), 1),
    "ownerZone": reg,
    "typeName": tn,
} for reg in REGIONS_SHORT + ["综合事业部"] for tn in type_names])'''):
    changes += 1

# getTotalssets: dict→list[1], fields: assetQty, realAssetQty
if replace_handler_return(lines, "getTotalssets",
    '''return ok([{"assetQty": round(r.uniform(70000, 90000), 1), "realAssetQty": round(r.uniform(70000, 90000), 1)}])'''):
    changes += 1

# ── D6: 23 APIs ──────────────────────────────────────────────

# getCapitalApprovalAnalysisLimitInquiry: fields: num, typeName
if replace_handler_return(lines, "getCapitalApprovalAnalysisLimitInquiry",
    '''type_names = ["当年实际完成支付额", "当年实际完成投资额", "当年计划支付额",
    "当年计划投资额", "当年资本项目批复投资额", "当年资本项目计划投资额"]
return ok([{
    "num": round(r.uniform(0, 500000), 1),
    "typeName": tn,
} for tn in type_names])'''):
    changes += 1

# getCapitalApprovalAnalysisProject: fields: num, typeName
if replace_handler_return(lines, "getCapitalApprovalAnalysisProject",
    '''type_names = ["当年交付项目数", "资本项目总数", "当年完工项目数", "在建项目数"]
return ok([{
    "num": round(r.uniform(0, 200), 0),
    "typeName": tn,
} for tn in type_names])'''):
    changes += 1

# getCapitalProjectsList: fields: 17 fields
if replace_handler_return(lines, "getCapitalProjectsList",
    '''return ok([{
    "captProjectPayProgress": round(r.uniform(0, 1), 2),
    "captProjectPhysicalProgress": round(r.uniform(0, 100), 1),
    "dateMonth": f"{year}-{r.randint(1,12):02d}",
    "finishInvestAmt": round(r.uniform(0, 50000), 1),
    "finishPayAmt": round(r.uniform(0, 50000), 1),
    "investProjectStatus": str(r.randint(1, 5)),
    "investProjectStatusName": r.choice(["在建", "完工", "交付", "暂停"]),
    "investProjectType": r.choice(["仓库码头", "设备购置", "技术改造", "安全环保"]),
    "ownerDept": r.choice(COMPANIES[:5]),
    "ownerLgZoneName": r.choice(REGIONS_LG[:5]),
    "planInvestAmt": round(r.uniform(100, 100000), 1),
    "planPayAmt": round(r.uniform(100, 100000), 1),
    "planYear": r.randint(2020, 2026),
    "proAmt": round(r.uniform(100, 100000), 1),
    "projectCurrentStage": r.choice(["配置", "实施", "验收", "完工"]),
    "projectName": "项目%d" % i,
    "projectNo": "PRJ%05d" % i,
} for i in range(20)])'''):
    changes += 1

# getCostProjectAmtByOwnerLgZoneName: fields: finishPayAmt, investAmt, ownerLgZoneName
if replace_handler_return(lines, "getCostProjectAmtByOwnerLgZoneName",
    '''return ok([{
    "finishPayAmt": round(r.uniform(10000, 5000000), 1),
    "investAmt": round(r.uniform(1000, 50000), 1),
    "ownerLgZoneName": reg,
} for reg in REGIONS_LG])'''):
    changes += 1

# getCostProjectCurrentStageQtyList: fields: ownerLgZoneName, projectCurrentStage, projectQty
if replace_handler_return(lines, "getCostProjectCurrentStageQtyList",
    '''stages = ["配置", "实施", "验收", "完工"]
return ok([{
    "ownerLgZoneName": reg,
    "projectCurrentStage": st,
    "projectQty": r.randint(10, 300),
} for reg in REGIONS_LG[:5] for st in stages[:1]])'''):
    changes += 1

# getCostProjectFinishByYear: fields: costApplyInvestAmt, dateYear, projectQty, realFinishPayAmt
if replace_handler_return(lines, "getCostProjectFinishByYear",
    '''return ok([{
    "costApplyInvestAmt": round(r.uniform(30000, 60000), 1),
    "dateYear": y,
    "projectQty": r.randint(800, 1500),
    "realFinishPayAmt": round(r.uniform(2000000, 6000000), 1),
} for y in [year, year - 1]])'''):
    changes += 1

# getCostProjectQtyByProjectCmp: fields: finishPayAmt, investAmt, projectCmp, projectQty
if replace_handler_return(lines, "getCostProjectQtyByProjectCmp",
    '''return ok([{
    "finishPayAmt": round(r.uniform(0, 100000), 1),
    "investAmt": round(r.uniform(0, 5000), 1),
    "projectCmp": cmp,
    "projectQty": r.randint(1, 50),
} for cmp in COMPANIES])'''):
    changes += 1

# getCostProjectQtyList: fields: ownerLgZoneName, projectQty
if replace_handler_return(lines, "getCostProjectQtyList",
    '''return ok([{
    "ownerLgZoneName": reg,
    "projectQty": float(r.randint(10, 300)),
} for reg in REGIONS_LG])'''):
    changes += 1

# getCostProjectYoyList: fields: currYear, deliveryRate, finishPayAmt, investAmt, projectQty
if replace_handler_return(lines, "getCostProjectYoyList",
    '''return ok([{
    "currYear": y,
    "deliveryRate": round(r.uniform(0, 100), 1),
    "finishPayAmt": round(r.uniform(2000000, 6000000), 1),
    "investAmt": round(r.uniform(30000, 60000), 1),
    "projectQty": r.randint(800, 1500),
} for y in [year, year - 1]])'''):
    changes += 1

# getDeliveryRate: fields: dateYear, rate
if replace_handler_return(lines, "getDeliveryRate",
    '''return ok([{
    "dateYear": y,
    "rate": round(r.uniform(50, 100), 1),
} for y in range(year - 5, year + 1)])'''):
    changes += 1

# getFinishProgressAndDeliveryRate: dict→list[1], fields
if replace_handler_return(lines, "getFinishProgressAndDeliveryRate",
    '''return ok([{
    "captProjectQty": r.randint(1, 10),
    "deliveryCaptProjectQty": r.randint(0, 5),
    "planInvestAmt": round(r.uniform(0, 500000), 1),
    "planPayAmt": round(r.uniform(0, 500000), 1),
    "realFinishInvestAmt": round(r.uniform(0, 500000), 0),
    "realFinishPayAmt": round(r.uniform(0, 500000), 1),
}])'''):
    changes += 1

# getInvestAmtList: fields: adminName,investAmt,ownerDept,...(11 fields)
if replace_handler_return(lines, "getInvestAmtList",
    '''return ok([{
    "adminName": "管理员%d" % i,
    "investAmt": round(r.uniform(1, 500), 1),
    "ownerDept": r.choice(COMPANIES[:5]),
    "phaseCode": r.randint(1, 5),
    "phaseName": r.choice(["实施", "配置", "验收", "完工"]),
    "projectCmp": r.choice(COMPANIES[:5]),
    "projectName": "投资项目%d" % i,
    "projectNo": "INV%05d" % i,
    "requestingDept": r.choice(COMPANIES[:5]),
    "startDate": "2025-%02d-01" % r.randint(1, 12),
    "winnerPrice": round(r.uniform(0, 1000), 1),
} for i in range(20)])'''):
    changes += 1

# getInvestPlanByYear: fields: captPlanPayAmt,dateYear,finishInvestAmt,planInvestAmt,realFinishPayAmt
if replace_handler_return(lines, "getInvestPlanByYear",
    '''return ok([{
    "captPlanPayAmt": round(r.uniform(0, 100000), 1),
    "dateYear": y,
    "finishInvestAmt": round(r.uniform(50000, 150000), 0),
    "planInvestAmt": round(r.uniform(80000, 200000), 1),
    "realFinishPayAmt": round(r.uniform(0, 100000), 1),
} for y in range(year - 6, year + 1)])'''):
    changes += 1

# getInvestPlanTypeProjectList: fields: engineeringQty,importantQty,investProjectType,planInvestAmt,planPayAmt,total
if replace_handler_return(lines, "getInvestPlanTypeProjectList",
    '''return ok([{
    "engineeringQty": r.randint(0, 5),
    "importantQty": r.randint(0, 5),
    "investProjectType": "仓库码头",
    "planInvestAmt": round(r.uniform(500, 5000), 1),
    "planPayAmt": round(r.uniform(500, 5000), 1),
    "total": r.randint(1, 20),
}])'''):
    changes += 1

# getOutOfPlanFinishProgressList: dict→list[1]
if replace_handler_return(lines, "getOutOfPlanFinishProgressList",
    '''return ok([{
    "finishInvestAmt": round(r.uniform(100000, 300000), 1),
    "finishPayAmt": round(r.uniform(50000, 150000), 1),
    "planInvestAmt": round(r.uniform(200000, 500000), 1),
    "planPayAmt": round(r.uniform(100000, 300000), 1),
}])'''):
    changes += 1

# getOutOfPlanProjectInvestFinishList: fields: dateYear,finishInvestAmt,planInvestAmt
if replace_handler_return(lines, "getOutOfPlanProjectInvestFinishList",
    '''return ok([{
    "dateYear": y,
    "finishInvestAmt": round(r.uniform(0, 200000), 1),
    "planInvestAmt": round(r.uniform(5000, 50000), 1),
} for y in range(year - 4, year + 1)])'''):
    changes += 1

# getOutOfPlanProjectPayFinishList: fields: dateYear,finishPayAmt,planPayAmt
if replace_handler_return(lines, "getOutOfPlanProjectPayFinishList",
    '''return ok([{
    "dateYear": y,
    "finishPayAmt": round(r.uniform(0, 200000), 1),
    "planPayAmt": round(r.uniform(5000, 50000), 1),
} for y in range(year - 4, year + 1)])'''):
    changes += 1

# getOutOfPlanProjectQtyYoy: fields: dateYear,projectDeliveryRate,projectQty
if replace_handler_return(lines, "getOutOfPlanProjectQtyYoy",
    '''return ok([{
    "dateYear": y,
    "projectDeliveryRate": round(r.uniform(0, 100), 1),
    "projectQty": r.randint(1, 10),
} for y in [year, year - 1]])'''):
    changes += 1

# getPlanExcludedProjectPenetrationAnalysis: fields: projectCmp,qty,typeName
if replace_handler_return(lines, "getPlanExcludedProjectPenetrationAnalysis",
    '''type_names = ["支付计划额", "投资计划额", "项目数"]
return ok([{
    "projectCmp": cmp,
    "qty": round(r.uniform(0, 500), 1),
    "typeName": tn,
} for cmp in COMPANIES for tn in type_names])'''):
    changes += 1

# getPlanFinishByProjectType: fields: finishInvestAmt,finishPayAmt,investProjectType,planInvestAmt,planPayAmt
if replace_handler_return(lines, "getPlanFinishByProjectType",
    '''proj_types = ["行政办公", "仓库码头", "设备购置", "技术改造", "安全环保", "信息化", "其他"]
return ok([{
    "finishInvestAmt": round(r.uniform(10000, 200000), 1),
    "finishPayAmt": round(r.uniform(10000, 100000), 1),
    "investProjectType": pt,
    "planInvestAmt": round(r.uniform(50000, 300000), 1),
    "planPayAmt": round(r.uniform(50000, 300000), 1),
} for pt in proj_types])'''):
    changes += 1

# getPlanFinishByZone: fields: finishInvestAmt,finishPayAmt,ownerLgZoneName,planInvestAmt,planPayAmt
if replace_handler_return(lines, "getPlanFinishByZone",
    '''return ok([{
    "finishInvestAmt": round(r.uniform(0, 200000), 1),
    "finishPayAmt": round(r.uniform(0, 100000), 1),
    "ownerLgZoneName": reg,
    "planInvestAmt": round(r.uniform(0, 300000), 1),
    "planPayAmt": round(r.uniform(0, 200000), 1),
} for reg in REGIONS_LG[:5]])'''):
    changes += 1

# getUnplannedProjectsInquiry: fields: 13 fields
if replace_handler_return(lines, "getUnplannedProjectsInquiry",
    '''return ok([{
    "chkStatus": r.choice(["待审", "通过", "退回"]),
    "deptName": r.choice(COMPANIES[:5]),
    "foreignLoans": round(r.uniform(0, 10), 2),
    "onstructionTime": "2020-01-01 / 2028-12-31",
    "ownFunds": round(r.uniform(0, 100), 2),
    "planYear": r.randint(2020, 2026),
    "proMainTypeName": r.choice(["仓库码头", "设备购置", "技术改造"]),
    "proName": "计划外项目%d" % i,
    "proNo": "OOP%05d" % i,
    "theYearInvestAmt": round(r.uniform(0, 5000), 2),
    "theYearInvestPlanNums": round(r.uniform(0, 5000), 2),
    "theYearPayAmt": round(r.uniform(0, 5000), 2),
    "theYearPayPlanNums": round(r.uniform(0, 5000), 2),
} for i in range(20)])'''):
    changes += 1

# planInvestAndPayYoy: dict→list, fields: dateYear,planInvestAmt,planPayAmt
if replace_handler_return(lines, "planInvestAndPayYoy",
    '''return ok([{
    "dateYear": y,
    "planInvestAmt": round(r.uniform(500, 5000), 1),
    "planPayAmt": round(r.uniform(500, 5000), 1),
} for y in [year, year - 1]])'''):
    changes += 1

# ── D7: 34 APIs ──────────────────────────────────────────────

# getContainerMachineHourRate: fields: dateMonth, machineHourRate
if replace_handler_return(lines, "getContainerMachineHourRate",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "machineHourRate": round(r.uniform(8, 15), 1),
} for m in range(1, 4)])'''):
    changes += 1

# getEquipmentElectricityTonCost: fields: dateMonth, tonCost
if replace_handler_return(lines, "getEquipmentElectricityTonCost",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "tonCost": round(r.uniform(0, 1), 2),
} for m in range(1, 4)])'''):
    changes += 1

# getEquipmentEnergyConsumptionPerUnit: fields: dateMonth, workingAmount
if replace_handler_return(lines, "getEquipmentEnergyConsumptionPerUnit",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "workingAmount": r.randint(50000000, 200000000),
} for m in range(1, 4)])'''):
    changes += 1

# getEquipmentFirstLevelClassNameList: fields: firstLevelClassName, num
if replace_handler_return(lines, "getEquipmentFirstLevelClassNameList",
    '''class_names = ["油运设备", "集装箱专用设备", "通用机械", "专用机械",
    "动力设备", "交通运输设备", "电子设备", "仪器仪表", "工具器具", "通信设备"]
return ok([{
    "firstLevelClassName": cn,
    "num": float(r.randint(10, 500)),
} for cn in class_names])'''):
    changes += 1

# getEquipmentFuelOilTonCost: fields: dateMonth, tonCost
if replace_handler_return(lines, "getEquipmentFuelOilTonCost",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "tonCost": round(r.uniform(0, 0.5), 2),
} for m in range(1, 4)])'''):
    changes += 1

# getEquipmentIndicatorOperationQty: fields: firstLevelName, num
if replace_handler_return(lines, "getEquipmentIndicatorOperationQty",
    '''class_names = ["专用机械", "交通运输设备", "动力设备", "工具器具",
    "电子设备", "仪器仪表", "通信设备", "通用机械", "集装箱专用设备", "油运设备"]
return ok([{
    "firstLevelName": cn,
    "num": r.randint(100000, 20000000),
} for cn in class_names])'''):
    changes += 1

# getEquipmentIndicatorUseCost: fields: firstLevelName, num
if replace_handler_return(lines, "getEquipmentIndicatorUseCost",
    '''class_names = ["机车", "专用机械", "动力设备", "通用机械", "集装箱专用设备",
    "交通运输设备", "电子设备", "工具器具", "仪器仪表", "油运设备"]
return ok([{
    "firstLevelName": cn,
    "num": round(r.uniform(100, 50000), 1),
} for cn in class_names])'''):
    changes += 1

# getEquipmentServiceableRate: fields: dateMonth, serviceableRate
if replace_handler_return(lines, "getEquipmentServiceableRate",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "serviceableRate": round(r.uniform(0.95, 1.0), 4),
} for m in range(1, 4)])'''):
    changes += 1

# getEquipmentUsageRate: fields: dateMonth, usageRate
if replace_handler_return(lines, "getEquipmentUsageRate",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "usageRate": round(r.uniform(2, 8), 1),
} for m in range(1, 4)])'''):
    changes += 1

# getMachineDataDisplayEquipmentReliability: fields: dateMonth, dateYear, usageRate
if replace_handler_return(lines, "getMachineDataDisplayEquipmentReliability",
    '''return ok([{
    "dateMonth": f"{y}-{m:02d}",
    "dateYear": float(y),
    "usageRate": round(r.uniform(500, 5000), 2),
} for y in [year - 1, year] for m in range(1, 4) if not (y == year and m > 3)])'''):
    changes += 1

# getMachineDataDisplayScreenEquipmentIntegrityRate: fields: dateMonth, usageRate
if replace_handler_return(lines, "getMachineDataDisplayScreenEquipmentIntegrityRate",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "usageRate": round(r.uniform(0.95, 1.0), 6),
} for m in range(1, 4)])'''):
    changes += 1

# getMachineDataDisplayScreenHourlyEfficiency: fields: ownerLgZoneName, usageRate
if replace_handler_return(lines, "getMachineDataDisplayScreenHourlyEfficiency",
    '''return ok([{
    "ownerLgZoneName": reg,
    "usageRate": round(r.uniform(100, 500), 2),
} for reg in REGIONS_ZONE[:4]])'''):
    changes += 1

# getMachineDataDisplaySingleUnitEnergyConsumption: fields: equipmentNo, workingAmount
if replace_handler_return(lines, "getMachineDataDisplaySingleUnitEnergyConsumption",
    '''return ok([{
    "equipmentNo": "A%s" % hashlib.md5(str(i).encode()).hexdigest()[:20],
    "workingAmount": round(r.uniform(0, 500000), 1),
} for i in range(75)])'''):
    changes += 1

# getModelDataDisplayScreenEffectiveUtilization: fields: dateMonth, usageRate
if replace_handler_return(lines, "getModelDataDisplayScreenEffectiveUtilization",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "usageRate": round(r.uniform(0.2, 0.5), 6),
} for m in range(1, 4)])'''):
    changes += 1

# getModelDataDisplayScreenEnergyConsumptionPerUnit: fields: ownerLgZoneName, workingAmount
if replace_handler_return(lines, "getModelDataDisplayScreenEnergyConsumptionPerUnit",
    '''return ok([{
    "ownerLgZoneName": reg,
    "workingAmount": round(r.uniform(100000, 500000), 1),
} for reg in REGIONS_ZONE])'''):
    changes += 1

# getModelDataDisplayScreenHierarchyRelation: fields: firstLevelClassName, secondLevelClassName
if replace_handler_return(lines, "getModelDataDisplayScreenHierarchyRelation",
    '''return ok([{
    "firstLevelClassName": "集装箱专用设备",
    "secondLevelClassName": r.choice(["岸桥", "场桥", "正面吊", "堆高机"]),
}])'''):
    changes += 1

# getModelDataDisplayScreenUtilization: fields: dateMonth, usageRate
if replace_handler_return(lines, "getModelDataDisplayScreenUtilization",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "usageRate": round(r.uniform(0.3, 0.5), 6),
} for m in range(1, 4)])'''):
    changes += 1

# getNonContainerProductionEquipmentReliability: fields: dateMonth, dateYear, usageRate
if replace_handler_return(lines, "getNonContainerProductionEquipmentReliability",
    '''return ok([{
    "dateMonth": f"{y}-{m:02d}",
    "dateYear": float(y),
    "usageRate": round(r.uniform(1000, 50000), 2),
} for y in [year - 1, year] for m in range(1, 4) if not (y == year and m > 3)])'''):
    changes += 1

# getOverviewQuery: dict→list, fields: num, typeName
if replace_handler_return(lines, "getOverviewQuery",
    '''type_names = ["作业台时", "机械作业量", "能源消耗", "材料费用",
    "完好台时", "非完好台时", "日历台时", "工作台时"]
return ok([{
    "num": round(r.uniform(0, 10000000), 1) if i < 4 else round(r.uniform(0, 50000000), 1),
    "typeName": tn,
} for i, tn in enumerate(type_names)])'''):
    changes += 1

# getProductEquipmentDataAnalysisList: fields: containerElec,containerOil,deptName,...
if replace_handler_return(lines, "getProductEquipmentDataAnalysisList",
    '''return ok([{
    "containerElec": round(r.uniform(0, 100), 2),
    "containerOil": round(r.uniform(0, 100), 2),
    "deptName": cmp,
    "elecCostTeu": round(r.uniform(0, 1), 2),
    "fee": round(r.uniform(0, 1000), 2),
    "maintenanceFee": round(r.uniform(0, 500), 2),
    "oilCostTeul": round(r.uniform(0, 1), 2),
    "ownerLgZoneName": r.choice(REGIONS_ZONE),
} for cmp in COMPANIES[:10] + ["散杂货码头分公司", "散粮码头公司",
    "大连港油码头有限公司", "辽港控股（营口）有限公司第一分公司",
    "辽港控股（营口）有限公司第二分公司", "辽港控股（营口）有限公司粮食分公司",
    "丹东港口集团杂货码头分公司", "丹东港口集团煤矿码头分公司",
    "丹东港口集团散粮码头分公司", "盘锦港集团有限公司第一分公司"]])'''):
    changes += 1

# getProductEquipmentIntegrityRateByMonth: fields: dateMonth, ownerZone, usageRate
if replace_handler_return(lines, "getProductEquipmentIntegrityRateByMonth",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "ownerZone": reg,
    "usageRate": round(r.uniform(0.95, 1.0), 4),
} for reg in REGIONS_ZONE for m in range(1, 3)])'''):
    changes += 1

# getProductEquipmentIntegrityRateByYear: fields: dateYear, ownerZone, usageRate
if replace_handler_return(lines, "getProductEquipmentIntegrityRateByYear",
    '''return ok([{
    "dateYear": y,
    "ownerZone": reg,
    "usageRate": round(r.uniform(0.95, 1.0), 4),
} for reg in REGIONS_ZONE for y in [year, year - 1]])'''):
    changes += 1

# getProductEquipmentRateByYear: fields: dateYear, usageRate
if replace_handler_return(lines, "getProductEquipmentRateByYear",
    '''return ok([{
    "dateYear": y,
    "usageRate": round(r.uniform(3, 8), 1),
} for y in range(year - 3, year + 1)])'''):
    changes += 1

# getProductEquipmentReliabilityByMonth: fields: dateMonth, ownerLgZoneName, usageRate
if replace_handler_return(lines, "getProductEquipmentReliabilityByMonth",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "ownerLgZoneName": reg,
    "usageRate": round(r.uniform(100000, 5000000), 1),
} for reg in REGIONS_ZONE for m in range(1, 4)])'''):
    changes += 1

# getProductEquipmentReliabilityByYear: fields: dateYear, ownerLgZoneName, usageRate
if replace_handler_return(lines, "getProductEquipmentReliabilityByYear",
    '''return ok([{
    "dateYear": y,
    "ownerLgZoneName": reg,
    "usageRate": round(r.uniform(100, 5000000), 1),
} for reg in REGIONS_ZONE for y in range(year - 3, year + 1)])'''):
    changes += 1

# getProductEquipmentUnitConsumptionByMonth: fields: secondLevelClassName, unitConsumption
if replace_handler_return(lines, "getProductEquipmentUnitConsumptionByMonth",
    '''class_names = ["工程技术船", "公铁车", "正面吊", "堆高机", "叉车", "岸桥",
    "场桥", "轮胎吊", "门座式起重机", "桥式起重机", "龙门式起重机", "拖头",
    "拖轮", "汽车起重机", "皮带机", "螺旋卸船机", "链斗卸船机", "抓斗卸船机",
    "翻车机", "油运设备", "斗轮堆取料机", "输油臂", "装船机", "卸船机",
    "机车", "流动机械", "散货专用设备", "集装箱专用设备", "其他设备"]
return ok([{
    "secondLevelClassName": cn,
    "unitConsumption": round(r.uniform(0, 100), 2),
} for cn in class_names[:r.randint(30, 39)]])'''):
    changes += 1

# getProductEquipmentUnitConsumptionByYear: fields: secondLevelClassName, unitConsumption
if replace_handler_return(lines, "getProductEquipmentUnitConsumptionByYear",
    '''class_names = ["工程技术船", "公铁车", "正面吊", "堆高机", "叉车", "岸桥",
    "场桥", "轮胎吊", "门座式起重机", "桥式起重机", "龙门式起重机", "拖头",
    "拖轮", "汽车起重机", "皮带机", "螺旋卸船机", "链斗卸船机", "抓斗卸船机",
    "翻车机", "油运设备", "斗轮堆取料机", "输油臂", "装船机", "卸船机",
    "机车", "流动机械", "散货专用设备", "集装箱专用设备", "其他设备"]
return ok([{
    "secondLevelClassName": cn,
    "unitConsumption": round(r.uniform(0, 100), 2),
} for cn in class_names[:r.randint(30, 41)]])'''):
    changes += 1

# getProductEquipmentUsageRateByMonth: fields: dateMonth, usageRate
if replace_handler_return(lines, "getProductEquipmentUsageRateByMonth",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "usageRate": round(r.uniform(0.1, 0.3), 3),
} for m in range(1, 4)])'''):
    changes += 1

# getProductEquipmentUsageRateByYear: fields: dateYear, usageRate
if replace_handler_return(lines, "getProductEquipmentUsageRateByYear",
    '''return ok([{
    "dateYear": y,
    "usageRate": round(r.uniform(0.1, 0.3), 3),
} for y in range(year - 3, year + 1)])'''):
    changes += 1

# getProductEquipmentWorkingAmountByMonth: fields: num, ownerLgZoneName
if replace_handler_return(lines, "getProductEquipmentWorkingAmountByMonth",
    '''return ok([{
    "num": float(r.randint(500000, 5000000)),
    "ownerLgZoneName": reg,
} for reg in REGIONS_ZONE])'''):
    changes += 1

# getProductEquipmentWorkingAmountByYear: fields: num, ownerLgZoneName
if replace_handler_return(lines, "getProductEquipmentWorkingAmountByYear",
    '''return ok([{
    "num": r.randint(10000000, 200000000),
    "ownerLgZoneName": reg,
} for reg in REGIONS_ZONE])'''):
    changes += 1

# getProductionEquipmentFaultNum: fields: dateMonth, num
if replace_handler_return(lines, "getProductionEquipmentFaultNum",
    '''return ok([{
    "dateMonth": f"{year}-{m:02d}",
    "num": r.randint(500, 1500),
} for m in range(1, 4)])'''):
    changes += 1

# getProductionEquipmentStatistic: fields: num, secondLevelName
if replace_handler_return(lines, "getProductionEquipmentStatistic",
    '''class_names = ["斗轮堆取料机", "岸桥", "场桥", "正面吊", "堆高机", "叉车",
    "门座式起重机", "桥式起重机", "龙门式起重机", "拖头", "拖轮", "汽车起重机",
    "皮带机", "螺旋卸船机", "链斗卸船机", "抓斗卸船机", "翻车机", "输油臂",
    "装船机", "卸船机", "机车", "流动机械", "工程技术船", "公铁车",
    "散货专用设备", "集装箱专用设备", "通用机械", "动力设备", "油运设备"]
return ok([{
    "num": r.randint(1, 200),
    "secondLevelName": cn,
} for cn in class_names[:r.randint(30, 39)]])'''):
    changes += 1

# getQuayEquipmentWorkingAmount: fields: num, typeName
if replace_handler_return(lines, "getQuayEquipmentWorkingAmount",
    '''type_names = ["输油臂作业量同比", "岸桥作业量同比", "门机作业量同比",
    "散货设备作业量同比", "总作业量同比", "输油臂作业量",
    "岸桥作业量", "门机作业量", "散货设备作业量", "总作业量"]
return ok([{
    "num": round(r.uniform(-50, 500000), 1),
    "typeName": tn,
} for tn in type_names])'''):
    changes += 1


# ══════════════════════════════════════════════════════════════
# Write result
# ══════════════════════════════════════════════════════════════

with open(MOCK_FILE, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("\n=== Transformation complete ===")
print("Total handlers modified: %d" % changes)
print("File saved: %s" % MOCK_FILE)
