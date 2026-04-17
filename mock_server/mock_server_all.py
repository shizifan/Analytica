"""
港口AI问数 Mock API Server
- 路径与原接口完全一致
- Token 与原接口完全一致
- 数据基于业务逻辑动态生成（确定性随机，幂等）
- 数据范围：2024-01 ~ 2026-06
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import hashlib, random, math
from datetime import datetime, timedelta
from typing import Optional
import uvicorn

app = FastAPI(title="港口司南 Mock API", version="1.0.0")

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

REGIONS = ["大连港", "营口港", "丹东港", "盘锦港", "绥中港"]
REGIONS_SHORT = ["大连", "营口", "丹东", "盘锦", "绥中"]           # D5 资产
REGIONS_ZONE = ["大连港区域", "营口港区域", "丹东港区域", "盘锦港区域", "绥中港区域"]  # D7 设备
REGIONS_LG = ["大连港", "营口港", "丹东港", "盘锦港", "绥中港", "辽港集团本部"]  # D6 投资
BUSINESS_TYPES = ["集装箱", "散杂货", "油化品", "商品车"]
COMPANIES = [
    "大连集装箱码头有限公司", "营口集装箱码头有限公司",
    "大连港散杂货码头分公司", "大连港油码头有限公司",
    "大连汽车码头有限公司", "盘锦港集团有限公司",
    "丹东港口集团有限公司", "绥中港集团有限公司",
    "辽港控股（营口）有限公司", "大连港集团有限公司",
]
STRATEGIC_CLIENTS = [
    "中远海运集团", "马士基航运", "地中海航运", "达飞轮船",
    "长荣海运", "赫伯罗特", "现代商船", "ONE(日本海洋网联船务)",
    "鞍钢集团", "本溪钢铁集团", "上汽通用五菱", "一汽集团",
    "中石化大连分公司", "中石油大连石化", "神华集团",
]

SEASONAL = [0.85,0.75,1.05,1.08,1.10,1.07,1.03,1.05,1.08,1.06,0.95,0.92]
YOY_BASE  = {2024: 1.048, 2025: 1.062, 2026: 1.057}

def seed(params: dict) -> int:
    key = str(sorted([(str(k), str(v)) for k, v in params.items() if v is not None]))
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)

def rng(params: dict) -> random.Random:
    return random.Random(seed(params))

def month_throughput_ton(year: int, month: int, region: str = None, rng_obj: random.Random = None) -> float:
    """基准月吞吐量（万吨），含季节+年度增长+区域权重"""
    base = 2800.0
    factor = SEASONAL[month - 1]
    yoy = YOY_BASE.get(year, 1.06)
    growth = yoy ** (year - 2024)
    region_weight = {"大连港": 0.35, "营口港": 0.28, "丹东港": 0.16, "盘锦港": 0.12, "绥中港": 0.09}.get(region, 1.0)
    total = base * factor * growth
    if region:
        total *= region_weight
    noise = rng_obj.uniform(0.97, 1.03) if rng_obj else 1.0
    return round(total * noise, 1)

def parse_date(date_str: str):
    """解析各种日期格式，返回(year, month, day)"""
    if not date_str:
        now = datetime.now()
        return now.year, now.month, now.day
    s = date_str.strip()
    try:
        if len(s) == 4:
            return int(s), 6, 30
        if len(s) == 7:
            dt = datetime.strptime(s, "%Y-%m")
            return dt.year, dt.month, 1
        if len(s) == 10:
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.year, dt.month, dt.day
    except:
        pass
    return 2025, 6, 30

def ok(data):
    return JSONResponse({"code": 200, "msg": "success", "data": data})

def check_token(request: Request, expected: str):
    token = request.headers.get("API-TOKEN", "")
    if token and token != expected:
        raise HTTPException(status_code=401, detail="Invalid API-TOKEN")

# ─────────────────────────────────────────────
# TOKEN 映射（原接口完整 TOKEN）
# ─────────────────────────────────────────────
T = {
    "weather_forecast":   "24FBB42E14C17ACC6A25969E25BFBECF74113C28A028CE867EA8B03F4C4ADC66",
    "realtime_weather":   "24FBB42E14C17ACC6A25969E25BFBECFF04C3E3A6F4A442C0DA5C671950A3663",
    "traffic_control":    "24FBB42E14C17ACC6A25969E25BFBECF071FCB360EEA8B8BF13A1D6EC27DC9A8",
    "key_vessel":         "24FBB42E14C17ACC6A25969E25BFBECF9008019B7EA43A0E286EF594A6902FA8",
    "throughput_ton":     "24FBB42E14C17ACC6A25969E25BFBECF36EF1D63A0571DAB2FB2D987C65E04E7",
    "throughput_teu":     "24FBB42E14C17ACC6A25969E25BFBECFE3E2DE79ACFC2153E38AEDAD344AFDFB",
    "single_ship_rate":   "24FBB42E14C17ACC6A25969E25BFBECF6B02A46F686CB9500CA7DFA7B4097951",
    "berth_by_region":    "24FBB42E14C17ACC6A25969E25BFBECF14F290450E6728284578455D84402F3C",
    "berth_by_biz":       "24FBB42E14C17ACC6A25969E25BFBECFBAF2339B3F17E898B14DD223DF827FFA",
    "cargo_inv_region":   "24FBB42E14C17ACC6A25969E25BFBECFC22EE6D962755C19E8F936DF84C8E461",
    "container_vehicle":  "46F4717D4D36AA272FFC710A28B050F7197F90A4B013C5DDF454DAD5F5842FAD",
    "inv_by_cargo":       "24FBB42E14C17ACC6A25969E25BFBECF2B73EC54D2B807CC53938F1D2030F126",
    "inv_by_biz":         "24FBB42E14C17ACC6A25969E25BFBECF5EF51BDCE7285517034BF1FA3CE96575",
    "tp_non_container":   "24FBB42E14C17ACC6A25969E25BFBECFAAC07F3B25F0739AFBC9750B349B64BB",
    "tp_container":       "24FBB42E14C17ACC6A25969E25BFBECF339A4372C3D4155FF9DEFEE3F271D3A2",
    "tp_by_year":         "24FBB42E14C17ACC6A25969E25BFBECF055A39AC6F90C5B49F83A45D1536137F",
    "ctn_tp_by_year":     "24FBB42E14C17ACC6A25969E25BFBECFFE95E6F21D4B554F35E3DA30CBBB7771",
    "oil_bulk_biz":       "24FBB42E14C17ACC6A25969E25BFBECF099C3B4FC01B72ABA3B25B0D1AB7F49F",
    "roro_biz":           "24FBB42E14C17ACC6A25969E25BFBECFB6563F3278BD411C6FF7824AC68DDD9D",
    "ctn_biz":            "24FBB42E14C17ACC6A25969E25BFBECF901ACDCAFE6E39A5B2519571CE335EE2",
    "company_biz":        "24FBB42E14C17ACC6A25969E25BFBECF54218CCBF43E144BA0FD29243A60A4CA",
    "tp_yoy_mom_year":    "24FBB42E14C17ACC6A25969E25BFBECFCCFD062E9BF3D205BD4FE8F36D552458",
    "ctn_yoy_year":       "24FBB42E14C17ACC6A25969E25BFBECFA57695EE933FCD13AF102D89D33E4546",
    "biz_tp_yoy_year":    "24FBB42E14C17ACC6A25969E25BFBECFCE58B93530572AEDA522A3E39860C4F8",
    "tp_yoy_month":       "24FBB42E14C17ACC6A25969E25BFBECF9FA01B2532CBBBDE2833EFD9268DE42C",
    "tp_yoy_day":         "24FBB42E14C17ACC6A25969E25BFBECFEC7D5A5AD631828C8B77B30B67B15CE2",
    "biz_tp_yoy_month":   "24FBB42E14C17ACC6A25969E25BFBECF84AB2801AC63E68CC044D558E8412210",
    "biz_tp_yoy_day":     "24FBB42E14C17ACC6A25969E25BFBECF77D88A6BCD6377AA90CC5B8BDEA25AD0",
    "ship_stat_region":   "24FBB42E14C17ACC6A25969E25BFBECFFB38B32DAB37592AD95AD094ED5A90D2",
    "ship_stat_biz":      "24FBB42E14C17ACC6A25969E25BFBECF5EC914F6A0930D2E03425B1A2E395C62",
    "biz_branch":         "24FBB42E14C17ACC6A25969E25BFBECF53B6F4D6E5DE6A9E5DB7280DD9A39963",
    "port_cmp_tp":        "24FBB42E14C17ACC6A25969E25BFBECFE6226DDFF0D4D31756D2324E991704F2",
    "tp_monthly_trend":   "24FBB42E14C17ACC6A25969E25BFBECF40FE291B51D21D9EF1A45133EEA048DD",
    "daily_inv":          "24FBB42E14C17ACC6A25969E25BFBECFC98145473E3E0E9DCCC35CF41858A94A",
    "inv_trend":          "24FBB42E14C17ACC6A25969E25BFBECF1268DD9BBE8AD8EE8690A057B3095C80",
    "vessel_eff":         "24FBB42E14C17ACC6A25969E25BFBECF5A358CFC3EEB6EBB46FEA5F1A7326954",
    "vessel_eff_trend":   "24FBB42E14C17ACC6A25969E25BFBECF6D9A32EEE331EDA3FE12D12154C2B6BB",
    "berth_occ":          "24FBB42E14C17ACC6A25969E25BFBECF745694A576CFB5803246AB4FDB7B6D77",
    "berth_duration":     "24FBB42E14C17ACC6A25969E25BFBECFA89C371E602AA48399CB5B88AF6FB552",
    "berth_list":         "24FBB42E14C17ACC6A25969E25BFBECF0A1FAF0E78BC80A3EEA53AE7523963AF",
    "ship_op_dynamic":    "46F4717D4D36AA272FFC710A28B050F7DC1BA33A3D0C89A8AC9C13741BAF7B2A",
    "prod_rate_avg":      "46F4717D4D36AA272FFC710A28B050F7F26B1CD4A48F4BC77D559E004AC44F3E",
    "prod_rate_trend":    "46F4717D4D36AA272FFC710A28B050F78B6A6E23774631F0FD52320E8B2AD34F",
    "pc_daily_tp":        "46F4717D4D36AA272FFC710A28B050F729E244CB2588799EEFED149F923B1AA3",
    "pc_month_tp":        "46F4717D4D36AA272FFC710A28B050F72A7E607144CC523844CF35636EA6D3EF",
    "pc_year_tp":         "46F4717D4D36AA272FFC710A28B050F7CE804B7E281864F71D561333523DCD53",
    "pc_year_trend":      "46F4717D4D36AA272FFC710A28B050F7652D8F58597E2197013B0FBA6CBE077D",
    "ship_dyn_num":       "46F4717D4D36AA272FFC710A28B050F781005CF409233C481A18A5158427C8B2",
    "ship_desc":          "46F4717D4D36AA272FFC710A28B050F79973F08D1DE81B74C87D892E1EAA2388",
    # 市场商务
    "mkt_monthly":        "46F4717D4D36AA272FFC710A28B050F7236C5F6DA2419BC3DC2C09B797335E03",
    "mkt_zone_monthly":   "46F4717D4D36AA272FFC710A28B050F790AA48728EC03C7F4E244B3EC6A9734F",
    "mkt_cumulative":     "46F4717D4D36AA272FFC710A28B050F716A59EFC96F1CC26836124CCAB3FFDE5",
    "mkt_zone_cumul":     "46F4717D4D36AA272FFC710A28B050F7369902D9AF69FB5D32520C0CC19E1B08",
    "mkt_curr_biz":       "46F4717D4D36AA272FFC710A28B050F7D29D3FBE29DBF8A3C8D41CD705FBDFED",
    "mkt_cumul_biz":      "46F4717D4D36AA272FFC710A28B050F7C476705DD6A00BEAAEC8B80621EE652B",
    "mkt_trend":          "46F4717D4D36AA272FFC710A28B050F7E5BF0B16C7D1935D19088A3C037AEB7C",
    "mkt_cumul_trend":    "46F4717D4D36AA272FFC710A28B050F7469D084A0B2C03C0DE08C40AB0D97613",
    "mkt_key_ent":        "46F4717D4D36AA272FFC710A28B050F776F1B162E6335D64AAAFA9740C64210E",
    "mkt_cumul_ent":      "46F4717D4D36AA272FFC710A28B050F7EE44F1CBC29FAB99EBB5F9D67BBE9B94",
    # 司南接口（客户/资产/投企）
    "actual_perf":        "C2B8184E822306ABE43FE46C608F0A100DD0662687EC7F01E315BA2FD5BAF570",
    "monthly_trend_tp":   "C2B8184E822306ABE43FE46C608F0A1031CDB2DF4DE82B40F2051E64EBD4EE95",
    "dispatch_port":      "C2B8184E822306ABE43FE46C608F0A106510CE9F3DBA05F4AAFD73B85D74BF23",
    "dispatch_wharf":     "C2B8184E822306ABE43FE46C608F0A10AC420D5E03301DDC11D20A94F5966410",
    "customer_qty":       "3CA0D8D714570AC8C8A1F950A198BF9AC22EE6D962755C19E8F936DF84C8E461",
    "customer_type":      "3CA0D8D714570AC8C8A1F950A198BF9A1CEC8408C1DEDF31B103C4E5F6577301",
    "customer_field":     "3CA0D8D714570AC8C8A1F950A198BF9A530A3BCF31FF78888C4F204FADA7A5D6",
    "strategic_cust":     "B1DCE83DF425C3E5A76104B5E481F535C9A2EA179B615575BEE438A7D07C5CEC",
    "strategic_ent":      "B1DCE83DF425C3E5A76104B5E481F535AAB30E46CDBA45A3C274179EBA957318",
    "customer_credit":    "3CA0D8D714570AC8C8A1F950A198BF9A55E1815EBCE44F65464E7163245AB1AD",
    "tp_collect":         "3CA0D8D714570AC8C8A1F950A198BF9A5EF51BDCE7285517034BF1FA3CE96575",
    "tp_by_cargo":        "3CA0D8D714570AC8C8A1F950A198BF9A055A39AC6F90C5B49F83A45D1536137F",
    "tp_by_zone":         "3CA0D8D714570AC8C8A1F950A198BF9A2B73EC54D2B807CC53938F1D2030F126",
    "contrib_by_cargo":   "3CA0D8D714570AC8C8A1F950A198BF9A099C3B4FC01B72ABA3B25B0D1AB7F49F",
    "contrib_order":      "3CA0D8D714570AC8C8A1F950A198BF9ACCFD062E9BF3D205BD4FE8F36D552458",
    "strategic_rev":      "B1DCE83DF425C3E5A76104B5E481F535AB27C1127D9E9D64D932479D75D5EEE7",
    "strategic_tp":       "B1DCE83DF425C3E5A76104B5E481F535197F90A4B013C5DDF454DAD5F5842FAD",
    "contrib_trend":      "3CA0D8D714570AC8C8A1F950A198BF9ACE58B93530572AEDA522A3E39860C4F8",
    "cumul_contrib":      "3CA0D8D714570AC8C8A1F950A198BF9A1268DD9BBE8AD8EE8690A057B3095C80",
    "invest_corp":        "3CA0D8D714570AC8C8A1F950A198BF9A84AB2801AC63E68CC044D558E8412210",
    "meeting_info":       "3CA0D8D714570AC8C8A1F950A198BF9A77D88A6BCD6377AA90CC5B8BDEA25AD0",
    "meet_detail":        "3CA0D8D714570AC8C8A1F950A198BF9AFB38B32DAB37592AD95AD094ED5A90D2",
    "new_enterprise":     "3CA0D8D714570AC8C8A1F950A198BF9A5EC914F6A0930D2E03425B1A2E395C62",
    "withdrawal":         "3CA0D8D714570AC8C8A1F950A198BF9AE6226DDFF0D4D31756D2324E991704F2",
    "biz_expiry":         "3CA0D8D714570AC8C8A1F950A198BF9A40FE291B51D21D9EF1A45133EEA048DD",
    "supervisor_change":  "3CA0D8D714570AC8C8A1F950A198BF9AC98145473E3E0E9DCCC35CF41858A94A",
    "total_assets":       "3CA0D8D714570AC8C8A1F950A198BF9A5A358CFC3EEB6EBB46FEA5F1A7326954",
    "asset_value":        "3CA0D8D714570AC8C8A1F950A198BF9A6D9A32EEE331EDA3FE12D12154C2B6BB",
    "main_assets":        "3CA0D8D714570AC8C8A1F950A198BF9A745694A576CFB5803246AB4FDB7B6D77",
    "real_asset_dist":    "3CA0D8D714570AC8C8A1F950A198BF9AA89C371E602AA48399CB5B88AF6FB552",
    "net_val_dist":       "C2B8184E822306ABE43FE46C608F0A10189E6C3733DC809B27C37A77AD204DFD",
    "orig_val_dist":      "3CA0D8D714570AC8C8A1F950A198BF9A0A1FAF0E78BC80A3EEA53AE7523963AF",
    "imp_asset_range":    "B1DCE83DF425C3E5A76104B5E481F53516A59EFC96F1CC26836124CCAB3FFDE5",
    "fin_asset_dist":     "3CA0D8D714570AC8C8A1F950A198BF9AFE95E6F21D4B554F35E3DA30CBBB7771",
    "fin_asset_net":      "3CA0D8D714570AC8C8A1F950A198BF9AA57695EE933FCD13AF102D89D33E4546",
    "equip_state":        "B1DCE83DF425C3E5A76104B5E481F535236C5F6DA2419BC3DC2C09B797335E03",
    "hist_trend":         "B1DCE83DF425C3E5A76104B5E481F53514F290450E6728284578455D84402F3C",
    "real_asset_qty":     "B1DCE83DF425C3E5A76104B5E481F535894453073A19C32022C1F32E220FBB77",
    "mothball_qty":       "B1DCE83DF425C3E5A76104B5E481F535885417B2B988907C1554AC57E7AEB928",
    "trend_new":          "B1DCE83DF425C3E5A76104B5E481F5356EAB6B8E302B01A4503C920A330EDA7B",
    "orig_qty":           "B1DCE83DF425C3E5A76104B5E481F535715518B02C8B5170FC6A012FCC1B91B3",
    "trend_scrap":        "B1DCE83DF425C3E5A76104B5E481F53555E1815EBCE44F65464E7163245AB1AD",
    "scrap_qty":          "B1DCE83DF425C3E5A76104B5E481F535BAF2339B3F17E898B14DD223DF827FFA",
    "new_asset_trans":    "B1DCE83DF425C3E5A76104B5E481F535C22EE6D962755C19E8F936DF84C8E461",
    "scrap_asset_trans":  "24FBB42E14C17ACC6A25969E25BFBECF24FA64F8B0024177D962D5AA1EFD1C83",
    "phys_assets":        "B1DCE83DF425C3E5A76104B5E481F5351CEC8408C1DEDF31B103C4E5F6577301",
    "regional_analysis":  "B1DCE83DF425C3E5A76104B5E481F535530A3BCF31FF78888C4F204FADA7A5D6",
    "category_analysis":  "B1DCE83DF425C3E5A76104B5E481F535055A39AC6F90C5B49F83A45D1536137F",
    "region_trans":       "B1DCE83DF425C3E5A76104B5E481F5352B73EC54D2B807CC53938F1D2030F126",
    "category_trans":     "B1DCE83DF425C3E5A76104B5E481F5355EF51BDCE7285517034BF1FA3CE96575",
    "housing_trans":      "B1DCE83DF425C3E5A76104B5E481F535AAC07F3B25F0739AFBC9750B349B64BB",
    "imp_region_pen":     "24FBB42E14C17ACC6A25969E25BFBECF688DD2E5056273E348A6AA208D92D44A",
    "equip_trans1":       "B1DCE83DF425C3E5A76104B5E481F535339A4372C3D4155FF9DEFEE3F271D3A2",
    "equip_trans2":       "24FBB42E14C17ACC6A25969E25BFBECFAA45BE834636728B28CDA8792D27E028",
    "land_sea_trans":     "B1DCE83DF425C3E5A76104B5E481F535099C3B4FC01B72ABA3B25B0D1AB7F49F",
    "equip_yoy":          "B1DCE83DF425C3E5A76104B5E481F535B6563F3278BD411C6FF7824AC68DDD9D",
    "equip_cat":          "B1DCE83DF425C3E5A76104B5E481F5353655F67A1FD1338ADA22C710B90C6C73",
    "equip_status_cat":   "B1DCE83DF425C3E5A76104B5E481F53505D27D351AF0D990995DBAAD2C535C81",
    "equip_regional":     "B1DCE83DF425C3E5A76104B5E481F53513718C2D92D126102BF7B97E2F0C8D5B",
    "equip_worth":        "B1DCE83DF425C3E5A76104B5E481F5351F7D263469426656C1065802D56D3D33",
    "housing_yoy":        "B1DCE83DF425C3E5A76104B5E481F53584AB2801AC63E68CC044D558E8412210",
    "housing_regional":   "B1DCE83DF425C3E5A76104B5E481F53577D88A6BCD6377AA90CC5B8BDEA25AD0",
    "housing_worth":      "B1DCE83DF425C3E5A76104B5E481F535FB38B32DAB37592AD95AD094ED5A90D2",
    "land_yoy":           "B1DCE83DF425C3E5A76104B5E481F5355EC914F6A0930D2E03425B1A2E395C62",
    "land_regional":      "B1DCE83DF425C3E5A76104B5E481F535E6226DDFF0D4D31756D2324E991704F2",
    "land_worth":         "B1DCE83DF425C3E5A76104B5E481F53540FE291B51D21D9EF1A45133EEA048DD",
    "asset_list":         "24FBB42E14C17ACC6A25969E25BFBECF72546B309A06922EC39F4BB351A458B6",
    "asset_worth_zone":   "24FBB42E14C17ACC6A25969E25BFBECF7CE12AA23200ED963E27AD5585804ACE",
    "asset_worth_cmp":    "24FBB42E14C17ACC6A25969E25BFBECF5A93262256382B148DDB2913D5173AF8",
    # 投资接口
    "invest_plan_type":   "B1DCE83DF425C3E5A76104B5E481F5356CAD71075BC804998E32DCBAE705FBAB",
    "plan_progress":      "B1DCE83DF425C3E5A76104B5E481F535E5BF0B16C7D1935D19088A3C037AEB7C",
    "plan_yoy":           "B1DCE83DF425C3E5A76104B5E481F53576F1B162E6335D64AAAFA9740C64210E",
    "finish_delivery":    "B1DCE83DF425C3E5A76104B5E481F535469D084A0B2C03C0DE08C40AB0D97613",
    "invest_by_year":     "B1DCE83DF425C3E5A76104B5E481F535EE44F1CBC29FAB99EBB5F9D67BBE9B94",
    "cost_proj_year":     "B1DCE83DF425C3E5A76104B5E481F535C29FACC7DE6072083C98C69DA4F604A1",
    "cost_proj_yoy":      "B1DCE83DF425C3E5A76104B5E481F535F547ABF2303BB47B821552314C106673",
    "cost_proj_qty":      "B1DCE83DF425C3E5A76104B5E481F535D125D4232784DAA4C46168E583218256",
    "cost_amt_zone":      "B1DCE83DF425C3E5A76104B5E481F5354D8F5DB7FA6E4AC31499F1F2468C9EBE",
    "cost_stage":         "B1DCE83DF425C3E5A76104B5E481F535011F834BFA89826B3221537950206E69",
    "cost_cmp":           "B1DCE83DF425C3E5A76104B5E481F5350FFB47E0BB36A59FB5C78D10A63B0770",
    "invest_amt_list":    "B1DCE83DF425C3E5A76104B5E481F5351466C3B3412388B980BF57D4D183DAB0",
    "oop_finish":         "B1DCE83DF425C3E5A76104B5E481F5351022A0ACAFBD961B43C0E83CC320F470",
    "oop_yoy":            "B1DCE83DF425C3E5A76104B5E481F53572546B309A06922EC39F4BB351A458B6",
    "oop_invest_5y":      "B1DCE83DF425C3E5A76104B5E481F535F26B1CD4A48F4BC77D559E004AC44F3E",
    "oop_pay_5y":         "B1DCE83DF425C3E5A76104B5E481F5358B6A6E23774631F0FD52320E8B2AD34F",
    "plan_zone":          "B1DCE83DF425C3E5A76104B5E481F535CE804B7E281864F71D561333523DCD53",
    "plan_type":          "B1DCE83DF425C3E5A76104B5E481F535652D8F58597E2197013B0FBA6CBE077D",
    "oop_penetration":    "B1DCE83DF425C3E5A76104B5E481F53524FA64F8B0024177D962D5AA1EFD1C83",
    "oop_list":           "B1DCE83DF425C3E5A76104B5E481F5355A0FFA45E480D71C0B20F14CF34E741E",
    "capital_limit":      "B1DCE83DF425C3E5A76104B5E481F535B8B116C7E086FB58AE6F9A37F7A2A23A",
    "capital_proj":       "B1DCE83DF425C3E5A76104B5E481F535688DD2E5056273E348A6AA208D92D44A",
    "visual_progress":    "B1DCE83DF425C3E5A76104B5E481F535AA45BE834636728B28CDA8792D27E028",
    "completion_status":  "B1DCE83DF425C3E5A76104B5E481F5357CE12AA23200ED963E27AD5585804ACE",
    "delivery_rate":      "B1DCE83DF425C3E5A76104B5E481F5355A93262256382B148DDB2913D5173AF8",
    "capital_delivered":  "B1DCE83DF425C3E5A76104B5E481F53574113C28A028CE867EA8B03F4C4ADC66",
    "capital_del_zone":   "B1DCE83DF425C3E5A76104B5E481F535F04C3E3A6F4A442C0DA5C671950A3663",
    "regional_quota":     "B1DCE83DF425C3E5A76104B5E481F535071FCB360EEA8B8BF13A1D6EC27DC9A8",
    "plan_del_analysis":  "B1DCE83DF425C3E5A76104B5E481F53533F464E961F5C4D9C26F9102B711BEBA",
    "type_invest_amt":    "B1DCE83DF425C3E5A76104B5E481F535BDE7D85129632D041BAB244A1404434F",
    "capital_list":       "B1DCE83DF425C3E5A76104B5E481F53536EF1D63A0571DAB2FB2D987C65E04E7",
    # 恢复的21个API Token（9个新增）
    "equip_machine_hour": "24FBB42E14C17ACC6A25969E25BFBECFAAB30E46CDBA45A3C274179EBA957318",
    "equip_use_list":     "24FBB42E14C17ACC6A25969E25BFBECF2A7E607144CC523844CF35636EA6D3EF",
    "monthly_cargo_cat":  "B1DCE83DF425C3E5A76104B5E481F535A8AB69FFA2B0364B63F9FE69B6717100",
    "sum_biz_tp":         "B1DCE83DF425C3E5A76104B5E481F5359008019B7EA43A0E286EF594A6902FA8",
    "biz_cumul_cargo":    "B1DCE83DF425C3E5A76104B5E481F53554218CCBF43E144BA0FD29243A60A4CA",
    "cumul_region_tp":    "B1DCE83DF425C3E5A76104B5E481F5359FA01B2532CBBBDE2833EFD9268DE42C",
    "cur_strat_trend":    "B1DCE83DF425C3E5A76104B5E481F5350A1FAF0E78BC80A3EEA53AE7523963AF",
    "sum_strat_cargo":    "B1DCE83DF425C3E5A76104B5E481F5351268DD9BBE8AD8EE8690A057B3095C80",
    "sum_contrib_rank":   "B1DCE83DF425C3E5A76104B5E481F535A89C371E602AA48399CB5B88AF6FB552",
    # D7设备域 + 司南商务驾驶舱（原硬编码token）
    "equipment_indicator_operation_qty":                    "B1DCE83DF425C3E5A76104B5E481F535FE95E6F21D4B554F35E3DA30CBBB7771",
    "equipment_indicator_use_cost":                    "B1DCE83DF425C3E5A76104B5E481F535A57695EE933FCD13AF102D89D33E4546",
    "production_equipment_fault_num":                    "24FBB42E14C17ACC6A25969E25BFBECFAB27C1127D9E9D64D932479D75D5EEE7",
    "production_equipment_statistic":                    "24FBB42E14C17ACC6A25969E25BFBECF90AA48728EC03C7F4E244B3EC6A9734F",
    "production_equipment_service_age_distribution":                    "24FBB42E14C17ACC6A25969E25BFBECF369902D9AF69FB5D32520C0CC19E1B08",
    "overview_query":                    "24FBB42E14C17ACC6A25969E25BFBECF236C5F6DA2419BC3DC2C09B797335E03",
    "single_equipment_integrity_rate":                    "24FBB42E14C17ACC6A25969E25BFBECF16A59EFC96F1CC26836124CCAB3FFDE5",
    "unit_hour_efficiency":                    "24FBB42E14C17ACC6A25969E25BFBECFD29D3FBE29DBF8A3C8D41CD705FBDFED",
    "unit_consumption":                    "24FBB42E14C17ACC6A25969E25BFBECFC476705DD6A00BEAAEC8B80621EE652B",
    "single_machine_utilization":                    "24FBB42E14C17ACC6A25969E25BFBECFDC1BA33A3D0C89A8AC9C13741BAF7B2A",
    "single_cost":                    "24FBB42E14C17ACC6A25969E25BFBECF9784CEB3FEDE446D84E8D729028A827E",
    "equipment_usage_rate":                    "24FBB42E14C17ACC6A25969E25BFBECF894453073A19C32022C1F32E220FBB77",
    "equipment_serviceable_rate":                    "24FBB42E14C17ACC6A25969E25BFBECF885417B2B988907C1554AC57E7AEB928",
    "equipment_first_level_class_name_list":                    "24FBB42E14C17ACC6A25969E25BFBECFC9A2EA179B615575BEE438A7D07C5CEC",
    "container_machine_hour_rate":                    "24FBB42E14C17ACC6A25969E25BFBECF7FFD8EB4A3249541CB9694BD4F728C02",
    "equipment_energy_consumption_per_unit":                    "24FBB42E14C17ACC6A25969E25BFBECFE5BF0B16C7D1935D19088A3C037AEB7C",
    "equipment_fuel_oil_ton_cost":                    "24FBB42E14C17ACC6A25969E25BFBECF76F1B162E6335D64AAAFA9740C64210E",
    "equipment_electricity_ton_cost":                    "24FBB42E14C17ACC6A25969E25BFBECFF547ABF2303BB47B821552314C106673",
    "machine_data_display_screen_hourly_efficiency":                    "24FBB42E14C17ACC6A25969E25BFBECF197F90A4B013C5DDF454DAD5F5842FAD",
    "model_data_display_screen_energy_consumption_per_unit":                    "24FBB42E14C17ACC6A25969E25BFBECFE1A990DB594BFE1DB0652AA1C663BE3D",
    "fuel_ton_cost_of_aircraft_data_display":                    "24FBB42E14C17ACC6A25969E25BFBECF6CAD71075BC804998E32DCBAE705FBAB",
    "machine_type_data_display_screen_power_consumption_cost_per_ton":                    "24FBB42E14C17ACC6A25969E25BFBECFF26344A51FADCCC3F43F811700555930",
    "model_data_display_screen_utilization":                    "24FBB42E14C17ACC6A25969E25BFBECF469D084A0B2C03C0DE08C40AB0D97613",
    "model_data_display_screen_effective_utilization":                    "24FBB42E14C17ACC6A25969E25BFBECFEE44F1CBC29FAB99EBB5F9D67BBE9B94",
    "machine_data_display_screen_equipment_integrity_rate":                    "24FBB42E14C17ACC6A25969E25BFBECFC29FACC7DE6072083C98C69DA4F604A1",
    "model_data_display_screen_hierarchy_relation":                    "24FBB42E14C17ACC6A25969E25BFBECF6ECEC354462018E2EAF9954609F4D215",
    "machine_data_display_equipment_reliability":                    "24FBB42E14C17ACC6A25969E25BFBECFD125D4232784DAA4C46168E583218256",
    "non_container_production_equipment_reliability":                    "24FBB42E14C17ACC6A25969E25BFBECF4D8F5DB7FA6E4AC31499F1F2468C9EBE",
    "machine_data_display_single_unit_energy_consumption":                    "24FBB42E14C17ACC6A25969E25BFBECF011F834BFA89826B3221537950206E69",
    "product_equipment_usage_rate_by_year":                    "24FBB42E14C17ACC6A25969E25BFBECF0FFB47E0BB36A59FB5C78D10A63B0770",
    "product_equipment_usage_rate_by_month":                    "24FBB42E14C17ACC6A25969E25BFBECF1466C3B3412388B980BF57D4D183DAB0",
    "product_equipment_rate_by_year":                    "24FBB42E14C17ACC6A25969E25BFBECF1022A0ACAFBD961B43C0E83CC320F470",
    "product_equipment_integrity_rate_by_year":                    "24FBB42E14C17ACC6A25969E25BFBECFF26B1CD4A48F4BC77D559E004AC44F3E",
    "product_equipment_integrity_rate_by_month":                    "24FBB42E14C17ACC6A25969E25BFBECF8B6A6E23774631F0FD52320E8B2AD34F",
    "quay_equipment_working_amount":                    "24FBB42E14C17ACC6A25969E25BFBECFCE804B7E281864F71D561333523DCD53",
    "product_equipment_data_analysis_list":                    "24FBB42E14C17ACC6A25969E25BFBECF652D8F58597E2197013B0FBA6CBE077D",
    "product_equipment_working_amount_by_year":                    "24FBB42E14C17ACC6A25969E25BFBECF81005CF409233C481A18A5158427C8B2",
    "product_equipment_working_amount_by_month":                    "24FBB42E14C17ACC6A25969E25BFBECF9973F08D1DE81B74C87D892E1EAA2388",
    "product_equipment_reliability_by_year":                    "24FBB42E14C17ACC6A25969E25BFBECF5738EACC2B682B2D07B21ED843506EB0",
    "product_equipment_reliability_by_month":                    "24FBB42E14C17ACC6A25969E25BFBECF2DDCEE357D5087B5FCE15331EF57772A",
    "product_equipment_unit_consumption_by_year":                    "24FBB42E14C17ACC6A25969E25BFBECF5A0FFA45E480D71C0B20F14CF34E741E",
    "product_equipment_unit_consumption_by_month":                    "24FBB42E14C17ACC6A25969E25BFBECFB8B116C7E086FB58AE6F9A37F7A2A23A",
    "cur_business_dashboard_throughput":                    "B1DCE83DF425C3E5A76104B5E481F535901ACDCAFE6E39A5B2519571CE335EE2",
    "monthly_regional_throughput_area_business_dashboard":                    "B1DCE83DF425C3E5A76104B5E481F535CCFD062E9BF3D205BD4FE8F36D552458",
    "cur_business_cockpit_trend_chart":                    "B1DCE83DF425C3E5A76104B5E481F535EC7D5A5AD631828C8B77B30B67B15CE2",
    "sum_business_cockpit_trend_chart":                    "B1DCE83DF425C3E5A76104B5E481F535CE58B93530572AEDA522A3E39860C4F8",
    "strategic_customer_contribution_customer_operating_revenue":                    "B1DCE83DF425C3E5A76104B5E481F5355A358CFC3EEB6EBB46FEA5F1A7326954",
    "cur_strategic_customer_contribution_by_cargo_type_throughput":                    "B1DCE83DF425C3E5A76104B5E481F535C98145473E3E0E9DCCC35CF41858A94A",
    "cur_contribution_rank_of_strategic_customer":                    "B1DCE83DF425C3E5A76104B5E481F535745694A576CFB5803246AB4FDB7B6D77",
    "sum_strategic_customer_contribution_customer_operating_revenue":                    "B1DCE83DF425C3E5A76104B5E481F5356D9A32EEE331EDA3FE12D12154C2B6BB",
    "sum_strategy_customer_trend_analysis":                    "B1DCE83DF425C3E5A76104B5E481F53553B6F4D6E5DE6A9E5DB7280DD9A39963",
}


# ─────────────────────────────────────────────
# 生产运营域 + 市场商务域
# ─────────────────────────────────────────────

from fastapi import Request
import random

SHIP_NAMES = [
    "丰顺海", "振兴轮", "辽港1号", "营口明珠", "渤海之星",
    "大连明珠", "东方荣耀", "北方之光", "华北先锋", "长白山号",
    "COSCO DALIAN", "MAERSK LINER", "ONE COMMITMENT", "EVERGREEN STAR",
    "MSC ATLANTIC", "CMA CGM NORTH", "HAPAG EXPRESS", "HMM PIONEER"
]
CARGO_TYPES_SHIP = ["集装箱船", "散货船", "油轮", "滚装船", "化学品船", "杂货船"]

# ─────────────────────────────────────────────
# 生产运营域
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/getWeatherForecast")
async def get_weather_forecast(request: Request, regionName: str = None):
    check_token(request, T["weather_forecast"])
    r = rng({"region": regionName, "day": str(__import__('datetime').date.today())})
    regions = [regionName] if regionName else REGIONS
    data = []
    for reg in regions:
        data.append({
            "regionName": reg,
            "forecasts": [
                {"date": f"2026-04-{15+i:02d}", "weather": r.choice(["晴","多云","阴","小雨","中雨"]),
                 "tempHigh": r.randint(10,25), "tempLow": r.randint(3,15),
                 "windDirection": r.choice(["北","东北","东","东南","南","西南","西","西北"]),
                 "windLevel": r.randint(1,5), "humidity": r.randint(40,90)}
                for i in range(5)
            ]
        })
    region_codes = {"大连": "DL", "营口": "YK", "丹东": "DD", "盘锦": "PJ", "绥中": "SZ"}
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
    } for reg in REGIONS_SHORT for d in range(1, 4)])

# [PROD_DATA]
@app.get("/api/gateway/getRealTimeWeather")
async def get_realtime_weather(request: Request, regionName: str = None):
    check_token(request, T["realtime_weather"])
    r = rng({"region": regionName})
    regions = [regionName] if regionName else REGIONS
    data = [{
        "regionName": reg,
        "currentWeather": r.choice(["晴","多云","阴"]),
        "temperature": round(r.uniform(8, 22), 1),
        "windSpeed": round(r.uniform(2.0, 12.0), 1),
        "windDirection": r.choice(["北风","东北风","东风","东南风"]),
        "humidity": r.randint(45, 85),
        "visibility": round(r.uniform(5.0, 20.0), 1),
        "waveHeight": round(r.uniform(0.2, 1.8), 1),
        "updateTime": "2026-04-15 10:30:00"
    } for reg in regions]
    stations = [
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
    } for st in stations for _ in range(r.randint(15, 25))])

# [NO_PROD_DATA]
@app.get("/api/gateway/getTrafficControl")
async def get_traffic_control(request: Request, regionName: str = None):
    # 生产对齐: 生产环境当前无管制信息，返回空列表
    check_token(request, T["traffic_control"])
    return ok([])

# [PROD_DATA]
@app.get("/api/gateway/getKeyVesselList")
async def get_key_vessel_list(request: Request, shipStatus: str, regionName: str):
    # 生产对齐: 字段对齐生产：shipRecordId/vesselName/berthName/cargoName/planQ/shipDynName/atbTime等
    check_token(request, T["key_vessel"])
    r = rng({"status": shipStatus, "region": regionName})
    statuses = [shipStatus] if shipStatus else ["D", "C"]
    regions_filter = [regionName] if regionName else ["大连", "营口", "丹东", "盘锦", "绥中"]
    VESSEL_NAMES = [
        "阿鲁娜", "回声", "东方角", "盛安洋", "印尼", "凯傲", "佳宝", "明乃2",
        "格瑞卡", "银致", "大永哲", "鸿运丰", "华能煤1", "辽港明珠", "渤海之星",
        "COSCO DALIAN", "MAERSK LINER", "ONE COMMITMENT", "EVERGREEN STAR",
    ]
    CARGO_NAMES = ["复合肥", "重烧镁", "大豆", "铁矿石", "煤炭", "原油", "玉米", "钢材", "化肥", "粮食"]
    BERTH_NAMES = ["", "63", "26A", "B11", "矿1", "3#", "26B", "A4", "湾11", "新3"]
    DYN_NAMES = ["停工", "卸货", "装货", "等泊", "完工"]
    vessels = []
    base_id = 2033813882814435328
    for i in range(r.randint(6, 12)):
        st = r.choice(statuses)
        reg = r.choice(regions_filter)
        d_anchor = r.randint(1, 10)
        d_atb = d_anchor + r.randint(1, 4)
        d_atc = d_atb + r.randint(0, 1)
        d_plan_end = d_atc + r.randint(2, 6) if r.random() > 0.3 else None
        vessels.append({
            "shipRecordId": base_id + r.randint(0, 10**16),
            "shipStatus": st,
            "regionName": reg,
            "vesselName": r.choice(VESSEL_NAMES),
            "berthName": r.choice(BERTH_NAMES),
            "cargoName": r.choice(CARGO_NAMES),
            "planQ": "+%d" % r.randint(5000, 80000) if r.random() > 0.3 else "-%d" % r.randint(5000, 80000),
            "shipDynName": r.choice(DYN_NAMES),
            "anchorTime": f"2026-04-{d_anchor:02d} {r.randint(0,23):02d}:{r.choice(['00','10','15','30','45'])}:00" if r.random() > 0.2 else None,
            "atbTime": f"2026-04-{d_atb:02d} {r.randint(0,23):02d}:{r.choice(['00','10','15','30','45'])}:00",
            "atcTime": f"2026-04-{d_atc:02d} {r.randint(0,23):02d}:{r.choice(['00','10','15','30','45'])}:00",
            "planEndWorkTime": f"2026-04-{d_plan_end:02d} {r.randint(6,22):02d}:00:00" if d_plan_end else None,
        })
    return ok(vessels)

# [PROD_DATA]
@app.get("/api/gateway/getThroughputAndTargetThroughputTon")
async def get_tp_target_ton(request: Request, dateYear: str = "2026", regionName: str = None):
    # 生产对齐: 2026年目标48000万吨，前3月实际约13000万吨
    check_token(request, T["throughput_ton"])
    year = int(dateYear)
    r = rng({"year": dateYear, "region": regionName})
    # 生产数据：2026全年目标48000万吨；截至3月完成13320万吨
    annual_target = {2026: 48000.0, 2025: 46000.0, 2024: 44000.0}.get(year, 48000.0)
    months_done = min(3, 12) if year == 2026 else 12
    actual = sum(month_throughput_ton(year, m, regionName, r) for m in range(1, months_done + 1))
    return ok([{"finishQty": round(actual, 2), "targetQty": annual_target}])

# [PROD_DATA]
@app.get("/api/gateway/getThroughputAndTargetThroughputTeu")
async def get_tp_target_teu(request: Request, dateYear: str = "2026", regionName: str = None):
    # 生产对齐: 2026年目标1200万TEU，前3月完成约339万TEU；修复原来 actual_teu/target_teu 未定义的bug
    check_token(request, T["throughput_teu"])
    year = int(dateYear)
    r = rng({"year": dateYear, "region": regionName})
    annual_target = {2026: 1200.0, 2025: 1150.0, 2024: 1100.0}.get(year, 1200.0)
    months_done = 3 if year == 2026 else 12
    # TEU完成量：月均约110-115万TEU
    base_monthly_teu = annual_target / 12
    actual_teu = round(sum(base_monthly_teu * SEASONAL[m-1] * r.uniform(0.95, 1.05) for m in range(1, months_done+1)), 2)
    return ok([{"finishQty": actual_teu, "targetQty": annual_target}])

# [PROD_DATA]
@app.get("/api/gateway/getSingleShipRate")
async def get_single_ship_rate(request: Request, startDate: str, endDate: str, regionName: str):
    # 生产对齐: 字段对齐生产：regionName/cmpName/cargoType/tonQ/workTh
    check_token(request, T["single_ship_rate"])
    r = rng({"s": startDate, "e": endDate, "reg": regionName})
    SHIP_RATE_DATA = [
        ("大连", "大连油品码头", "油品"),
        ("大连", "大连散粮", "粮食"),
        ("大连", "大连散杂货码头", "矿石"),
        ("大连", "大连长兴岛港口", "矿石"),
        ("营口", "营口二公司", "煤炭"),
        ("营口", "营口三公司", "矿石"),
        ("营口", "营口粮食", "粮食"),
        ("营口", "营口五公司", "油品"),
        ("丹东", "丹东煤矿公司", "煤炭"),
        ("丹东", "丹东煤矿公司", "矿石"),
        ("盘锦", "盘锦散杂货中心", "矿石"),
        ("盘锦", "盘锦散杂货中心", "粮食"),
    ]
    data = []
    for reg, cmp, cargo in SHIP_RATE_DATA:
        if regionName and reg != regionName:
            continue
        ton_q = round(r.uniform(10000, 3000000), 1)
        work_th = round(r.uniform(20, 700), 2)
        data.append({
            "regionName": reg,
            "cmpName": cmp,
            "cargoType": cargo,
            "tonQ": ton_q,
            "workTh": work_th,
        })
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getBerthOccupancyRateByRegion")
async def get_berth_by_region(request: Request, startDate: str = "2026-01-01", endDate: str = "2026-03-31"):
    # 生产对齐: 月份由请求日期范围动态推算
    check_token(request, T["berth_by_region"])
    sy, sm, _ = parse_date(startDate)
    ey, em, _ = parse_date(endDate)
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1; y += 1
    months = months[:12]
    # 每(月份×港区)独立seed，保证同月份在不同查询范围中返回相同值
    return ok([{
        "regionName": reg,
        "dateMonth": mo,
        "rate": round(rng({"mo": mo, "reg": reg}).uniform(0.25, 0.65), 4),
    } for reg in REGIONS for mo in months])

# [PROD_DATA]
@app.get("/api/gateway/getBerthOccupancyRateByBusinessType")
async def get_berth_by_biz(request: Request, startDate: str = "2026-01-01", endDate: str = "2026-03-31"):
    # 生产对齐: businessType枚举对齐生产：散杂货/集装箱/油品/滚装
    check_token(request, T["berth_by_biz"])
    BERTH_BIZ_TYPES = ["散杂货", "集装箱", "油品", "滚装"]
    sy, sm, _ = parse_date(startDate)
    ey, em, _ = parse_date(endDate)
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1; y += 1
    months = months[:12]
    # 每(月份×业务类型)独立seed
    BIZ_BASE = {"散杂货": 0.38, "集装箱": 0.55, "油品": 0.32, "滚装": 0.18}
    return ok([{
        "businessType": bt,
        "dateMonth": mo,
        "rate": round(rng({"mo": mo, "bt": bt}).uniform(
            max(0.05, BIZ_BASE.get(bt, 0.3) - 0.15),
            min(0.75, BIZ_BASE.get(bt, 0.3) + 0.15)
        ), 4),
    } for mo in months for bt in BERTH_BIZ_TYPES])

# [PROD_DATA]
@app.get("/api/gateway/getImportantCargoPortInventoryByRegion")
async def get_inv_by_region(request: Request, regionName: str):
    # 生产对齐: 字段对齐：{cargoKind, tonQ, portRegion, bsCargoKind}
    check_token(request, T["cargo_inv_region"])
    CARGO_MAP = [
        ("粮食", "散杂货"), ("铁矿石", "散杂货"), ("煤炭", "散杂货"), ("钢材", "散杂货"),
        ("化肥", "散杂货"), ("原油", "油化品"), ("成品油", "油化品"), ("化工品", "油化品"),
        ("集装箱", "集装箱"), ("商品车", "商品车"),
    ]
    REGIONS_SHORT2 = {"大连港": "大连", "营口港": "营口", "丹东港": "丹东", "盘锦港": "盘锦", "绥中港": "绥中"}
    filter_regs = [regionName] if regionName else list(REGIONS_SHORT2.keys())
    data = []
    for reg in filter_regs:
        short = REGIONS_SHORT2.get(reg, reg)
        for cargo, bs in CARGO_MAP:
            r_item = rng({"reg": short, "cargo": cargo})
            ton_q = round(r_item.uniform(0, 200), 2)
            data.append({"cargoKind": cargo, "tonQ": ton_q, "portRegion": short, "bsCargoKind": bs})
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getContainerAndVehicleTrade")
async def get_container_vehicle_trade(request: Request, regionName: str):
    # 生产对齐: 字段对齐：{regionName, cargoKind, tradeType, transType, cntQ}
    check_token(request, T["container_vehicle"])
    REGIONS_SHORT2 = {"大连港": "大连", "营口港": "营口", "丹东港": "丹东", "盘锦港": "盘锦", "绥中港": "绥中"}
    filter_regs = [regionName] if regionName else list(REGIONS_SHORT2.keys())
    TRADE_TYPES = [("O", "外贸"), ("D", "内贸")]
    TRANS_TYPES = [("I", "进口"), ("E", "出口")]
    CARGO_KINDS = ["集装箱", "商品车"]
    data = []
    for reg in filter_regs:
        short = REGIONS_SHORT2.get(reg, reg)
        for cargo in CARGO_KINDS:
            for tt, _ in TRADE_TYPES:
                for trans, _ in TRANS_TYPES:
                    r_item = rng({"reg": short, "cargo": cargo, "tt": tt, "trans": trans})
                    cnt_q = round(r_item.uniform(100, 80000), 1) if cargo == "集装箱" else round(r_item.uniform(100, 30000), 1)
                    data.append({"regionName": short, "cargoKind": cargo, "tradeType": tt, "transType": trans, "cntQ": cnt_q})
    return ok(data)

# [OFFLINE] @app.get("/api/gateway/getImportantCargoPortInventoryByCargoType")
# [OFFLINE] async def get_inv_by_cargo(request: Request, date: str = None, businessType: str = None, regionName: str = None):
# [OFFLINE]     check_token(request, T["inv_by_cargo"])
# [OFFLINE]     r = rng({"date": date, "biz": businessType})
# [OFFLINE]     cargo_types = [businessType] if businessType else ["铁矿石","煤炭","粮食","化肥","钢材","集装箱","商品车"]
# [OFFLINE]     return ok([{
# [OFFLINE]         "cargoType": ct,
# [OFFLINE]         "inventory": round(r.uniform(10, 250), 1),
# [OFFLINE]         "capacityRatio": round(r.uniform(30, 95), 1),
# [OFFLINE]         "maxCapacity": round(r.uniform(200, 800), 1),
# [OFFLINE]         "dailyChange": round(r.uniform(-15, 20), 1),
# [OFFLINE]         "date": date,
# [OFFLINE]         "unit": "万吨"
# [OFFLINE]     } for ct in cargo_types])

# [NO_PROD_DATA]
@app.get("/api/gateway/getImportantCargoPortInventoryByBusinessType")
async def get_inv_by_biz(request: Request, date: str = "2026-04-15", regionName: str = None):
    check_token(request, T["inv_by_biz"])
    r = rng({"date": date, "region": regionName})
    return ok([{
        "businessType": bt,
        "regionName": regionName or "全港",
        "inventory": round(r.uniform(20, 300), 1),
        "capacityRatio": round(r.uniform(35, 90), 1),
        "date": date
    } for bt in BUSINESS_TYPES])
# [PROD_DATA]
@app.get("/api/gateway/getThroughputAnalysisNonContainer")
async def get_tp_non_container(request: Request, dateYear: int = 2026):
    check_token(request, T["tp_non_container"])
    year = dateYear
    r = rng({"year": year})
    base = 28000.0
    growth = YOY_BASE.get(year, 1.06) ** (year - 2024)
    total = round(base * growth * r.uniform(0.98, 1.02), 1)
    return ok([{
        "finishQty": round(r.uniform(1000, 8000), 1),
        "regionName": reg,
        "targetQty": round(r.uniform(5000, 25000), 1),
    } for reg in REGIONS])

# [PROD_DATA]
@app.get("/api/gateway/getThroughputAnalysisContainer")
async def get_tp_container(request: Request, dateYear: int = 2026, preYear: int = 2025):
    # 生产数据：{dateMonth, qty}，含当年+上年月度序列（共16条=当年4月+上年12月）
    check_token(request, T["tp_container"])
    data = []
    for y in [preYear, dateYear]:
        months = 12 if y == preYear else min(4, 12)
        for m in range(1, months + 1):
            r_mo = rng({"mo": f"{y}-{m:02d}", "k": "ctn_tp"})
            base_teu = 100.0 * SEASONAL[m-1] * (YOY_BASE.get(y, 1.06) ** (y - 2024))
            qty = round(base_teu * r_mo.uniform(0.92, 1.08), 1)
            data.append({"dateMonth": f"{y}-{m:02d}", "qty": qty})
    return ok(data)

def build_monthly_tp_series(dateYear: str, preYear: str, region: str = None):
    y1 = int(dateYear)
    y0 = int(preYear) if preYear else y1 - 1
    series = []
    for m in range(1, 13):
        r0 = rng({"y": y0, "m": m, "reg": region})
        r1 = rng({"y": y1, "m": m, "reg": region})
        tp0 = month_throughput_ton(y0, m, region, r0)
        tp1 = month_throughput_ton(y1, m, region, r1)
        series.append({
            "month": f"{y1}-{m:02d}",
            f"year{y1}": tp1,
            f"year{y0}": tp0,
            "yoyRate": round((tp1/tp0 - 1)*100, 2) if tp0 else 0
        })
    return series

# [PROD_DATA]
@app.get("/api/gateway/getThroughputAnalysisByYear")
async def get_tp_by_year(request: Request, dateYear: str = "2026", preYear: str = "2025"):
    check_token(request, T["tp_by_year"])
    sy = int(dateYear)
    r = rng({"y": sy, "type": "tp_year"})
    return ok([{
        "dateMonth": f"{sy}-{m:02d}" if m <= 12 else f"{sy+1}-{m-12:02d}",
        "qty": round(month_throughput_ton(sy if m <= 12 else sy+1, m if m <= 12 else m-12, None, r), 1),
    } for m in range(1, 17)])

# [PROD_DATA]
@app.get("/api/gateway/getContainerThroughputAnalysisByYear")
async def get_ctn_tp_by_year(request: Request, dateYear: str = "2026", preYear: str = "2025", regionName: str = None):
    check_token(request, T["ctn_tp_by_year"])
    y1, y0 = int(dateYear), int(preYear)
    series = []
    for m in range(1, 13):
        r1 = rng({"y": y1, "m": m, "type": "ctn"})
        base = 40000 * SEASONAL[m-1] * (YOY_BASE.get(y1, 1.06) ** (y1-2024))
        prev = 40000 * SEASONAL[m-1] * (YOY_BASE.get(y0, 1.06) ** (y0-2024))
        teu = round(base * r1.uniform(0.97, 1.03))
        series.append({
            "month": f"{y1}-{m:02d}",
            "currentYearTeu": teu,
            "prevYearTeu": round(prev),
            "yoyRate": round((teu/prev - 1)*100, 2) if prev else 0
        })
    return ok(series)

# [PROD_DATA]
@app.get("/api/gateway/getOilsChemBreakBulkByBusinessType")
async def get_oil_bulk_biz(request: Request, flag: str = "0", dateMonth: str = "2026-03", businessType: str = "集装箱"):
    # 生产对齐: targetQty=全年固定值，finishQty按月份季节波动
    check_token(request, T["oil_bulk_biz"])
    year, month, _ = parse_date(dateMonth)
    # 真实生产数据：targetQty全年固定
    TARGET_QTY = {
        "大连港": {"集装箱": 557.1, "散杂货": 557.1, "油化品": 557.1},
        "营口港": {"集装箱": 890.8, "散杂货": 890.8, "油化品": 890.8},
        "丹东港": {"集装箱": 264.6, "散杂货": 264.6, "油化品": 264.6},
        "盘锦港": {"集装箱": 180.0, "散杂货": 180.0, "油化品": 180.0},
        "绥中港": {"集装箱": 50.0,  "散杂货": 50.0,  "油化品": 50.0},
    }
    result = []
    for reg in REGIONS:
        tq = TARGET_QTY.get(reg, {}).get(businessType or "散杂货", 300.0)
        r_mo = rng({"reg": reg, "mo": dateMonth, "bt": businessType or "散杂货"})
        seasonal = SEASONAL[month - 1]
        annual_weight = tq / 12
        fq = round(annual_weight * seasonal * r_mo.uniform(0.85, 1.15), 1)
        result.append({"finishQty": fq, "regionName": reg, "targetQty": tq})
    return ok(result)

# [PROD_DATA]
@app.get("/api/gateway/getRoroByBusinessType")
async def get_roro_biz(request: Request, flag: str = "0", dateMonth: str = "2026-03"):
    # 生产对齐: 只有大连港有目标，targetQty=13固定
    check_token(request, T["roro_biz"])
    year, month, _ = parse_date(dateMonth)
    r_mo = rng({"mo": dateMonth, "k": "roro"})
    seasonal = SEASONAL[month - 1]
    fq = round(13.0 / 12 * seasonal * r_mo.uniform(0.80, 1.20), 1)
    return ok([{"finishQty": fq, "regionName": "大连港", "targetQty": 13.0}])

# [PROD_DATA]
@app.get("/api/gateway/getContainerByBusinessType")
async def get_ctn_biz(request: Request, flag: str = "0", dateMonth: str = "2026-03"):
    # 生产对齐: targetQty全年固定，finishQty按月份季节波动
    check_token(request, T["ctn_biz"])
    year, month, _ = parse_date(dateMonth)
    TARGET_QTY = {"大连港": 45.1, "营口港": 48.7, "丹东港": 2.0, "盘锦港": 4.2, "绥中港": 0.5}
    seasonal = SEASONAL[month - 1]
    result = []
    for reg in REGIONS:
        tq = TARGET_QTY.get(reg, 10.0)
        r_mo = rng({"reg": reg, "mo": dateMonth, "k": "ctn_biz"})
        fq = round(tq / 12 * seasonal * r_mo.uniform(0.85, 1.15), 1)
        result.append({"finishQty": fq, "regionName": reg, "targetQty": tq})
    return ok(result)

# [NO_PROD_DATA]
@app.get("/api/gateway/getCompanyStatisticsBusinessType")
async def get_company_stats(request: Request, flag: str = "1", dateMonth: str = None, date: str = None, dateYear: str = None, regionName: str = "全港"):
    check_token(request, T["company_biz"])
    r = rng({"flag": flag, "dm": dateMonth, "dd": date, "dy": dateYear})
    return ok([{
        "companyName": cmp,
        "container": round(r.uniform(5000, 50000)),
        "bulkCargo": round(r.uniform(10000, 200000), 1),
        "oilChem": round(r.uniform(5000, 80000), 1),
        "roro": round(r.uniform(500, 8000)),
        "total": 0,
        "flag": flag
    } for cmp in COMPANIES])

def yoy_mom_data(date_val: str, r_obj, is_container=False, region=None):
    year, month, _ = parse_date(date_val)
    base = (35000 if is_container else month_throughput_ton(year, month, region, r_obj))
    yoy = round(r_obj.uniform(3.0, 10.5), 2)
    mom = round(r_obj.uniform(-8.0, 12.0), 2)
    return {
        "date": date_val, "current": base,
        "prevYear": round(base / (1 + yoy/100), 1),
        "prevMonth": round(base / (1 + mom/100), 1),
        "yoyRate": yoy, "momRate": mom,
        "regionName": region
    }

# [PROD_DATA]
@app.get("/api/gateway/getThroughputAnalysisYoyMomByYear")
async def get_tp_yoy_year(request: Request, date: str = "2026-01-01"):
    # 生产对齐: dateType包含月/日/年三种，regionName含辽港
    check_token(request, T["tp_yoy_mom_year"])
    r = rng({"d": date})
    stat_types = ["当期", "同比", "环比"]
    date_types = ["月", "日", "年"]
    return ok([{
        "dateType": dt,
        "qty": round(r.uniform(0.5, 5000), 1),
        "regionName": reg,
        "statType": st,
    } for reg in REGIONS + ["辽港"] for st in stat_types for dt in date_types])

# [PROD_DATA]
@app.get("/api/gateway/getContainerAnalysisYoyMomByYear")
async def get_ctn_yoy_year(request: Request, date: str = "2026-01-01"):
    check_token(request, T["ctn_yoy_year"])
    r = rng({"d": date, "t": "ctn"})
    stat_types = ["当期", "同比", "环比"]
    return ok([{
        "dateType": "年",
        "qty": round(r.uniform(0.5, 200), 1),
        "regionName": reg,
        "statType": st,
    } for reg in REGIONS for st in stat_types])

# [NO_PROD_DATA]
@app.get("/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByYear")
async def get_biz_tp_yoy_year(request: Request, date: str = "2026-01-01", regionName: str = "全港"):
    check_token(request, T["biz_tp_yoy_year"])
    r = rng({"d": date, "reg": regionName})
    return ok([{**yoy_mom_data(date, r, region=regionName), "businessType": bt} for bt in BUSINESS_TYPES])

# [PROD_DATA]
@app.get("/api/gateway/getThroughputAnalysisYoyMomByMonth")
async def get_tp_yoy_month(request: Request, dateMonth: str = "2026-03"):
    # 生产对齐: 每(月份×港区)独立seed，qty/yoyQty/momQty基于month_throughput_ton
    check_token(request, T["tp_yoy_month"])
    year, month, _ = parse_date(dateMonth)
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    yoy_year = year - 1
    REGION_WEIGHT = {"大连港": 0.38, "营口港": 0.32, "丹东港": 0.16, "盘锦港": 0.09, "绥中港": 0.05}
    data = []
    for reg in REGIONS + ["辽港"]:
        w = REGION_WEIGHT.get(reg, 1.0) if reg != "辽港" else 1.0
        r_mo = rng({"mo": dateMonth, "reg": reg})
        qty = round(month_throughput_ton(year, month, None if reg == "辽港" else None, r_mo) * w, 2)
        r_yoy = rng({"mo": f"{yoy_year}-{month:02d}", "reg": reg})
        yoy_qty = round(month_throughput_ton(yoy_year, month, None, r_yoy) * w, 2)
        r_mom = rng({"mo": f"{prev_year}-{prev_month:02d}", "reg": reg})
        mom_qty = round(month_throughput_ton(prev_year, prev_month, None, r_mom) * w, 2)
        data.append({"qty": qty, "yoyQty": yoy_qty, "momQty": mom_qty, "regionName": reg})
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getThroughputAnalysisYoyMomByDay")
async def get_tp_yoy_day(request: Request, date: str = "2026-04-15"):
    # 生产对齐: 每(日期×港区)独立seed，日吞吐量基于月吞吐量/当月天数
    check_token(request, T["tp_yoy_day"])
    year, month, day = parse_date(date)
    import calendar
    days_in_month = calendar.monthrange(year, month)[1]
    days_in_prev_month = calendar.monthrange(year, month-1 if month > 1 else 12)[1] if month > 1 else calendar.monthrange(year-1, 12)[1]
    REGION_WEIGHT = {"大连港": 0.38, "营口港": 0.32, "丹东港": 0.16, "盘锦港": 0.09, "绥中港": 0.05}
    data = []
    for reg in REGIONS + ["辽港"]:
        w = REGION_WEIGHT.get(reg, 1.0) if reg != "辽港" else 1.0
        r_d = rng({"d": date, "reg": reg})
        monthly = month_throughput_ton(year, month, None, r_d) * w
        qty = round(monthly / days_in_month * r_d.uniform(0.7, 1.3), 2)
        r_yoy = rng({"d": f"{year-1}-{month:02d}-{day:02d}", "reg": reg})
        yoy_monthly = month_throughput_ton(year-1, month, None, r_yoy) * w
        yoy_qty = round(yoy_monthly / days_in_month * r_yoy.uniform(0.7, 1.3), 2)
        prev_m = month-1 if month > 1 else 12
        prev_y = year if month > 1 else year - 1
        r_mom = rng({"d": f"{prev_y}-{prev_m:02d}-{day:02d}", "reg": reg})
        mom_monthly = month_throughput_ton(prev_y, prev_m, None, r_mom) * w
        mom_qty = round(mom_monthly / days_in_prev_month * r_mom.uniform(0.7, 1.3), 2)
        data.append({"qty": qty, "yoyQty": yoy_qty, "momQty": mom_qty, "regionName": reg})
    return ok(data)

# [NO_PROD_DATA]
@app.get("/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByMonth")
async def get_biz_tp_yoy_month(request: Request, dateMonth: str = "2026-03", regionName: str = "全港"):
    check_token(request, T["biz_tp_yoy_month"])
    r = rng({"dm": dateMonth, "reg": regionName})
    year, month, _ = parse_date(dateMonth)
    return ok([{
        "businessType": bt, "regionName": regionName or "全港",
        "dateMonth": dateMonth,
        "currentMonth": round(month_throughput_ton(year, month, regionName, r) * 0.25 * r.uniform(0.8,1.2), 1),
        "yoyRate": round(r.uniform(2.0, 12.0), 2),
        "momRate": round(r.uniform(-8.0, 10.0), 2)
    } for bt in BUSINESS_TYPES])

# [NO_PROD_DATA]
@app.get("/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByDay")
async def get_biz_tp_yoy_day(request: Request, date: str = "2026-04-15", regionName: str = "全港"):
    check_token(request, T["biz_tp_yoy_day"])
    r = rng({"d": date, "reg": regionName})
    return ok([{
        "businessType": bt, "regionName": regionName or "全港",
        "date": date,
        "currentDay": round(r.uniform(5, 40), 1),
        "yoyRate": round(r.uniform(2.0, 10.0), 2),
        "momRate": round(r.uniform(-12.0, 15.0), 2)
    } for bt in BUSINESS_TYPES])

# [PROD_DATA]
@app.get("/api/gateway/getShipStatisticsByRegion")
async def get_ship_stats_region(request: Request, regionName: str):
    # 生产对齐: 字段对齐：planQty/berthQty/anchorageQty/regionName/businessType
    check_token(request, T["ship_stat_region"])
    r = rng({"reg": regionName})
    regions = [regionName] if regionName else REGIONS
    SHIP_BIZ_TYPES = ["货船", "集装箱船", "油船", "滚装船"]
    data = []
    for reg in regions:
        for ship_type in SHIP_BIZ_TYPES:
            data.append({
                "regionName": reg,
                "businessType": ship_type,
                "planQty": r.randint(0, 15),
                "berthQty": r.randint(0, 12),
                "anchorageQty": r.randint(0, 5),
            })
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getShipStatisticsByBusinessType")
async def get_ship_stats_biz(request: Request, regionName: str = None):
    # 生产对齐: businessType枚举：货船/集装箱船/油船/滚装船（油轮→油船）
    check_token(request, T["ship_stat_biz"])
    r = rng({"reg": regionName})
    return ok([{
        "anchorageQty": r.randint(0, 10),
        "berthQty": r.randint(3, 20),
        "businessType": bt,
        "planQty": r.randint(5, 30),
    } for bt in ["货船", "集装箱船", "油船", "滚装船"]])

# [PROD_DATA]
@app.get("/api/gateway/getBusinessSegmentBranch")
async def get_biz_branch(request: Request, regionName: str):
    # 生产对齐: 字段对齐：mainOrgCode/orgName/bsCargoKind/sndStatName/snOrgName/shortName
    check_token(request, T["biz_branch"])
    # 真实生产数据：公司组织层级静态表
    ALL_BRANCHES = [
        ("10002254", "大连港散杂货码头公司",     "散杂货", "散杂货码头", "大连港散杂货码头公司",     "散杂货码头"),
        ("90002254", "大连港散杂货码头公司（矿石）", "散杂货", "散杂货码头", "大连港散杂货码头公司",   "散杂货码头"),
        ("20002815", "大连港散粮码头公司",         "散杂货", "散粮码头",   "大连港散粮码头公司",       "散粮码头"),
        ("10022330", "大连长兴岛港口有限公司",     "散杂货", "长兴岛港口", "大连长兴岛港口有限公司",   "长兴岛港口"),
        ("10002253", "大连港油品码头公司",         "油品",   "油品码头",   "大连港油品码头公司",       "新港"),
        ("10002255", "大连港集装箱码头公司",       "集装箱", "集装箱码头", "大连港集装箱码头公司",     "集装箱码头"),
        ("10002256", "大连汽车码头有限公司",       "商品车", "汽车码头",   "大连汽车码头有限公司",     "汽车码头"),
        ("30001001", "营口集装箱码头公司",         "集装箱", "集装箱码头", "营口集装箱码头公司",       "营口集装"),
        ("30001002", "营口港散杂货公司",           "散杂货", "散杂货码头", "营口港散杂货公司",         "散杂货"),
        ("30001003", "营口港油化码头公司",         "油品",   "油化码头",   "营口港油化码头公司",       "油化"),
        ("40001001", "丹东港口集团有限公司",       "散杂货", "散杂货码头", "丹东港口集团有限公司",     "丹东散杂"),
        ("50001001", "盘锦港集团有限公司",         "散杂货", "散杂货码头", "盘锦港集团有限公司",       "盘锦散杂"),
        ("60001001", "绥中港集团有限公司",         "散杂货", "散杂货码头", "绥中港集团有限公司",       "绥中散杂"),
    ]
    data = [
        {"mainOrgCode": row[0], "orgName": row[1], "bsCargoKind": row[2],
         "sndStatName": row[3], "snOrgName": row[4], "shortName": row[5]}
        for row in ALL_BRANCHES
        if not regionName or regionName in row[1] or regionName in row[4]
    ]
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getPortCompanyThroughput")
async def get_port_cmp_tp(request: Request, date: str, cmpName: str):
    # 生产对齐: 生产数据num大量为0.0；dateYear为int
    check_token(request, T["port_cmp_tp"])
    year, _, _ = parse_date(date)
    r = rng({"d": date, "c": cmpName})
    return ok([{
        "businessType": bt,
        "dateYear": year,
        "num": round(r.uniform(0, 500), 1) if r.random() > 0.6 else 0.0,
    } for bt in BUSINESS_TYPES[:2]])

# [NO_PROD_DATA]
@app.get("/api/gateway/getThroughputMonthlyTrend")
async def get_tp_monthly_trend(request: Request, dateYear: str, cmpName: str):
    check_token(request, T["tp_monthly_trend"])
    year = int(dateYear)
    r = rng({"y": dateYear, "c": cmpName})
    return ok([{
        "month": f"{year}-{m:02d}",
        "throughput": round(month_throughput_ton(year, m, None, rng({"y": year, "m": m, "c": cmpName})) * (0.125 if cmpName else 1.0), 1),
        "companyName": cmpName or "全港",
        "yoyRate": round(rng({"y": year, "m": m, "c": cmpName, "k": "yoy"}).uniform(3.0, 9.0), 2)
    } for m in range(1, 13)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getDailyPortInventoryData")
async def get_daily_inv(request: Request, dateCur: str, cmpName: str):
    check_token(request, T["daily_inv"])
    r = rng({"d": dateCur, "c": cmpName})
    return ok({
        "date": dateCur, "companyName": cmpName or "全港",
        "ironOre": round(r.uniform(80, 250), 1),
        "coal": round(r.uniform(50, 180), 1),
        "grain": round(r.uniform(15, 60), 1),
        "containerTeu": r.randint(15000, 50000),
        "vehicleCount": r.randint(5000, 20000),
        "petroleum": round(r.uniform(30, 120), 1),
        "totalCapacityRatio": round(r.uniform(55, 88), 1)
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getPortInventoryTrend")
async def get_inv_trend(request: Request, dateYear: str, cmpName: str):
    check_token(request, T["inv_trend"])
    r = rng({"y": dateYear, "c": cmpName})
    return ok([{
        "month": f"{dateYear}-{m:02d}",
        "avgInventory": round(rng({"y": dateYear, "m": m, "c": cmpName}).uniform(300, 600), 1),
        "maxInventory": round(rng({"y": dateYear, "m": m, "c": cmpName, "k": "max"}).uniform(550, 800), 1),
        "minInventory": round(rng({"y": dateYear, "m": m, "c": cmpName, "k": "min"}).uniform(150, 300), 1),
        "companyName": cmpName or "全港"
    } for m in range(1, 13)])

# [PROD_DATA]
@app.get("/api/gateway/getVesselOperationEfficiency")
async def get_vessel_eff(request: Request, cmpName: str, startMonth: str, endMonth: str):
    # 生产对齐: 生产环境当前返回null值
    check_token(request, T["vessel_eff"])
    return ok([{"curEfficiency": None, "lastEfficiency": None}])

# [NO_PROD_DATA]
@app.get("/api/gateway/getVesselOperationEfficiencyTrend")
async def get_vessel_eff_trend(request: Request, startMonth: str, endMonth: str, cmpName: str):
    check_token(request, T["vessel_eff_trend"])
    r = rng({"s": startMonth, "e": endMonth})
    months = []
    start_dt = __import__('datetime').datetime.strptime(startMonth or "2026-01", "%Y-%m")
    end_dt = __import__('datetime').datetime.strptime(endMonth or "2026-03", "%Y-%m")
    curr = start_dt
    while curr <= end_dt:
        months.append({
            "month": curr.strftime("%Y-%m"),
            "avgEfficiency": round(r.uniform(70, 110), 1),
            "containerEfficiency": round(r.uniform(75, 120), 1),
            "bulkEfficiency": round(r.uniform(800, 2500), 1),
            "momChange": round(r.uniform(-5, 8), 2)
        })
        curr = (curr.replace(day=1) + __import__('datetime').timedelta(days=32)).replace(day=1)
    return ok(months)

# [NO_PROD_DATA]
@app.get("/api/gateway/getBerthOccupancyRate")
async def get_berth_occ(request: Request, mainOrgCode: str, statDate: str, endDate: str):
    check_token(request, T["berth_occ"])
    r = rng({"org": mainOrgCode, "d": statDate})
    return ok({
        "orgCode": mainOrgCode,
        "statDate": statDate,
        "occupancyRate": round(r.uniform(55, 90), 2),
        "berthCount": r.randint(8, 20),
        "totalBerthHours": r.randint(1500, 4000),
        "berthingShips": r.randint(5, 18)
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getTotalBerthDuration")
async def get_berth_duration(request: Request, orgName: str, statDate: str, endDate: str):
    check_token(request, T["berth_duration"])
    r = rng({"org": orgName, "d": statDate})
    return ok({
        "orgName": orgName,
        "statDate": statDate,
        "totalBerthingHours": round(r.uniform(500, 3000), 1),
        "berthCount": r.randint(8, 25),
        "calendarHours": 720,
        "occupancyRate": round(r.uniform(55, 88), 2)
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getBerthList")
async def get_berth_list(request: Request, cmpName: str):
    check_token(request, T["berth_list"])
    r = rng({"c": cmpName})
    berths = []
    for i in range(r.randint(5, 15)):
        status = r.choice(["在泊", "离泊", "计划"])
        berths.append({
            "berthNo": f"B{r.randint(1,30):02d}",
            "shipName": r.choice(SHIP_NAMES) if status != "计划" else "待分配",
            "status": status,
            "arrivalTime": f"2026-04-{r.randint(10,15):02d} {r.randint(0,23):02d}:00",
            "departureTime": f"2026-04-{r.randint(15,20):02d} {r.randint(0,23):02d}:00",
            "cargoType": r.choice(BUSINESS_TYPES),
            "companyName": cmpName or r.choice(COMPANIES)
        })
    return ok(berths)

# [NO_PROD_DATA]
@app.get("/api/gateway/getShipOperationDynamic")
async def get_ship_op_dynamic(request: Request, shipRecordId: str = "SR001"):
    check_token(request, T["ship_op_dynamic"])
    r = rng({"id": shipRecordId})
    return ok([{
        "shipRecordId": shipRecordId,
        "shipName": r.choice(SHIP_NAMES),
        "currentStatus": r.choice(["装货中", "卸货中", "等待", "靠泊", "离港"]),
        "berthNo": f"B{r.randint(1, 30):02d}",
        "startTime": "2026-04-14 08:00:00",
        "estimatedEndTime": "2026-04-16 18:00:00",
        "completedTon": round(r.uniform(1000, 50000), 1),
        "totalTon": round(r.uniform(50000, 150000), 1),
        "efficiency": round(r.uniform(60, 120), 1),
    }])
# [PROD_DATA]
@app.get("/api/gateway/getProductViewShipOperationRateAvg")
async def get_prod_rate_avg(request: Request, startDate: str = "2026-01-01", endDate: str = "2026-03-31"):
    # 生产对齐: 货种对齐生产：矿石/油品/粮食（无散杂货/集装箱）
    check_token(request, T["prod_rate_avg"])
    r = rng({"s": startDate, "e": endDate})
    cargo_kinds = ["矿石", "油品", "粮食"]
    return ok([{
        "statCargoKind": ck,
        "tonQ": round(r.uniform(500000, 9000000), 1),
        "workTh": round(r.uniform(50, 2500), 1),
    } for ck in cargo_kinds])

# [PROD_DATA]
@app.get("/api/gateway/getProductViewShipOperationRateTrend")
async def get_prod_rate_trend(request: Request, startDate: str = "2026-01-01", endDate: str = "2026-03-31"):
    # 生产对齐: 按日期范围返回月度序列，每(月份×货种)独立seed
    check_token(request, T["prod_rate_trend"])
    # 生产数据货种：矿石/油品/粮食/煤炭
    CARGO_KINDS = ["矿石", "油品", "粮食", "煤炭"]
    # 各货种基准（吨量范围，工时范围）
    CARGO_RANGES = {
        "矿石": (1000000, 4000000, 200, 800),
        "油品": (500000, 2500000, 100, 600),
        "粮食": (100000, 800000, 50, 300),
        "煤炭": (200000, 1500000, 80, 400),
    }
    sy, sm, _ = parse_date(startDate)
    ey, em, _ = parse_date(endDate)
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1; y += 1
    data = []
    for my, mm in months:
        mo_str = f"{my}-{mm:02d}"
        seasonal = SEASONAL[mm - 1]
        for ck in CARGO_KINDS:
            r_mo = rng({"mo": mo_str, "ck": ck})
            lo_t, hi_t, lo_w, hi_w = CARGO_RANGES[ck]
            ton_q = round(r_mo.uniform(lo_t, hi_t) * seasonal, 1)
            work_th = round(r_mo.uniform(lo_w, hi_w) * seasonal, 1)
            data.append({
                "monthId": mo_str,
                "monthStr": f"{mm:02d}月",
                "statCargoKind": ck,
                "tonQ": ton_q,
                "workTh": work_th,
            })
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getPersonalCenterCargoThroughput")
async def get_pc_daily(request: Request, date: str = "2026-04-15", momDate: str = "2026-04-14", yoyDate: str = "2025-04-15"):
    check_token(request, T["pc_daily_tp"])
    year, month, day = parse_date(date)
    r = rng({"d": date, "mom": momDate})
    base = round(r.uniform(80, 140), 1)
    return ok([{
        "regionName": reg,
        "curTonQ": round(r.uniform(1, 50), 1),
        "curTeuQ": round(r.uniform(100, 2000), 0),
        "momTonQ": round(r.uniform(1, 50), 1),
        "momTeuQ": round(r.uniform(100, 2000), 0),
        "yoyTonQ": round(r.uniform(1, 50), 1),
        "yoyTeuQ": round(r.uniform(100, 2000), 0),
    } for reg in REGIONS_SHORT])

# [PROD_DATA]
@app.get("/api/gateway/getPersonalCenterMonthCargoThroughput")
async def get_pc_month(request: Request, endDate: str = "2026-03-31", momEndDate: str = "2026-02-28", yoyEndDate: str = "2025-03-31", momStartDate: str = "2026-02-01", startDate: str = "2026-03-01", yoyStartDate: str = "2025-03-01"):
    check_token(request, T["pc_month_tp"])
    year, month, _ = parse_date(endDate)
    r = rng({"ed": endDate, "mom": momEndDate})
    base = month_throughput_ton(year, month, None, r)
    return ok([{
        "regionName": reg,
        "curTonQ": round(r.uniform(50, 500), 1),
        "curTeuQ": round(r.uniform(1, 50), 1),
        "momTonQ": round(r.uniform(50, 500), 1),
        "momTeuQ": round(r.uniform(1, 50), 1),
        "yoyTonQ": round(r.uniform(50, 500), 1),
        "yoyTeuQ": round(r.uniform(1, 50), 1),
    } for reg in REGIONS_SHORT])

# [PROD_DATA]
@app.get("/api/gateway/getPersonalCenterYearCargoThroughput")
async def get_pc_year(request: Request, endDate: str = "2026-03-31", yoyEndDate: str = "2025-03-31", startDate: str = "2026-01-01", yoyStartDate: str = "2025-01-01"):
    check_token(request, T["pc_year_tp"])
    year, month, _ = parse_date(endDate)
    r = rng({"ed": endDate, "yoy": yoyEndDate})
    cum = sum(month_throughput_ton(year, m, None, r) for m in range(1, month+1))
    return ok([{
        "regionName": reg,
        "curTonQ": round(r.uniform(500, 8000), 1),
        "curTeuQ": round(r.uniform(50, 500), 1),
        "yoyTonQ": round(r.uniform(500, 8000), 1),
        "yoyTeuQ": round(r.uniform(50, 500), 1),
    } for reg in REGIONS_SHORT])

# [PROD_DATA]
@app.get("/api/gateway/getPersonalCenterYearCargoThroughputTrend")
async def get_pc_year_trend(request: Request, startDate: str = "2026-01-01", endDate: str = "2026-03-31"):
    # 生产对齐: 按startDate/endDate展开月度序列，每(月份×港区)独立seed
    check_token(request, T["pc_year_trend"])
    REGION_WEIGHT = {"大连": 0.38, "营口": 0.32, "丹东": 0.16, "盘锦": 0.09, "绥中": 0.05}
    TEU_WEIGHT = {"大连": 0.45, "营口": 0.40, "丹东": 0.08, "盘锦": 0.05, "绥中": 0.02}
    sy, sm, _ = parse_date(startDate)
    ey, em, _ = parse_date(endDate)
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1; y += 1
    data = []
    for my, mm in months:
        mo_str = f"{my}-{mm:02d}"
        seasonal = SEASONAL[mm - 1]
        for reg in REGIONS_SHORT:
            r_mo = rng({"mo": mo_str, "reg": reg, "k": "pc_trend"})
            wt = REGION_WEIGHT.get(reg, 0.2)
            base_ton = month_throughput_ton(my, mm, None, r_mo) * wt
            base_teu = base_ton * TEU_WEIGHT.get(reg, 0.1) / 10
            data.append({
                "monthId": f"{mm:02d}月",
                "regionName": reg,
                "tonQ": round(base_ton * r_mo.uniform(0.95, 1.05), 1),
                "teuQ": round(base_teu * r_mo.uniform(0.90, 1.10), 1),
                "yearId": str(my),
            })
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getProdShipDynNum")
async def get_ship_dyn_num(request: Request):
    # 生产对齐: 船舶类型名称对齐生产：侯泊船/预到船/在泊船/离泊船
    check_token(request, T["ship_dyn_num"])
    r = rng({"d": "20260415"})
    type_names = ["在泊船", "侯泊船", "离泊船", "预到船"]
    return ok([{
        "num": r.randint(0, 43),
        "orgType": reg + "区域",
        "typeName": tn,
    } for reg in REGIONS_SHORT for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getProdShipDesc")
async def get_ship_desc(request: Request):
    # 生产对齐: 生产返回URL-encoded HTML内容；portVesselDesc/anchorageVesselDesc/orgType
    check_token(request, T["ship_desc"])
    from urllib.parse import quote
    r = rng({"d": "20260415"})
    REGION_ZONES = ["大连区域", "营口区域", "丹东区域", "盘锦区域", "绥中区域"]
    data = []
    for zone in REGION_ZONES:
        berth_count = r.randint(5, 30)
        anchor_count = r.randint(0, 8)
        port_html = f"<p>在泊船舶{berth_count}艘，正常作业中。</p>"
        anchor_html = f"<p>锚地船舶{anchor_count}艘。</p>" if anchor_count > 0 else "<p>无</p>"
        data.append({
            "portVesselDesc": quote(port_html),
            "anchorageVesselDesc": quote(anchor_html),
            "orgType": zone,
        })
    return ok(data)

# ─────────────────────────────────────────────
# 市场商务驾驶舱
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/getMonthlyThroughput")
async def get_mkt_monthly(request: Request, curDateMonth: str, yearDateMonth: str, zoneName: str):
    # 生产对齐: 返回列表：[{ioTrade, throughput, dateMonth}]，含当期和同比年份
    check_token(request, T["mkt_monthly"])
    cy, cm, _ = parse_date(curDateMonth)
    py, pm, _ = parse_date(yearDateMonth)
    r = rng({"cm": curDateMonth, "pm": yearDateMonth})
    cur_total = month_throughput_ton(cy, cm, None, r)
    prev_total = month_throughput_ton(py, pm, None, r)
    return ok([
        {"ioTrade": "外贸", "throughput": round(cur_total * 0.43, 2), "dateMonth": curDateMonth},
        {"ioTrade": "内贸", "throughput": round(cur_total * 0.57, 2), "dateMonth": curDateMonth},
        {"ioTrade": "外贸", "throughput": round(prev_total * 0.43, 2), "dateMonth": yearDateMonth},
        {"ioTrade": "内贸", "throughput": round(prev_total * 0.57, 2), "dateMonth": yearDateMonth},
    ])

# [PROD_DATA]
@app.get("/api/gateway/getMonthlyZoneThroughput")
async def get_mkt_zone_monthly(request: Request, curDateMonth: str, yearDateMonth: str, zoneName: str):
    # 生产对齐: 返回扁平列表：{throughput, dateMonth, zoneName}，含当期和同比
    check_token(request, T["mkt_zone_monthly"])
    cy, cm, _ = parse_date(curDateMonth)
    py, pm, _ = parse_date(yearDateMonth)
    ZONE_NAMES = ["大连区域", "营口区域", "丹东区域", "盘锦区域", "绥中区域"]
    REGION_WEIGHT = {"大连区域": 0.38, "营口区域": 0.32, "丹东区域": 0.16, "盘锦区域": 0.09, "绥中区域": 0.05}
    data = []
    for zone in ZONE_NAMES:
        r = rng({"cm": curDateMonth, "pm": yearDateMonth, "z": zone})
        w = REGION_WEIGHT.get(zone, 0.2)
        cur = round(month_throughput_ton(cy, cm, None, r) * w * r.uniform(0.97, 1.03), 2)
        prev = round(month_throughput_ton(py, pm, None, r) * w * r.uniform(0.97, 1.03), 2)
        data.append({"throughput": cur, "dateMonth": curDateMonth, "zoneName": zone})
        data.append({"throughput": prev, "dateMonth": yearDateMonth, "zoneName": zone})
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getCumulativeThroughput")
async def get_mkt_cumul(request: Request, curDateYear: str, yearDateYear: str, zoneName: str = None):
    # 生产对齐: 返回列表：{ioTrade, throughput, dateYear}，含当期年和同比年
    check_token(request, T["mkt_cumulative"])
    cy, py = int(curDateYear), int(yearDateYear)
    r = rng({"cy": curDateYear, "py": yearDateYear})
    months = 3  # 假设截至当前月
    cur = sum(month_throughput_ton(cy, m, None, r) for m in range(1, months + 1))
    prev = sum(month_throughput_ton(py, m, None, r) for m in range(1, months + 1))
    return ok([
        {"ioTrade": "外贸", "throughput": round(cur * 0.43, 2), "dateYear": str(cy)},
        {"ioTrade": "内贸", "throughput": round(cur * 0.57, 2), "dateYear": str(cy)},
        {"ioTrade": "外贸", "throughput": round(prev * 0.43, 2), "dateYear": str(py)},
        {"ioTrade": "内贸", "throughput": round(prev * 0.57, 2), "dateYear": str(py)},
    ])

# [PROD_DATA]
@app.get("/api/gateway/getCumulativeZoneThroughput")
async def get_mkt_zone_cumul(request: Request, curDateYear: str, yearDateYear: str, zoneName: str):
    # 生产对齐: 返回扁平列表：{throughput, dateYear, zoneName}，含当期年和同比年
    check_token(request, T["mkt_zone_cumul"])
    cy, py = int(curDateYear), int(yearDateYear)
    ZONE_NAMES = ["大连区域", "营口区域", "丹东区域", "盘锦区域", "绥中区域"]
    ZONE_WEIGHTS = {"大连区域": 0.38, "营口区域": 0.32, "丹东区域": 0.16, "盘锦区域": 0.09, "绥中区域": 0.05}
    data = []
    for zone in ZONE_NAMES:
        r = rng({"cy": curDateYear, "py": yearDateYear, "z": zone})
        w = ZONE_WEIGHTS.get(zone, 0.2)
        cur = round(sum(month_throughput_ton(cy, m, None, r) for m in range(1, 4)) * w, 2)
        prev = round(sum(month_throughput_ton(py, m, None, r) for m in range(1, 4)) * w, 2)
        data.append({"throughput": cur, "dateYear": str(cy), "zoneName": zone})
        data.append({"throughput": prev, "dateYear": str(py), "zoneName": zone})
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getCurrentBusinessSegmentThroughput")
async def get_mkt_curr_biz(request: Request, curDateMonth: str, yearDateMonth: str, zoneName: str):
    # 生产对齐: 复杂结构：{dateMonth,zoneName,ioTrade,inOutFlag,businessSegment,bigCategory,midCategory,unitName,throughput}
    check_token(request, T["mkt_curr_biz"])
    ZONE_NAMES = ["大连区域", "营口区域", "丹东区域", "盘锦区域", "绥中区域"]
    BIZ_SEGMENTS = [
        ("油化品", "石油、天然气及制品", ["其中：原油", "成品油", "液化气、天然气"]),
        ("散杂货", "矿石", ["铁矿石", "有色矿石"]),
        ("散杂货", "煤炭及制品", ["炼焦煤", "动力煤"]),
        ("集装箱", "集装箱", ["集装箱（TEU）"]),
        ("滚装", "商品车", ["进口汽车", "国产汽车"]),
    ]
    IO_TRADE = ["外贸", "内贸"]
    IN_OUT = ["进口", "出口"]
    data = []
    for dm in [curDateMonth, yearDateMonth]:
        for zone in ZONE_NAMES:
            r = rng({"dm": dm, "z": zone})
            for biz, big_cat, mid_cats in BIZ_SEGMENTS:
                for io in IO_TRADE:
                    for inout in IN_OUT:
                        for mid in mid_cats:
                            tp = round(r.uniform(0, 200), 1) if r.random() > 0.4 else 0.0
                            data.append({
                                "dateMonth": dm, "zoneName": zone,
                                "ioTrade": io, "inOutFlag": inout,
                                "businessSegment": biz, "bigCategory": big_cat,
                                "midCategory": mid, "unitName": "万吨", "throughput": tp,
                            })
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getCumulativeBusinessSegmentThroughput")
async def get_mkt_cumul_biz(request: Request, curDateYear: str, yearDateYear: str, zoneName: str):
    # 生产对齐: 与getCurrentBusinessSegmentThroughput相同结构，dateYear替换dateMonth
    check_token(request, T["mkt_cumul_biz"])
    ZONE_NAMES = ["大连区域", "营口区域", "丹东区域", "盘锦区域", "绥中区域"]
    BIZ_SEGMENTS = [
        ("油化品", "石油、天然气及制品", ["其中：原油", "成品油", "液化气、天然气"]),
        ("散杂货", "矿石", ["铁矿石", "有色矿石"]),
        ("散杂货", "煤炭及制品", ["炼焦煤", "动力煤"]),
        ("集装箱", "集装箱", ["集装箱（TEU）"]),
        ("滚装", "商品车", ["进口汽车", "国产汽车"]),
    ]
    IO_TRADE = ["外贸", "内贸"]
    IN_OUT = ["进口", "出口"]
    data = []
    for dy in [curDateYear, yearDateYear]:
        for zone in ZONE_NAMES:
            r = rng({"dy": dy, "z": zone})
            for biz, big_cat, mid_cats in BIZ_SEGMENTS:
                for io in IO_TRADE:
                    for inout in IN_OUT:
                        for mid in mid_cats:
                            tp = round(r.uniform(0, 5000), 1) if r.random() > 0.3 else 0.0
                            data.append({
                                "dateYear": dy, "zoneName": zone,
                                "ioTrade": io, "inOutFlag": inout,
                                "businessSegment": biz, "bigCategory": big_cat,
                                "midCategory": mid, "unitName": "万吨", "throughput": tp,
                            })
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getTrendChart")
async def get_mkt_trend(request: Request, businessSegment: str, startDate: str, endDate: str):
    # 生产对齐: 返回请求businessSegment的月度趋势：{throughput, businessSegment, dateMonth}
    check_token(request, T["mkt_trend"])
    WEIGHTS = {"集装箱": 0.30, "散杂货": 0.36, "油化品": 0.22, "商品车": 0.12}
    w = WEIGHTS.get(businessSegment, 0.25)
    sy, sm, _ = parse_date(startDate)
    ey, em, _ = parse_date(endDate)
    data = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        mo = f"{y}-{m:02d}"
        # 每月独立seed，保证跨查询范围一致
        r_mo = rng({"mo": mo, "bs": businessSegment})
        tp = round(month_throughput_ton(y, m, None, r_mo) * w * r_mo.uniform(0.95, 1.05), 1)
        data.append({"throughput": tp, "businessSegment": businessSegment, "dateMonth": mo})
        m += 1
        if m > 12:
            m = 1; y += 1
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getCumulativeTrendChart")
async def get_mkt_cumul_trend(request: Request, businessSegment: str, curDateYear: str, yearDateYear: str):
    # 生产对齐: 返回：{throughput, businessSegment, dateYear}，含当期年和同比年
    check_token(request, T["mkt_cumul_trend"])
    cy, py = int(curDateYear), int(yearDateYear)
    r = rng({"bs": businessSegment, "cy": curDateYear})
    WEIGHTS = {"集装箱": 0.30, "散杂货": 0.36, "油化品": 0.22, "商品车": 0.12}
    w = WEIGHTS.get(businessSegment, 0.25)
    cur_months = 3 if cy == 2026 else 12
    prev_months = 12
    cur_tp = round(sum(month_throughput_ton(cy, m, None, r) for m in range(1, cur_months + 1)) * w, 2)
    prev_tp = round(sum(month_throughput_ton(py, m, None, r) for m in range(1, prev_months + 1)) * w, 2)
    return ok([
        {"throughput": prev_tp, "businessSegment": businessSegment, "dateYear": str(py)},
        {"throughput": cur_tp,  "businessSegment": businessSegment, "dateYear": str(cy)},
    ])

# [PROD_DATA]
@app.get("/api/gateway/getKeyEnterprise")
async def get_key_enterprise(request: Request, businessSegment: str, curDateMonth: str, yearDateMonth: str):
    # 生产对齐: 返回：{companyName, dateMonth, throughput}，含当期和同比两批数据
    check_token(request, T["mkt_key_ent"])
    cy, cm, _ = parse_date(curDateMonth)
    py, pm, _ = parse_date(yearDateMonth)
    r = rng({"bs": businessSegment, "cm": curDateMonth})
    TOP_CMP = {
        "集装箱": ["股份集码", "DCT", "营口集装箱码头有限公司", "盘锦集装箱", "绥中港集团"],
        "散杂货": ["散杂货码头", "大连港散杂货码头分公司", "辽港控股（营口）有限公司第三分公司", "丹东散杂"],
        "油化品": ["大连港油品码头公司", "营口港油化码头公司", "大连长兴岛港口有限公司"],
        "商品车": ["大连汽车码头有限公司", "大连海嘉汽车码头有限公司"],
    }
    companies = TOP_CMP.get(businessSegment, ["散杂货码头", "DCT", "大连港油码头有限公司"])
    data = []
    for cmp in companies:
        r2 = rng({"c": cmp, "cm": curDateMonth})
        cur_tp = round(r2.uniform(10, 600), 2)
        prev_tp = round(r2.uniform(10, 600), 2)
        data.append({"companyName": cmp, "dateMonth": curDateMonth, "throughput": cur_tp})
        data.append({"companyName": cmp, "dateMonth": yearDateMonth, "throughput": prev_tp})
    return ok(data)

# [PROD_DATA]
@app.get("/api/gateway/getCumulativeKeyEnterprise")
async def get_cumul_key_enterprise(request: Request, businessSegment: str, curDateYear: str, yearDateYear: str):
    # 生产对齐: 返回：{companyName, dateYear, throughput}，含当期年和同比年
    check_token(request, T["mkt_cumul_ent"])
    year = int(curDateYear)
    prev_year = int(yearDateYear)
    r = rng({"bs": businessSegment, "cy": curDateYear})
    TOP_CMP = {
        "集装箱": ["集装箱码头公司", "股份集码", "DCT", "营口集装箱码头有限公司", "盘锦集装箱", "绥中港集团"],
        "散杂货": ["散杂货码头", "大连港散杂货码头分公司", "辽港控股（营口）有限公司第三分公司",
                   "散杂货事业部", "辽港控股（营口）有限公司粮食分公司"],
        "油化品": ["大连港油品码头公司", "营口港油化码头公司", "大连长兴岛港口有限公司"],
        "商品车": ["大连汽车码头有限公司", "大连海嘉汽车码头有限公司"],
    }
    companies = TOP_CMP.get(businessSegment, ["散杂货码头", "DCT", "营口集装箱码头有限公司",
                                               "大连港油码头有限公司", "散粮码头",
                                               "大连汽车码头有限公司"])
    data = []
    for cmp in companies:
        r2 = rng({"c": cmp, "cy": curDateYear})
        cur_tp = round(r2.uniform(50, 1800), 2)
        prev_tp = round(r2.uniform(50, 1800), 2)
        data.append({"companyName": cmp, "dateYear": str(year), "throughput": cur_tp})
        data.append({"companyName": cmp, "dateYear": str(prev_year), "throughput": prev_tp})
    return ok(data)


# ─────────────────────────────────────────────
# 客户域 / 投企域 / 资产域 / 投资域
# ─────────────────────────────────────────────

from fastapi import Request
import random

ASSET_TYPES = ["设备", "设施", "房屋", "土地海域"]
PROJECT_TYPES = ["技改项目", "新建项目", "扩建项目", "维护改造", "安全环保"]
INVEST_ZONES = ["大连", "营口", "丹东", "锦州", "绥中"]
CREDIT_LEVELS = ["AAA", "AA", "A", "BBB", "BB"]

# ─────────────────────────────────────────────
# 司南接口 test/lg_dw 路径
# ─────────────────────────────────────────────

# [NO_PROD_DATA]
@app.get("/api/gateway/getActualPerformance")
async def get_actual_perf(request: Request, yesterday: str = None, lastMonthDay: str = None):
    check_token(request, T["actual_perf"])
    r = rng({"y": yesterday, "lm": lastMonthDay})
    year, month, _ = parse_date(yesterday)
    base = round(r.uniform(85, 135), 1)
    return ok({
        "yesterday": yesterday, "lastMonthDay": lastMonthDay,
        "yesterdayThroughput": base,
        "lastMonthDayThroughput": round(base / (1 + r.uniform(-0.12, 0.15)), 1),
        "momRate": round(r.uniform(-12.0, 15.0), 2),
        "yoyRate": round(r.uniform(3.0, 10.0), 2),
        "byBusinessType": [
            {"businessType": bt, "throughput": round(base * w * r.uniform(0.9,1.1), 1)}
            for bt, w in zip(BUSINESS_TYPES, [0.35,0.30,0.22,0.13])
        ]
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getMonthlyTrendThroughput")
async def get_monthly_trend_tp(request: Request, endDate: str, startDate: str):
    check_token(request, T["monthly_trend_tp"])
    ey, em, _ = parse_date(endDate)
    sy, sm, _ = parse_date(startDate)
    r = rng({"s": startDate, "e": endDate})
    series = []
    year, month = sy, sm
    while (year, month) <= (ey, em):
        series.append({
            "month": f"{year}-{month:02d}",
            "throughput": month_throughput_ton(year, month, None, r),
            "yoyRate": round(r.uniform(3.0, 9.5), 2)
        })
        month += 1
        if month > 12:
            month = 1; year += 1
    return ok(series)

# [NO_PROD_DATA]
@app.get("/api/gateway/getlnportDispatchPort")
async def get_dispatch_port(request: Request, dispatchDate: str):
    check_token(request, T["dispatch_port"])
    r = rng({"d": dispatchDate})
    return ok([{
        "regionName": reg,
        "dispatchDate": dispatchDate,
        "dayShift": round(r.uniform(30, 90), 1),
        "nightShift": round(r.uniform(25, 80), 1),
        "totalThroughput": 0,
        "inPortShips": r.randint(8, 25),
        "unit": "万吨"
    } for reg in REGIONS])

# [NO_PROD_DATA]
@app.get("/api/gateway/getlnportDispatchWharf")
async def get_dispatch_wharf(request: Request, dispatchDate: str):
    check_token(request, T["dispatch_wharf"])
    r = rng({"d": dispatchDate})
    return ok([{
        "wharfName": cmp,
        "dispatchDate": dispatchDate,
        "dayShift": round(r.uniform(5, 30), 1),
        "nightShift": round(r.uniform(4, 25), 1),
        "totalThroughput": 0,
        "operationRate": round(r.uniform(65, 92), 1)
    } for cmp in COMPANIES])

# 资产净值分布（test路径）
# [NO_PROD_DATA]
@app.get("/api/gateway/getNetValueDistribution")
async def get_net_val_dist(request: Request, ownerZone: str):
    check_token(request, T["net_val_dist"])
    r = rng({"zone": ownerZone})
    zones = [ownerZone] if ownerZone else REGIONS
    return ok([{
        "ownerZone": z,
        "netValueRanges": [
            {"range": "0-100万", "count": r.randint(50, 300), "totalNetValue": round(r.uniform(100, 1500), 1)},
            {"range": "100-500万", "count": r.randint(30, 150), "totalNetValue": round(r.uniform(500, 5000), 1)},
            {"range": "500-1000万", "count": r.randint(10, 80), "totalNetValue": round(r.uniform(1000, 8000), 1)},
            {"range": "1000万以上", "count": r.randint(5, 40), "totalNetValue": round(r.uniform(5000, 30000), 1)}
        ]
    } for z in zones])

# ─────────────────────────────────────────────
# 客户管理域
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/getCustomerQty")
async def get_customer_qty(request: Request):
    check_token(request, T["customer_qty"])
    r = rng({"k": "customer_qty"})
    return ok([{
        "customerFilesNumber": r.randint(8000, 10000),
        "outPortQty": r.randint(5000, 7000),
        "strategyClientQty": r.randint(30, 50),
        "totalQty": r.randint(6000, 7000),
    }])

# [PROD_DATA]
@app.get("/api/gateway/getCustomerTypeAnalysis")
async def get_customer_type(request: Request):
    check_token(request, T["customer_type"])
    r = rng({"k": "type"})
    types = ["货主企业", "船务代理", "集装箱船公司", "散货船公司", "油品企业", "汽车企业", "其他"]
    counts = [r.randint(50, 150) for _ in types]
    total = sum(counts)
    types = ["自然人", "机关团体", "非自然人", "非企业单位", "企业法人", "个体工商户",
        "非法人组织", "外国人", "外国法人", "临时账户", "其他组织", "合伙企业", "个人独资企业"]
    return ok([{
        "clientType": t,
        "qty": r.randint(1, 3000),
    } for t in types])

# [PROD_DATA]
@app.get("/api/gateway/getCustomerFieldAnalysis")
async def get_customer_field(request: Request):
    check_token(request, T["customer_field"])
    r = rng({"k": "field"})
    fields = ["钢铁冶金", "能源化工", "汽车制造", "粮食农业", "国际贸易", "物流运输", "其他行业"]
    counts = [r.randint(20, 100) for _ in fields]
    total = sum(counts)
    fields = ["煤炭", "矿石", "钢材", "粮食", "石油化工", "集装箱", "汽车", "木材",
        "水泥", "化肥", "机械设备", "日用百货", "建材", "有色金属", "其他", "农副产品", "纸浆"]
    return ok([{
        "indstryFieldName": f,
        "qty": r.randint(1, 200),
    } for f in fields])

# [PROD_DATA]
@app.get("/api/gateway/getStrategicCustomers")
async def get_strategic_customers(request: Request):
    check_token(request, T["strategic_cust"])
    r = rng({"k": "strategic"})
    return ok([{
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
    ]])

# [NO_PROD_DATA]
@app.get("/api/gateway/getStrategicClientsEnterprises")
async def get_strategic_enterprises(request: Request, displayCode: str):
    check_token(request, T["strategic_ent"])
    r = rng({"code": displayCode})
    return ok([{
        "clientCode": displayCode,
        "enterpriseName": r.choice(COMPANIES),
        "cooperationType": r.choice(["码头作业","堆场租赁","代理服务","配套物流"]),
        "annualVolume": round(r.uniform(5, 50), 1),
        "unit": "万TEU/万吨"
    } for _ in range(r.randint(2, 5))])

# [PROD_DATA]
@app.get("/api/gateway/getCustomerCredit")
async def get_customer_credit(request: Request, orgName: str, customerName: str, gradeResult: str):
    # 生产对齐: 字段对齐：orgName/orgCode/customerName/cstmId/year/frequency/gradeScore/gradeResult/creditLimit/creditTerm
    check_token(request, T["customer_credit"])
    r = rng({"org": orgName, "cust": customerName})
    ORG_MAP = [
        ("大连长兴岛港口投资发展有限公司", "10000227"),
        ("辽港控股（营口）有限公司第三分公司", "20047036"),
        ("大连港散杂货码头公司", "10002254"),
        ("大连港油品码头公司", "10002253"),
        ("大连港集装箱码头有限公司", "10002255"),
    ]
    GRADE_LEVELS = ["A级", "B级", "C级", "D级"]
    FREQ = ["Q1", "Q2", "Q3", "Q4"]
    data = []
    n = r.randint(3, 8)
    for i in range(n):
        org, org_code = r.choice(ORG_MAP)
        grade = gradeResult if gradeResult else r.choice(GRADE_LEVELS)
        score = {"A级": r.uniform(85, 100), "B级": r.uniform(75, 85),
                 "C级": r.uniform(60, 75), "D级": r.uniform(40, 60)}.get(grade, r.uniform(60, 90))
        data.append({
            "orgName": org, "orgCode": org_code,
            "customerName": customerName or f"客户{r.randint(10000, 99999)}",
            "cstmId": str(r.randint(10000000, 19999999)),
            "year": "2025", "frequency": r.choice(FREQ),
            "gradeScore": round(score, 2), "gradeResult": grade,
            "creditLimit": round(r.uniform(0, 300000), 2),
            "creditTerm": r.choice([30.0, 45.0, 60.0, 90.0]),
        })
    return ok(data)

# [NO_PROD_DATA]
@app.get("/api/gateway/getThroughputCollect")
async def get_tp_collect(request: Request, date: str = "2026-03", yoyDate: str = "2025-03"):
    check_token(request, T["tp_collect"])
    year, month, _ = parse_date(date)
    py, pm, _ = parse_date(yoyDate)
    r = rng({"d": date, "yoy": yoyDate})
    cur = month_throughput_ton(year, month, None, r)
    prev = month_throughput_ton(py, pm, None, r)
    return ok([{
        "date": date, "yoyDate": yoyDate,
        "currentThroughput": cur, "yoyThroughput": prev,
        "yoyRate": round((cur / prev - 1) * 100, 2) if prev else 0,
        "momRate": round(r.uniform(-8.0, 10.0), 2),
        "dailyAvg": round(cur / 30, 1)
    }])

# [NO_PROD_DATA]
@app.get("/api/gateway/getThroughputByCargoCategoryName")
async def get_tp_by_cargo(request: Request, date: str = "2026-03", yoyDate: str = "2025-03"):
    check_token(request, T["tp_by_cargo"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "yoy": yoyDate})
    cargo_list = ["铁矿石", "煤炭", "粮食", "化肥", "钢材", "集装箱", "商品车", "油品", "化工品"]
    base = month_throughput_ton(year, month, None, r)
    weights = [0.20, 0.18, 0.10, 0.06, 0.08, 0.15, 0.08, 0.10, 0.05]
    return ok([{
        "cargoCategoryName": c, "date": date,
        "throughput": round(base * w * r.uniform(0.95, 1.05), 1),
        "yoyRate": round(r.uniform(2.0, 12.0), 2)
    } for c, w in zip(cargo_list, weights)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getThroughputByZoneName")
async def get_tp_by_zone(request: Request, date: str = "2026-03", yoyDate: str = "2025-03"):
    check_token(request, T["tp_by_zone"])
    year, month, _ = parse_date(date)
    data = []
    zone_weights = {"大连港": 0.35, "营口港": 0.28, "丹东港": 0.16, "盘锦港": 0.12, "绥中港": 0.09}
    for reg, w in zone_weights.items():
        r = rng({"d": date, "yoy": yoyDate, "z": reg})
        cur = month_throughput_ton(year, month, reg, r)
        data.append({
            "zoneName": reg, "date": date,
            "throughput": cur,
            "yoyRate": round(r.uniform(2.0, 11.0), 2),
            "shareRatio": round(w * 100, 1)
        })
    return ok(data)

# [NO_PROD_DATA]
@app.get("/api/gateway/getContributionByCargoCategoryName")
async def get_contrib_by_cargo(request: Request, date: str = None, statisticType: int = 0, contributionType: str = None):
    check_token(request, T["contrib_by_cargo"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "st": statisticType})
    cargo_list = ["铁矿石", "煤炭", "集装箱", "商品车", "油品", "散杂货"]
    base = month_throughput_ton(year, month, None, r)
    return ok([{
        "cargoCategoryName": c, "statisticType": statisticType,
        "contribution": round(base * r.uniform(0.05, 0.25), 1),
        "contributionRate": round(r.uniform(5, 30), 2),
        "strategicClientCount": r.randint(2, 8)
    } for c in cargo_list])

# [NO_PROD_DATA]
@app.get("/api/gateway/getClientContributionOrder")
async def get_client_contrib_order(request: Request, date: str = None, statisticType: int = 0, contributionType: str = None):
    check_token(request, T["contrib_order"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "st": statisticType})
    base = month_throughput_ton(year, month, None, r)
    clients = r.choices(STRATEGIC_CLIENTS, k=10)
    shares = sorted([r.uniform(3, 18) for _ in clients], reverse=True)
    total_s = sum(shares)
    return ok([{
        "rank": i + 1, "clientName": c,
        "throughput": round(base * s / total_s, 1),
        "contributionRate": round(s / total_s * 100, 2),
        "statisticType": statisticType,
        "yoyRate": round(r.uniform(-5.0, 15.0), 2)
    } for i, (c, s) in enumerate(zip(clients, shares))])

# [NO_PROD_DATA]
@app.get("/api/gateway/getStrategicCustomerRevenue")
async def get_strategic_rev(request: Request, curDate: str = "2026-03", clientName: str = None, contributionValue: str = None, statisticType: str = None, yearDate: str = None):
    check_token(request, T["strategic_rev"])
    r = rng({"d": curDate, "c": clientName})
    clients = [clientName] if clientName else r.choices(STRATEGIC_CLIENTS, k=8)
    revs = sorted([r.uniform(500, 5000) for _ in clients], reverse=True)
    total = sum(revs)
    return ok([{
        "clientName": c, "curDate": curDate,
        "revenue": round(rev, 1),
        "revenueShare": round(rev / total * 100, 2),
        "yoyRate": round(r.uniform(2.0, 15.0), 2),
        "unit": "万元"
    } for c, rev in zip(clients, revs)])

# [PROD_DATA]
@app.get("/api/gateway/getStrategicCustomerThroughput")
async def get_strategic_tp(request: Request, curDate: str = "2026-03", clientName: str = None, cargoCategoryName: str = None, statisticType: str = None, yearDate: str = None):
    # 生产对齐: 字段对齐：{clientName, ttlNum, cargoCategoryName, ttlDate}
    check_token(request, T["strategic_tp"])
    CARGO_CATS = ["集装箱", "散杂货", "油化品", "滚装"]
    dates = [curDate] if not yearDate else [curDate, yearDate]
    clients = [clientName] if clientName else STRATEGIC_CLIENTS[:10]
    cats = [cargoCategoryName] if cargoCategoryName else CARGO_CATS
    data = []
    for dt in dates:
        for cl in clients:
            for cat in cats:
                r_item = rng({"cl": cl, "cat": cat, "dt": dt})
                tq = round(r_item.uniform(0, 500), 1)
                data.append({"clientName": cl, "ttlNum": str(tq), "cargoCategoryName": cat, "ttlDate": dt})
    return ok(data)


# [NO_PROD_DATA]
@app.get("/api/gateway/getContributionTrend")
async def get_contrib_trend(request: Request, year: str = "2026", lastYear: str = "2025", statisticType: str = None, contributionType: str = None):
    check_token(request, T["contrib_trend"])
    y1, y0 = int(year), int(lastYear)
    r = rng({"y": year, "ly": lastYear})
    return ok([{
        "month": f"{y1}-{m:02d}",
        "strategicContribution": round(month_throughput_ton(y1, m, None, r) * 0.65, 1),
        "prevYearContribution": round(month_throughput_ton(y0, m, None, r) * 0.62, 1),
        "contributionRate": round(r.uniform(58, 72), 2)
    } for m in range(1, 7)])


# [NO_PROD_DATA]
@app.get("/api/gateway/getCumulativeContributionTrend")
async def get_cumul_contrib(request: Request, startYear: int, endYear: int, contributionType: str):
    check_token(request, T["cumul_contrib"])
    r = rng({"sy": startYear, "ey": endYear})
    return ok([{
        "year": str(y),
        "cumulativeThroughput": round(sum(month_throughput_ton(y, m, None, r) for m in range(1,13)), 1),
        "strategicContribution": round(sum(month_throughput_ton(y, m, None, r) for m in range(1,13)) * 0.65, 1),
        "contributionRate": round(r.uniform(60, 70), 2)
    } for y in range(startYear, endYear+1)])

# ─────────────────────────────────────────────
# 投企管理
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/investCorpShareholdingProp")
async def invest_corp_prop(request: Request):
    check_token(request, T["invest_corp"])
    r = rng({"k": "invest_corp"})
    ranges = ["0-20%控股", "20-50%参股", "50%以上控股", "100%全资"]
    counts = [r.randint(8, 25) for _ in ranges]
    total = sum(counts)
    ratio_names = ["绝对控制线", "相对控制线", "安全控制线", "重大决议否决线",
        "临时股东会召开线", "重大决议基本否决线", "资产收益及选任管理者", "提案权", "代位诉讼权"]
    ratios = ["67%", "51%", "34%", "34%", "10%", "34%", "10%", "3%", "1%"]
    return ok([{
        "num": r.randint(10, 200),
        "ratio": ratios[i],
        "ratioName": rn,
    } for i, rn in enumerate(ratio_names)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getMeetingInfo")
async def get_meeting_info(request: Request, date: str):
    # 生产对齐: 生产当期返回空列表
    check_token(request, T["meeting_info"])
    return ok([])

# [PROD_DATA]
@app.get("/api/gateway/getMeetDetail")
async def get_meet_detail(request: Request, date: str, yianZt: str = None):
    # 生产对齐: 生产当期返回null
    check_token(request, T["meet_detail"])
    return ok(None)

# [PROD_DATA]
@app.get("/api/gateway/getNewEnterprise")
async def get_new_enterprise(request: Request, date: str):
    # 生产对齐: 生产当期返回空列表
    check_token(request, T["new_enterprise"])
    return ok([])

# [PROD_DATA]
@app.get("/api/gateway/getWithdrawalInfo")
async def get_withdrawal(request: Request, date: str):
    # 生产对齐: 生产当期返回空列表
    check_token(request, T["withdrawal"])
    return ok([])

# [PROD_DATA]
@app.get("/api/gateway/getBusinessExpirationInfo")
async def get_biz_expiry(request: Request, date: str):
    # 生产对齐: 生产当期返回空列表
    check_token(request, T["biz_expiry"])
    return ok([])

# [PROD_DATA]
@app.get("/api/gateway/getSupervisorIncidentInfo")
async def get_supervisor_change(request: Request, date: str):
    # 生产对齐: 生产当期返回空列表
    check_token(request, T["supervisor_change"])
    return ok([])

# ─────────────────────────────────────────────
# 资产管理域
# ─────────────────────────────────────────────

def asset_base(zone=None, r_obj=None):
    region_mult = {"大连港区":0.40,"营口港区":0.30,"丹东港区":0.18,"锦州港区":0.12}
    m = region_mult.get(zone, 1.0)
    base_count = 15000 * m
    base_orig = 250000.0 * m  # 万元
    base_net = base_orig * 0.65
    noise = r_obj.uniform(0.95, 1.05) if r_obj else 1.0
    return round(base_count * noise), round(base_orig * noise, 1), round(base_net * noise, 1)

# [PROD_DATA]
@app.get("/api/gateway/getTotalssets")
async def get_total_assets(request: Request, assetOwnerZone: str):
    # 生产对齐: 生产返回0值
    check_token(request, T["total_assets"])
    return ok([{"assetQty": 0.0, "realAssetQty": 0.0}])

# [PROD_DATA]
@app.get("/api/gateway/getAssetValue")
async def get_asset_value(request: Request, ownerZone: str):
    # 生产对齐: 生产返回null字段
    check_token(request, T["asset_value"])
    return ok([{
        "netlValue": None,
        "originalValue": None,
        "periodNetlValue": None,
        "periodOriginalValue": None,
    }])

# [PROD_DATA]
@app.get("/api/gateway/getMainAssetsInfo")
async def get_main_assets(request: Request, ownerZone: str):
    # 生产对齐: 生产返回空列表
    check_token(request, T["main_assets"])
    return ok([])

# [PROD_DATA]
@app.get("/api/gateway/getRealAssetsDistribution")
async def get_real_assets_dist(request: Request, ownerZone: str):
    # 生产对齐: 生产返回空列表
    check_token(request, T["real_asset_dist"])
    return ok([])

# [PROD_DATA]
@app.get("/api/gateway/getOriginalValueDistribution")
async def get_orig_val_dist(request: Request, ownerZone: str):
    # 生产对齐: 生产返回空列表
    check_token(request, T["orig_val_dist"])
    return ok([])

# [OFFLINE] @app.get("/api/gateway/getDistributionOfImportantAssetNetValueRanges")
# [OFFLINE] async def get_imp_asset_ranges(request: Request, ownerZone: str):
# [OFFLINE]     check_token(request, T["imp_asset_range"])
# [OFFLINE]     r = rng({"zone": ownerZone})
# [OFFLINE]     return ok({
# [OFFLINE]         "ownerZone": ownerZone or "全域",
# [OFFLINE]         "ranges": [
# [OFFLINE]             {"range": "1000万以下", "count": r.randint(200, 800), "totalNetValue": round(r.uniform(5000, 30000), 1)},
# [OFFLINE]             {"range": "1000-5000万", "count": r.randint(100, 300), "totalNetValue": round(r.uniform(20000, 80000), 1)},
# [OFFLINE]             {"range": "5000-1亿", "count": r.randint(50, 150), "totalNetValue": round(r.uniform(50000, 150000), 1)},
# [OFFLINE]             {"range": "1亿以上", "count": r.randint(10, 50), "totalNetValue": round(r.uniform(100000, 500000), 1)}
# [OFFLINE]         ]
# [OFFLINE]     })

# [OFFLINE] @app.get("/api/gateway/getFinancialAssetsDistribution")
# [OFFLINE] async def get_fin_assets_dist(request: Request):
# [OFFLINE]     check_token(request, T["fin_asset_dist"])
# [OFFLINE]     r = rng({"k": "fin_asset"})
# [OFFLINE]     types = ["长期股权投资", "应收账款", "短期借款", "债券投资", "基金"]
# [OFFLINE]     counts = [r.randint(10, 80) for _ in types]
# [OFFLINE]     return ok([{"assetType": t, "count": c, "ratio": round(c/sum(counts)*100,1)}
# [OFFLINE]                for t, c in zip(types, counts)])

# [OFFLINE] @app.get("/api/gateway/getFinancialAssetsNetValueDistribution")
# [OFFLINE] async def get_fin_assets_net(request: Request):
# [OFFLINE]     check_token(request, T["fin_asset_net"])
# [OFFLINE]     r = rng({"k": "fin_net"})
# [OFFLINE]     types = ["长期股权投资", "应收账款", "短期借款", "债券投资", "基金"]
# [OFFLINE]     return ok([{
# [OFFLINE]         "assetType": t,
# [OFFLINE]         "netValue": round(r.uniform(5000, 50000), 1),
# [OFFLINE]         "ratio": round(r.uniform(5, 40), 1),
# [OFFLINE]         "unit": "万元"
# [OFFLINE]     } for t in types])

# [OFFLINE] @app.get("/api/gateway/getEquipmentFacilityStateDistribution")
# [OFFLINE] async def get_equip_state(request: Request, ownerZone: str):
# [OFFLINE]     check_token(request, T["equip_state"])
# [OFFLINE]     r = rng({"zone": ownerZone})
# [OFFLINE]     states = ["正常使用", "维修中", "计划维修", "闲置", "报废待处理"]
# [OFFLINE]     counts = [r.randint(20, 500) for _ in states]
# [OFFLINE]     total = sum(counts)
# [OFFLINE]     return ok({
# [OFFLINE]         "ownerZone": ownerZone or "全域",
# [OFFLINE]         "distribution": [
# [OFFLINE]             {"status": s, "count": c, "ratio": round(c/total*100, 1)}
# [OFFLINE]             for s, c in zip(states, counts)
# [OFFLINE]         ]
# [OFFLINE]     })

# [NO_PROD_DATA]
@app.get("/api/gateway/getHistoricalTrends")
async def get_hist_trends(request: Request, ownerZone: str):
    check_token(request, T["hist_trend"])
    r = rng({"zone": ownerZone})
    return ok([{
        "year": str(y),
        "totalCount": r.randint(10000, 20000),
        "totalOriginalValue": round(r.uniform(200000, 400000), 1),
        "totalNetValue": round(r.uniform(130000, 280000), 1),
        "newAdded": r.randint(200, 800),
        "scrapped": r.randint(50, 300)
    } for y in range(2022, 2027)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getRealAssetQty")
async def get_real_asset_qty(request: Request, ownerZone: str):
    check_token(request, T["real_asset_qty"])
    r = rng({"zone": ownerZone})
    return ok({
        "ownerZone": ownerZone or "全域",
        "newAddedThisYear": r.randint(200, 600),
        "newAddedValue": round(r.uniform(5000, 30000), 1),
        "yoyCountChange": r.randint(-50, 150),
        "unit": "件/万元"
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getMothballingRealAssetQty")
async def get_mothball_qty(request: Request, ownerZone: str):
    check_token(request, T["mothball_qty"])
    r = rng({"zone": ownerZone})
    return ok({
        "ownerZone": ownerZone or "全域",
        "scrappedThisYear": r.randint(80, 250),
        "scrappedValue": round(r.uniform(2000, 15000), 1),
        "mothballedThisYear": r.randint(20, 80),
        "mothballedValue": round(r.uniform(500, 5000), 1)
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getTrendNewAssets")
async def get_trend_new(request: Request, ownerZone: str):
    check_token(request, T["trend_new"])
    r = rng({"zone": ownerZone})
    return ok([{
        "year": str(y), "newCount": r.randint(150, 500),
        "newValue": round(r.uniform(3000, 20000), 1)
    } for y in range(2022, 2027)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getOriginalQuantity")
async def get_orig_qty(request: Request, ownerZone: str, dateYear: str):
    check_token(request, T["orig_qty"])
    r = rng({"zone": ownerZone, "y": dateYear})
    return ok({
        "ownerZone": ownerZone or "全域", "dateYear": dateYear,
        "newAddedCount": r.randint(200, 600),
        "newAddedOriginalValue": round(r.uniform(5000, 30000), 1),
        "unit": "件/万元"
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getTrendScrappedAssets")
async def get_trend_scrap(request: Request, ownerZone: str):
    check_token(request, T["trend_scrap"])
    r = rng({"zone": ownerZone})
    return ok([{
        "year": str(y), "scrappedCount": r.randint(80, 250),
        "scrappedValue": round(r.uniform(1000, 8000), 1)
    } for y in range(2022, 2027)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getOriginalValueScrappedQuantity")
async def get_scrap_qty(request: Request, ownerZone: str, dateYear: str):
    check_token(request, T["scrap_qty"])
    r = rng({"zone": ownerZone, "y": dateYear})
    return ok({
        "ownerZone": ownerZone or "全域", "dateYear": dateYear,
        "scrappedCount": r.randint(80, 200),
        "scrappedOriginalValue": round(r.uniform(2000, 12000), 1)
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getNewAssetTransparentAnalysis")
async def get_new_asset_trans(request: Request, ownerZone: str, dateYear: str, asseTypeName: str):
    check_token(request, T["new_asset_trans"])
    r = rng({"zone": ownerZone, "y": dateYear})
    return ok([{
        "companyName": cmp,
        "newCount": r.randint(20, 100),
        "newOriginalValue": round(r.uniform(500, 5000), 1),
        "mainCategory": r.choice(ASSET_TYPES)
    } for cmp in COMPANIES])

# [NO_PROD_DATA]
@app.get("/api/gateway/getScrapAssetTransmitAnalysis")
async def get_scrap_trans(request: Request, ownerZone: str, dateYear: str, asseTypeName: str):
    check_token(request, T["scrap_asset_trans"])
    r = rng({"zone": ownerZone, "y": dateYear})
    return ok([{
        "companyName": cmp,
        "scrappedCount": r.randint(5, 50),
        "scrappedOriginalValue": round(r.uniform(100, 2000), 1)
    } for cmp in COMPANIES])

# [PROD_DATA]
@app.get("/api/gateway/getPhysicalAssets")
async def get_physical_assets(request: Request, dateYear: str):
    check_token(request, T["phys_assets"])
    r = rng({"y": dateYear})
    total_count = r.randint(12000, 18000)
    orig = round(r.uniform(280000, 380000), 1)
    type_names = ["实物资产数", "资产原值", "资产净值"]
    return ok([{
        "dateYear": float(y),
        "num": round(r.uniform(50000, 100000), 1),
        "typeName": tn,
    } for y in [year, year - 1] for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getRegionalAnalysis")
async def get_regional_analysis(request: Request, dateYear: str = "2026"):
    check_token(request, T["regional_analysis"])
    r = rng({"y": dateYear})
    type_names = ["实物资产数", "资产原值"]
    return ok([{
        "num": round(r.uniform(1000, 20000), 1),
        "ownerZone": reg,
        "typeName": tn,
    } for reg in REGIONS_SHORT + ["综合事业部"] for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getCategoryAnalysis")
async def get_category_analysis(request: Request, dateYear: str):
    check_token(request, T["category_analysis"])
    r = rng({"y": dateYear})
    asset_types = ["设备", "设施", "房屋", "土地海域", "林木", "在建工程"]
    type_names = ["实物资产数", "资产原值", "资产净值", "面积"]
    return ok([{
        "assetTypeName": at,
        "num": round(r.uniform(100, 20000), 1),
        "typeName": tn,
    } for at in asset_types for tn in type_names])

# [NO_PROD_DATA]
@app.get("/api/gateway/getRegionalAnalysisTransparentTransmission")
async def get_region_trans(request: Request, dateYear: str, ownerZone: str):
    check_token(request, T["region_trans"])
    r = rng({"y": dateYear, "z": ownerZone})
    return ok([{
        "ownerZone": ownerZone or "全域",
        "assetTypeName": at,
        "count": r.randint(100, 1500),
        "originalValue": round(r.uniform(5000, 50000), 1),
        "netValue": round(r.uniform(3000, 35000), 1)
    } for at in ASSET_TYPES])

# [PROD_DATA]
@app.get("/api/gateway/getCategoryAnalysisTransparentTransmission")
async def get_category_trans(request: Request, dateYear: str, assetTypeName: str):
    check_token(request, T["category_trans"])
    r = rng({"y": dateYear, "at": assetTypeName})
    type_names = ["实物资产数", "资产原值", "资产净值"]
    return ok([{
        "num": round(r.uniform(1, 5000), 1),
        "ownerUnitName": cmp,
        "typeName": tn,
    } for cmp in COMPANIES for tn in type_names])

# [NO_PROD_DATA]
@app.get("/api/gateway/getHousingAssertAnalysisTransparentTransmission")
async def get_housing_trans(request: Request, dateYear: str, ownerZone: str = None):
    check_token(request, T["housing_trans"])
    r = rng({"y": dateYear, "z": ownerZone})
    zones = [ownerZone] if ownerZone else REGIONS
    return ok([{
        "ownerZone": z, "buildingType": r.choice(["办公用房","生产用房","仓储用房","辅助用房"]),
        "count": r.randint(20, 150),
        "area": round(r.uniform(1000, 30000), 1),
        "originalValue": round(r.uniform(2000, 20000), 1),
        "netValue": round(r.uniform(1500, 15000), 1)
    } for z in zones for _ in range(2)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getImportantAssetRegionAnalysisPenetrationPage")
async def get_imp_region_pen(request: Request, dateYear: str, ownerZone: str = "全港", assetTypeName: str = None):
    check_token(request, T["imp_region_pen"])
    r = rng({"y": dateYear, "z": ownerZone})
    zones = [ownerZone] if ownerZone and ownerZone != "全港" else REGIONS_SHORT
    return ok([{
        "ownerZone": z, "assetCategory": r.choice(["设备", "设施", "土地海域"]),
        "count": r.randint(50, 500),
        "netValue": round(r.uniform(5000, 50000), 1)
    } for z in zones])

# [NO_PROD_DATA]
@app.get("/api/gateway/getEquipmentAnalysisTransparentTransmission")
async def get_equip_trans_all(request: Request, dateYear: str, assetStatus: str = None, assetTypeName: str = "设备"):
    check_token(request, T["equip_trans1"])
    r = rng({"y": dateYear, "st": assetStatus})
    equip_types = ["门机", "岸桥", "轮胎吊", "堆高机", "叉车", "牵引车", "输送机"]
    return ok([{
        "equipmentType": et,
        "status": assetStatus or r.choice(["正常", "维修", "闲置"]),
        "count": r.randint(5, 80),
        "totalNetValue": round(r.uniform(500, 10000), 1)
    } for et in equip_types])


# [NO_PROD_DATA]
@app.get("/api/gateway/getEquipmentAnalysisTransparentTransmissionByFirst")
async def get_equip_trans2(request: Request, dateYear: str, assetStatus: str = None,
                            assetTypeName: str = "设备", firstLevelClassName: str = "装卸机械"):
    check_token(request, T["equip_trans2"])
    r = rng({"y": dateYear, "st": assetStatus, "at": assetTypeName})
    sub_types = ["50吨门机","100吨门机","双箱岸桥","单箱岸桥","轮胎吊16T","轮胎吊20T"]
    return ok([{
        "equipmentSubType": st, "parentType": assetTypeName,
        "status": assetStatus or "正常",
        "count": r.randint(2, 30),
        "avgAge": round(r.uniform(3, 18), 1),
        "netValue": round(r.uniform(200, 5000), 1)
    } for st in r.choices(sub_types, k=4)])

# [PROD_DATA]
@app.get("/api/gateway/getLandMaritimeAnalysisTransparentTransmission")
async def get_land_sea_trans(request: Request, dateYear: str, ownerZone: str = None):
    check_token(request, T["land_sea_trans"])
    r = rng({"y": dateYear, "z": ownerZone})
    zones = [ownerZone] if ownerZone else REGIONS
    type_names = ["实物资产数", "资产原值", "资产净值"]
    return ok([{
        "num": round(r.uniform(1, 5000), 1),
        "ownerUnitName": cmp,
        "typeName": tn,
    } for cmp in COMPANIES for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentFacilityAnalysisYoy")
async def get_equip_yoy(request: Request, dateYear: str):
    check_token(request, T["equip_yoy"])
    r = rng({"y": dateYear})
    y1, y0 = int(dateYear), int(dateYear)-1
    type_names = ["实物资产数", "资产原值", "资产净值"]
    return ok([{
        "dateYear": float(y),
        "num": round(r.uniform(5000, 30000), 1),
        "typeName": tn,
    } for y in [year, year - 1] for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentFacilityAnalysis")
async def get_equip_cat(request: Request, dateYear: str, type: str):
    check_token(request, T["equip_cat"])
    r = rng({"y": dateYear, "t": type})
    categories = {
        "1": ["装卸设备","运输设备","起重设备","输送设备","特种设备"],
        "2": ["道路设施","管道设施","电气设施","通信设施","安防设施"]
    }.get(type, ["其他"])
    equip_types = ["锅炉设备", "通信设备", "仪器仪表", "电子设备", "交通运输设备",
        "动力设备", "专用机械", "通用机械", "工具器具", "其他设备"]
    type_names = ["实物资产数", "资产原值", "资产净值", "面积", "报废数", "处置数"]
    return ok([{
        "assetTypeName": et,
        "num": round(r.uniform(1, 5000), 1),
        "typeName": tn,
    } for et in equip_types for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentFacilityStatusAnalysis")
async def get_equip_status_cat(request: Request, dateYear: str, type: str):
    check_token(request, T["equip_status_cat"])
    r = rng({"y": dateYear, "t": type})
    statuses = ["正常使用","维修中","计划检修","超期服役","闲置","报废申请中"]
    counts = [r.randint(20, 500) for _ in statuses]
    total = sum(counts)
    statuses = ["报废", "封存", "启用", "在建", "停用", "闲置"]
    type_names = ["实物资产数", "资产原值", "资产净值", "面积"]
    return ok([{
        "assetStatus": st,
        "num": round(r.uniform(1, 5000), 1),
        "typeName": tn,
    } for st in statuses for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentFacilityRegionalAnalysis")
async def get_equip_regional(request: Request, dateYear: str, type: str):
    check_token(request, T["equip_regional"])
    r = rng({"y": dateYear, "t": type})
    type_names = ["实物资产数", "资产原值"]
    return ok([{
        "num": round(r.uniform(500, 10000), 1),
        "ownerZone": reg,
        "typeName": tn,
    } for reg in REGIONS_SHORT + ["综合事业部"] for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentFacilityWorthAnalysis")
async def get_equip_worth(request: Request, dateYear: str, type: str):
    check_token(request, T["equip_worth"])
    r = rng({"y": dateYear, "t": type})
    ranges = ["500万以下","500-2000万","2000-5000万","5000-1亿","1亿以上"]
    ranges = ["0-50", "50-100", "100-500", "500-1000", "1000以上"]
    type_names = ["资产净值", "实物资产数"]
    return ok([{
        "num": r.randint(1, 500),
        "rate": rng_val,
        "typeName": tn,
    } for rng_val in ranges for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getHousingAnalysisYoy")
async def get_housing_yoy(request: Request, dateYear: str):
    check_token(request, T["housing_yoy"])
    r = rng({"y": dateYear})
    type_names = ["面积", "实物资产数", "资产原值", "资产净值"]
    return ok([{
        "dateYear": float(y),
        "num": round(r.uniform(0, 50000), 1),
        "typeName": tn,
    } for y in [year, year - 1] for tn in type_names])

# [NO_PROD_DATA]
@app.get("/api/gateway/getHousingRegionalAnalysis")
async def get_housing_regional(request: Request, dateYear: str):
    check_token(request, T["housing_regional"])
    r = rng({"y": dateYear})
    return ok([{
        "ownerZone": z,
        "count": r.randint(80, 400),
        "area": round(r.uniform(30000, 200000), 1),
        "netValue": round(r.uniform(3000, 20000), 1)
    } for z in REGIONS])

# [NO_PROD_DATA]
@app.get("/api/gateway/getHousingWorthAnalysis")
async def get_housing_worth(request: Request, dateYear: str):
    check_token(request, T["housing_worth"])
    r = rng({"y": dateYear})
    ranges = ["500万以下","500-1000万","1000-3000万","3000万以上"]
    return ok([{
        "netValueRange": rg, "count": r.randint(20, 200),
        "totalNetValue": round(r.uniform(1000, 20000), 1)
    } for rg in ranges])

# [PROD_DATA]
@app.get("/api/gateway/getLandMaritimeAnalysisYoy")
async def get_land_yoy(request: Request, dateYear: str):
    check_token(request, T["land_yoy"])
    r = rng({"y": dateYear})
    type_names = ["资产原值", "资产净值", "实物资产数"]
    return ok([{
        "dateYear": float(y),
        "num": round(r.uniform(100000, 800000000), 1),
        "typeName": tn,
    } for y in [year, year - 1] for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getLandMaritimeRegionalAnalysis")
async def get_land_regional(request: Request, dateYear: str):
    check_token(request, T["land_regional"])
    r = rng({"y": dateYear})
    type_names = ["实物资产数", "资产原值"]
    return ok([{
        "num": round(r.uniform(1, 500), 1),
        "ownerZone": reg,
        "typeName": tn,
    } for reg in REGIONS_SHORT + ["综合事业部"] for tn in type_names[:1]])

# [PROD_DATA]
@app.get("/api/gateway/getLandMaritimeWorthAnalysis")
async def get_land_worth(request: Request, dateYear: str):
    check_token(request, T["land_worth"])
    r = rng({"y": dateYear})
    type_names = ["资产净值", "实物资产数"]
    return ok([{
        "num": r.randint(1, 50),
        "rate": rng_val,
        "typeName": tn,
    } for rng_val in ["0-50", "50-100"] for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getImportAssertAnalysisList")
async def get_asset_list(request: Request, dateYear: str,
                          portCode: str = None, assetTypeId: str = None,
                          assetTypeName: str = None, ownerZone: str = None,
                          pageNo: int = 1, pageSize: int = 20):
    check_token(request, T["asset_list"])
    r = rng({"pc": portCode, "at": assetTypeId, "p": pageNo})
    asset_names = ["50T门机","岸桥A1","RTG-01","叉车组","皮带机","配电室","生产楼A"]
    return ok([{
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
    } for i in range(20)])

# [NO_PROD_DATA]
@app.get("/api/gateway/getImportAssetWorthAnalysisByOwnerZone")
async def get_asset_worth_zone(request: Request, dateYear: str, type: str, minNum: float, maxNum: float, typeName: str):
    check_token(request, T["asset_worth_zone"])
    r = rng({"y": dateYear, "t": type})
    return ok([{
        "ownerZone": z, "assetType": type,
        "count": r.randint(100, 1000),
        "netValue": round(r.uniform(5000, 80000), 1),
        "shareRatio": 0
    } for z in REGIONS])

# [NO_PROD_DATA]
@app.get("/api/gateway/getImportAssetWorthAnalysisByCmpName")
async def get_asset_worth_cmp(request: Request, dateYear: str, type: str, minNum: float, maxNum: float, ownerZone: str, typeName: str):
    check_token(request, T["asset_worth_cmp"])
    r = rng({"y": dateYear, "t": type})
    return ok([{
        "companyName": cmp, "assetType": type,
        "count": r.randint(50, 500),
        "netValue": round(r.uniform(2000, 50000), 1)
    } for cmp in COMPANIES])

# ─────────────────────────────────────────────
# 投资管理域（31个API）
# ─────────────────────────────────────────────

def invest_base(year: int, zone: str = None) -> float:
    base = 120000.0  # 万元
    zone_w = {"大连":0.35,"营口":0.28,"丹东":0.20,"锦州":0.12,"绥中":0.05}.get(zone, 1.0)
    growth = 1.05 ** (year - 2024)
    return base * zone_w * growth if zone else base * growth

# [PROD_DATA]
@app.get("/api/gateway/getInvestPlanTypeProjectList")
async def get_invest_plan_type(request: Request, ownerLgZoneName: str = None, currYear: str = "2026"):
    check_token(request, T["invest_plan_type"])
    r = rng({"z": ownerLgZoneName, "y": currYear})
    year = int(currYear)
    base = invest_base(year, ownerLgZoneName)
    return ok([{
        "engineeringQty": r.randint(0, 5),
        "importantQty": r.randint(0, 5),
        "investProjectType": "仓库码头",
        "planInvestAmt": round(r.uniform(500, 5000), 1),
        "planPayAmt": round(r.uniform(500, 5000), 1),
        "total": r.randint(1, 20),
    }])

# [NO_PROD_DATA]
@app.get("/api/gateway/getPlanProgressByMonth")
async def get_plan_progress(request: Request, ownerLgZoneName: str = None,
                              startMonth: str = "2026-01", endMonth: str = None):
    check_token(request, T["plan_progress"])
    year = int(startMonth[:4])
    r = rng({"z": ownerLgZoneName, "s": startMonth})
    base = invest_base(year, ownerLgZoneName)
    monthly_plan = base / 12
    series = []
    cumul_plan = 0; cumul_actual = 0
    for m in range(1, 4):
        plan = monthly_plan * SEASONAL[m-1]
        actual = plan * r.uniform(0.85, 1.10)
        cumul_plan += plan; cumul_actual += actual
        series.append({
            "month": f"{year}-{m:02d}",
            "plannedAmount": round(plan, 1),
            "actualAmount": round(actual, 1),
            "cumulativePlan": round(cumul_plan, 1),
            "cumulativeActual": round(cumul_actual, 1),
            "progressRatio": round(cumul_actual/cumul_plan*100, 2)
        })
    return ok(series)

# [PROD_DATA]
@app.get("/api/gateway/planInvestAndPayYoy")
async def plan_invest_yoy(request: Request, currYear: int = 2026, preYear: int = 2025, ownerLgZoneName: str = None):
    # 生产对齐: 2026年数据很少（仅1个项目），2025年金额巨大
    check_token(request, T["plan_yoy"])
    r = rng({"cy": currYear, "py": preYear})
    # 生产数据：2026年仅2000万，2025年全年约60万
    return ok([
        {"dateYear": currYear, "planInvestAmt": round(r.uniform(1000, 5000), 1), "planPayAmt": round(r.uniform(1000, 5000), 1)},
        {"dateYear": preYear,  "planInvestAmt": round(r.uniform(500000, 700000), 1), "planPayAmt": round(r.uniform(350000, 450000), 1)},
    ])

# [PROD_DATA]
@app.get("/api/gateway/getFinishProgressAndDeliveryRate")
async def get_finish_delivery(request: Request, ownerLgZoneName: str = None, currYear: str = "2026"):
    # 生产对齐: 2026年数据极少，大部分为0
    check_token(request, T["finish_delivery"])
    return ok([{
        "captProjectQty": 1,
        "deliveryCaptProjectQty": 0,
        "planInvestAmt": 0.0,
        "planPayAmt": 0.0,
        "realFinishInvestAmt": 0,
        "realFinishPayAmt": 0.0,
    }])

# [PROD_DATA]
@app.get("/api/gateway/getInvestPlanByYear")
async def get_invest_by_year(request: Request, ownerLgZoneName: str = None):
    check_token(request, T["invest_by_year"])
    year = 2026
    r = rng({"z": ownerLgZoneName})
    return ok([{
        "captPlanPayAmt": round(r.uniform(0, 100000), 1),
        "dateYear": y,
        "finishInvestAmt": round(r.uniform(50000, 150000), 0),
        "planInvestAmt": round(r.uniform(80000, 200000), 1),
        "realFinishPayAmt": round(r.uniform(0, 100000), 1),
    } for y in range(year - 6, year + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getCostProjectFinishByYear")
async def get_cost_proj_year(request: Request, ownerLgZoneName: str = None):
    check_token(request, T["cost_proj_year"])
    year = 2026
    r = rng({"z": ownerLgZoneName})
    return ok([{
        "costApplyInvestAmt": round(r.uniform(30000, 60000), 1),
        "dateYear": y,
        "projectQty": r.randint(800, 1500),
        "realFinishPayAmt": round(r.uniform(2000000, 6000000), 1),
    } for y in [year, year - 1]])

# [PROD_DATA]
@app.get("/api/gateway/getCostProjectYoyList")
async def get_cost_proj_yoy(request: Request, currYear: int = 2026, preYear: int = 2025):
    check_token(request, T["cost_proj_yoy"])
    r = rng({"cy": currYear, "py": preYear})
    return ok([{
        "currYear": y,
        "deliveryRate": round(r.uniform(0, 100), 1),
        "finishPayAmt": round(r.uniform(2000000, 6000000), 1),
        "investAmt": round(r.uniform(30000, 60000), 1),
        "projectQty": r.randint(800, 1500),
    } for y in [currYear, preYear]])

# [PROD_DATA]
@app.get("/api/gateway/getCostProjectQtyList")
async def get_cost_proj_qty(request: Request, currYear: int = 2026):
    check_token(request, T["cost_proj_qty"])
    r = rng({"cy": currYear})
    categories = ["设备维修","设施改造","安全整改","环保投入","信息化建设"]
    counts = [r.randint(5, 20) for _ in categories]
    total = sum(counts)
    return ok([{
        "ownerLgZoneName": reg,
        "projectQty": float(r.randint(10, 300)),
    } for reg in REGIONS_LG])

# [PROD_DATA]
@app.get("/api/gateway/getCostProjectAmtByOwnerLgZoneName")
async def get_cost_amt_zone(request: Request, currYear: int = 2026):
    check_token(request, T["cost_amt_zone"])
    r = rng({"cy": currYear})
    return ok([{
        "finishPayAmt": round(r.uniform(10000, 5000000), 1),
        "investAmt": round(r.uniform(1000, 50000), 1),
        "ownerLgZoneName": reg,
    } for reg in REGIONS_LG])

# [PROD_DATA]
@app.get("/api/gateway/getCostProjectCurrentStageQtyList")
async def get_cost_stage(request: Request, currYear: int = 2026, ownerLgZoneName: str = None):
    check_token(request, T["cost_stage"])
    r = rng({"cy": currYear, "z": ownerLgZoneName})
    stages = ["立项审批","招标阶段","施工中","竣工验收","结算审计","已完结"]
    stages = ["配置", "实施", "验收", "完工"]
    return ok([{
        "ownerLgZoneName": reg,
        "projectCurrentStage": st,
        "projectQty": r.randint(10, 300),
    } for reg in REGIONS_LG[:5] for st in stages[:1]])

# [PROD_DATA]
@app.get("/api/gateway/getCostProjectQtyByProjectCmp")
async def get_cost_cmp(request: Request, dateYear: str = "2026", zoneName: str = None):
    check_token(request, T["cost_cmp"])
    r = rng({"y": dateYear, "z": zoneName})
    return ok([{
        "finishPayAmt": round(r.uniform(0, 100000), 1),
        "investAmt": round(r.uniform(0, 5000), 1),
        "projectCmp": cmp,
        "projectQty": r.randint(1, 50),
    } for cmp in COMPANIES])

# [PROD_DATA]
@app.get("/api/gateway/getInvestAmtList")
async def get_invest_amt_list(request: Request, dateYear: str,
                               projectCmp: str = None, projectName: str = None,
                               projectNo: str = None, adminName: str = None, currentStage: str = None,
                               zoneName: str = None, pageNo: int = 1, pageSize: int = 20):
    check_token(request, T["invest_amt_list"])
    r = rng({"pc": projectCmp, "pn": projectName, "p": pageNo})
    return ok([{
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
    } for i in range(20)])

# [PROD_DATA]
@app.get("/api/gateway/getOutOfPlanFinishProgressList")
async def get_oop_finish(request: Request, dateYear: str = None):
    check_token(request, T["oop_finish"])
    r = rng({"y": dateYear})
    year = int(dateYear) if dateYear else 2026
    return ok([{
        "finishInvestAmt": round(r.uniform(100000, 300000), 1),
        "finishPayAmt": round(r.uniform(50000, 150000), 1),
        "planInvestAmt": round(r.uniform(200000, 500000), 1),
        "planPayAmt": round(r.uniform(100000, 300000), 1),
    }])

# [PROD_DATA]
@app.get("/api/gateway/getOutOfPlanProjectQtyYoy")
async def get_oop_yoy(request: Request, currYear: int = 2026, preYear: int = 2025):
    # 生产对齐: 字段：{dateYear, projectQty, projectDeliveryRate}
    check_token(request, T["oop_yoy"])
    r = rng({"cy": currYear, "py": preYear})
    return ok([
        {"dateYear": preYear,  "projectQty": r.randint(30, 60), "projectDeliveryRate": round(r.uniform(0, 50), 1)},
        {"dateYear": currYear, "projectQty": r.randint(1, 5),   "projectDeliveryRate": 0.0},
    ])

# [PROD_DATA]
@app.get("/api/gateway/getOutOfPlanProjectInvestFinishList")
async def get_oop_invest_5y(request: Request):
    check_token(request, T["oop_invest_5y"])
    r = rng({"k": "oop5y"})
    cur_year = 2026
    return ok([{
        "dateYear": y,
        "finishInvestAmt": round(r.uniform(0, 200000), 1),
        "planInvestAmt": round(r.uniform(5000, 50000), 1),
    } for y in range(cur_year - 4, cur_year + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getOutOfPlanProjectPayFinishList")
async def get_oop_pay_5y(request: Request):
    check_token(request, T["oop_pay_5y"])
    r = rng({"k": "oop_pay"})
    cur_year = 2026
    return ok([{
        "dateYear": y,
        "finishPayAmt": round(r.uniform(0, 200000), 1),
        "planPayAmt": round(r.uniform(5000, 50000), 1),
    } for y in range(cur_year - 4, cur_year + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getPlanFinishByZone")
async def get_plan_zone(request: Request, currYear: str = "2026"):
    check_token(request, T["plan_zone"])
    r = rng({"y": currYear})
    year = int(currYear)
    return ok([{
        "finishInvestAmt": round(r.uniform(0, 200000), 1),
        "finishPayAmt": round(r.uniform(0, 100000), 1),
        "ownerLgZoneName": reg,
        "planInvestAmt": round(r.uniform(0, 300000), 1),
        "planPayAmt": round(r.uniform(0, 200000), 1),
    } for reg in REGIONS_LG[:5]])

# [PROD_DATA]
@app.get("/api/gateway/getPlanFinishByProjectType")
async def get_plan_type(request: Request):
    check_token(request, T["plan_type"])
    r = rng({"k": "plan_type"})
    year = 2026
    proj_types = ["行政办公", "仓库码头", "设备购置", "技术改造", "安全环保", "信息化", "其他"]
    return ok([{
        "finishInvestAmt": round(r.uniform(10000, 200000), 1),
        "finishPayAmt": round(r.uniform(10000, 100000), 1),
        "investProjectType": pt,
        "planInvestAmt": round(r.uniform(50000, 300000), 1),
        "planPayAmt": round(r.uniform(50000, 300000), 1),
    } for pt in proj_types])

# [PROD_DATA]
@app.get("/api/gateway/getPlanExcludedProjectPenetrationAnalysis")
async def get_oop_penetration(request: Request, ownerLgZoneName: str = None, investProjectType: str = None):
    check_token(request, T["oop_penetration"])
    r = rng({"z": ownerLgZoneName, "t": investProjectType})
    zones = [ownerLgZoneName] if ownerLgZoneName else INVEST_ZONES
    type_names = ["支付计划额", "投资计划额", "项目数"]
    return ok([{
        "projectCmp": cmp,
        "qty": round(r.uniform(0, 500), 1),
        "typeName": tn,
    } for cmp in COMPANIES for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getUnplannedProjectsInquiry")
async def get_oop_list(request: Request, dateYear: str = "2026", regionName: str = None,
                        pageNo: int = 1, pageSize: int = 20):
    check_token(request, T["oop_list"])
    r = rng({"y": dateYear, "reg": regionName, "p": pageNo})
    return ok([{
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
    } for i in range(20)])

# [PROD_DATA]
@app.get("/api/gateway/getCapitalApprovalAnalysisLimitInquiry")
async def get_capital_limit(request: Request, dateYear: str = "2026"):
    check_token(request, T["capital_limit"])
    r = rng({"y": dateYear})
    year = int(dateYear)
    base = invest_base(year) * 0.60
    type_names = ["当年实际完成支付额", "当年实际完成投资额", "当年计划支付额",
        "当年计划投资额", "当年资本项目批复投资额", "当年资本项目计划投资额"]
    return ok([{
        "num": round(r.uniform(0, 500000), 1),
        "typeName": tn,
    } for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getCapitalApprovalAnalysisProject")
async def get_capital_proj(request: Request, dateYear: str = "2026"):
    check_token(request, T["capital_proj"])
    r = rng({"y": dateYear})
    type_names = ["当年交付项目数", "资本项目总数", "当年完工项目数", "在建项目数"]
    return ok([{
        "num": round(r.uniform(0, 200), 0),
        "typeName": tn,
    } for tn in type_names])

# [NO_PROD_DATA]
@app.get("/api/gateway/getVisualProgressAnalysisAndStatistics")
async def get_visual_progress(request: Request, dateYear: str = "2026"):
    check_token(request, T["visual_progress"])
    r = rng({"y": dateYear})
    stages = ["前期准备","开工建设","主体施工","竣工验收","交付使用"]
    counts = [r.randint(2, 10) for _ in stages]
    return ok({
        "dateYear": dateYear,
        "totalCapitalProjects": sum(counts),
        "stageDistribution": [
            {"stage": s, "count": c, "ratio": round(c/sum(counts)*100, 1)}
            for s, c in zip(stages, counts)
        ]
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getCompletionStatus")
async def get_completion_status(request: Request, dateYear: str = "2026"):
    check_token(request, T["completion_status"])
    r = rng({"y": dateYear})
    year = int(dateYear)
    base = invest_base(year)
    return ok({
        "dateYear": dateYear,
        "planApprovedAmount": round(base, 1),
        "actualCompletedAmount": round(base * r.uniform(0.25, 0.35), 1),
        "completionRate": round(r.uniform(25, 35), 2),
        "completedProjects": r.randint(5, 15),
        "totalProjects": r.randint(50, 90),
        "projectCompletionRate": round(r.uniform(8, 18), 2)
    })

# [PROD_DATA]
@app.get("/api/gateway/getDeliveryRate")
async def get_delivery_rate(request: Request, dateYear: str = "2026"):
    # 生产对齐: 返回历史年份实际交付率，不含当年
    check_token(request, T["delivery_rate"])
    HIST_RATES = [(2020, 7.0), (2021, 15.0), (2022, 22.0), (2023, 38.0), (2024, 88.0)]
    return ok([{"dateYear": y, "rate": rate} for y, rate in HIST_RATES])

# [NO_PROD_DATA]
@app.get("/api/gateway/getNumberCapitalProjectsDelivered")
async def get_capital_delivered(request: Request, dateYear: str = "2026"):
    check_token(request, T["capital_delivered"])
    r = rng({"y": dateYear})
    return ok({
        "dateYear": dateYear,
        "deliveredCount": r.randint(5, 15),
        "deliveredValue": round(invest_base(int(dateYear))*0.60 * r.uniform(0.2, 0.35), 1),
        "targetCount": r.randint(15, 30),
        "deliveryRate": round(r.uniform(25, 50), 2)
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getNumberCapitalProjectsDeliveredZoneName")
async def get_capital_del_zone(request: Request, dateMonth: str = "2026-03"):
    check_token(request, T["capital_del_zone"])
    r = rng({"dm": dateMonth})
    return ok([{
        "ownerLgZoneName": z,
        "deliveredCount": r.randint(1, 5),
        "deliveredValue": round(r.uniform(1000, 10000), 1),
        "dateMonth": dateMonth
    } for z in INVEST_ZONES])

# [NO_PROD_DATA]
@app.get("/api/gateway/getRegionalInvestmentQuota")
async def get_regional_quota(request: Request, dateMonth: str = "2026-03"):
    check_token(request, T["regional_quota"])
    r = rng({"dm": dateMonth})
    year = int(dateMonth[:4])
    return ok([{
        "ownerLgZoneName": z,
        "approvedQuota": round(invest_base(year, z), 1),
        "usedQuota": round(invest_base(year, z) * r.uniform(0.25, 0.35), 1),
        "usageRate": round(r.uniform(25, 35), 2),
        "dateMonth": dateMonth
    } for z in INVEST_ZONES])

# [NO_PROD_DATA]
@app.get("/api/gateway/getNumberCapitalProjectsDeliveredPlanAnalysis")
async def get_plan_del_analysis(request: Request, dateMonth: str = "2026-03"):
    check_token(request, T["plan_del_analysis"])
    r = rng({"dm": dateMonth})
    return ok([{
        "planType": pt,
        "totalCount": r.randint(3, 12),
        "deliveredCount": r.randint(1, 6),
        "deliveryRate": round(r.uniform(20, 55), 2)
    } for pt in PROJECT_TYPES])

# [NO_PROD_DATA]
@app.get("/api/gateway/getTypeAnalysisInvestmentAmountQuery")
async def get_type_invest_amt(request: Request, dateMonth: str = "2026-03"):
    check_token(request, T["type_invest_amt"])
    r = rng({"dm": dateMonth})
    year = int(dateMonth[:4])
    return ok([{
        "projectType": pt,
        "approvedAmount": round(invest_base(year)*0.60/5 * r.uniform(0.5,1.5), 1),
        "completedAmount": round(invest_base(year)*0.15/5 * r.uniform(0.5,1.2), 1),
        "completionRate": round(r.uniform(20, 40), 2),
        "dateMonth": dateMonth
    } for pt in PROJECT_TYPES])

# [PROD_DATA]
@app.get("/api/gateway/getCapitalProjectsList")
async def get_capital_list(request: Request, projectName: str = None, investProjectType: str = None,
                            projectCurrentStage: str = None, investProjectStatus: str = None,
                            ownerDept: str = None, dateYear: str = None, dateMonth: str = None,
                            ownerLgZoneName: str = None, pageNo: int = 1, pageSize: int = 20):
    check_token(request, T["capital_list"])
    r = rng({"pn": projectName, "pt": investProjectType, "p": pageNo})
    year = dateYear or "2026"
    project_names = [
        "营口港集装箱码头扩建工程", "大连港散货码头改造项目",
        "锦州港油品管道建设", "丹东港RoRo泊位新建",
        "信息化综合管控平台建设", "港区智能理货系统",
        "岸电改造工程", "消防系统升级改造",
        "大连港防波堤加固工程", "营口港疏港铁路扩能"
    ]
    return ok([{
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
    } for i in range(20)])

# ─────────────────────────────────────────────
# 健康检查
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "港口司南 Mock API Server", "version": "1.0.0",
            "apiCount": 159, "dataRange": "2024-01 ~ 2026-06"}

@app.get("/api/health")
async def health():
    return {"status": "healthy", "timestamp": "2026-04-15T10:00:00+08:00"}


    import argparse
    parser = argparse.ArgumentParser(description="港口司南 Mock API Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    print(f"\n=== 港口司南 Mock API Server v1.0 ===")
    print(f"=== 监听: http://{args.host}:{args.port}  |  接口数: 160  |  文档: /docs ===\n")
    uvicorn.run("__main__:app", host=args.host, port=args.port, reload=args.reload, log_level="info")


# ─────────────────────────────────────────────
# 资产子屏（44个）+ 司南商务驾驶舱（16个）
# ─────────────────────────────────────────────

from fastapi import Request

# 设备类型常量
EQUIP_L1 = ["装卸设备", "运输设备", "起重设备", "输送设备", "特种设备"]
EQUIP_L2 = ["岸桥", "门机", "RTG轮胎吊", "RMG轨道吊", "叉车", "牵引车", "堆高机", "平板车"]
ZONES = REGIONS  # 复用港区常量

# ─────────────────────────────────────────────
# 资产子屏 — 设施运维展示大屏（含设备指标 / 利用率 / 完好率 / 台时效率）
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentIndicatorOperationQty")
async def get_equip_indicator_op_qty(request: Request, dateMonth: str, ownerZone: str = None, cmpName: str = None):
    check_token(request, T["equipment_indicator_operation_qty"])
    year, month, _ = parse_date(dateMonth)
    r = rng({"dm": dateMonth, "z": ownerZone})
    zones = [ownerZone] if ownerZone else ZONES
    class_names = ["专用机械", "交通运输设备", "动力设备", "工具器具",
        "电子设备", "仪器仪表", "通信设备", "通用机械", "集装箱专用设备", "油运设备"]
    return ok([{
        "firstLevelName": cn,
        "num": r.randint(100000, 20000000),
    } for cn in class_names])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentIndicatorUseCost")
async def get_equip_indicator_cost(request: Request, dateMonth: str, ownerZone: str = None, cmpName: str = None):
    check_token(request, T["equipment_indicator_use_cost"])
    r = rng({"dm": dateMonth, "z": ownerZone})
    zones = [ownerZone] if ownerZone else ZONES
    class_names = ["机车", "专用机械", "动力设备", "通用机械", "集装箱专用设备",
        "交通运输设备", "电子设备", "工具器具", "仪器仪表", "油运设备"]
    return ok([{
        "firstLevelName": cn,
        "num": round(r.uniform(100, 50000), 1),
    } for cn in class_names])

# [PROD_DATA]
@app.get("/api/gateway/getProductionEquipmentFaultNum")
async def get_equip_fault_num(request: Request, dateYear: str, ownerZone: str = None, cmpName: str = None):
    check_token(request, T["production_equipment_fault_num"])
    r = rng({"y": dateYear, "z": ownerZone})
    year = str(dateYear)[:4]
    zones = [ownerZone] if ownerZone else ZONES
    months_count = min(int(datetime.now().strftime("%m")), 12) if str(year) == "2026" else 12
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "num": rng({"mo": f"{year}-{m:02d}", "k": "fault"}).randint(500, 1500),
    } for m in range(1, months_count + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getProductionEquipmentStatistic")
async def get_prod_equip_statistic(request: Request, dateMonth: str, ownerZone: str = None):
    check_token(request, T["production_equipment_statistic"])
    r = rng({"dm": dateMonth, "z": ownerZone})
    zones = [ownerZone] if ownerZone else ZONES
    class_names = ["斗轮堆取料机", "岸桥", "场桥", "正面吊", "堆高机", "叉车",
        "门座式起重机", "桥式起重机", "龙门式起重机", "拖头", "拖轮", "汽车起重机",
        "皮带机", "螺旋卸船机", "链斗卸船机", "抓斗卸船机", "翻车机", "输油臂",
        "装船机", "卸船机", "机车", "流动机械", "工程技术船", "公铁车",
        "散货专用设备", "集装箱专用设备", "通用机械", "动力设备", "油运设备"]
    return ok([{
        "num": r.randint(1, 200),
        "secondLevelName": cn,
    } for cn in class_names[:r.randint(30, 39)]])

# [NO_PROD_DATA]
@app.get("/api/gateway/getProductionEquipmentServiceAgeDistribution")
async def get_equip_age_dist(request: Request, dateMonth: str, ownerZone: str = None, machineName: str = None):
    check_token(request, T["production_equipment_service_age_distribution"])
    r = rng({"dm": dateMonth, "z": ownerZone})
    age_ranges = ["0-5年", "5-10年", "10-15年", "15-20年", "20年以上"]
    counts = [r.randint(50, 300) for _ in age_ranges]
    total = sum(counts)
    return ok({
        "ownerZone": ownerZone or "全域", "dateMonth": dateMonth,
        "distribution": [{"ageRange": ar, "count": c, "ratio": round(c/total*100, 1)}
                         for ar, c in zip(age_ranges, counts)]
    })

# [PROD_DATA]
@app.get("/api/gateway/getOverviewQuery")
async def get_overview_query(request: Request, date: str, equipmentNo: str, ownerLgZoneName: str, cmpName: str, firstLevelClassName: str):
    # 生产对齐: 生产多数字段返回null
    check_token(request, T["overview_query"])
    type_names = ["作业台时", "机械作业量", "能源消耗", "材料费用",
        "完好台时", "非完好台时", "日历台时", "工作台时"]
    return ok([{
        "num": None,
        "typeName": tn,
    } for tn in type_names])

# [NO_PROD_DATA]
@app.get("/api/gateway/getSingleEquipmentIntegrityRate")
async def get_single_integrity(request: Request, equipmentNo: str):
    check_token(request, T["single_equipment_integrity_rate"])
    r = rng({"eq": equipmentNo})
    return ok({
        "equipmentNo": equipmentNo,
        "equipmentName": f"设备{equipmentNo}",
        "currentMonthRate": round(r.uniform(90.0, 99.5), 2),
        "yearAvgRate": round(r.uniform(88.0, 97.0), 2),
        "trend": [{"month": f"2026-{m:02d}", "rate": round(r.uniform(88, 99), 2)} for m in range(1, 4)],
        "unit": "%"
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getUnitHourEfficiency")
async def get_unit_hour_eff(request: Request, equipmentNo: str):
    check_token(request, T["unit_hour_efficiency"])
    r = rng({"eq": equipmentNo})
    return ok({
        "equipmentNo": equipmentNo,
        "currentMonthEfficiency": round(r.uniform(65.0, 115.0), 1),
        "yearAvgEfficiency": round(r.uniform(60.0, 110.0), 1),
        "trend": [{"month": f"2026-{m:02d}", "efficiency": round(r.uniform(60, 118), 1)} for m in range(1, 4)],
        "unit": "自然箱/小时"
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getUnitConsumption")
async def get_unit_consumption(request: Request, equipmentNo: str):
    check_token(request, T["unit_consumption"])
    r = rng({"eq": equipmentNo})
    return ok({
        "equipmentNo": equipmentNo,
        "currentMonthConsumption": round(r.uniform(0.8, 3.5), 2),
        "yearAvgConsumption": round(r.uniform(0.9, 3.2), 2),
        "fuelConsumption": round(r.uniform(0.3, 1.5), 2),
        "electricityConsumption": round(r.uniform(0.4, 2.0), 2),
        "trend": [{"month": f"2026-{m:02d}", "consumption": round(r.uniform(0.8, 3.5), 2)} for m in range(1, 4)],
        "unit": "kgce/自然箱"
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getSingleMachineUtilization")
async def get_single_utilization(request: Request, equipmentNo: str):
    check_token(request, T["single_machine_utilization"])
    r = rng({"eq": equipmentNo})
    return ok({
        "equipmentNo": equipmentNo,
        "currentMonthRate": round(r.uniform(50.0, 85.0), 2),
        "yearAvgRate": round(r.uniform(48.0, 82.0), 2),
        "effectiveUtilizationRate": round(r.uniform(40.0, 75.0), 2),
        "trend": [{"month": f"2026-{m:02d}", "rate": round(r.uniform(45, 88), 2)} for m in range(1, 4)],
        "unit": "%"
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getSingleCost")
async def get_single_cost(request: Request, equipmentNo: str):
    check_token(request, T["single_cost"])
    r = rng({"eq": equipmentNo})
    return ok({
        "equipmentNo": equipmentNo,
        "totalCostThisYear": round(r.uniform(50, 800), 1),
        "fuelCost": round(r.uniform(15, 300), 1),
        "electricityCost": round(r.uniform(20, 400), 1),
        "maintenanceCost": round(r.uniform(10, 150), 1),
        "otherCost": round(r.uniform(5, 50), 1),
        "costPerUnit": round(r.uniform(0.5, 5.0), 2),
        "unit": "万元 / 元/自然箱"
    })

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentUsageRate")
async def get_equip_usage_rate(request: Request, dateYear: int, ownerZone: str = None, cmpName: str = None, firstLevelClassName: str = None):
    check_token(request, T["equipment_usage_rate"])
    r = rng({"y": dateYear, "z": ownerZone})
    year = str(dateYear)
    zones = [ownerZone] if ownerZone else ZONES
    months_count = min(int(datetime.now().strftime("%m")), 12) if year == "2026" else 12
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "usageRate": round(rng({"mo": f"{year}-{m:02d}", "k": "usage"}).uniform(2, 8), 1),
    } for m in range(1, months_count + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentServiceableRate")
async def get_equip_serviceable(request: Request, dateYear: int, ownerZone: str = None, cmpName: str = None, firstLevelClassName: str = None):
    check_token(request, T["equipment_serviceable_rate"])
    r = rng({"y": dateYear, "z": ownerZone})
    year = str(dateYear)
    zones = [ownerZone] if ownerZone else ZONES
    months_count = min(int(datetime.now().strftime("%m")), 12) if year == "2026" else 12
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "serviceableRate": round(rng({"mo": f"{year}-{m:02d}", "k": "svc"}).uniform(0.95, 1.0), 4),
    } for m in range(1, months_count + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentFirstLevelClassNameList")
async def get_equip_l1_list(request: Request, dateMonth: str, ownerZone: str = None, cmpName: str = None):
    check_token(request, T["equipment_first_level_class_name_list"])
    r = rng({"y": dateMonth, "z": ownerZone})
    class_names = ["油运设备", "集装箱专用设备", "通用机械", "专用机械",
        "动力设备", "交通运输设备", "电子设备", "仪器仪表", "工具器具", "通信设备"]
    return ok([{
        "firstLevelClassName": cn,
        "num": float(r.randint(10, 500)),
    } for cn in class_names])

# [NO_PROD_DATA]
@app.get("/api/gateway/getEquipmentMachineHourRate")
async def get_equip_machine_hour(request: Request, dateMonth: str, ownerZone: str = None, cmpName: str = None, firstLevelClassName: str = None):
    check_token(request, T["equip_machine_hour"])
    r = rng({"y": dateMonth, "z": ownerZone})
    zones = [ownerZone] if ownerZone else REGIONS_ZONE
    return ok([{
        "ownerZone": z, "dateMonth": dateMonth,
        "avgMachineHourRate": round(r.uniform(65.0, 115.0), 1),
        "unit": "自然箱/小时"
    } for z in zones])
# [PROD_DATA]
@app.get("/api/gateway/getContainerMachineHourRate")
async def get_container_machine_hour(request: Request, dateYear: int, ownerZone: str = None, cmpName: str = None, firstLevelClassName: str = None):
    check_token(request, T["container_machine_hour_rate"])
    r = rng({"y": dateYear, "z": ownerZone})
    year = str(dateYear)
    zones = [ownerZone] if ownerZone else ZONES
    months_count = min(int(datetime.now().strftime("%m")), 12) if year == "2026" else 12
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "machineHourRate": round(rng({"mo": f"{year}-{m:02d}", "k": "mhr"}).uniform(8, 15), 1),
    } for m in range(1, months_count + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentEnergyConsumptionPerUnit")
async def get_equip_energy(request: Request, dateYear: int, ownerZone: str = None, cmpName: str = None, firstLevelClassName: str = None):
    check_token(request, T["equipment_energy_consumption_per_unit"])
    r = rng({"y": dateYear, "z": ownerZone})
    year = str(dateYear)
    zones = [ownerZone] if ownerZone else ZONES
    months_count = min(int(datetime.now().strftime("%m")), 12) if year == "2026" else 12
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "workingAmount": rng({"mo": f"{year}-{m:02d}", "k": "energy"}).randint(50000000, 200000000),
    } for m in range(1, months_count + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentFuelOilTonCost")
async def get_equip_fuel_cost(request: Request, dateYear: int, ownerZone: str = None, cmpName: str = None, firstLevelClassName: str = None):
    check_token(request, T["equipment_fuel_oil_ton_cost"])
    r = rng({"y": dateYear, "z": ownerZone})
    year = str(dateYear)
    zones = [ownerZone] if ownerZone else ZONES
    months_count = min(int(datetime.now().strftime("%m")), 12) if year == "2026" else 12
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "tonCost": round(rng({"mo": f"{year}-{m:02d}", "k": "fuel"}).uniform(0, 0.5), 2),
    } for m in range(1, months_count + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getEquipmentElectricityTonCost")
async def get_equip_elec_cost(request: Request, dateYear: int, ownerZone: str = None, cmpName: str = None, firstLevelClassName: str = None):
    check_token(request, T["equipment_electricity_ton_cost"])
    r = rng({"y": dateYear, "z": ownerZone})
    year = str(dateYear)
    zones = [ownerZone] if ownerZone else ZONES
    months_count = min(int(datetime.now().strftime("%m")), 12) if year == "2026" else 12
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "tonCost": round(rng({"mo": f"{year}-{m:02d}", "k": "elec"}).uniform(0, 1), 2),
    } for m in range(1, months_count + 1)])

# ─────────────────────────────────────────────
# 资产子屏 — 机种数据展示屏
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/getMachineDataDisplayScreenHourlyEfficiency")
async def get_machine_hourly_eff(request: Request, secondLevelClassName: str, date: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["machine_data_display_screen_hourly_efficiency"])
    r = rng({"cls": secondLevelClassName, "d": date})
    year, month, _ = parse_date(date)
    return ok([{
        "ownerLgZoneName": reg,
        "usageRate": round(r.uniform(100, 500), 2),
    } for reg in REGIONS_ZONE[:4]])

# [PROD_DATA]
@app.get("/api/gateway/getModelDataDisplayScreenEnergyConsumptionPerUnit")
async def get_model_energy(request: Request, secondLevelClassName: str, date: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["model_data_display_screen_energy_consumption_per_unit"])
    r = rng({"cls": secondLevelClassName, "d": date})
    return ok([{
        "ownerLgZoneName": reg,
        "workingAmount": round(r.uniform(100000, 500000), 1),
    } for reg in REGIONS_ZONE])

# [NO_PROD_DATA]
@app.get("/api/gateway/getFuelTonCostOfAircraftDataDisplay")
async def get_fuel_ton_cost_aircraft(request: Request, secondLevelClassName: str, date: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["fuel_ton_cost_of_aircraft_data_display"])
    r = rng({"cls": secondLevelClassName, "d": date})
    return ok({
        "secondLevelClassName": secondLevelClassName, "date": date,
        "fuelTonCost": round(r.uniform(4.0, 18.0), 2),
        "prevYearSameMonth": round(r.uniform(3.8, 17.5), 2),
        "yoyRate": round(r.uniform(-5.0, 8.0), 2),
        "unit": "元/自然箱"
    })

# [NO_PROD_DATA]
@app.get("/api/gateway/getMachineTypeDataDisplayScreenPowerConsumptionCostPerTon")
async def get_machine_power_cost(request: Request, secondLevelClassName: str, date: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["machine_type_data_display_screen_power_consumption_cost_per_ton"])
    r = rng({"cls": secondLevelClassName, "d": date})
    return ok({
        "secondLevelClassName": secondLevelClassName, "date": date,
        "electricityTonCost": round(r.uniform(6.0, 25.0), 2),
        "prevYearSameMonth": round(r.uniform(5.8, 24.0), 2),
        "yoyRate": round(r.uniform(-6.0, 5.0), 2),
        "unit": "元/自然箱"
    })

# [PROD_DATA]
@app.get("/api/gateway/getModelDataDisplayScreenUtilization")
async def get_model_utilization(request: Request, secondLevelClassName: str, dateYear: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["model_data_display_screen_utilization"])
    year = str(dateYear)
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "usageRate": round(rng({"cls": secondLevelClassName, "y": dateYear, "m": m}).uniform(0.3, 0.5), 6),
    } for m in range(1, 4)])

# [PROD_DATA]
@app.get("/api/gateway/getModelDataDisplayScreenEffectiveUtilization")
async def get_model_eff_util(request: Request, secondLevelClassName: str, dateYear: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["model_data_display_screen_effective_utilization"])
    year = str(dateYear)
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "usageRate": round(rng({"cls": secondLevelClassName, "y": dateYear, "m": m}).uniform(0.2, 0.5), 6),
    } for m in range(1, 4)])

# [PROD_DATA]
@app.get("/api/gateway/getMachineDataDisplayScreenEquipmentIntegrityRate")
async def get_machine_integrity(request: Request, secondLevelClassName: str, dateYear: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["machine_data_display_screen_equipment_integrity_rate"])
    year = str(dateYear)
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "usageRate": round(rng({"cls": secondLevelClassName, "y": dateYear, "m": m}).uniform(0.95, 1.0), 6),
    } for m in range(1, 4)])

# [PROD_DATA]
@app.get("/api/gateway/getModelDataDisplayScreenHierarchyRelation")
async def get_model_hierarchy(request: Request, secondLevelClassName: str):
    check_token(request, T["model_data_display_screen_hierarchy_relation"])
    r = rng({"cls": secondLevelClassName})
    container_l1 = ["装卸设备", "起重设备"]
    is_container = r.random() < 0.6 if not secondLevelClassName else any(kw in secondLevelClassName for kw in ["箱","桥","吊"])
    return ok([{
        "firstLevelClassName": "集装箱专用设备",
        "secondLevelClassName": r.choice(["岸桥", "场桥", "正面吊", "堆高机"]),
    }])

# [PROD_DATA]
@app.get("/api/gateway/getMachineDataDisplayEquipmentReliability")
async def get_machine_reliability(request: Request, secondLevelClassName: str, dateYear: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["machine_data_display_equipment_reliability"])
    yr = int(dateYear)
    return ok([{
        "dateMonth": f"{y}-{m:02d}",
        "dateYear": float(y),
        "usageRate": round(rng({"cls": secondLevelClassName, "y": y, "m": m}).uniform(500, 5000), 2),
    } for y in [yr - 1, yr] for m in range(1, 4) if not (y == yr and m > 3)])

# [PROD_DATA]
@app.get("/api/gateway/getNonContainerProductionEquipmentReliability")
async def get_non_ctn_reliability(request: Request, secondLevelClassName: str, dateYear: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["non_container_production_equipment_reliability"])
    yr = int(dateYear)
    return ok([{
        "dateMonth": f"{y}-{m:02d}",
        "dateYear": float(y),
        "usageRate": round(rng({"cls": secondLevelClassName, "y": y, "m": m}).uniform(1000, 50000), 2),
    } for y in [yr - 1, yr] for m in range(1, 4) if not (y == yr and m > 3)])

# [PROD_DATA]
@app.get("/api/gateway/getMachineDataDisplaySingleUnitEnergyConsumption")
async def get_machine_single_energy(request: Request, secondLevelClassName: str, date: str, ownerLgZoneName: str = None, cmpName: str = None):
    check_token(request, T["machine_data_display_single_unit_energy_consumption"])
    r = rng({"cls": secondLevelClassName, "d": date})
    return ok([{
        "equipmentNo": "A%s" % hashlib.md5(str(i).encode()).hexdigest()[:20],
        "workingAmount": round(r.uniform(0, 500000), 1),
    } for i in range(75)])

# ─────────────────────────────────────────────
# 资产子屏 — 生产设备数据分析
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentUsageRateByYear")
async def get_prod_equip_usage_year(request: Request, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_usage_rate_by_year"])
    r = rng({"z": ownerLgZoneName})
    return ok([{
        "dateYear": y,
        "usageRate": round(r.uniform(0.1, 0.3), 3),
    } for y in range(year - 3, year + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentUsageRateByMonth")
async def get_prod_equip_usage_month(request: Request, dateYear: int, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_usage_rate_by_month"])
    year = str(dateYear)
    r = rng({"y": dateYear, "z": ownerLgZoneName})
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "usageRate": round(rng({"y": year, "m": m, "z": ownerLgZoneName, "k": "pu"}).uniform(0.1, 0.3), 3),
    } for m in range(1, 4)])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentRateByYear")
async def get_prod_equip_rate_year(request: Request, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_rate_by_year"])
    r = rng({"z": ownerLgZoneName, "k": "rate_year"})
    return ok([{
        "dateYear": y,
        "usageRate": round(r.uniform(3, 8), 1),
    } for y in range(year - 3, year + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentIntegrityRateByYear")
async def get_prod_integrity_year(request: Request, dateYear: int, preYear: int, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_integrity_rate_by_year"])
    r = rng({"y": dateYear, "py": preYear})
    return ok([{
        "dateYear": y,
        "ownerZone": reg,
        "usageRate": round(r.uniform(0.95, 1.0), 4),
    } for reg in REGIONS_ZONE for y in [year, year - 1]])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentIntegrityRateByMonth")
async def get_prod_integrity_month(request: Request, dateMonth: str, preDateMonth: str, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_integrity_rate_by_month"])
    # dateMonth形如 "2026-03"，取年份
    year = dateMonth[:4] if dateMonth else "2026"
    r = rng({"dm": dateMonth, "pdm": preDateMonth})
    return ok([{
        "dateMonth": f"{year}-{m2:02d}",
        "ownerZone": reg,
        "usageRate": round(rng({"mo": f"{year}-{m2:02d}", "reg": reg, "k": "integ"}).uniform(0.95, 1.0), 4),
    } for reg in REGIONS_ZONE for m2 in range(1, 3)])

# [PROD_DATA]
@app.get("/api/gateway/getQuayEquipmentWorkingAmount")
async def get_quay_working_amount(request: Request, dateMonth: str, ownerLgZoneName: str = None):
    check_token(request, T["quay_equipment_working_amount"])
    year, month, _ = parse_date(dateMonth)
    r = rng({"dm": dateMonth, "z": ownerLgZoneName})
    base = 35000 * SEASONAL[month-1] * (YOY_BASE.get(year, 1.06) ** (year-2024))
    zones = [ownerLgZoneName] if ownerLgZoneName else ZONES
    type_names = ["输油臂作业量同比", "岸桥作业量同比", "门机作业量同比",
        "散货设备作业量同比", "总作业量同比", "输油臂作业量",
        "岸桥作业量", "门机作业量", "散货设备作业量", "总作业量"]
    return ok([{
        "num": round(r.uniform(-50, 500000), 1),
        "typeName": tn,
    } for tn in type_names])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentDataAnalysisList")
async def get_prod_equip_list(request: Request, dateMonth: str, pageNo: int = 1, pageSize: int = 20, ownerLgZoneName: str = None):
    check_token(request, T["product_equipment_data_analysis_list"])
    r = rng({"p": pageNo})
    return ok([{
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
        "丹东港口集团散粮码头分公司", "盘锦港集团有限公司第一分公司"]])

# [NO_PROD_DATA]
@app.get("/api/gateway/getEquipmentUseList")
async def get_equip_use_list(request: Request, startDate: str, endDate: str, month: str,
                               pageNo: int = 1, pageSize: int = 20,
                               ownerLgZoneName: str = None, cmpName: str = None, secondLevelClassName: str = None):
    check_token(request, T["equip_use_list"])
    r = rng({"p": pageNo})
    equip_l2 = ["门机", "岸桥", "轮胎吊", "堆高机", "叉车", "牵引车", "输送机", "场桥", "正面吊"]
    return ok([{
        "equipNo": f"EQ{r.randint(10000, 99999)}",
        "equipName": f"{r.choice(equip_l2)}-{r.randint(1, 30):02d}",
        "startTime": f"2026-04-{r.randint(1, 15):02d} {r.randint(6, 22):02d}:00",
        "endTime": f"2026-04-{r.randint(15, 28):02d} {r.randint(8, 23):02d}:00",
        "operationHours": round(r.uniform(4.0, 16.0), 1),
        "workingQty": round(r.uniform(50, 500), 1),
        "efficiency": round(r.uniform(60, 120), 1)
    } for _ in range(min(pageSize, 20))])
# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentWorkingAmountByYear")
async def get_prod_working_year(request: Request, dateYear: int, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_working_amount_by_year"])
    r = rng({"y": dateYear, "z": ownerLgZoneName})
    base = 450000 * (YOY_BASE.get(dateYear, 1.06) ** (dateYear-2024))
    return ok([{
        "num": r.randint(10000000, 200000000),
        "ownerLgZoneName": reg,
    } for reg in REGIONS_ZONE])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentWorkingAmountByMonth")
async def get_prod_working_month(request: Request, dateMonth: str, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_working_amount_by_month"])
    year, month, _ = parse_date(dateMonth)
    r = rng({"dm": dateMonth, "z": ownerLgZoneName})
    base = 40000 * SEASONAL[month-1] * (YOY_BASE.get(year, 1.06) ** (year-2024))
    return ok([{
        "num": float(r.randint(500000, 5000000)),
        "ownerLgZoneName": reg,
    } for reg in REGIONS_ZONE])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentReliabilityByYear")
async def get_prod_reliability_year(request: Request, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_reliability_by_year"])
    r = rng({"z": ownerLgZoneName, "cls": firstLevelClassName})
    return ok([{
        "dateYear": y,
        "ownerLgZoneName": reg,
        "usageRate": round(r.uniform(100, 5000000), 1),
    } for reg in REGIONS_ZONE for y in range(year - 3, year + 1)])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentReliabilityByMonth")
async def get_prod_reliability_month(request: Request, dateYear: int, ownerLgZoneName: str = None, firstLevelClassName: str = None):
    check_token(request, T["product_equipment_reliability_by_month"])
    year = str(dateYear)
    r = rng({"y": dateYear, "z": ownerLgZoneName})
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "ownerLgZoneName": reg,
        "usageRate": round(rng({"y": year, "m": m, "reg": reg, "k": "rel"}).uniform(100000, 5000000), 1),
    } for reg in REGIONS_ZONE for m in range(1, 4)])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentUnitConsumptionByYear")
async def get_prod_consumption_year(request: Request, dateYear: int):
    check_token(request, T["product_equipment_unit_consumption_by_year"])
    r = rng({"y": dateYear})
    class_names = ["工程技术船", "公铁车", "正面吊", "堆高机", "叉车", "岸桥",
        "场桥", "轮胎吊", "门座式起重机", "桥式起重机", "龙门式起重机", "拖头",
        "拖轮", "汽车起重机", "皮带机", "螺旋卸船机", "链斗卸船机", "抓斗卸船机",
        "翻车机", "油运设备", "斗轮堆取料机", "输油臂", "装船机", "卸船机",
        "机车", "流动机械", "散货专用设备", "集装箱专用设备", "其他设备"]
    return ok([{
        "secondLevelClassName": cn,
        "unitConsumption": round(r.uniform(0, 100), 2),
    } for cn in class_names[:r.randint(30, 41)]])

# [PROD_DATA]
@app.get("/api/gateway/getProductEquipmentUnitConsumptionByMonth")
async def get_prod_consumption_month(request: Request, dateMonth: str):
    check_token(request, T["product_equipment_unit_consumption_by_month"])
    r = rng({"dm": dateMonth})
    class_names = ["工程技术船", "公铁车", "正面吊", "堆高机", "叉车", "岸桥",
        "场桥", "轮胎吊", "门座式起重机", "桥式起重机", "龙门式起重机", "拖头",
        "拖轮", "汽车起重机", "皮带机", "螺旋卸船机", "链斗卸船机", "抓斗卸船机",
        "翻车机", "油运设备", "斗轮堆取料机", "输油臂", "装船机", "卸船机",
        "机车", "流动机械", "散货专用设备", "集装箱专用设备", "其他设备"]
    return ok([{
        "secondLevelClassName": cn,
        "unitConsumption": round(r.uniform(0, 100), 2),
    } for cn in class_names[:r.randint(30, 39)]])

# ─────────────────────────────────────────────
# 司南商务驾驶舱（16个新接口）
# ─────────────────────────────────────────────

# [PROD_DATA]
@app.get("/api/gateway/getCurBusinessDashboardThroughput")
async def get_cur_biz_tp(request: Request, date: str):
    # 生产对齐: 多数字段返回null，部分有值
    check_token(request, T["cur_business_dashboard_throughput"])
    r = rng({"d": date, "k": "cur_biz_tp"})
    type_names_values = [
        ("当期吞吐量", None),
        ("同期吞吐量", None),
        ("同期中转量吞吐量", round(r.uniform(80000, 120000), 1)),
        ("计划吞吐量", round(r.uniform(2000, 3000), 1)),
        ("实际完成率", None),
        ("同期完成率", None),
        ("计划完成率", None),
        ("同比增速", None),
    ]
    return ok([{"num": v, "typeName": tn} for tn, v in type_names_values])

# [NO_PROD_DATA]
@app.get("/api/gateway/getMonthlyCargoThroughputCategory")
async def get_monthly_cargo_cat(request: Request, date: str):
    check_token(request, T["monthly_cargo_cat"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "k": "monthly_cargo"})
    base = month_throughput_ton(year, month, None, r)
    cargo_weights = {"集装箱": 0.35, "散杂货": 0.30, "油化品": 0.22, "商品车": 0.13}
    return ok([{
        "cargoType": ct, "date": date,
        "throughput": round(base * w * r.uniform(0.95, 1.05), 1),
        "prevYearThroughput": round(base * w * r.uniform(0.88, 0.97), 1),
        "yoyRate": round(r.uniform(2.0, 12.0), 2),
        "shareRatio": round(w * 100, 1)
    } for ct, w in cargo_weights.items()])
# [PROD_DATA]
@app.get("/api/gateway/getMonthlyRegionalThroughputAreaBusinessDashboard")
async def get_monthly_regional_tp(request: Request, date: str):
    # 生产对齐: 返回：{num, typeName, zoneName}，typeName包含计划/当期吞吐量等
    check_token(request, T["monthly_regional_throughput_area_business_dashboard"])
    r = rng({"d": date, "k": "monthly_regional"})
    ZONES = ["辽港", "大连港", "营口港", "丹东港", "盘锦港", "绥中港"]
    ZONE_BASE = {"辽港": 2226.0, "大连港": 750.0, "营口港": 993.0, "丹东港": 327.0, "盘锦港": 169.0, "绥中港": 28.0}
    TYPE_NAMES = ["计划吞吐量", "实际完成率"]
    data = []
    for zone in ZONES:
        base = ZONE_BASE.get(zone, 200.0)
        for tn in TYPE_NAMES:
            noise = r.uniform(0.9, 1.1)
            num = round(base * noise, 1) if tn == "计划吞吐量" else round(r.uniform(70, 110), 1)
            data.append({"num": num, "typeName": tn, "zoneName": zone})
    return ok(data)

# [NO_PROD_DATA]
@app.get("/api/gateway/getCurBusinessCockpitTrendChart")
async def get_cur_biz_trend(request: Request, date: str):
    check_token(request, T["cur_business_cockpit_trend_chart"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "k": "cur_trend"})
    return ok([{
        "month": f"{year}-{m:02d}",
        "throughput": month_throughput_ton(year, m, None, r),
        "prevYearThroughput": month_throughput_ton(year-1, m, None, r),
        "yoyRate": round(r.uniform(3.0, 9.0), 2)
    } for m in range(1, month+1)])

# [PROD_DATA]
@app.get("/api/gateway/getSumBusinessDashboardThroughput")
async def get_sum_biz_tp(request: Request, date: str):
    # 生产对齐: 与getCurBusinessDashboardThroughput一致，多数字段返回null
    check_token(request, T["sum_biz_tp"])
    r = rng({"d": date, "k": "sum_biz"})
    type_names_values = [
        ("同期吞吐量", None),
        ("当期吞吐量", None),
        ("同期中转量吞吐量", round(r.uniform(200000, 400000), 1)),
        ("计划吞吐量", round(r.uniform(8000, 12000), 1)),
        ("实际完成率", None),
        ("同期完成率", None),
        ("计划完成率", None),
        ("同比增速", None),
    ]
    return ok([{"num": v, "typeName": tn} for tn, v in type_names_values])

# [NO_PROD_DATA]
@app.get("/api/gateway/getBusinessDashboardCumulativeThroughputByCargoType")
async def get_biz_cumul_by_cargo(request: Request, date: str):
    check_token(request, T["biz_cumul_cargo"])
    year = int(date[:4]) if date else 2026
    r = rng({"d": date, "k": "cumul_cargo"})
    months = 3
    base = sum(month_throughput_ton(year, m, None, r) for m in range(1, months + 1))
    cargo_w = {"集装箱": 0.35, "散杂货": 0.30, "油化品": 0.22, "商品车": 0.13}
    return ok([{
        "cargoType": ct, "date": date,
        "cumulativeThroughput": round(base * w * r.uniform(0.97, 1.03), 1),
        "prevYearCumulative": round(base * w * r.uniform(0.86, 0.97), 1),
        "yoyRate": round(r.uniform(2.0, 10.0), 2)
    } for ct, w in cargo_w.items()])

# [PROD_DATA]
@app.get("/api/gateway/getCumulativeRegionalThroughput")
async def get_cumul_regional_tp(request: Request, date: str):
    check_token(request, T["cumul_region_tp"])
    year = int(date[:4]) if date else 2026
    months = 3
    r = rng({"d": date, "k": "cumul_reg"})
    type_names = ["计划吞吐量", "累计吞吐量", "去年同期累计吞吐量",
        "同比增速", "当期完成进度", "去年同期完成进度"]
    return ok([{
        "num": round(r.uniform(100, 3000), 1),
        "typeName": tn,
        "zoneName": reg,
    } for reg in REGIONS for tn in type_names])


# [NO_PROD_DATA]
@app.get("/api/gateway/getSumBusinessCockpitTrendChart")
async def get_sum_biz_trend(request: Request, date: str):
    check_token(request, T["sum_business_cockpit_trend_chart"])
    year = int(date[:4]) if date else 2026
    r = rng({"d": date, "k": "sum_trend"})
    cumul, prev_cumul = 0.0, 0.0
    series = []
    for m in range(1, 7):
        monthly = month_throughput_ton(year, m, None, r)
        prev_m = month_throughput_ton(year-1, m, None, r)
        cumul += monthly; prev_cumul += prev_m
        series.append({
            "month": f"{year}-{m:02d}",
            "monthlyThroughput": round(monthly, 1),
            "cumulativeThroughput": round(cumul, 1),
            "prevYearCumulative": round(prev_cumul, 1)
        })
    return ok(series)

# [NO_PROD_DATA]
@app.get("/api/gateway/getStrategicCustomerContributionCustomerOperatingRevenue")
async def get_strategic_contrib_rev(request: Request, date: str):
    check_token(request, T["strategic_customer_contribution_customer_operating_revenue"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "k": "strat_rev"})
    base = month_throughput_ton(year, month, None, r)
    clients = r.choices(STRATEGIC_CLIENTS, k=10)
    revs = sorted([r.uniform(300, 4000) for _ in clients], reverse=True)
    total = sum(revs)
    return ok([{
        "clientName": c, "date": date,
        "operatingRevenue": round(rv, 1),
        "revenueShare": round(rv/total*100, 2),
        "yoyRate": round(r.uniform(1.0, 15.0), 2),
        "unit": "万元"
    } for c, rv in zip(clients, revs)])

# [PROD_DATA]
@app.get("/api/gateway/getCurStrategicCustomerContributionByCargoTypeThroughput")
async def get_cur_strategic_cargo(request: Request, date: str):
    check_token(request, T["cur_strategic_customer_contribution_by_cargo_type_throughput"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "k": "strat_cargo"})
    base = month_throughput_ton(year, month, None, r) * 0.65  # 战略客户贡献约65%
    cargo_w = {"集装箱":0.38,"散杂货":0.28,"油化品":0.20,"商品车":0.14}
    return ok([{
        "categoryName": cat,
        "num": round(r.uniform(0, 500), 1),
    } for cat in ["散杂货", "集装箱", "油化品", "商品车"]])

# [PROD_DATA]
@app.get("/api/gateway/getCurContributionRankOfStrategicCustomer")
async def get_cur_contrib_rank(request: Request, date: str):
    check_token(request, T["cur_contribution_rank_of_strategic_customer"])
    year, month, _ = parse_date(date)
    r = rng({"d": date, "k": "cur_rank"})
    base = month_throughput_ton(year, month, None, r)
    clients = r.choices(STRATEGIC_CLIENTS, k=10)
    shares = sorted([r.uniform(2, 16) for _ in clients], reverse=True)
    total_s = sum(shares)
    return ok([{
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
    ]])

# [PROD_DATA]
@app.get("/api/gateway/getCurStrategyCustomerTrendAnalysis")
async def get_cur_strategy_trend(request: Request, date: str):
    check_token(request, T["cur_strat_trend"])
    year = int(date[:4]) if date else 2026
    r = rng({"d": date, "k": "cur_strat_trend"})
    type_names = ["战略客户吞吐量", "全港吞吐量", "战略客户贡献率",
        "战略客户营收", "去年同期战略客户吞吐量"]
    return ok([{
        "dateMonth": f"{year}-{m:02d}",
        "num": round(month_throughput_ton(year, m, None, rng({"y": year, "m": m, "k": "cst"})) * rng({"y": year, "m": m, "k": "cst_n"}).uniform(0.5, 1.2), 1),
        "typeName": tn,
    } for m in range(1, 4) for tn in type_names])
# [NO_PROD_DATA]
@app.get("/api/gateway/getSumStrategicCustomerContributionCustomerOperatingRevenue")
async def get_sum_strategic_rev(request: Request, date: str):
    check_token(request, T["sum_strategic_customer_contribution_customer_operating_revenue"])
    year = int(date[:4]) if date else 2026
    r = rng({"d": date, "k": "sum_strat_rev"})
    months = 3
    base_rev = sum(month_throughput_ton(year, m, None, r) for m in range(1, months+1)) * 0.65 * r.uniform(1.2, 1.5)
    clients = r.choices(STRATEGIC_CLIENTS, k=10)
    shares = sorted([r.uniform(2, 16) for _ in clients], reverse=True)
    total_s = sum(shares)
    return ok([{
        "clientName": c, "date": date,
        "cumulativeRevenue": round(base_rev * s/total_s, 1),
        "revenueShare": round(s/total_s*100, 2),
        "yoyRate": round(r.uniform(1.0, 12.0), 2),
        "unit": "万元"
    } for c, s in zip(clients, shares)])

# [PROD_DATA]
@app.get("/api/gateway/getSumStrategicCustomerContributionByCargoTypeThroughput")
async def get_sum_strategic_cargo(request: Request, date: str):
    check_token(request, T["sum_strat_cargo"])
    year = int(date[:4]) if date else 2026
    r = rng({"d": date, "k": "sum_strat_cargo"})
    months = 3
    base = sum(month_throughput_ton(year, m, None, r) for m in range(1, months + 1)) * 0.65
    cargo_w = {"集装箱": 0.38, "散杂货": 0.28, "油化品": 0.20, "商品车": 0.14}
    return ok([{
        "categoryName": ct,
        "num": round(base * w * r.uniform(0.97, 1.03), 1),
    } for ct, w in cargo_w.items()])

# [PROD_DATA]
@app.get("/api/gateway/getSumContributionRankOfStrategicCustomer")
async def get_sum_contrib_rank(request: Request, date: str):
    check_token(request, T["sum_contrib_rank"])
    year = int(date[:4]) if date else 2026
    r = rng({"d": date, "k": "sum_rank"})
    extended_clients = STRATEGIC_CLIENTS + [
        "广州汽车集团股份有限公司", "华能国际电力股份有限公司",
        "中国华电集团有限公司", "国家电力投资集团有限公司",
        "中国铝业集团有限公司", "中粮集团有限公司",
        "宝武钢铁集团有限公司", "首钢集团有限公司",
        "河钢集团有限公司", "太原钢铁集团有限公司",
    ]
    return ok([{
        "clientName": cl,
        "num": round(r.uniform(0, 200), 1),
    } for cl in extended_clients])


# [PROD_DATA]
@app.get("/api/gateway/getSumStrategyCustomerTrendAnalysis")
async def get_sum_strategy_trend(request: Request):
    check_token(request, T["sum_strategy_customer_trend_analysis"])
    year = 2026
    r = rng({"k": "sum_strat_trend"})
    cumul_tp, cumul_rev = 0.0, 0.0
    series = []
    for m in range(1, 7):
        monthly = month_throughput_ton(year, m, None, r)
        strat = monthly * 0.65
        rev = strat * r.uniform(1.2, 1.5)
        cumul_tp += strat; cumul_rev += rev
        series.append({
            "month": f"{year}-{m:02d}",
            "strategicThroughput": round(strat, 1),
            "cumulativeStrategicThroughput": round(cumul_tp, 1),
            "cumulativeRevenue": round(cumul_rev, 1),
            "contributionRate": round(r.uniform(60.0, 72.0), 2)
        })
    return ok([{
        "dateYear": y,
        "num": round(r.uniform(0, 2000), 1),
    } for y in [year, year - 1]])



# ════════════════════════════════════════════════════════════════
# 智能体元数据查询接口（无需 TOKEN）
# ════════════════════════════════════════════════════════════════

_META_APIS = [{"path": "/api/gateway/getWeatherForecast", "domain": "D1", "time": "T_RT", "granularity": "G_ZONE", "intent": "查询各港区未来5天天气预报（天气/温度/风速/湿度）", "tags": ["天气", "预报", "风速", "温度", "港区"], "required": [], "optional": ["regionName"], "param_note": "regionName不填返回全部港区", "returns": "forecasts数组：date/weather/tempHigh/tempLow/windDirection/windLevel", "disambiguate": "区别getRealTimeWeather=当前实时；本接口=未来5天预报"}, {"path": "/api/gateway/getRealTimeWeather", "domain": "D1", "time": "T_RT", "granularity": "G_ZONE", "intent": "查询各港区当前实时气象（温度/风速/能见度/浪高）", "tags": ["天气", "实时", "当前", "浪高", "能见度"], "required": [], "optional": ["regionName"], "param_note": "regionName不填返回全部港区", "returns": "currentWeather/temperature/windSpeed/visibility/waveHeight", "disambiguate": "区别getWeatherForecast=未来5天预报；本接口=当前实况"}, {"path": "/api/gateway/getTrafficControl", "domain": "D1", "time": "T_RT", "granularity": "G_ZONE", "intent": "查询当前航道交通管制信息（大风封航/浓雾限航/演习管制）", "tags": ["管制", "封航", "限航", "交通", "航道"], "required": [], "optional": ["regionName"], "param_note": "", "returns": "controlType/startTime/endTime/affectedArea/controlLevel", "disambiguate": ""}, {"path": "/api/gateway/getKeyVesselList", "domain": "D1", "time": "T_RT", "granularity": "G_BERTH", "intent": "查询重点船舶列表（在泊/锚地状态，含船名/货类/到港时间）", "tags": ["船舶", "在泊", "锚地", "重点船", "船舶动态"], "required": ["shipStatus", "regionName"], "optional": [], "param_note": "shipStatus: D=在泊 C=锚地；regionName=港区名称", "returns": "shipName/shipType/status/berthNo/arrivalTime/expectedDeparture/cargoType", "disambiguate": "区别getProdShipDesc=描述性摘要；getProdShipDynNum=数量汇总"}, {"path": "/api/gateway/getProdShipDynNum", "domain": "D1", "time": "T_RT", "granularity": "G_PORT", "intent": "查询全港船舶动态数量汇总（在泊/锚地/进港/出港总数）", "tags": ["船舶数量", "在泊数", "锚地数", "动态", "汇总"], "required": [], "optional": [], "param_note": "无入参，返回当时快照", "returns": "inBerth/anchor/entering/departing/total", "disambiguate": "区别getKeyVesselList=明细列表；getProdShipDesc=描述摘要"}, {"path": "/api/gateway/getProdShipDesc", "domain": "D1", "time": "T_RT", "granularity": "G_PORT", "intent": "查询重点船舶和锚地船舶的描述性摘要（驾驶舱展示用）", "tags": ["船舶摘要", "重点船", "锚地", "驾驶舱"], "required": [], "optional": [], "param_note": "", "returns": "keyShips数组 + anchorShips数组", "disambiguate": "区别getProdShipDynNum=纯数量；getKeyVesselList=完整列表"}, {"path": "/api/gateway/getShipStatisticsByRegion", "domain": "D1", "time": "T_RT", "granularity": "G_ZONE", "intent": "按港区+船舶类型统计在港船舶数量（集装箱船/散货船/油轮等）", "tags": ["船舶统计", "按港区", "按船型", "数量"], "required": ["regionName"], "optional": [], "param_note": "", "returns": "regionName/shipType/inPortCount/anchorCount", "disambiguate": "区别getShipStatisticsByBusinessType=按业务类型分；本接口=按港区+船型"}, {"path": "/api/gateway/getShipStatisticsByBusinessType", "domain": "D1", "time": "T_RT", "granularity": "G_BIZ", "intent": "按业务类型统计在港船舶数量（集装箱/散杂货/油化品/商品车）", "tags": ["船舶统计", "按业务", "货类", "数量"], "required": [], "optional": ["regionName"], "param_note": "", "returns": "businessType/inPortCount/anchorCount", "disambiguate": "区别getShipStatisticsByRegion=按港区+船型分"}, {"path": "/api/gateway/getBerthList", "domain": "D1", "time": "T_RT", "granularity": "G_BERTH", "intent": "查询公司泊位列表及当前状态（在泊/离泊/计划）", "tags": ["泊位", "泊位列表", "在泊状态", "靠泊计划"], "required": ["cmpName"], "optional": [], "param_note": "cmpName=公司名称", "returns": "berthNo/shipName/status/arrivalTime/departureTime/cargoType", "disambiguate": "区别getBerthOccupancyRate=占用率指标；本接口=明细列表"}, {"path": "/api/gateway/getBerthOccupancyRate", "domain": "D1", "time": "T_TREND", "granularity": "G_CMP", "intent": "查询指定公司在时间段内的泊位占用率", "tags": ["泊位占用率", "占用率", "靠泊时间"], "required": ["mainOrgCode", "statDate", "endDate"], "optional": [], "param_note": "mainOrgCode=机构编码；statDate/endDate=统计起止日期", "returns": "occupancyRate/berthCount/totalBerthingHours", "disambiguate": "区别getBerthOccupancyRateByRegion=按港区；ByBusinessType=按业务"}, {"path": "/api/gateway/getBerthOccupancyRateByRegion", "domain": "D1", "time": "T_TREND", "granularity": "G_ZONE", "intent": "按港区查询泊位占用率及在泊时间统计", "tags": ["泊位占用率", "港区", "靠泊时长"], "required": [], "optional": ["startDate", "endDate"], "param_note": "", "returns": "regionName/occupancyRate/berthCount/avgBerthingHours", "disambiguate": "区别ByBusinessType=按业务类型"}, {"path": "/api/gateway/getBerthOccupancyRateByBusinessType", "domain": "D1", "time": "T_TREND", "granularity": "G_BIZ", "intent": "按业务类型查询泊位占用率", "tags": ["泊位占用率", "业务类型", "集装箱", "散货"], "required": [], "optional": ["startDate", "endDate"], "param_note": "", "returns": "businessType/occupancyRate/berthCount/avgTurnaround", "disambiguate": "区别ByRegion=按港区"}, {"path": "/api/gateway/getTotalBerthDuration", "domain": "D1", "time": "T_TREND", "granularity": "G_CMP", "intent": "查询机构靠泊总时长和占用率（指定时间段）", "tags": ["靠泊时长", "泊位时间", "占用率"], "required": ["orgName", "statDate", "endDate"], "optional": [], "param_note": "orgName=机构名；statDate/endDate=统计区间", "returns": "totalBerthingHours/calendarHours/occupancyRate", "disambiguate": "区别getBerthOccupancyRate=用机构编码；本接口=用机构名"}, {"path": "/api/gateway/getImportantCargoPortInventoryByRegion", "domain": "D1", "time": "T_RT", "granularity": "G_ZONE", "intent": "查询各港区主要货物港存量（铁矿石/煤/粮食/石油/集装箱/商品车）", "tags": ["港存", "库存", "铁矿石", "煤炭", "粮食", "按港区"], "required": ["regionName"], "optional": [], "param_note": "", "returns": "ironOre/coal/grain/petroleum/containerTeu/vehicleCount", "disambiguate": "区别ByCargoType=按货类；ByBusinessType=按业务类型"}, {"path": "/api/gateway/getImportantCargoPortInventoryByCargoType", "domain": "D1", "time": "T_RT", "granularity": "G_CARGO", "intent": "按货类查询港存量及库容占用率", "tags": ["港存", "库存", "货类", "库容率"], "required": [], "optional": ["date", "businessType", "regionName"], "param_note": "", "returns": "cargoType/inventory/capacityRatio/maxCapacity/dailyChange", "disambiguate": "区别ByRegion=按港区分"}, {"path": "/api/gateway/getDailyPortInventoryData", "domain": "D1", "time": "T_DAY", "granularity": "G_CMP", "intent": "查询指定公司指定日期的港存快照（各货类汇总+库容率）", "tags": ["港存", "日存量", "公司", "日期"], "required": ["dateCur", "cmpName"], "optional": [], "param_note": "dateCur=查询日期yyyy-MM-dd", "returns": "ironOre/coal/grain/containerTeu/vehicleCount/totalCapacityRatio", "disambiguate": "区别getPortInventoryTrend=多月趋势"}, {"path": "/api/gateway/getPortInventoryTrend", "domain": "D1", "time": "T_TREND", "granularity": "G_CMP", "intent": "查询公司全年各月港存趋势（平均/最高/最低）", "tags": ["港存趋势", "月度趋势", "公司", "库存变化"], "required": ["dateYear", "cmpName"], "optional": [], "param_note": "", "returns": "月份序列：avgInventory/maxInventory/minInventory", "disambiguate": "区别getDailyPortInventoryData=单日快照"}, {"path": "/api/gateway/getContainerAndVehicleTrade", "domain": "D1", "time": "T_RT", "granularity": "G_ZONE", "intent": "查询港区集装箱（内外贸）和商品车（进出口）数量", "tags": ["集装箱", "商品车", "内外贸", "进出口", "TEU"], "required": ["regionName"], "optional": [], "param_note": "", "returns": "containerTotal/containerForeign/containerDomestic/vehicleTotal/vehicleExport", "disambiguate": ""}, {"path": "/api/gateway/getVesselOperationEfficiency", "domain": "D1", "time": "T_TREND", "granularity": "G_CMP", "intent": "查询公司船舶作业效率（单船效率平均/最高/最低，按月区间）", "tags": ["船舶效率", "作业效率", "单船效率", "台时"], "required": ["cmpName", "startMonth", "endMonth"], "optional": [], "param_note": "startMonth/endMonth=yyyy-MM", "returns": "avgEfficiency/maxEfficiency/minEfficiency/totalShips/unit", "disambiguate": "区别getVesselOperationEfficiencyTrend=月度趋势曲线"}, {"path": "/api/gateway/getVesselOperationEfficiencyTrend", "domain": "D1", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询月度船舶作业效率趋势（集装箱/散货/油品效率曲线）", "tags": ["效率趋势", "月度效率", "集装箱效率", "趋势"], "required": ["startMonth", "endMonth", "cmpName"], "optional": [], "param_note": "startMonth/endMonth=yyyy-MM", "returns": "月份序列：avgEfficiency/containerEfficiency/bulkEfficiency", "disambiguate": "区别getVesselOperationEfficiency=单时段汇总均值"}, {"path": "/api/gateway/getSingleShipRate", "domain": "D1", "time": "T_TREND", "granularity": "G_CMP", "intent": "查询各公司单船效率（作业/小时），按时间段统计", "tags": ["单船效率", "自然箱/小时", "吨/小时"], "required": ["startDate", "endDate", "regionName"], "optional": [], "param_note": "", "returns": "companyName/avgEfficiency/maxEfficiency/totalShips", "disambiguate": ""}, {"path": "/api/gateway/getProductViewShipOperationRateAvg", "domain": "D1", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询港口平均船舶作业效率（集装箱/散货/油品/滚装各业务类型）", "tags": ["平均效率", "作业效率", "各业务类型"], "required": [], "optional": ["startDate", "endDate"], "param_note": "", "returns": "avgContainerRate/avgBulkRate/avgOilRate/avgRoroRate", "disambiguate": "区别Trend=按月趋势；本接口=时段汇总均值"}, {"path": "/api/gateway/getProductViewShipOperationRateTrend", "domain": "D1", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询船舶作业效率月度趋势（集装箱/散货/油品曲线）", "tags": ["效率趋势", "月度趋势", "集装箱效率"], "required": [], "optional": ["startDate", "endDate"], "param_note": "", "returns": "月份序列：containerRate/bulkRate/oilRate", "disambiguate": "区别Avg=汇总均值"}, {"path": "/api/gateway/getPersonalCenterCargoThroughput", "domain": "D1", "time": "T_DAY", "granularity": "G_PORT", "intent": "查询指定日期吞吐量及与环比日的对比（个人中心首页）", "tags": ["日吞吐", "当日", "环比", "个人中心"], "required": [], "optional": ["date", "momDate", "yoyDate"], "param_note": "date=查询日，momDate=环比日，yoyDate=同比日", "returns": "currentDay/momDay/momRate/unit", "disambiguate": "区别Month=月度；Year=年累计"}, {"path": "/api/gateway/getPersonalCenterMonthCargoThroughput", "domain": "D1", "time": "T_MON", "granularity": "G_PORT", "intent": "查询截至某日当月累计吞吐量及与环比月的对比", "tags": ["月吞吐", "当月累计", "环比", "个人中心"], "required": [], "optional": ["endDate", "momEndDate", "yoyEndDate", "momStartDate", "startDate", "yoyStartDate"], "param_note": "endDate=截止日", "returns": "currentMonthTotal/momMonthTotal/momRate", "disambiguate": "区别Day=日；Year=年累计"}, {"path": "/api/gateway/getPersonalCenterYearCargoThroughput", "domain": "D1", "time": "T_CUM", "granularity": "G_PORT", "intent": "查询截至某日年累计吞吐量及同比", "tags": ["年累计", "同比", "个人中心", "累计吞吐"], "required": [], "optional": ["endDate", "yoyEndDate", "startDate", "yoyStartDate"], "param_note": "", "returns": "currentYearCumulative/prevYearCumulative/yoyRate", "disambiguate": "区别Month=月度；Day=日"}, {"path": "/api/gateway/getPersonalCenterYearCargoThroughputTrend", "domain": "D1", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询年度各月吞吐量趋势（含累计）", "tags": ["月度趋势", "个人中心", "年度趋势"], "required": [], "optional": ["startDate", "endDate"], "param_note": "", "returns": "月份序列：throughput/cumulative", "disambiguate": ""}, {"path": "/api/gateway/getThroughputMonthlyTrend", "domain": "D1", "time": "T_TREND", "granularity": "G_CMP", "intent": "查询公司全年月度吞吐量趋势（含同比）", "tags": ["月度趋势", "公司", "年度趋势"], "required": ["dateYear", "cmpName"], "optional": [], "param_note": "", "returns": "月份序列：throughput/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getPortCompanyThroughput", "domain": "D1", "time": "T_MON", "granularity": "G_CMP", "intent": "查询各公司指定月份吞吐量及同比", "tags": ["公司吞吐", "各公司", "月度", "同比"], "required": ["date", "cmpName"], "optional": [], "param_note": "date=yyyy-MM", "returns": "companyName/throughput/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getBusinessSegmentBranch", "domain": "D1", "time": "T_NONE", "granularity": "G_CMP", "intent": "查询港区下各公司的业务分支组织关系", "tags": ["组织关系", "业务分支", "公司", "港区"], "required": ["regionName"], "optional": [], "param_note": "", "returns": "regionName/companyName/orgCode/businessType", "disambiguate": ""}, {"path": "/api/gateway/getThroughputAndTargetThroughputTon", "domain": "D1", "time": "T_CUM", "granularity": "G_ZONE", "intent": "查询年度吞吐量实际完成值与目标值对比（万吨，含完成率）", "tags": ["吞吐量", "目标完成", "完成率", "万吨", "年度"], "required": [], "optional": ["regionName", "dateYear"], "param_note": "", "returns": "actualThroughput/targetThroughput/completionRate/unit", "disambiguate": "区别TEU版=集装箱箱量目标"}, {"path": "/api/gateway/getThroughputAndTargetThroughputTeu", "domain": "D1", "time": "T_CUM", "granularity": "G_ZONE", "intent": "查询年度集装箱吞吐量实际值与目标值对比（TEU）", "tags": ["集装箱", "TEU", "目标完成", "内外贸"], "required": [], "optional": ["regionName", "dateYear"], "param_note": "", "returns": "actualTeu/targetTeu/foreignTradeTeu/domesticTradeTeu", "disambiguate": "区别Ton版=万吨目标"}, {"path": "/api/gateway/getThroughputAnalysisByYear", "domain": "D1", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询年度各月吞吐量趋势（当年vs上年同期月度对比）", "tags": ["月度趋势", "同比", "年度对比", "万吨"], "required": [], "optional": ["dateYear", "preYear", "regionName"], "param_note": "dateYear/preYear=yyyy", "returns": "月份序列：year当年/year上年/yoyRate", "disambiguate": "区别getContainerThroughputAnalysisByYear=只看集装箱TEU"}, {"path": "/api/gateway/getContainerThroughputAnalysisByYear", "domain": "D1", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询集装箱吞吐量年度月趋势（当年vs上年，TEU）", "tags": ["集装箱", "TEU", "月度趋势", "年度对比"], "required": [], "optional": ["dateYear", "preYear", "regionName"], "param_note": "", "returns": "月份序列：currentYearTeu/prevYearTeu/yoyRate", "disambiguate": "区别ByYear(吨版)=万吨"}, {"path": "/api/gateway/getThroughputAnalysisNonContainer", "domain": "D1", "time": "T_YR", "granularity": "G_PORT", "intent": "查询年度非集装箱吞吐量（干散/液散/件杂/滚装）", "tags": ["非集装箱", "散货", "散杂货", "滚装", "年度"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "totalTon/dryBulk/liquidBulk/breakBulk/ro_ro/yoyRate", "disambiguate": "区别Container版=集装箱"}, {"path": "/api/gateway/getThroughputAnalysisContainer", "domain": "D1", "time": "T_YR", "granularity": "G_PORT", "intent": "查询年度集装箱吞吐量（内外贸/空重箱）", "tags": ["集装箱", "TEU", "内外贸", "空重箱", "年度"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "totalTeu/foreignTrade/domesticTrade/emptyBox/fullBox/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getOilsChemBreakBulkByBusinessType", "domain": "D1", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区油化品和散杂货吞吐量（按月，支持同比/环比切换）", "tags": ["油化品", "散杂货", "港区", "月度"], "required": [], "optional": ["flag", "dateMonth", "businessType"], "param_note": "flag=0当月/1同比/2环比", "returns": "regionName/oilChemical/breakBulk", "disambiguate": ""}, {"path": "/api/gateway/getRoroByBusinessType", "domain": "D1", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区滚装（商品车）吞吐量", "tags": ["滚装", "商品车", "港区", "月度"], "required": [], "optional": ["flag", "dateMonth"], "param_note": "", "returns": "regionName/vehicleCount", "disambiguate": ""}, {"path": "/api/gateway/getContainerByBusinessType", "domain": "D1", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区集装箱吞吐量（TEU，按月）", "tags": ["集装箱", "TEU", "港区", "月度"], "required": [], "optional": ["flag", "dateMonth"], "param_note": "", "returns": "regionName/totalTeu", "disambiguate": ""}, {"path": "/api/gateway/getCompanyStatisticsBusinessType", "domain": "D1", "time": "T_MON", "granularity": "G_CMP", "intent": "按公司查询各业务类型吞吐量（集装箱/散货/油化/滚装）", "tags": ["公司统计", "业务类型", "各公司", "分拆"], "required": [], "optional": ["flag", "dateMonth", "date", "dateYear", "regionName"], "param_note": "flag控制时间维度", "returns": "companyName/container/bulkCargo/oilChem/roro", "disambiguate": ""}, {"path": "/api/gateway/getThroughputAnalysisYoyMomByYear", "domain": "D1", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询指定年份吞吐量同比/环比（年度层面）", "tags": ["同比", "环比", "年度", "吞吐"], "required": [], "optional": ["date"], "param_note": "date=yyyy-MM-dd", "returns": "current/prevYear/prevMonth/yoyRate/momRate", "disambiguate": "区别ByMonth=月度层面；ByDay=日层面"}, {"path": "/api/gateway/getThroughputAnalysisYoyMomByMonth", "domain": "D1", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询指定月份吞吐量同比/环比（月度层面）", "tags": ["同比", "环比", "月度", "吞吐"], "required": [], "optional": ["dateMonth"], "param_note": "dateMonth=yyyy-MM", "returns": "dateMonth/currentMonth/prevYearSameMonth/yoyRate/momRate", "disambiguate": "区别ByYear=年度；ByDay=日"}, {"path": "/api/gateway/getThroughputAnalysisYoyMomByDay", "domain": "D1", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询指定日期吞吐量同比/环比（日层面）", "tags": ["同比", "环比", "日度", "吞吐"], "required": [], "optional": ["date"], "param_note": "date=yyyy-MM-dd", "returns": "date/currentDay/prevYearSameDay/yoyRate/momRate", "disambiguate": "区别ByYear=年；ByMonth=月"}, {"path": "/api/gateway/getContainerAnalysisYoyMomByYear", "domain": "D1", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询集装箱吞吐量同比/环比（年度）", "tags": ["集装箱", "同比", "环比", "TEU", "年度"], "required": [], "optional": ["date"], "param_note": "", "returns": "yoyRate/momRate（集装箱TEU）", "disambiguate": ""}, {"path": "/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByYear", "domain": "D1", "time": "T_YOY", "granularity": "G_BIZ", "intent": "查询各业务类型吞吐量同比/环比（年度，可按港区筛选）", "tags": ["业务类型", "同比", "环比", "年度"], "required": [], "optional": ["date", "regionName"], "param_note": "", "returns": "businessType/current/yoyRate/momRate", "disambiguate": ""}, {"path": "/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByMonth", "domain": "D1", "time": "T_YOY", "granularity": "G_BIZ", "intent": "查询各业务类型吞吐量同比/环比（月度）", "tags": ["业务类型", "同比", "环比", "月度"], "required": [], "optional": ["dateMonth", "regionName"], "param_note": "", "returns": "businessType/currentMonth/yoyRate/momRate", "disambiguate": ""}, {"path": "/api/gateway/getBusinessTypeThroughputAnalysisYoyMomByDay", "domain": "D1", "time": "T_YOY", "granularity": "G_BIZ", "intent": "查询各业务类型吞吐量同比/环比（日度）", "tags": ["业务类型", "同比", "环比", "日度"], "required": [], "optional": ["date", "regionName"], "param_note": "", "returns": "businessType/currentDay/yoyRate/momRate", "disambiguate": ""}, {"path": "/api/gateway/getMonthlyThroughput", "domain": "D2", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询当月吞吐量及与去年同期对比（市场商务驾驶舱，可按港区筛选）", "tags": ["当月吞吐", "同比", "市场商务", "港区"], "required": ["curDateMonth", "yearDateMonth", "zoneName"], "optional": [], "param_note": "curDateMonth/yearDateMonth=yyyy-MM；zoneName=港区名（必填）", "returns": "currentMonthTotal/prevYearSameMonth/yoyRate/yoyDiff", "disambiguate": "区别getCurBusinessDashboardThroughput=无zoneName参数；getCumulativeThroughput=累计"}, {"path": "/api/gateway/getCurBusinessDashboardThroughput", "domain": "D2", "time": "T_MON", "granularity": "G_PORT", "intent": "查询当月吞吐量及同比（全港汇总，无港区筛选）", "tags": ["当月吞吐", "同比", "全港", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "currentMonthThroughput/prevYearSameMonth/yoyRate", "disambiguate": "区别getMonthlyThroughput=有zoneName参数；本接口=全港无港区筛选"}, {"path": "/api/gateway/getMonthlyZoneThroughput", "domain": "D2", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区当月吞吐量分布及占比", "tags": ["港区吞吐", "当月", "分港区", "占比"], "required": ["curDateMonth", "yearDateMonth", "zoneName"], "optional": [], "param_note": "", "returns": "zoneName/currentThroughput/yoyRate/shareRatio", "disambiguate": "区别getMonthlyThroughput=全港汇总；区别CumulativeZone=累计版"}, {"path": "/api/gateway/getCumulativeThroughput", "domain": "D2", "time": "T_CUM", "granularity": "G_PORT", "intent": "查询年累计吞吐量及同比（内外贸分拆）", "tags": ["累计吞吐", "年累计", "同比", "内外贸"], "required": ["curDateYear", "yearDateYear"], "optional": ["zoneName"], "param_note": "curDateYear/yearDateYear=yyyy；zoneName非必填", "returns": "currentYearCumulative/prevYearCumulative/yoyRate（内外贸分拆）", "disambiguate": "区别getMonthlyThroughput=当月值；getSumBusinessDashboardThroughput=同功能无内外贸分拆"}, {"path": "/api/gateway/getCumulativeZoneThroughput", "domain": "D2", "time": "T_CUM", "granularity": "G_ZONE", "intent": "查询各港区年累计吞吐量及占比", "tags": ["港区累计", "年累计", "分港区", "占比"], "required": ["curDateYear", "yearDateYear", "zoneName"], "optional": [], "param_note": "", "returns": "zoneName/currentYearCumulative/yoyRate/shareRatio", "disambiguate": "区别getMonthlyZoneThroughput=当月版"}, {"path": "/api/gateway/getCurrentBusinessSegmentThroughput", "domain": "D2", "time": "T_MON", "granularity": "G_BIZ", "intent": "查询当月各业务板块（集装箱/散杂货/油化品/商品车）吞吐量", "tags": ["业务板块", "当月", "集装箱", "散杂货", "油化品", "商品车"], "required": ["curDateMonth", "yearDateMonth", "zoneName"], "optional": [], "param_note": "", "returns": "businessSegment/currentThroughput/prevYearThroughput/yoyRate", "disambiguate": "区别getCumulativeBusinessSegmentThroughput=累计版"}, {"path": "/api/gateway/getCumulativeBusinessSegmentThroughput", "domain": "D2", "time": "T_CUM", "granularity": "G_BIZ", "intent": "查询年累计各业务板块吞吐量", "tags": ["业务板块", "年累计", "集装箱", "散杂货"], "required": ["curDateYear", "yearDateYear", "zoneName"], "optional": [], "param_note": "", "returns": "businessSegment/currentYearCumulative/yoyRate", "disambiguate": "区别getCurrentBusinessSegment=当月版"}, {"path": "/api/gateway/getMonthlyRegionalThroughputAreaBusinessDashboard", "domain": "D2", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询当月各港区吞吐量及占比（商务驾驶舱版）", "tags": ["港区吞吐", "当月", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "zoneName/currentThroughput/shareRatio/yoyRate", "disambiguate": "区别getMonthlyZoneThroughput=需三参数版"}, {"path": "/api/gateway/getTrendChart", "domain": "D2", "time": "T_TREND", "granularity": "G_BIZ", "intent": "查询指定业务板块月度吞吐量趋势图数据（市场商务版）", "tags": ["趋势图", "月度趋势", "业务板块"], "required": ["businessSegment", "startDate", "endDate"], "optional": [], "param_note": "businessSegment=集装箱/散杂货/油化品/商品车", "returns": "月份序列：throughput/yoyRate", "disambiguate": "区别getCurBusinessCockpitTrendChart=全港当月版；getCumulativeTrendChart=累计版"}, {"path": "/api/gateway/getCurBusinessCockpitTrendChart", "domain": "D2", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询全港吞吐量月度趋势（当年各月，商务驾驶舱版）", "tags": ["趋势图", "全港", "月度趋势", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "月份序列：throughput/prevYearThroughput/yoyRate", "disambiguate": "区别getTrendChart=需指定业务板块"}, {"path": "/api/gateway/getCumulativeTrendChart", "domain": "D2", "time": "T_CUM", "granularity": "G_BIZ", "intent": "查询业务板块年累计吞吐量趋势（含月度/累计双序列）", "tags": ["累计趋势", "月度+累计", "业务板块"], "required": ["businessSegment", "curDateYear", "yearDateYear"], "optional": [], "param_note": "", "returns": "月份序列：monthlyThroughput/cumulativeThroughput", "disambiguate": "区别getTrendChart=仅月度；getSumBusinessCockpitTrendChart=全港累计版"}, {"path": "/api/gateway/getSumBusinessCockpitTrendChart", "domain": "D2", "time": "T_CUM", "granularity": "G_PORT", "intent": "查询全港年累计吞吐量趋势（含月度/累计/去年同期三序列）", "tags": ["累计趋势", "全港", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy", "returns": "月份序列：monthlyThroughput/cumulativeThroughput/prevYearCumulative", "disambiguate": "区别getCumulativeTrendChart=按业务板块版"}, {"path": "/api/gateway/getKeyEnterprise", "domain": "D2", "time": "T_MON", "granularity": "G_CLIENT", "intent": "查询当月重点企业吞吐量排名（Top10，按业务板块）", "tags": ["重点企业", "排名", "当月", "贡献"], "required": ["businessSegment", "curDateMonth", "yearDateMonth"], "optional": [], "param_note": "", "returns": "rank/enterpriseName/throughput/contributionRate/yoyRate", "disambiguate": "区别getCumulativeKeyEnterprise=累计排名"}, {"path": "/api/gateway/getCumulativeKeyEnterprise", "domain": "D2", "time": "T_CUM", "granularity": "G_CLIENT", "intent": "查询年累计重点企业吞吐量排名", "tags": ["重点企业", "排名", "年累计"], "required": ["businessSegment", "curDateYear", "yearDateYear"], "optional": [], "param_note": "", "returns": "rank/enterpriseName/cumulativeThroughput/contributionRate", "disambiguate": "区别getKeyEnterprise=当月版"}, {"path": "/api/gateway/getCustomerQty", "domain": "D3", "time": "T_NONE", "granularity": "G_CLIENT", "intent": "查询客户总数量（含活跃/战略/新增统计）", "tags": ["客户数量", "战略客户数", "新增客户"], "required": [], "optional": [], "param_note": "无入参", "returns": "totalCustomers/activeCustomers/strategicCustomers/newCustomers", "disambiguate": ""}, {"path": "/api/gateway/getCustomerTypeAnalysis", "domain": "D3", "time": "T_NONE", "granularity": "G_CLIENT", "intent": "查询客户类型结构分析（货主/船公司/代理等分类及占比）", "tags": ["客户类型", "客户结构", "占比"], "required": [], "optional": [], "param_note": "无入参", "returns": "customerType/count/ratio", "disambiguate": "区别FieldAnalysis=按行业"}, {"path": "/api/gateway/getCustomerFieldAnalysis", "domain": "D3", "time": "T_NONE", "granularity": "G_CLIENT", "intent": "查询客户所属行业分析（钢铁/能源/汽车/粮食等）", "tags": ["行业分析", "客户行业", "货主行业"], "required": [], "optional": [], "param_note": "无入参", "returns": "field/count/ratio", "disambiguate": "区别TypeAnalysis=按客户类型"}, {"path": "/api/gateway/getStrategicCustomers", "domain": "D3", "time": "T_NONE", "granularity": "G_CLIENT", "intent": "查询战略客户名单及合作信息（级别/年份/合同状态）", "tags": ["战略客户", "客户名单", "合作级别"], "required": [], "optional": [], "param_note": "无入参，返回战略客户列表", "returns": "clientName/cooperationLevel/startYear/contractStatus", "disambiguate": ""}, {"path": "/api/gateway/getStrategicClientsEnterprises", "domain": "D3", "time": "T_NONE", "granularity": "G_CLIENT", "intent": "查询指定战略客户的关联企业及合作方式", "tags": ["战略客户", "关联企业", "合作方式"], "required": ["displayCode"], "optional": [], "param_note": "displayCode=战略客户编码", "returns": "enterpriseName/cooperationType/annualVolume", "disambiguate": ""}, {"path": "/api/gateway/getCustomerCredit", "domain": "D3", "time": "T_NONE", "granularity": "G_CLIENT", "intent": "查询客户信用级别和授信额度（已用/可用）", "tags": ["信用", "授信", "信用级别", "风险"], "required": ["orgName", "customerName", "gradeResult"], "optional": [], "param_note": "gradeResult=信用等级筛选值", "returns": "creditLevel/creditLimit/usedCredit/availableCredit/riskLevel", "disambiguate": ""}, {"path": "/api/gateway/getCumulativeContributionTrend", "domain": "D3", "time": "T_HIST", "granularity": "G_PORT", "intent": "查询多年战略客户累计贡献趋势（历年对比）", "tags": ["历年贡献", "多年对比", "累计贡献"], "required": ["startYear", "endYear", "contributionType"], "optional": [], "param_note": "startYear/endYear=年份范围", "returns": "年份序列：cumulativeThroughput/strategicContribution/contributionRate", "disambiguate": "区别getContributionTrend=单年vs上年月度对比"}, {"path": "/api/gateway/getStrategicCustomerContributionCustomerOperatingRevenue", "domain": "D3", "time": "T_MON", "granularity": "G_CLIENT", "intent": "查询当月战略客户营业收入贡献（商务驾驶舱版）", "tags": ["战略客户", "收入", "当月", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "clientName/operatingRevenue/revenueShare/yoyRate", "disambiguate": "区别getSumStrategicCustomer...Revenue=累计版"}, {"path": "/api/gateway/getCurStrategicCustomerContributionByCargoTypeThroughput", "domain": "D3", "time": "T_MON", "granularity": "G_CARGO", "intent": "查询当月战略客户按货类贡献的吞吐量", "tags": ["战略客户", "货类贡献", "当月", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "cargoType/strategicThroughput/contributionRate", "disambiguate": "区别Sum版=累计"}, {"path": "/api/gateway/getCurContributionRankOfStrategicCustomer", "domain": "D3", "time": "T_MON", "granularity": "G_CLIENT", "intent": "查询当月战略客户贡献排名（商务驾驶舱版）", "tags": ["战略客户排名", "当月排名", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "rank/clientName/throughput/contributionRate", "disambiguate": "区别Sum版=累计排名"}, {"path": "/api/gateway/getSumStrategicCustomerContributionCustomerOperatingRevenue", "domain": "D3", "time": "T_CUM", "granularity": "G_CLIENT", "intent": "查询年累计战略客户营业收入贡献排名", "tags": ["战略客户", "累计收入", "年累计"], "required": ["date"], "optional": [], "param_note": "date=yyyy", "returns": "clientName/cumulativeRevenue/revenueShare/yoyRate", "disambiguate": "区别Cur版=当月"}, {"path": "/api/gateway/getSumStrategyCustomerTrendAnalysis", "domain": "D3", "time": "T_HIST", "granularity": "G_CLIENT", "intent": "查询战略客户历年累计趋势分析", "tags": ["战略客户", "历年趋势", "累计趋势"], "required": [], "optional": [], "param_note": "无入参", "returns": "月份序列：cumulativeStrategicThroughput/cumulativeRevenue/contributionRate", "disambiguate": "区别Cur版=当年月度趋势"}, {"path": "/api/gateway/investCorpShareholdingProp", "domain": "D4", "time": "T_NONE", "granularity": "G_CMP", "intent": "查询投资企业持股比例分布（0-20%/20-50%/50%以上/全资）", "tags": ["持股比例", "投企", "股权结构"], "required": [], "optional": [], "param_note": "无入参", "returns": "shareholdingRange/count/ratio", "disambiguate": ""}, {"path": "/api/gateway/getMeetingInfo", "domain": "D4", "time": "T_MON", "granularity": "G_CMP", "intent": "查询指定月份董事会/监事会/股东大会召开数量及待处理议案", "tags": ["会议", "董事会", "监事会", "议案"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "boardMeetings/supervisorMeetings/shareholderMeetings/pendingMotions", "disambiguate": "区别getMeetDetail=单次会议明细"}, {"path": "/api/gateway/getMeetDetail", "domain": "D4", "time": "T_MON", "granularity": "G_CMP", "intent": "查询指定月份会议议案明细（按议案状态筛选）", "tags": ["议案明细", "董事会", "会议记录"], "required": ["date", "yianZt"], "optional": [], "param_note": "yianZt=议案状态编码", "returns": "meetingType/motionTitle/motionStatus/proposer", "disambiguate": "区别getMeetingInfo=汇总数量"}, {"path": "/api/gateway/getNewEnterprise", "domain": "D4", "time": "T_YR", "granularity": "G_CMP", "intent": "查询年内新设企业信息（注册时间/注册资本/业务范围）", "tags": ["新设企业", "新增", "注册资本"], "required": ["date"], "optional": [], "param_note": "date=yyyy", "returns": "enterpriseName/establishDate/registeredCapital/businessScope", "disambiguate": "区别getWithdrawalInfo=注销退出"}, {"path": "/api/gateway/getWithdrawalInfo", "domain": "D4", "time": "T_YR", "granularity": "G_CMP", "intent": "查询年内退出/注销企业信息", "tags": ["退出企业", "注销", "退股", "合并"], "required": ["date"], "optional": [], "param_note": "date=yyyy", "returns": "enterpriseName/withdrawalType/withdrawalDate/reason", "disambiguate": "区别getNewEnterprise=新设"}, {"path": "/api/gateway/getBusinessExpirationInfo", "domain": "D4", "time": "T_NONE", "granularity": "G_CMP", "intent": "查询营业执照即将到期的企业及续期状态", "tags": ["营业执照", "到期", "续期", "到期预警"], "required": ["date"], "optional": [], "param_note": "date=当前日期", "returns": "enterpriseName/businessLicenseExpiry/daysToExpiry/renewalStatus", "disambiguate": ""}, {"path": "/api/gateway/getSupervisorIncidentInfo", "domain": "D4", "time": "T_YR", "granularity": "G_CMP", "intent": "查询监管人员变动信息（新任/离任/调任）", "tags": ["人员变动", "董事长", "总经理", "监事"], "required": ["date"], "optional": [], "param_note": "date=yyyy", "returns": "enterpriseName/changeType/position/personName/changeDate", "disambiguate": ""}, {"path": "/api/gateway/getTotalssets", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询指定港区资产总数量（实物资产+金融资产）", "tags": ["资产总数", "实物资产", "金融资产"], "required": ["assetOwnerZone"], "optional": [], "param_note": "assetOwnerZone=港区名称", "returns": "totalCount/physicalAssetCount/financialAssetCount", "disambiguate": "区别getAssetValue=价值；getMainAssetsInfo=重要资产"}, {"path": "/api/gateway/getAssetValue", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询港区资产原值和净值（含折旧率）", "tags": ["资产价值", "原值", "净值", "折旧"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "originalValue/netValue/depreciationRate", "disambiguate": "区别getTotalssets=数量；getMainAssetsInfo=重要资产明细"}, {"path": "/api/gateway/getMainAssetsInfo", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询港区主要资产类别数量（设备/设施/房屋/土地）", "tags": ["主要资产", "设备数量", "设施", "房屋", "土地"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "equipmentCount/facilityCount/buildingCount/landCount/importantAssetNetValue", "disambiguate": ""}, {"path": "/api/gateway/getRealAssetsDistribution", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询实物资产类型分布（设备/设施/房屋/土地数量占比）", "tags": ["资产分布", "类型分布", "实物资产"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "assetType/count/ratio", "disambiguate": ""}, {"path": "/api/gateway/getOriginalValueDistribution", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询各类资产原值分布", "tags": ["原值分布", "资产原值"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "assetType/originalValue/ratio", "disambiguate": "区别getRealAssetsDistribution=数量分布"}, {"path": "/api/gateway/getDistributionOfImportantAssetNetValueRanges", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询重要资产净值区间分布（1000万以下/1000-5000万等）", "tags": ["净值区间", "重要资产", "价值分布"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "range/count/totalNetValue", "disambiguate": ""}, {"path": "/api/gateway/getFinancialAssetsDistribution", "domain": "D5", "time": "T_NONE", "granularity": "G_PORT", "intent": "查询金融资产类型分布（股权/应收款/债券/基金）", "tags": ["金融资产", "股权投资", "应收账款", "分布"], "required": [], "optional": [], "param_note": "无入参", "returns": "assetType/count/ratio", "disambiguate": "区别NetValue=净值分布"}, {"path": "/api/gateway/getFinancialAssetsNetValueDistribution", "domain": "D5", "time": "T_NONE", "granularity": "G_PORT", "intent": "查询金融资产净值分布（各类型价值占比）", "tags": ["金融资产净值", "价值分布", "股权投资价值"], "required": [], "optional": [], "param_note": "无入参", "returns": "assetType/netValue/ratio", "disambiguate": "区别Distribution=数量分布"}, {"path": "/api/gateway/getHistoricalTrends", "domain": "D5", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询港区资产历年变化趋势（2022-2026，数量/原值/净值/新增/报废）", "tags": ["历年趋势", "资产变化", "历史数据"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "年份序列：totalCount/totalOriginalValue/newAdded/scrapped", "disambiguate": ""}, {"path": "/api/gateway/getRealAssetQty", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询本年新增实物资产数量和价值", "tags": ["新增资产", "年度新增", "资产数量"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "newAddedThisYear/newAddedValue/yoyCountChange", "disambiguate": "区别getMothballingRealAssetQty=报废封存"}, {"path": "/api/gateway/getMothballingRealAssetQty", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询本年报废/封存资产数量和价值", "tags": ["报废资产", "封存", "资产减少"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "scrappedThisYear/scrappedValue/mothballedThisYear", "disambiguate": "区别getRealAssetQty=新增"}, {"path": "/api/gateway/getTrendNewAssets", "domain": "D5", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年新增资产趋势（数量+价值）", "tags": ["新增趋势", "历年新增", "资产新增"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "年份序列：newCount/newValue", "disambiguate": "区别getTrendScrappedAssets=报废趋势"}, {"path": "/api/gateway/getTrendScrappedAssets", "domain": "D5", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年报废资产趋势", "tags": ["报废趋势", "历年报废"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "年份序列：scrappedCount/scrappedValue", "disambiguate": "区别getTrendNewAssets=新增趋势"}, {"path": "/api/gateway/getOriginalQuantity", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询本年新增资产原始数量和原值", "tags": ["新增数量", "原值", "年度"], "required": ["ownerZone", "dateYear"], "optional": [], "param_note": "", "returns": "newAddedCount/newAddedOriginalValue", "disambiguate": ""}, {"path": "/api/gateway/getOriginalValueScrappedQuantity", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询本年报废资产数量及原值", "tags": ["报废数量", "原值", "年度报废"], "required": ["ownerZone", "dateYear"], "optional": [], "param_note": "", "returns": "scrappedCount/scrappedOriginalValue", "disambiguate": ""}, {"path": "/api/gateway/getNewAssetTransparentAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_CMP", "intent": "查询各公司新增资产穿透分析（数量/价值/主要类别）", "tags": ["新增穿透", "公司新增", "透明分析"], "required": ["ownerZone", "dateYear", "asseTypeName"], "optional": [], "param_note": "asseTypeName=资产类型名称（注意拼写：asseTypeName无t）", "returns": "companyName/newCount/newOriginalValue/mainCategory", "disambiguate": "区别ScrapAsset=报废穿透"}, {"path": "/api/gateway/getScrapAssetTransmitAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_CMP", "intent": "查询各公司报废资产穿透分析", "tags": ["报废穿透", "公司报废", "透明分析"], "required": ["ownerZone", "dateYear", "asseTypeName"], "optional": [], "param_note": "asseTypeName=资产类型名（注意拼写）", "returns": "companyName/scrappedCount/scrappedOriginalValue", "disambiguate": "区别NewAsset=新增穿透"}, {"path": "/api/gateway/getPhysicalAssets", "domain": "D5", "time": "T_YR", "granularity": "G_PORT", "intent": "查询全港实物资产汇总（总数量/原值/净值）", "tags": ["实物资产汇总", "总量", "原值净值"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "totalPhysicalAssets/totalOriginalValue/totalNetValue", "disambiguate": ""}, {"path": "/api/gateway/getRegionalAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区资产数量/原值/净值对比", "tags": ["港区资产", "区域对比", "资产分布"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "ownerZone/assetCount/originalValue/netValue/shareRatio", "disambiguate": ""}, {"path": "/api/gateway/getCategoryAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询各类别资产数量/原值/净值（设备/设施/房屋/土地）", "tags": ["资产类别", "类型分析", "设备设施房屋土地"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "assetTypeName/count/originalValue/netValue/shareRatio", "disambiguate": "区别getRegionalAnalysis=按港区"}, {"path": "/api/gateway/getRegionalAnalysisTransparentTransmission", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询指定港区各类型资产穿透详情", "tags": ["区域穿透", "港区详情", "类型细分"], "required": ["dateYear", "ownerZone"], "optional": [], "param_note": "", "returns": "assetTypeName/count/originalValue/netValue", "disambiguate": ""}, {"path": "/api/gateway/getCategoryAnalysisTransparentTransmission", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询指定类型资产按港区穿透详情", "tags": ["类型穿透", "资产类型", "港区细分"], "required": ["dateYear", "assetTypeName"], "optional": [], "param_note": "", "returns": "ownerZone/count/originalValue/netValue", "disambiguate": ""}, {"path": "/api/gateway/getHousingAssertAnalysisTransparentTransmission", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询房屋资产穿透分析（按港区/用房类型/面积/价值）", "tags": ["房屋资产", "房屋穿透", "建筑面积"], "required": ["dateYear"], "optional": ["ownerZone"], "param_note": "", "returns": "ownerZone/buildingType/count/area/originalValue", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentFacilityStateDistribution", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询设备设施运行状态分布（正常/维修/闲置/报废申请）", "tags": ["设备状态", "状态分布", "维修", "闲置"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "status/count/ratio", "disambiguate": "区别D7的EquipmentUsageRate=利用率指标"}, {"path": "/api/gateway/getEquipmentFacilityAnalysisYoy", "domain": "D5", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询设备设施数量和净值同比变化", "tags": ["设备同比", "净值同比", "设施同比"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "currentCount/prevYearCount/yoyCountChange/yoyValueRate", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentFacilityAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询设备或设施分类分析（type=1设备/type=2设施）", "tags": ["设备分类", "设施分类", "装卸设备", "运输设备"], "required": ["dateYear", "type"], "optional": [], "param_note": "type=1查设备；type=2查设施", "returns": "category/count/netValue", "disambiguate": "区别StatusAnalysis=按状态；RegionalAnalysis=按港区"}, {"path": "/api/gateway/getEquipmentFacilityStatusAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询设备/设施按状态分布（正常/维修/超期/闲置等）", "tags": ["状态分析", "设备状态", "超期服役"], "required": ["dateYear", "type"], "optional": [], "param_note": "type=1设备/2设施", "returns": "status/count/ratio", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentFacilityRegionalAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区设备/设施数量和净值分布", "tags": ["区域分析", "设备区域", "港区设备"], "required": ["dateYear", "type"], "optional": [], "param_note": "type=1设备/2设施", "returns": "ownerZone/count/netValue/shareRatio", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentFacilityWorthAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询设备/设施净值区间分布", "tags": ["净值区间", "设备价值", "价值分布"], "required": ["dateYear", "type"], "optional": [], "param_note": "type=设备/设施名称字符串", "returns": "netValueRange/count/totalNetValue", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentAnalysisTransparentTransmissionByFirst", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询设备二级子类穿透分析", "tags": ["设备子类", "设备穿透", "二级分类"], "required": ["dateYear"], "optional": ["assetStatus", "assetTypeName", "firstLevelClassName"], "param_note": "", "returns": "equipmentSubType/status/count/avgAge/netValue", "disambiguate": "区别无ByFirst=一级穿透"}, {"path": "/api/gateway/getLandMaritimeAnalysisTransparentTransmission", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询土地和海域资产穿透分析（面积/价值按港区）", "tags": ["土地", "海域", "面积", "港区"], "required": ["dateYear"], "optional": ["ownerZone"], "param_note": "", "returns": "ownerZone/landArea/seaArea/landValue/seaValue", "disambiguate": ""}, {"path": "/api/gateway/getHousingAnalysisYoy", "domain": "D5", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询房屋资产同比（数量/面积/净值）", "tags": ["房屋同比", "建筑面积", "净值同比"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "currentCount/currentArea/currentNetValue/yoyNetValueRate", "disambiguate": ""}, {"path": "/api/gateway/getHousingRegionalAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区房屋资产（数量/面积/净值）", "tags": ["房屋资产", "按港区", "建筑面积"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "ownerZone/count/area/netValue", "disambiguate": ""}, {"path": "/api/gateway/getHousingWorthAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询房屋资产净值区间分布", "tags": ["房屋净值", "价值区间"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "netValueRange/count/totalNetValue", "disambiguate": ""}, {"path": "/api/gateway/getLandMaritimeAnalysisYoy", "domain": "D5", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询土地海域资产同比（面积/净值）", "tags": ["土地同比", "海域同比", "亩"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "totalLandArea/totalSeaArea/landNetValue/yoyNetValueRate", "disambiguate": ""}, {"path": "/api/gateway/getLandMaritimeRegionalAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区土地海域面积和净值", "tags": ["土地按港区", "海域", "面积"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "ownerZone/landArea/seaArea/totalNetValue", "disambiguate": ""}, {"path": "/api/gateway/getLandMaritimeWorthAnalysis", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询土地海域资产类型价值分析（工业/港口/绿化/海域使用权）", "tags": ["土地类型", "海域价值", "单价"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "assetSubType/totalArea/totalNetValue/pricePerUnit", "disambiguate": ""}, {"path": "/api/gateway/getImportAssertAnalysisList", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询重要资产明细列表（支持多条件筛选，分页）", "tags": ["资产列表", "明细", "分页"], "required": ["dateYear"], "optional": ["portCode", "assetTypeId", "assetTypeName", "ownerZone"], "param_note": "分页：pageNo/pageSize", "returns": "assetCode/assetName/assetType/originalValue/netValue/status", "disambiguate": ""}, {"path": "/api/gateway/getImportAssetWorthAnalysisByOwnerZone", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区重要资产净值分析（按净值区间筛选）", "tags": ["重要资产", "净值分析", "港区"], "required": ["dateYear", "type", "minNum", "maxNum", "typeName"], "optional": [], "param_note": "minNum/maxNum=净值区间（万元）", "returns": "ownerZone/count/netValue/shareRatio", "disambiguate": "区别ByCmpName=按公司"}, {"path": "/api/gateway/getImportAssetWorthAnalysisByCmpName", "domain": "D5", "time": "T_YR", "granularity": "G_CMP", "intent": "查询各公司重要资产净值分析", "tags": ["重要资产", "净值分析", "公司"], "required": ["dateYear", "type", "minNum", "maxNum", "ownerZone", "typeName"], "optional": [], "param_note": "minNum/maxNum=净值区间（万元）", "returns": "companyName/count/netValue", "disambiguate": "区别ByOwnerZone=按港区"}, {"path": "/api/gateway/getActualPerformance", "domain": "D1", "time": "T_DAY", "granularity": "G_PORT", "intent": "查询昨日吞吐量实际完成情况及环比（驾驶舱首页）", "tags": ["昨日完成", "实际吞吐", "日报"], "required": [], "optional": ["yesterday", "lastMonthDay"], "param_note": "yesterday=yyyy-MM-dd；lastMonthDay=环比参考日", "returns": "yesterdayThroughput/lastMonthDayThroughput/momRate/byBusinessType", "disambiguate": ""}, {"path": "/api/gateway/getMonthlyTrendThroughput", "domain": "D1", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询指定时间段月度吞吐量趋势序列", "tags": ["月度趋势", "时间段", "趋势序列"], "required": ["endDate", "startDate"], "optional": [], "param_note": "startDate/endDate=yyyy-MM", "returns": "月份序列：throughput/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getNetValueDistribution", "domain": "D5", "time": "T_NONE", "granularity": "G_ZONE", "intent": "查询各港区资产净值区间分布（test路径版）", "tags": ["净值分布", "区间分布", "港区"], "required": ["ownerZone"], "optional": [], "param_note": "", "returns": "ownerZone/netValueRanges", "disambiguate": ""}, {"path": "/api/gateway/getlnportDispatchPort", "domain": "D1", "time": "T_DAY", "granularity": "G_ZONE", "intent": "查询指定日期各港区日班/夜班吞吐量调度数据", "tags": ["调度", "日班", "夜班", "港区"], "required": ["dispatchDate"], "optional": [], "param_note": "dispatchDate=yyyy-MM-dd", "returns": "regionName/dayShift/nightShift/inPortShips", "disambiguate": "区别Wharf=按码头"}, {"path": "/api/gateway/getlnportDispatchWharf", "domain": "D1", "time": "T_DAY", "granularity": "G_CMP", "intent": "查询指定日期各码头日班/夜班吞吐量调度数据", "tags": ["调度", "码头", "日班", "夜班"], "required": ["dispatchDate"], "optional": [], "param_note": "dispatchDate=yyyy-MM-dd", "returns": "wharfName/dayShift/nightShift/operationRate", "disambiguate": "区别Port=按港区"}, {"path": "/api/gateway/getInvestPlanTypeProjectList", "domain": "D6", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询年度投资计划类型汇总（资本性/成本性/计划外项目数和金额）", "tags": ["投资计划", "资本项目", "成本项目", "计划外"], "required": [], "optional": ["ownerLgZoneName", "currYear"], "param_note": "", "returns": "capitalProjects/costProjects/unplannedProjects/totalApproved", "disambiguate": ""}, {"path": "/api/gateway/getPlanProgressByMonth", "domain": "D6", "time": "T_TREND", "granularity": "G_ZONE", "intent": "查询年度投资计划月度进度（累计计划vs实际完成）", "tags": ["投资进度", "月度进度", "计划完成率"], "required": [], "optional": ["ownerLgZoneName", "startMonth", "endMonth"], "param_note": "", "returns": "月份序列：plannedAmount/actualAmount/progressRatio", "disambiguate": ""}, {"path": "/api/gateway/planInvestAndPayYoy", "domain": "D6", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询年度投资计划和付款额同比", "tags": ["投资同比", "付款同比", "年度对比"], "required": [], "optional": ["currYear", "preYear", "ownerLgZoneName"], "param_note": "", "returns": "currInvestPlan/prevInvestPlan/investYoyRate/currPayAmount/payYoyRate", "disambiguate": ""}, {"path": "/api/gateway/getFinishProgressAndDeliveryRate", "domain": "D6", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询年度投资完成进度和资本项目交付率", "tags": ["完成进度", "交付率", "资本项目"], "required": [], "optional": ["ownerLgZoneName", "currYear"], "param_note": "", "returns": "completionRate/deliveredProjects/deliveryRate", "disambiguate": ""}, {"path": "/api/gateway/getInvestPlanByYear", "domain": "D6", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年投资计划和完成情况历年对比", "tags": ["历年投资", "投资趋势", "完成率"], "required": [], "optional": ["ownerLgZoneName"], "param_note": "", "returns": "年份序列：approvedAmount/completedAmount/completionRate", "disambiguate": ""}, {"path": "/api/gateway/getCostProjectFinishByYear", "domain": "D6", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年成本性项目完成情况", "tags": ["成本项目", "历年完成", "成本投资"], "required": [], "optional": ["ownerLgZoneName"], "param_note": "", "returns": "年份序列：projectCount/approvedAmount/completedAmount", "disambiguate": ""}, {"path": "/api/gateway/getCostProjectYoyList", "domain": "D6", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询成本性项目数量和金额同比", "tags": ["成本项目", "同比", "年度对比"], "required": [], "optional": ["currYear", "preYear"], "param_note": "", "returns": "currProjectCount/prevProjectCount/countYoyRate/amountYoyRate", "disambiguate": ""}, {"path": "/api/gateway/getCostProjectQtyList", "domain": "D6", "time": "T_YR", "granularity": "G_PORT", "intent": "查询成本性项目分类数量和金额占比", "tags": ["成本项目分类", "设备维修", "安全整改"], "required": [], "optional": ["currYear"], "param_note": "", "returns": "category/count/ratio/amount", "disambiguate": ""}, {"path": "/api/gateway/getCostProjectAmtByOwnerLgZoneName", "domain": "D6", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区成本性项目金额（批复/完成/招标）", "tags": ["成本项目", "按港区", "招标金额"], "required": [], "optional": ["currYear"], "param_note": "", "returns": "ownerLgZoneName/approvedAmount/completedAmount/bidAmount", "disambiguate": ""}, {"path": "/api/gateway/getCostProjectCurrentStageQtyList", "domain": "D6", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询成本性项目当前阶段数量（立项/招标/施工/竣工等）", "tags": ["项目阶段", "施工阶段", "进度"], "required": [], "optional": ["currYear", "ownerLgZoneName"], "param_note": "", "returns": "stage/count", "disambiguate": ""}, {"path": "/api/gateway/getCostProjectQtyByProjectCmp", "domain": "D6", "time": "T_YR", "granularity": "G_CMP", "intent": "查询各公司成本性项目数量和完成情况", "tags": ["成本项目", "按公司", "完成率"], "required": [], "optional": ["dateYear", "zoneName"], "param_note": "", "returns": "companyName/projectCount/approvedAmount/completionRate", "disambiguate": ""}, {"path": "/api/gateway/getInvestAmtList", "domain": "D6", "time": "T_YR", "granularity": "G_PROJ", "intent": "查询投资项目金额明细列表（分页，支持多条件筛选）", "tags": ["投资明细", "项目列表", "分页"], "required": ["dateYear"], "optional": ["projectCmp", "projectName", "projectNo", "adminName", "currentStage", "zoneName"], "param_note": "分页：pageNo/pageSize", "returns": "projectName/projectCmp/approvedAmount/completedAmount/startDate", "disambiguate": ""}, {"path": "/api/gateway/getOutOfPlanFinishProgressList", "domain": "D6", "time": "T_YR", "granularity": "G_PORT", "intent": "查询计划外项目完成进度汇总", "tags": ["计划外", "完成进度", "未计划项目"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "totalCount/completedCount/completionRate/totalAmount", "disambiguate": ""}, {"path": "/api/gateway/getOutOfPlanProjectQtyYoy", "domain": "D6", "time": "T_YOY", "granularity": "G_PORT", "intent": "查询计划外项目数量和金额同比", "tags": ["计划外", "同比", "年度对比"], "required": [], "optional": ["currYear", "preYear"], "param_note": "", "returns": "currCount/prevCount/countYoyRate/amountYoyRate", "disambiguate": ""}, {"path": "/api/gateway/getOutOfPlanProjectInvestFinishList", "domain": "D6", "time": "T_HIST", "granularity": "G_PORT", "intent": "查询计划外项目近5年投资完成历史", "tags": ["计划外", "历年", "投资完成"], "required": [], "optional": [], "param_note": "无入参", "returns": "年份序列：projectCount/approvedAmount/completionRate", "disambiguate": ""}, {"path": "/api/gateway/getOutOfPlanProjectPayFinishList", "domain": "D6", "time": "T_HIST", "granularity": "G_PORT", "intent": "查询计划外项目近5年付款完成历史", "tags": ["计划外", "付款", "历年"], "required": [], "optional": [], "param_note": "无入参", "returns": "年份序列：approvedAmount/paidAmount/paymentRate", "disambiguate": ""}, {"path": "/api/gateway/getPlanFinishByZone", "domain": "D6", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区投资计划完成情况和交付率", "tags": ["各港区", "投资完成", "交付率"], "required": [], "optional": ["currYear"], "param_note": "", "returns": "ownerLgZoneName/approvedAmount/completionRate/deliveryRate", "disambiguate": ""}, {"path": "/api/gateway/getPlanFinishByProjectType", "domain": "D6", "time": "T_YR", "granularity": "G_PROJ", "intent": "查询各项目类型完成情况（技改/新建/扩建/维护改造/安全环保）", "tags": ["项目类型", "技改", "新建", "完成率"], "required": [], "optional": [], "param_note": "无入参", "returns": "projectType/count/approvedAmount/completionRate", "disambiguate": ""}, {"path": "/api/gateway/getPlanExcludedProjectPenetrationAnalysis", "domain": "D6", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询计划外项目按港区/类型的穿透分析", "tags": ["计划外穿透", "按港区", "按类型"], "required": [], "optional": ["ownerLgZoneName", "investProjectType", "dateYear"], "param_note": "", "returns": "ownerLgZoneName/investProjectType/count/approvedAmount", "disambiguate": ""}, {"path": "/api/gateway/getUnplannedProjectsInquiry", "domain": "D6", "time": "T_YR", "granularity": "G_PROJ", "intent": "查询计划外项目明细查询（分页）", "tags": ["计划外明细", "项目查询", "分页"], "required": [], "optional": ["dateYear", "regionName", "proMainTypeName"], "param_note": "", "returns": "projectName/regionName/approvedAmount/status", "disambiguate": ""}, {"path": "/api/gateway/getCapitalApprovalAnalysisLimitInquiry", "domain": "D6", "time": "T_YR", "granularity": "G_PORT", "intent": "查询资本性项目批复金额/完成/付款汇总分析", "tags": ["资本项目", "批复金额", "付款率"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "totalApprovedAmount/completedAmount/paymentRate", "disambiguate": ""}, {"path": "/api/gateway/getCapitalApprovalAnalysisProject", "domain": "D6", "time": "T_YR", "granularity": "G_PROJ", "intent": "查询各项目类型资本性项目批复分析", "tags": ["资本项目", "项目类型", "批复"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "projectType/count/approvedAmount/completionRate", "disambiguate": ""}, {"path": "/api/gateway/getVisualProgressAnalysisAndStatistics", "domain": "D6", "time": "T_YR", "granularity": "G_PORT", "intent": "查询资本性项目建设阶段分布（前期/施工/竣工验收/交付）", "tags": ["建设阶段", "进度分布", "资本项目"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "stageDistribution/totalCapitalProjects", "disambiguate": ""}, {"path": "/api/gateway/getCompletionStatus", "domain": "D6", "time": "T_YR", "granularity": "G_PORT", "intent": "查询资本性项目年度完成状态（金额完成率+项目完成率）", "tags": ["完成状态", "资本项目", "完成率"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "planApprovedAmount/actualCompletedAmount/completionRate/projectCompletionRate", "disambiguate": ""}, {"path": "/api/gateway/getDeliveryRate", "domain": "D6", "time": "T_YR", "granularity": "G_PORT", "intent": "查询资本性项目交付率（已交付/按时交付）", "tags": ["交付率", "按时交付", "资本项目"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "capitalProjects/deliveredProjects/deliveryRate/onTimeDeliveryRate", "disambiguate": ""}, {"path": "/api/gateway/getNumberCapitalProjectsDelivered", "domain": "D6", "time": "T_YR", "granularity": "G_PORT", "intent": "查询已交付资本性项目数量和价值", "tags": ["已交付", "交付数量", "资本项目"], "required": [], "optional": ["dateYear"], "param_note": "", "returns": "deliveredCount/deliveredValue/deliveryRate", "disambiguate": "区别ByZone=按港区；ByPlan=按类型"}, {"path": "/api/gateway/getNumberCapitalProjectsDeliveredZoneName", "domain": "D6", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区当月资本性项目交付数量", "tags": ["交付", "按港区", "月度"], "required": [], "optional": ["dateMonth"], "param_note": "", "returns": "ownerLgZoneName/deliveredCount/deliveredValue", "disambiguate": ""}, {"path": "/api/gateway/getRegionalInvestmentQuota", "domain": "D6", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区投资额度使用情况（批复/已用/使用率）", "tags": ["投资额度", "按港区", "额度使用"], "required": [], "optional": ["dateMonth"], "param_note": "", "returns": "ownerLgZoneName/approvedQuota/usedQuota/usageRate", "disambiguate": ""}, {"path": "/api/gateway/getNumberCapitalProjectsDeliveredPlanAnalysis", "domain": "D6", "time": "T_MON", "granularity": "G_PROJ", "intent": "查询各计划类型资本性项目交付率", "tags": ["交付分析", "计划类型", "交付率"], "required": [], "optional": ["dateMonth"], "param_note": "", "returns": "planType/totalCount/deliveredCount/deliveryRate", "disambiguate": ""}, {"path": "/api/gateway/getTypeAnalysisInvestmentAmountQuery", "domain": "D6", "time": "T_MON", "granularity": "G_PROJ", "intent": "查询各项目类型投资金额完成情况（月度）", "tags": ["项目类型", "月度金额", "完成率"], "required": [], "optional": ["dateMonth"], "param_note": "", "returns": "projectType/approvedAmount/completedAmount/completionRate", "disambiguate": ""}, {"path": "/api/gateway/getCapitalProjectsList", "domain": "D6", "time": "T_YR", "granularity": "G_PROJ", "intent": "查询资本性项目明细列表（分页，支持多维度筛选）", "tags": ["资本项目", "明细列表", "分页"], "required": [], "optional": ["projectName", "investProjectType", "projectCurrentStage", "investProjectStatus", "ownerDept", "dateYear", "dateMonth", "ownerLgZoneName"], "param_note": "分页：pageNo/pageSize", "returns": "projectName/approvedAmount/completedAmount/visualProgress/deliveryStatus", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentIndicatorOperationQty", "domain": "D7", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区设备作业量指标（集装箱/散货，月度）", "tags": ["设备作业量", "指标", "月度", "港区"], "required": ["dateMonth"], "optional": ["ownerZone", "cmpName"], "param_note": "dateMonth=yyyy-MM", "returns": "ownerZone/totalWorkingQty/containerQty/bulkQty/yoyRate", "disambiguate": "区别getEquipmentIndicatorUseCost=使用成本"}, {"path": "/api/gateway/getEquipmentIndicatorUseCost", "domain": "D7", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区设备使用成本指标（燃油/电力/维修，月度）", "tags": ["设备成本", "燃油", "电力", "维修"], "required": ["dateMonth"], "optional": ["ownerZone", "cmpName"], "param_note": "", "returns": "ownerZone/totalCost/fuelCost/electricityCost/maintenanceCost", "disambiguate": "区别OperationQty=作业量"}, {"path": "/api/gateway/getProductionEquipmentFaultNum", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询生产设备年度故障次数（重大/一般，含同比）", "tags": ["故障次数", "设备故障", "维修"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName"], "param_note": "", "returns": "totalFaults/majorFaults/minorFaults/avgRepairHours/yoyFaultChange", "disambiguate": ""}, {"path": "/api/gateway/getProductionEquipmentStatistic", "domain": "D7", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询生产设备月度概览（总数/在用/完好率/利用率/平均役龄）", "tags": ["设备概览", "完好率", "利用率", "役龄"], "required": ["dateMonth"], "optional": ["ownerZone"], "param_note": "", "returns": "totalEquipCount/integrityRate/utilizationRate/avgAge", "disambiguate": ""}, {"path": "/api/gateway/getProductionEquipmentServiceAgeDistribution", "domain": "D7", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询生产设备役龄分布（0-5年/5-10年/10-15年等）", "tags": ["役龄分布", "设备年龄", "老化"], "required": ["dateMonth"], "optional": ["ownerZone", "machineName"], "param_note": "", "returns": "ageRange/count/ratio", "disambiguate": ""}, {"path": "/api/gateway/getOverviewQuery", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询单台设备综合概览（完好率/台时效率/单耗/作业量/成本，单据大屏）", "tags": ["单机概览", "设备综合", "单据大屏"], "required": ["date", "equipmentNo", "ownerLgZoneName", "cmpName", "firstLevelClassName"], "optional": [], "param_note": "equipmentNo=设备编号；若查看整体，equipmentNo可传空", "returns": "integrityRate/utilizationRate/unitHourEfficiency/unitConsumption/totalCost", "disambiguate": ""}, {"path": "/api/gateway/getSingleEquipmentIntegrityRate", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询单台设备完好率及月度趋势", "tags": ["单机完好率", "完好率趋势"], "required": ["equipmentNo"], "optional": [], "param_note": "", "returns": "currentMonthRate/yearAvgRate/trend", "disambiguate": "区别getMachineDataDisplayScreenEquipmentIntegrityRate=机种级完好率"}, {"path": "/api/gateway/getUnitHourEfficiency", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询单台设备台时效率及月度趋势", "tags": ["台时效率", "单机效率", "自然箱/小时"], "required": ["equipmentNo"], "optional": [], "param_note": "", "returns": "currentMonthEfficiency/yearAvgEfficiency/trend", "disambiguate": ""}, {"path": "/api/gateway/getUnitConsumption", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询单台设备能源单耗及月度趋势（燃油+电力）", "tags": ["单耗", "能耗", "燃油", "电力", "单台"], "required": ["equipmentNo"], "optional": [], "param_note": "", "returns": "currentMonthConsumption/fuelConsumption/electricityConsumption", "disambiguate": ""}, {"path": "/api/gateway/getSingleMachineUtilization", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询单台设备利用率及有效利用率月度趋势", "tags": ["利用率", "有效利用率", "单台"], "required": ["equipmentNo"], "optional": [], "param_note": "", "returns": "currentMonthRate/effectiveUtilizationRate/trend", "disambiguate": ""}, {"path": "/api/gateway/getSingleCost", "domain": "D7", "time": "T_YR", "granularity": "G_EQUIP", "intent": "查询单台设备年度成本（燃油/电力/维修/其他及单位成本）", "tags": ["单机成本", "设备成本", "维修费"], "required": ["equipmentNo"], "optional": [], "param_note": "", "returns": "totalCostThisYear/fuelCost/maintenanceCost/costPerUnit", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentUsageRate", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区年度设备利用率（含月度分布曲线）", "tags": ["利用率", "年度利用率", "港区", "月度分布"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName", "firstLevelClassName"], "param_note": "", "returns": "ownerZone/annualUsageRate/byMonth", "disambiguate": "区别getProductEquipmentUsageRateByYear=历年对比；BYMonth=月度版"}, {"path": "/api/gateway/getEquipmentServiceableRate", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区年度设备完好率（含月度分布）", "tags": ["完好率", "年度完好率", "港区"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName", "firstLevelClassName"], "param_note": "", "returns": "ownerZone/annualServiceableRate/byMonth", "disambiguate": "区别getProductEquipmentIntegrityRateByYear=历年版"}, {"path": "/api/gateway/getEquipmentFirstLevelClassNameList", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询设备一级分类列表及数量（装卸/运输/起重/输送/特种）", "tags": ["设备分类", "一级分类", "分类列表"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName"], "param_note": "", "returns": "firstLevelClassName/count", "disambiguate": ""}, {"path": "/api/gateway/getContainerMachineHourRate", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询集装箱装卸设备台时效率（岸桥/RTG分项，月度曲线）", "tags": ["集装箱台时", "岸桥", "RTG", "月度"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName", "firstLevelClassName"], "param_note": "", "returns": "avgContainerMachineHourRate/quayCraneRate/rtgRate/byMonth", "disambiguate": "区别getEquipmentMachineHourRate=全类设备"}, {"path": "/api/gateway/getEquipmentEnergyConsumptionPerUnit", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区年度设备能源单耗（含月度趋势）", "tags": ["能源单耗", "年度", "港区", "kgce"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName", "firstLevelClassName"], "param_note": "", "returns": "ownerZone/annualEnergyPerUnit/byMonth", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentFuelOilTonCost", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区年度燃油吨成本（元/自然箱，月度趋势）", "tags": ["燃油成本", "吨成本", "元/自然箱"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName", "firstLevelClassName"], "param_note": "", "returns": "ownerZone/fuelOilTonCost/yoyRate/byMonth", "disambiguate": "区别getEquipmentElectricityTonCost=电量成本"}, {"path": "/api/gateway/getEquipmentElectricityTonCost", "domain": "D7", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询各港区年度电量吨成本（元/自然箱，月度趋势）", "tags": ["电量成本", "电费", "元/自然箱"], "required": ["dateYear"], "optional": ["ownerZone", "cmpName", "firstLevelClassName"], "param_note": "", "returns": "ownerZone/electricityTonCost/yoyRate/byMonth", "disambiguate": "区别FuelOil=燃油成本"}, {"path": "/api/gateway/getMachineDataDisplayScreenHourlyEfficiency", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询指定机种当月台时效率及各台设备明细（机种展示屏）", "tags": ["机种台时", "机种展示", "月度"], "required": ["secondLevelClassName", "date"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "secondLevelClassName=设备二级分类（如岸桥/门机）；date=yyyy-MM", "returns": "currentMonthAvg/yoyRate/byEquipment明细", "disambiguate": "区别getEquipmentMachineHourRate=港区汇总版"}, {"path": "/api/gateway/getModelDataDisplayScreenEnergyConsumptionPerUnit", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询指定机种当月能耗单耗（机种展示屏）", "tags": ["机种能耗", "单耗", "月度"], "required": ["secondLevelClassName", "date"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "avgConsumption/fuelConsumption/electricityConsumption", "disambiguate": ""}, {"path": "/api/gateway/getFuelTonCostOfAircraftDataDisplay", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询指定机种燃油吨成本（机种展示屏）", "tags": ["机种燃油", "燃油成本", "月度"], "required": ["secondLevelClassName", "date"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "fuelTonCost/prevYearSameMonth/yoyRate", "disambiguate": "区别getEquipmentFuelOilTonCost=港区汇总版"}, {"path": "/api/gateway/getMachineTypeDataDisplayScreenPowerConsumptionCostPerTon", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询指定机种电量吨成本（机种展示屏）", "tags": ["机种电量", "电量成本", "月度"], "required": ["secondLevelClassName", "date"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "electricityTonCost/prevYearSameMonth/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getModelDataDisplayScreenUtilization", "domain": "D7", "time": "T_YR", "granularity": "G_EQUIP", "intent": "查询指定机种年度利用率（机种展示屏）", "tags": ["机种利用率", "年度", "月度分布"], "required": ["secondLevelClassName", "dateYear"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "annualUtilizationRate/byMonth", "disambiguate": ""}, {"path": "/api/gateway/getModelDataDisplayScreenEffectiveUtilization", "domain": "D7", "time": "T_YR", "granularity": "G_EQUIP", "intent": "查询指定机种年度有效利用率（机种展示屏）", "tags": ["机种有效利用率", "年度"], "required": ["secondLevelClassName", "dateYear"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "annualEffectiveUtilRate/byMonth", "disambiguate": "区别getModelDataDisplayScreenUtilization=总利用率"}, {"path": "/api/gateway/getMachineDataDisplayScreenEquipmentIntegrityRate", "domain": "D7", "time": "T_YR", "granularity": "G_EQUIP", "intent": "查询指定机种年度完好率（机种展示屏）", "tags": ["机种完好率", "年度"], "required": ["secondLevelClassName", "dateYear"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "annualIntegrityRate/byMonth", "disambiguate": ""}, {"path": "/api/gateway/getModelDataDisplayScreenHierarchyRelation", "domain": "D7", "time": "T_NONE", "granularity": "G_EQUIP", "intent": "查询设备二级分类的层级关系（判断是否属于集装箱设备）", "tags": ["层级关系", "集装箱设备", "分类归属"], "required": ["secondLevelClassName"], "optional": [], "param_note": "", "returns": "firstLevelClassName/isContainerEquipment/relatedEquipCount", "disambiguate": ""}, {"path": "/api/gateway/getMachineDataDisplayEquipmentReliability", "domain": "D7", "time": "T_YR", "granularity": "G_EQUIP", "intent": "查询集装箱设备可靠性指标（MTBF/MTTR/故障次数，机种展示屏）", "tags": ["可靠性", "MTBF", "MTTR", "集装箱设备"], "required": ["secondLevelClassName", "dateYear"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "mtbf/mttr/reliability/faultCount", "disambiguate": "区别getNonContainer=非集装箱版"}, {"path": "/api/gateway/getNonContainerProductionEquipmentReliability", "domain": "D7", "time": "T_YR", "granularity": "G_EQUIP", "intent": "查询非集装箱设备可靠性指标（散货/油化/滚装）", "tags": ["可靠性", "非集装箱", "散货设备", "MTBF"], "required": ["secondLevelClassName", "dateYear"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "mtbf/mttr/reliability/faultCount", "disambiguate": "区别getContainer版=集装箱设备"}, {"path": "/api/gateway/getMachineDataDisplaySingleUnitEnergyConsumption", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询指定机种下各单台设备月度能耗（机种展示屏）", "tags": ["单台能耗", "机种", "月度"], "required": ["secondLevelClassName", "date"], "optional": ["ownerLgZoneName", "cmpName"], "param_note": "", "returns": "每台设备：consumption/fuel/electricity", "disambiguate": ""}, {"path": "/api/gateway/getProductEquipmentUsageRateByYear", "domain": "D7", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年生产设备有效利用率历年对比", "tags": ["历年利用率", "有效利用率", "年度趋势"], "required": [], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "", "returns": "年份序列：effectiveUtilizationRate/yoyChange", "disambiguate": "区别ByMonth=当年月度分布"}, {"path": "/api/gateway/getProductEquipmentUsageRateByMonth", "domain": "D7", "time": "T_TREND", "granularity": "G_ZONE", "intent": "查询年度生产设备有效利用率月度分布", "tags": ["月度利用率", "设备利用率", "月度分布"], "required": ["dateYear"], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "", "returns": "月份序列：effectiveUtilizationRate/momChange", "disambiguate": "区别ByYear=历年趋势"}, {"path": "/api/gateway/getProductEquipmentRateByYear", "domain": "D7", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年生产设备利用率历年对比", "tags": ["历年利用率", "设备利用率"], "required": [], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "", "returns": "年份序列：utilizationRate", "disambiguate": "区别UsageRate=有效利用率（更严格）"}, {"path": "/api/gateway/getProductEquipmentIntegrityRateByYear", "domain": "D7", "time": "T_YOY", "granularity": "G_ZONE", "intent": "查询生产设备年度完好率（当年vs上年同比）", "tags": ["完好率", "年度完好率", "同比"], "required": ["dateYear", "preYear"], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "dateYear=当年；preYear=对比年", "returns": "currentYearRate/prevYearRate/yoyChange/byEquipType", "disambiguate": "区别ByMonth=月度版"}, {"path": "/api/gateway/getProductEquipmentIntegrityRateByMonth", "domain": "D7", "time": "T_YOY", "granularity": "G_ZONE", "intent": "查询生产设备月度完好率（当月vs去年同月同比）", "tags": ["月度完好率", "同比", "当月"], "required": ["dateMonth", "preDateMonth"], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "dateMonth=当月yyyy-MM；preDateMonth=去年同月", "returns": "currentMonthRate/prevYearSameMonthRate/yoyChange", "disambiguate": "区别ByYear=年度版"}, {"path": "/api/gateway/getQuayEquipmentWorkingAmount", "domain": "D7", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询岸边设备月度作业量及同比（集装箱台数）", "tags": ["岸边设备", "作业量", "同比", "月度"], "required": ["dateMonth"], "optional": ["ownerLgZoneName"], "param_note": "", "returns": "ownerLgZoneName/currentMonthQty/prevYearSameMonthQty/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getProductEquipmentDataAnalysisList", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询生产设备数据分析列表（分页，多指标）", "tags": ["设备列表", "分析列表", "分页"], "required": ["dateMonth"], "optional": ["pageNo", "pageSize", "ownerLgZoneName"], "param_note": "", "returns": "equipNo/usageRate/integrityRate/machineHourRate/unitConsumption/status", "disambiguate": ""}, {"path": "/api/gateway/getProductEquipmentWorkingAmountByYear", "domain": "D7", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年生产设备作业量历年对比", "tags": ["历年作业量", "设备作业", "年度趋势"], "required": ["dateYear"], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "", "returns": "年份序列：totalWorkingQty/yoyRate", "disambiguate": "区别ByMonth=当年月度"}, {"path": "/api/gateway/getProductEquipmentWorkingAmountByMonth", "domain": "D7", "time": "T_TREND", "granularity": "G_ZONE", "intent": "查询生产设备当月作业量及同比", "tags": ["月度作业量", "同比", "当月"], "required": ["dateMonth"], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "", "returns": "currentMonthQty/prevYearSameMonthQty/yoyRate", "disambiguate": "区别ByYear=历年趋势"}, {"path": "/api/gateway/getProductEquipmentReliabilityByYear", "domain": "D7", "time": "T_HIST", "granularity": "G_ZONE", "intent": "查询近5年生产设备可靠性（MTBF）历年趋势", "tags": ["可靠性历年", "MTBF趋势"], "required": [], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "", "returns": "年份序列：mtbf/reliability/faultCount", "disambiguate": "区别ByMonth=当年月度"}, {"path": "/api/gateway/getProductEquipmentReliabilityByMonth", "domain": "D7", "time": "T_TREND", "granularity": "G_ZONE", "intent": "查询年度生产设备可靠性月度趋势", "tags": ["月度可靠性", "MTBF月度"], "required": ["dateYear"], "optional": ["ownerLgZoneName", "firstLevelClassName"], "param_note": "", "returns": "月份序列：mtbf/reliability/faultCount", "disambiguate": "区别ByYear=历年趋势"}, {"path": "/api/gateway/getProductEquipmentUnitConsumptionByYear", "domain": "D7", "time": "T_HIST", "granularity": "G_PORT", "intent": "查询近5年生产设备能耗单耗历年对比", "tags": ["历年单耗", "能耗趋势"], "required": ["dateYear"], "optional": [], "param_note": "", "returns": "年份序列：unitConsumption/fuelConsumption/electricityConsumption", "disambiguate": "区别ByMonth=当年月度"}, {"path": "/api/gateway/getProductEquipmentUnitConsumptionByMonth", "domain": "D7", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询生产设备当月能耗单耗及同比/环比", "tags": ["月度单耗", "同比", "环比"], "required": ["dateMonth"], "optional": [], "param_note": "", "returns": "unitConsumption/yoyRate/momRate", "disambiguate": "区别ByYear=历年趋势"}, {"path": "/api/gateway/getImportantCargoPortInventoryByBusinessType", "domain": "D1", "time": "T_RT", "granularity": "G_BIZ", "intent": "按业务类型查询港存量（集装箱/散杂货/油化品/商品车）", "tags": ["港存", "库存", "业务类型"], "required": [], "optional": ["date", "regionName"], "param_note": "", "returns": "businessType/inventory/capacityRatio", "disambiguate": "区别ByRegion=按港区；ByCargoType=按货类"}, {"path": "/api/gateway/getShipOperationDynamic", "domain": "D1", "time": "T_RT", "granularity": "G_BERTH", "intent": "查询单艘船舶作业动态（装卸进度/效率/作业记录）", "tags": ["作业动态", "单船", "装卸进度", "效率"], "required": [], "optional": ["shipRecordId"], "param_note": "shipRecordId=船舶记录ID", "returns": "shipName/currentStatus/completedTon/totalTon/efficiency", "disambiguate": "区别getKeyVesselList=船舶列表；本接口=单船作业详情"}, {"path": "/api/gateway/getThroughputCollect", "domain": "D2", "time": "T_MON", "granularity": "G_PORT", "intent": "查询吞吐量汇总（当月实际/同比/环比/日均）", "tags": ["吞吐汇总", "同比", "环比", "日均"], "required": ["date", "yoyDate"], "optional": [], "param_note": "date=yyyy-MM；yoyDate=同比月", "returns": "currentThroughput/yoyThroughput/yoyRate/momRate/dailyAvg", "disambiguate": "区别getCurBusinessDashboardThroughput=驾驶舱简版"}, {"path": "/api/gateway/getThroughputByCargoCategoryName", "domain": "D2", "time": "T_MON", "granularity": "G_CARGO", "intent": "按货类查询吞吐量分布（铁矿石/煤炭/集装箱等9大类）", "tags": ["货类吞吐", "按货类", "月度"], "required": ["date", "yoyDate"], "optional": [], "param_note": "date/yoyDate=yyyy-MM", "returns": "cargoCategoryName/throughput/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getThroughputByZoneName", "domain": "D2", "time": "T_MON", "granularity": "G_ZONE", "intent": "按港区查询吞吐量分布及占比", "tags": ["港区吞吐", "按港区", "占比"], "required": ["date", "yoyDate"], "optional": [], "param_note": "date/yoyDate=yyyy-MM", "returns": "zoneName/throughput/yoyRate/shareRatio", "disambiguate": "区别getMonthlyZoneThroughput=驾驶舱版"}, {"path": "/api/gateway/getMonthlyCargoThroughputCategory", "domain": "D2", "time": "T_MON", "granularity": "G_CARGO", "intent": "查询当月各货类吞吐量及同比（商务驾驶舱货类板块）", "tags": ["货类", "当月", "商务驾驶舱", "同比"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "cargoType/throughput/prevYearThroughput/yoyRate/shareRatio", "disambiguate": "区别getThroughputByCargoCategoryName=9大类版"}, {"path": "/api/gateway/getSumBusinessDashboardThroughput", "domain": "D2", "time": "T_CUM", "granularity": "G_PORT", "intent": "查询累计吞吐量驾驶舱指标（计划/实际/去年同期/增速/完成进度）", "tags": ["累计吞吐", "商务驾驶舱", "完成进度", "同比"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "num/typeName（8项指标）", "disambiguate": "区别getCumulativeThroughput=有内外贸分拆"}, {"path": "/api/gateway/getBusinessDashboardCumulativeThroughputByCargoType", "domain": "D2", "time": "T_CUM", "granularity": "G_CARGO", "intent": "查询累计吞吐量按货类分拆（集装箱/散杂货/油化品/商品车）", "tags": ["累计", "按货类", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "cargoType/cumulativeThroughput/prevYearCumulative/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getCumulativeRegionalThroughput", "domain": "D2", "time": "T_CUM", "granularity": "G_ZONE", "intent": "查询各港区累计吞吐量驾驶舱指标（计划/实际/同比/完成进度）", "tags": ["港区累计", "商务驾驶舱", "完成进度"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "num/typeName/zoneName（每港区6项指标）", "disambiguate": "区别getCumulativeZoneThroughput=简版"}, {"path": "/api/gateway/getContributionByCargoCategoryName", "domain": "D3", "time": "T_MON", "granularity": "G_CARGO", "intent": "按货类查询战略客户贡献量（铁矿石/煤炭/集装箱等）", "tags": ["货类贡献", "战略客户", "按货类"], "required": [], "optional": ["date", "statisticType", "contributionType"], "param_note": "statisticType=统计维度", "returns": "cargoCategoryName/contribution/contributionRate/strategicClientCount", "disambiguate": ""}, {"path": "/api/gateway/getClientContributionOrder", "domain": "D3", "time": "T_MON", "granularity": "G_CLIENT", "intent": "查询战略客户贡献排名（按吞吐量降序）", "tags": ["客户排名", "贡献排名", "战略客户"], "required": [], "optional": ["date", "statisticType", "contributionType"], "param_note": "", "returns": "rank/clientName/throughput/contributionRate/yoyRate", "disambiguate": "区别getSumContributionRankOfStrategicCustomer=累计版"}, {"path": "/api/gateway/getStrategicCustomerRevenue", "domain": "D3", "time": "T_MON", "granularity": "G_CLIENT", "intent": "查询战略客户营收贡献（按收入排名）", "tags": ["客户营收", "收入", "战略客户"], "required": [], "optional": ["curDate", "clientName", "contributionValue", "statisticType", "yearDate"], "param_note": "curDate=yyyy-MM", "returns": "clientName/revenue/revenueShare/yoyRate", "disambiguate": ""}, {"path": "/api/gateway/getStrategicCustomerThroughput", "domain": "D3", "time": "T_MON", "granularity": "G_CLIENT", "intent": "查询战略客户吞吐量贡献（按吞吐量排名）", "tags": ["客户吞吐", "贡献", "战略客户"], "required": [], "optional": ["curDate", "clientName", "cargoCategoryName", "statisticType", "yearDate"], "param_note": "curDate=yyyy-MM", "returns": "clientName/throughput/contributionRate/yoyRate", "disambiguate": "区别getStrategicCustomerRevenue=看收入"}, {"path": "/api/gateway/getContributionTrend", "domain": "D3", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询战略客户月度贡献趋势（当年vs上年）", "tags": ["贡献趋势", "月度趋势", "战略客户"], "required": [], "optional": ["year", "lastYear", "statisticType", "contributionType"], "param_note": "year/lastYear=yyyy", "returns": "month/strategicContribution/prevYearContribution/contributionRate", "disambiguate": "区别getCumulativeContributionTrend=累计趋势"}, {"path": "/api/gateway/getCurStrategyCustomerTrendAnalysis", "domain": "D3", "time": "T_TREND", "granularity": "G_PORT", "intent": "查询当期战略客户趋势分析（月度吞吐/贡献率/营收趋势）", "tags": ["战略客户趋势", "商务驾驶舱", "月度"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "dateMonth/num/typeName（多项指标按月）", "disambiguate": "区别getSumStrategyCustomerTrendAnalysis=累计版"}, {"path": "/api/gateway/getSumStrategicCustomerContributionByCargoTypeThroughput", "domain": "D3", "time": "T_CUM", "granularity": "G_CARGO", "intent": "查询战略客户累计贡献按货类分拆", "tags": ["累计贡献", "按货类", "战略客户", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "categoryName/num", "disambiguate": ""}, {"path": "/api/gateway/getSumContributionRankOfStrategicCustomer", "domain": "D3", "time": "T_CUM", "granularity": "G_CLIENT", "intent": "查询战略客户累计贡献排名", "tags": ["累计排名", "战略客户", "商务驾驶舱"], "required": ["date"], "optional": [], "param_note": "date=yyyy-MM", "returns": "clientName/num", "disambiguate": "区别getClientContributionOrder=当月版"}, {"path": "/api/gateway/getImportantAssetRegionAnalysisPenetrationPage", "domain": "D5", "time": "T_YR", "granularity": "G_ZONE", "intent": "查询重要资产按港区穿透分析（按区域/资产类别统计数量和净值）", "tags": ["重要资产", "港区穿透", "资产分析"], "required": ["dateYear"], "optional": ["ownerZone", "assetTypeName"], "param_note": "dateYear=yyyy", "returns": "ownerZone/assetCategory/count/netValue", "disambiguate": ""}, {"path": "/api/gateway/getEquipmentAnalysisTransparentTransmission", "domain": "D5", "time": "T_YR", "granularity": "G_ASSET", "intent": "查询设备分析透传数据（按设备类型统计数量/状态/净值）", "tags": ["设备分析", "透传", "设备类型", "净值"], "required": ["dateYear"], "optional": ["assetStatus", "assetTypeName"], "param_note": "dateYear=yyyy", "returns": "equipmentType/status/count/totalNetValue", "disambiguate": "区别ByFirst=按一级分类"}, {"path": "/api/gateway/getEquipmentMachineHourRate", "domain": "D7", "time": "T_MON", "granularity": "G_ZONE", "intent": "查询各港区设备台时效率（按月）", "tags": ["台时效率", "设备", "港区", "月度"], "required": ["dateMonth"], "optional": ["ownerZone", "cmpName", "firstLevelClassName"], "param_note": "dateMonth=yyyy-MM", "returns": "ownerZone/dateMonth/avgMachineHourRate", "disambiguate": "区别getContainerMachineHourRate=集装箱专用"}, {"path": "/api/gateway/getEquipmentUseList", "domain": "D7", "time": "T_MON", "granularity": "G_EQUIP", "intent": "查询设备使用明细列表（分页，含作业时长/工作量/效率）", "tags": ["设备使用", "明细列表", "分页", "作业时长"], "required": ["startDate", "endDate", "month"], "optional": ["pageNo", "pageSize", "ownerLgZoneName", "cmpName", "secondLevelClassName"], "param_note": "startDate/endDate=yyyy-MM-dd；month=yyyy-MM", "returns": "equipNo/equipName/operationHours/workingQty/efficiency", "disambiguate": ""}]
_DOMAIN_INDEX = {"D1": {"name": "生产运营", "desc": "天气/交通管制/船舶动态/泊位占用/港存/装卸效率/商品车/集装箱", "api_count": 53, "top_tags": ["同比", "环比", "集装箱", "港区", "月度趋势", "业务类型", "TEU", "月度"]}, "D2": {"name": "市场商务", "desc": "吞吐量分析(当月/累计/趋势/分业务/分区域/重点企业)", "api_count": 21, "top_tags": ["年累计", "商务驾驶舱", "当月", "同比", "业务板块", "全港", "占比", "当月吞吐"]}, "D3": {"name": "客户管理", "desc": "战略客户贡献(吞吐/收入/货类/排名/趋势)/客户信用/客户结构", "api_count": 20, "top_tags": ["战略客户", "商务驾驶舱", "货类贡献", "客户维度", "收入", "排名", "月度趋势", "当月"]}, "D4": {"name": "投企管理", "desc": "持股比例/董监事变更/业务到期/新设退出企业/会议议案", "api_count": 7, "top_tags": ["董事会", "持股比例", "投企", "股权结构", "会议", "监事会", "议案", "议案明细"]}, "D5": {"name": "资产管理", "desc": "资产总量/价值/分布/设备设施/房屋/土地海域/新增报废趋势", "api_count": 43, "top_tags": ["重要资产", "原值", "价值分布", "建筑面积", "港区", "实物资产", "金融资产", "土地"]}, "D6": {"name": "投资管理", "desc": "资本项目/成本项目/计划进度/按区域/按类型/计划外/交付率", "api_count": 31, "top_tags": ["资本项目", "成本项目", "计划外", "完成率", "交付率", "按港区", "年度对比", "分页"]}, "D7": {"name": "设备子屏", "desc": "生产设备利用率/完好率/台时效率/可靠性/单耗/燃油/电量/机种分析", "api_count": 44, "top_tags": ["月度", "港区", "年度", "同比", "完好率", "利用率", "月度分布", "设备成本"]}}
_DOMAIN_CARDS = {"D1": [{"name": "getWeatherForecast", "intent": "查询各港区未来5天天气预报（天气/温度/风速/湿度）", "time": "T_RT", "gran": "G_ZONE", "req": "无", "tags": ["天气", "预报", "风速", "温度"], "note": "区别getRealTimeWeather=当前实时；本接口=未来5天预报"}, {"name": "getRealTimeWeather", "intent": "查询各港区当前实时气象（温度/风速/能见度/浪高）", "time": "T_RT", "gran": "G_ZONE", "req": "无", "tags": ["天气", "实时", "当前", "浪高"], "note": "区别getWeatherForecast=未来5天预报；本接口=当前实况"}, {"name": "getTrafficControl", "intent": "查询当前航道交通管制信息（大风封航/浓雾限航/演习管制）", "time": "T_RT", "gran": "G_ZONE", "req": "无", "tags": ["管制", "封航", "限航", "交通"], "note": ""}, {"name": "getKeyVesselList", "intent": "查询重点船舶列表（在泊/锚地状态，含船名/货类/到港时间）", "time": "T_RT", "gran": "G_BERTH", "req": "shipStatus+regionName", "tags": ["船舶", "在泊", "锚地", "重点船"], "note": "区别getProdShipDesc=描述性摘要；getProdShipDynNum=数量汇总"}, {"name": "getProdShipDynNum", "intent": "查询全港船舶动态数量汇总（在泊/锚地/进港/出港总数）", "time": "T_RT", "gran": "G_PORT", "req": "无", "tags": ["船舶数量", "在泊数", "锚地数", "动态"], "note": "区别getKeyVesselList=明细列表；getProdShipDesc=描述摘要"}, {"name": "getProdShipDesc", "intent": "查询重点船舶和锚地船舶的描述性摘要（驾驶舱展示用）", "time": "T_RT", "gran": "G_PORT", "req": "无", "tags": ["船舶摘要", "重点船", "锚地", "驾驶舱"], "note": "区别getProdShipDynNum=纯数量；getKeyVesselList=完整列表"}, {"name": "getShipOperationDynamic", "intent": "查询单艘船舶作业动态（装卸进度/效率/作业记录）", "time": "T_RT", "gran": "G_BERTH", "req": "无", "tags": ["作业动态", "单船", "装卸进度", "作业记录"], "note": "本接口是单船级别；其他船舶接口是全港/港区级别"}, {"name": "getShipStatisticsByRegion", "intent": "按港区+船舶类型统计在港船舶数量（集装箱船/散货船/油轮等）", "time": "T_RT", "gran": "G_ZONE", "req": "regionName", "tags": ["船舶统计", "按港区", "按船型", "数量"], "note": "区别getShipStatisticsByBusinessType=按业务类型分；本接口=按港区+船型"}, {"name": "getShipStatisticsByBusinessType", "intent": "按业务类型统计在港船舶数量（集装箱/散杂货/油化品/商品车）", "time": "T_RT", "gran": "G_BIZ", "req": "无", "tags": ["船舶统计", "按业务", "货类", "数量"], "note": "区别getShipStatisticsByRegion=按港区+船型分"}, {"name": "getBerthList", "intent": "查询公司泊位列表及当前状态（在泊/离泊/计划）", "time": "T_RT", "gran": "G_BERTH", "req": "cmpName", "tags": ["泊位", "泊位列表", "在泊状态", "靠泊计划"], "note": "区别getBerthOccupancyRate=占用率指标；本接口=明细列表"}, {"name": "getBerthOccupancyRate", "intent": "查询指定公司在时间段内的泊位占用率", "time": "T_TREND", "gran": "G_CMP", "req": "mainOrgCode+statDate+endDate", "tags": ["泊位占用率", "占用率", "靠泊时间"], "note": "区别getBerthOccupancyRateByRegion=按港区；ByBusinessType=按业务"}, {"name": "getBerthOccupancyRateByRegion", "intent": "按港区查询泊位占用率及在泊时间统计", "time": "T_TREND", "gran": "G_ZONE", "req": "无", "tags": ["泊位占用率", "港区", "靠泊时长"], "note": "区别ByBusinessType=按业务类型"}, {"name": "getBerthOccupancyRateByBusinessType", "intent": "按业务类型查询泊位占用率", "time": "T_TREND", "gran": "G_BIZ", "req": "无", "tags": ["泊位占用率", "业务类型", "集装箱", "散货"], "note": "区别ByRegion=按港区"}, {"name": "getTotalBerthDuration", "intent": "查询机构靠泊总时长和占用率（指定时间段）", "time": "T_TREND", "gran": "G_CMP", "req": "orgName+statDate+endDate", "tags": ["靠泊时长", "泊位时间", "占用率"], "note": "区别getBerthOccupancyRate=用机构编码；本接口=用机构名"}, {"name": "getImportantCargoPortInventoryByRegion", "intent": "查询各港区主要货物港存量（铁矿石/煤/粮食/石油/集装箱/商品车）", "time": "T_RT", "gran": "G_ZONE", "req": "regionName", "tags": ["港存", "库存", "铁矿石", "煤炭"], "note": "区别ByCargoType=按货类；ByBusinessType=按业务类型"}, {"name": "getImportantCargoPortInventoryByCargoType", "intent": "按货类查询港存量及库容占用率", "time": "T_RT", "gran": "G_CARGO", "req": "无", "tags": ["港存", "库存", "货类", "库容率"], "note": "区别ByRegion=按港区分"}, {"name": "getImportantCargoPortInventoryByBusinessType", "intent": "按业务类型查询港存量及库容占用率", "time": "T_RT", "gran": "G_BIZ", "req": "无", "tags": ["港存", "库存", "业务类型", "集装箱"], "note": "区别ByCargoType=按货类；ByRegion=按港区"}, {"name": "getDailyPortInventoryData", "intent": "查询指定公司指定日期的港存快照（各货类汇总+库容率）", "time": "T_DAY", "gran": "G_CMP", "req": "dateCur+cmpName", "tags": ["港存", "日存量", "公司", "日期"], "note": "区别getPortInventoryTrend=多月趋势"}, {"name": "getPortInventoryTrend", "intent": "查询公司全年各月港存趋势（平均/最高/最低）", "time": "T_TREND", "gran": "G_CMP", "req": "dateYear+cmpName", "tags": ["港存趋势", "月度趋势", "公司", "库存变化"], "note": "区别getDailyPortInventoryData=单日快照"}, {"name": "getContainerAndVehicleTrade", "intent": "查询港区集装箱（内外贸）和商品车（进出口）数量", "time": "T_RT", "gran": "G_ZONE", "req": "regionName", "tags": ["集装箱", "商品车", "内外贸", "进出口"], "note": ""}, {"name": "getVesselOperationEfficiency", "intent": "查询公司船舶作业效率（单船效率平均/最高/最低，按月区间）", "time": "T_TREND", "gran": "G_CMP", "req": "cmpName+startMonth+endMonth", "tags": ["船舶效率", "作业效率", "单船效率", "台时"], "note": "区别getVesselOperationEfficiencyTrend=月度趋势曲线"}, {"name": "getVesselOperationEfficiencyTrend", "intent": "查询月度船舶作业效率趋势（集装箱/散货/油品效率曲线）", "time": "T_TREND", "gran": "G_PORT", "req": "startMonth+endMonth+cmpName", "tags": ["效率趋势", "月度效率", "集装箱效率", "趋势"], "note": "区别getVesselOperationEfficiency=单时段汇总均值"}, {"name": "getSingleShipRate", "intent": "查询各公司单船效率（作业/小时），按时间段统计", "time": "T_TREND", "gran": "G_CMP", "req": "startDate+endDate+regionName", "tags": ["单船效率", "自然箱/小时", "吨/小时"], "note": ""}, {"name": "getProductViewShipOperationRateAvg", "intent": "查询港口平均船舶作业效率（集装箱/散货/油品/滚装各业务类型）", "time": "T_TREND", "gran": "G_PORT", "req": "无", "tags": ["平均效率", "作业效率", "各业务类型"], "note": "区别Trend=按月趋势；本接口=时段汇总均值"}, {"name": "getProductViewShipOperationRateTrend", "intent": "查询船舶作业效率月度趋势（集装箱/散货/油品曲线）", "time": "T_TREND", "gran": "G_PORT", "req": "无", "tags": ["效率趋势", "月度趋势", "集装箱效率"], "note": "区别Avg=汇总均值"}, {"name": "getPersonalCenterCargoThroughput", "intent": "查询指定日期吞吐量及与环比日的对比（个人中心首页）", "time": "T_DAY", "gran": "G_PORT", "req": "无", "tags": ["日吞吐", "当日", "环比", "个人中心"], "note": "区别Month=月度；Year=年累计"}, {"name": "getPersonalCenterMonthCargoThroughput", "intent": "查询截至某日当月累计吞吐量及与环比月的对比", "time": "T_MON", "gran": "G_PORT", "req": "无", "tags": ["月吞吐", "当月累计", "环比", "个人中心"], "note": "区别Day=日；Year=年累计"}, {"name": "getPersonalCenterYearCargoThroughput", "intent": "查询截至某日年累计吞吐量及同比", "time": "T_CUM", "gran": "G_PORT", "req": "无", "tags": ["年累计", "同比", "个人中心", "累计吞吐"], "note": "区别Month=月度；Day=日"}, {"name": "getPersonalCenterYearCargoThroughputTrend", "intent": "查询年度各月吞吐量趋势（含累计）", "time": "T_TREND", "gran": "G_PORT", "req": "无", "tags": ["月度趋势", "个人中心", "年度趋势"], "note": ""}, {"name": "getThroughputMonthlyTrend", "intent": "查询公司全年月度吞吐量趋势（含同比）", "time": "T_TREND", "gran": "G_CMP", "req": "dateYear+cmpName", "tags": ["月度趋势", "公司", "年度趋势"], "note": ""}, {"name": "getPortCompanyThroughput", "intent": "查询各公司指定月份吞吐量及同比", "time": "T_MON", "gran": "G_CMP", "req": "date+cmpName", "tags": ["公司吞吐", "各公司", "月度", "同比"], "note": ""}, {"name": "getBusinessSegmentBranch", "intent": "查询港区下各公司的业务分支组织关系", "time": "T_NONE", "gran": "G_CMP", "req": "regionName", "tags": ["组织关系", "业务分支", "公司", "港区"], "note": ""}, {"name": "getThroughputAndTargetThroughputTon", "intent": "查询年度吞吐量实际完成值与目标值对比（万吨，含完成率）", "time": "T_CUM", "gran": "G_ZONE", "req": "无", "tags": ["吞吐量", "目标完成", "完成率", "万吨"], "note": "区别TEU版=集装箱箱量目标"}, {"name": "getThroughputAndTargetThroughputTeu", "intent": "查询年度集装箱吞吐量实际值与目标值对比（TEU）", "time": "T_CUM", "gran": "G_ZONE", "req": "无", "tags": ["集装箱", "TEU", "目标完成", "内外贸"], "note": "区别Ton版=万吨目标"}, {"name": "getThroughputAnalysisByYear", "intent": "查询年度各月吞吐量趋势（当年vs上年同期月度对比）", "time": "T_TREND", "gran": "G_PORT", "req": "无", "tags": ["月度趋势", "同比", "年度对比", "万吨"], "note": "区别getContainerThroughputAnalysisByYear=只看集装箱TEU"}, {"name": "getContainerThroughputAnalysisByYear", "intent": "查询集装箱吞吐量年度月趋势（当年vs上年，TEU）", "time": "T_TREND", "gran": "G_PORT", "req": "无", "tags": ["集装箱", "TEU", "月度趋势", "年度对比"], "note": "区别ByYear(吨版)=万吨"}, {"name": "getThroughputAnalysisNonContainer", "intent": "查询年度非集装箱吞吐量（干散/液散/件杂/滚装）", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["非集装箱", "散货", "散杂货", "滚装"], "note": "区别Container版=集装箱"}, {"name": "getThroughputAnalysisContainer", "intent": "查询年度集装箱吞吐量（内外贸/空重箱）", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["集装箱", "TEU", "内外贸", "空重箱"], "note": ""}, {"name": "getOilsChemBreakBulkByBusinessType", "intent": "查询各港区油化品和散杂货吞吐量（按月，支持同比/环比切换）", "time": "T_MON", "gran": "G_ZONE", "req": "无", "tags": ["油化品", "散杂货", "港区", "月度"], "note": ""}, {"name": "getRoroByBusinessType", "intent": "查询各港区滚装（商品车）吞吐量", "time": "T_MON", "gran": "G_ZONE", "req": "无", "tags": ["滚装", "商品车", "港区", "月度"], "note": ""}, {"name": "getContainerByBusinessType", "intent": "查询各港区集装箱吞吐量（TEU，按月）", "time": "T_MON", "gran": "G_ZONE", "req": "无", "tags": ["集装箱", "TEU", "港区", "月度"], "note": ""}, {"name": "getCompanyStatisticsBusinessType", "intent": "按公司查询各业务类型吞吐量（集装箱/散货/油化/滚装）", "time": "T_MON", "gran": "G_CMP", "req": "无", "tags": ["公司统计", "业务类型", "各公司", "分拆"], "note": ""}, {"name": "getThroughputAnalysisYoyMomByYear", "intent": "查询指定年份吞吐量同比/环比（年度层面）", "time": "T_YOY", "gran": "G_PORT", "req": "无", "tags": ["同比", "环比", "年度", "吞吐"], "note": "区别ByMonth=月度层面；ByDay=日层面"}, {"name": "getThroughputAnalysisYoyMomByMonth", "intent": "查询指定月份吞吐量同比/环比（月度层面）", "time": "T_YOY", "gran": "G_PORT", "req": "无", "tags": ["同比", "环比", "月度", "吞吐"], "note": "区别ByYear=年度；ByDay=日"}, {"name": "getThroughputAnalysisYoyMomByDay", "intent": "查询指定日期吞吐量同比/环比（日层面）", "time": "T_YOY", "gran": "G_PORT", "req": "无", "tags": ["同比", "环比", "日度", "吞吐"], "note": "区别ByYear=年；ByMonth=月"}, {"name": "getContainerAnalysisYoyMomByYear", "intent": "查询集装箱吞吐量同比/环比（年度）", "time": "T_YOY", "gran": "G_PORT", "req": "无", "tags": ["集装箱", "同比", "环比", "TEU"], "note": ""}, {"name": "getBusinessTypeThroughputAnalysisYoyMomByYear", "intent": "查询各业务类型吞吐量同比/环比（年度，可按港区筛选）", "time": "T_YOY", "gran": "G_BIZ", "req": "无", "tags": ["业务类型", "同比", "环比", "年度"], "note": ""}, {"name": "getBusinessTypeThroughputAnalysisYoyMomByMonth", "intent": "查询各业务类型吞吐量同比/环比（月度）", "time": "T_YOY", "gran": "G_BIZ", "req": "无", "tags": ["业务类型", "同比", "环比", "月度"], "note": ""}, {"name": "getBusinessTypeThroughputAnalysisYoyMomByDay", "intent": "查询各业务类型吞吐量同比/环比（日度）", "time": "T_YOY", "gran": "G_BIZ", "req": "无", "tags": ["业务类型", "同比", "环比", "日度"], "note": ""}, {"name": "getActualPerformance", "intent": "查询昨日吞吐量实际完成情况及环比（驾驶舱首页）", "time": "T_DAY", "gran": "G_PORT", "req": "无", "tags": ["昨日完成", "实际吞吐", "日报"], "note": ""}, {"name": "getMonthlyTrendThroughput", "intent": "查询指定时间段月度吞吐量趋势序列", "time": "T_TREND", "gran": "G_PORT", "req": "endDate+startDate", "tags": ["月度趋势", "时间段", "趋势序列"], "note": ""}, {"name": "getlnportDispatchPort", "intent": "查询指定日期各港区日班/夜班吞吐量调度数据", "time": "T_DAY", "gran": "G_ZONE", "req": "dispatchDate", "tags": ["调度", "日班", "夜班", "港区"], "note": "区别Wharf=按码头"}, {"name": "getlnportDispatchWharf", "intent": "查询指定日期各码头日班/夜班吞吐量调度数据", "time": "T_DAY", "gran": "G_CMP", "req": "dispatchDate", "tags": ["调度", "码头", "日班", "夜班"], "note": "区别Port=按港区"}], "D2": [{"name": "getMonthlyThroughput", "intent": "查询当月吞吐量及与去年同期对比（市场商务驾驶舱，可按港区筛选）", "time": "T_MON", "gran": "G_ZONE", "req": "curDateMonth+yearDateMonth+zoneName", "tags": ["当月吞吐", "同比", "市场商务", "港区"], "note": "区别getCurBusinessDashboardThroughput=无zoneName参数；getCumulativeThroughput=累计"}, {"name": "getCurBusinessDashboardThroughput", "intent": "查询当月吞吐量及同比（全港汇总，无港区筛选）", "time": "T_MON", "gran": "G_PORT", "req": "date", "tags": ["当月吞吐", "同比", "全港", "商务驾驶舱"], "note": "区别getMonthlyThroughput=有zoneName参数；本接口=全港无港区筛选"}, {"name": "getMonthlyZoneThroughput", "intent": "查询各港区当月吞吐量分布及占比", "time": "T_MON", "gran": "G_ZONE", "req": "curDateMonth+yearDateMonth+zoneName", "tags": ["港区吞吐", "当月", "分港区", "占比"], "note": "区别getMonthlyThroughput=全港汇总；区别CumulativeZone=累计版"}, {"name": "getCumulativeThroughput", "intent": "查询年累计吞吐量及同比（内外贸分拆）", "time": "T_CUM", "gran": "G_PORT", "req": "curDateYear+yearDateYear", "tags": ["累计吞吐", "年累计", "同比", "内外贸"], "note": "区别getMonthlyThroughput=当月值；getSumBusinessDashboardThroughput=同功能无内外贸分拆"}, {"name": "getSumBusinessDashboardThroughput", "intent": "查询年累计吞吐量及同比（商务驾驶舱版，全港汇总）", "time": "T_CUM", "gran": "G_PORT", "req": "date", "tags": ["年累计", "吞吐量", "同比", "商务驾驶舱"], "note": "区别getCumulativeThroughput=内外贸分拆版"}, {"name": "getCumulativeZoneThroughput", "intent": "查询各港区年累计吞吐量及占比", "time": "T_CUM", "gran": "G_ZONE", "req": "curDateYear+yearDateYear+zoneName", "tags": ["港区累计", "年累计", "分港区", "占比"], "note": "区别getMonthlyZoneThroughput=当月版"}, {"name": "getCumulativeRegionalThroughput", "intent": "查询各港区年累计吞吐量（商务驾驶舱版）", "time": "T_CUM", "gran": "G_ZONE", "req": "date", "tags": ["港区累计", "年累计", "商务驾驶舱"], "note": "区别getCumulativeZoneThroughput=需传三参数版"}, {"name": "getCurrentBusinessSegmentThroughput", "intent": "查询当月各业务板块（集装箱/散杂货/油化品/商品车）吞吐量", "time": "T_MON", "gran": "G_BIZ", "req": "curDateMonth+yearDateMonth+zoneName", "tags": ["业务板块", "当月", "集装箱", "散杂货"], "note": "区别getCumulativeBusinessSegmentThroughput=累计版"}, {"name": "getCumulativeBusinessSegmentThroughput", "intent": "查询年累计各业务板块吞吐量", "time": "T_CUM", "gran": "G_BIZ", "req": "curDateYear+yearDateYear+zoneName", "tags": ["业务板块", "年累计", "集装箱", "散杂货"], "note": "区别getCurrentBusinessSegment=当月版"}, {"name": "getMonthlyCargoThroughputCategory", "intent": "查询当月各货类吞吐量及占比（商务驾驶舱版）", "time": "T_MON", "gran": "G_CARGO", "req": "date", "tags": ["货类吞吐", "当月", "分货类", "占比"], "note": "区别getBusinessDashboardCumulativeThroughputByCargoType=累计版"}, {"name": "getBusinessDashboardCumulativeThroughputByCargoType", "intent": "查询年累计各货类吞吐量（商务驾驶舱版）", "time": "T_CUM", "gran": "G_CARGO", "req": "date", "tags": ["货类吞吐", "年累计", "分货类"], "note": "区别getMonthlyCargoThroughputCategory=当月版"}, {"name": "getMonthlyRegionalThroughputAreaBusinessDashboard", "intent": "查询当月各港区吞吐量及占比（商务驾驶舱版）", "time": "T_MON", "gran": "G_ZONE", "req": "date", "tags": ["港区吞吐", "当月", "商务驾驶舱"], "note": "区别getMonthlyZoneThroughput=需三参数版"}, {"name": "getTrendChart", "intent": "查询指定业务板块月度吞吐量趋势图数据（市场商务版）", "time": "T_TREND", "gran": "G_BIZ", "req": "businessSegment+startDate+endDate", "tags": ["趋势图", "月度趋势", "业务板块"], "note": "区别getCurBusinessCockpitTrendChart=全港当月版；getCumulativeTrendChart=累计版"}, {"name": "getCurBusinessCockpitTrendChart", "intent": "查询全港吞吐量月度趋势（当年各月，商务驾驶舱版）", "time": "T_TREND", "gran": "G_PORT", "req": "date", "tags": ["趋势图", "全港", "月度趋势", "商务驾驶舱"], "note": "区别getTrendChart=需指定业务板块"}, {"name": "getCumulativeTrendChart", "intent": "查询业务板块年累计吞吐量趋势（含月度/累计双序列）", "time": "T_CUM", "gran": "G_BIZ", "req": "businessSegment+curDateYear+yearDateYear", "tags": ["累计趋势", "月度+累计", "业务板块"], "note": "区别getTrendChart=仅月度；getSumBusinessCockpitTrendChart=全港累计版"}, {"name": "getSumBusinessCockpitTrendChart", "intent": "查询全港年累计吞吐量趋势（含月度/累计/去年同期三序列）", "time": "T_CUM", "gran": "G_PORT", "req": "date", "tags": ["累计趋势", "全港", "商务驾驶舱"], "note": "区别getCumulativeTrendChart=按业务板块版"}, {"name": "getKeyEnterprise", "intent": "查询当月重点企业吞吐量排名（Top10，按业务板块）", "time": "T_MON", "gran": "G_CLIENT", "req": "businessSegment+curDateMonth+yearDateMonth", "tags": ["重点企业", "排名", "当月", "贡献"], "note": "区别getCumulativeKeyEnterprise=累计排名"}, {"name": "getCumulativeKeyEnterprise", "intent": "查询年累计重点企业吞吐量排名", "time": "T_CUM", "gran": "G_CLIENT", "req": "businessSegment+curDateYear+yearDateYear", "tags": ["重点企业", "排名", "年累计"], "note": "区别getKeyEnterprise=当月版"}], "D3": [{"name": "getCustomerQty", "intent": "查询客户总数量（含活跃/战略/新增统计）", "time": "T_NONE", "gran": "G_CLIENT", "req": "无", "tags": ["客户数量", "战略客户数", "新增客户"], "note": ""}, {"name": "getCustomerTypeAnalysis", "intent": "查询客户类型结构分析（货主/船公司/代理等分类及占比）", "time": "T_NONE", "gran": "G_CLIENT", "req": "无", "tags": ["客户类型", "客户结构", "占比"], "note": "区别FieldAnalysis=按行业"}, {"name": "getCustomerFieldAnalysis", "intent": "查询客户所属行业分析（钢铁/能源/汽车/粮食等）", "time": "T_NONE", "gran": "G_CLIENT", "req": "无", "tags": ["行业分析", "客户行业", "货主行业"], "note": "区别TypeAnalysis=按客户类型"}, {"name": "getStrategicCustomers", "intent": "查询战略客户名单及合作信息（级别/年份/合同状态）", "time": "T_NONE", "gran": "G_CLIENT", "req": "无", "tags": ["战略客户", "客户名单", "合作级别"], "note": ""}, {"name": "getStrategicClientsEnterprises", "intent": "查询指定战略客户的关联企业及合作方式", "time": "T_NONE", "gran": "G_CLIENT", "req": "displayoCde", "tags": ["战略客户", "关联企业", "合作方式"], "note": ""}, {"name": "getCustomerCredit", "intent": "查询客户信用级别和授信额度（已用/可用）", "time": "T_NONE", "gran": "G_CLIENT", "req": "orgName+customerName+gradeResult", "tags": ["信用", "授信", "信用级别", "风险"], "note": ""}, {"name": "getThroughputCollect", "intent": "查询客户维度当月/同比吞吐量汇总（客户管理版）", "time": "T_MON", "gran": "G_PORT", "req": "无", "tags": ["客户吞吐", "月度", "同比"], "note": ""}, {"name": "getThroughputByCargoCategoryName", "intent": "查询各货类吞吐量及占比（客户管理视角）", "time": "T_MON", "gran": "G_CARGO", "req": "无", "tags": ["货类吞吐", "货类占比", "客户维度"], "note": "区别市场商务版=getMonthlyCargoThroughputCategory"}, {"name": "getThroughputByZoneName", "intent": "查询各港区吞吐量及占比（客户管理视角）", "time": "T_MON", "gran": "G_ZONE", "req": "无", "tags": ["港区吞吐", "客户维度", "分港区"], "note": ""}, {"name": "getContributionByCargoCategoryName", "intent": "查询战略客户按货类的贡献度分析", "time": "T_MON", "gran": "G_CARGO", "req": "无", "tags": ["贡献度", "货类贡献", "战略客户"], "note": ""}, {"name": "getClientContributionOrder", "intent": "查询客户贡献度排名（Top10，按贡献量降序）", "time": "T_MON", "gran": "G_CLIENT", "req": "无", "tags": ["客户排名", "贡献度排名", "Top10"], "note": "区别getCurContributionRankOfStrategicCustomer=商务驾驶舱版"}, {"name": "getStrategicCustomerRevenue", "intent": "查询战略客户营业收入排名（客户收入贡献）", "time": "T_MON", "gran": "G_CLIENT", "req": "无", "tags": ["收入", "战略客户收入", "营业收入", "排名"], "note": "区别getStrategicCustomerThroughput=吞吐量维度"}, {"name": "getStrategicCustomerThroughput", "intent": "查询战略客户吞吐量贡献排名", "time": "T_MON", "gran": "G_CLIENT", "req": "无", "tags": ["战略客户吞吐", "排名", "贡献率"], "note": "区别getStrategicCustomerRevenue=收入维度"}, {"name": "getContributionTrend", "intent": "查询战略客户月度贡献趋势（当年vs上年）", "time": "T_TREND", "gran": "G_PORT", "req": "无", "tags": ["贡献趋势", "月度趋势", "战略客户"], "note": "区别getCumulativeContributionTrend=多年历史"}, {"name": "getCumulativeContributionTrend", "intent": "查询多年战略客户累计贡献趋势（历年对比）", "time": "T_HIST", "gran": "G_PORT", "req": "startYear+endYear+contributionType", "tags": ["历年贡献", "多年对比", "累计贡献"], "note": "区别getContributionTrend=单年vs上年月度对比"}, {"name": "getStrategicCustomerContributionCustomerOperatingRevenue", "intent": "查询当月战略客户营业收入贡献（商务驾驶舱版）", "time": "T_MON", "gran": "G_CLIENT", "req": "date", "tags": ["战略客户", "收入", "当月", "商务驾驶舱"], "note": "区别getSumStrategicCustomer...Revenue=累计版"}, {"name": "getCurStrategicCustomerContributionByCargoTypeThroughput", "intent": "查询当月战略客户按货类贡献的吞吐量", "time": "T_MON", "gran": "G_CARGO", "req": "date", "tags": ["战略客户", "货类贡献", "当月", "商务驾驶舱"], "note": "区别Sum版=累计"}, {"name": "getCurContributionRankOfStrategicCustomer", "intent": "查询当月战略客户贡献排名（商务驾驶舱版）", "time": "T_MON", "gran": "G_CLIENT", "req": "date", "tags": ["战略客户排名", "当月排名", "商务驾驶舱"], "note": "区别Sum版=累计排名"}, {"name": "getCurStrategyCustomerTrendAnalysis", "intent": "查询当年战略客户月度趋势分析（吞吐+收入+贡献率）", "time": "T_TREND", "gran": "G_CLIENT", "req": "date", "tags": ["战略客户", "月度趋势", "商务驾驶舱"], "note": "区别Sum版=含累计序列"}, {"name": "getSumStrategicCustomerContributionCustomerOperatingRevenue", "intent": "查询年累计战略客户营业收入贡献排名", "time": "T_CUM", "gran": "G_CLIENT", "req": "date", "tags": ["战略客户", "累计收入", "年累计"], "note": "区别Cur版=当月"}, {"name": "getSumStrategicCustomerContributionByCargoTypeThroughput", "intent": "查询年累计战略客户按货类贡献吞吐量", "time": "T_CUM", "gran": "G_CARGO", "req": "date", "tags": ["战略客户", "货类贡献", "年累计"], "note": ""}, {"name": "getSumContributionRankOfStrategicCustomer", "intent": "查询年累计战略客户贡献排名", "time": "T_CUM", "gran": "G_CLIENT", "req": "date", "tags": ["战略客户排名", "年累计排名"], "note": "区别Cur版=当月"}, {"name": "getSumStrategyCustomerTrendAnalysis", "intent": "查询战略客户历年累计趋势分析", "time": "T_HIST", "gran": "G_CLIENT", "req": "无", "tags": ["战略客户", "历年趋势", "累计趋势"], "note": "区别Cur版=当年月度趋势"}], "D4": [{"name": "investCorpShareholdingProp", "intent": "查询投资企业持股比例分布（0-20%/20-50%/50%以上/全资）", "time": "T_NONE", "gran": "G_CMP", "req": "无", "tags": ["持股比例", "投企", "股权结构"], "note": ""}, {"name": "getMeetingInfo", "intent": "查询指定月份董事会/监事会/股东大会召开数量及待处理议案", "time": "T_MON", "gran": "G_CMP", "req": "date", "tags": ["会议", "董事会", "监事会", "议案"], "note": "区别getMeetDetail=单次会议明细"}, {"name": "getMeetDetail", "intent": "查询指定月份会议议案明细（按议案状态筛选）", "time": "T_MON", "gran": "G_CMP", "req": "date+yianZt", "tags": ["议案明细", "董事会", "会议记录"], "note": "区别getMeetingInfo=汇总数量"}, {"name": "getNewEnterprise", "intent": "查询年内新设企业信息（注册时间/注册资本/业务范围）", "time": "T_YR", "gran": "G_CMP", "req": "date", "tags": ["新设企业", "新增", "注册资本"], "note": "区别getWithdrawalInfo=注销退出"}, {"name": "getWithdrawalInfo", "intent": "查询年内退出/注销企业信息", "time": "T_YR", "gran": "G_CMP", "req": "date", "tags": ["退出企业", "注销", "退股", "合并"], "note": "区别getNewEnterprise=新设"}, {"name": "getBusinessExpirationInfo", "intent": "查询营业执照即将到期的企业及续期状态", "time": "T_NONE", "gran": "G_CMP", "req": "date", "tags": ["营业执照", "到期", "续期", "到期预警"], "note": ""}, {"name": "getSupervisorIncidentInfo", "intent": "查询监管人员变动信息（新任/离任/调任）", "time": "T_YR", "gran": "G_CMP", "req": "date", "tags": ["人员变动", "董事长", "总经理", "监事"], "note": ""}], "D5": [{"name": "getTotalssets", "intent": "查询指定港区资产总数量（实物资产+金融资产）", "time": "T_NONE", "gran": "G_ZONE", "req": "assetOwnerZone", "tags": ["资产总数", "实物资产", "金融资产"], "note": "区别getAssetValue=价值；getMainAssetsInfo=重要资产"}, {"name": "getAssetValue", "intent": "查询港区资产原值和净值（含折旧率）", "time": "T_NONE", "gran": "G_ZONE", "req": "ownerZone", "tags": ["资产价值", "原值", "净值", "折旧"], "note": "区别getTotalssets=数量；getMainAssetsInfo=重要资产明细"}, {"name": "getMainAssetsInfo", "intent": "查询港区主要资产类别数量（设备/设施/房屋/土地）", "time": "T_NONE", "gran": "G_ZONE", "req": "ownerZone", "tags": ["主要资产", "设备数量", "设施", "房屋"], "note": ""}, {"name": "getRealAssetsDistribution", "intent": "查询实物资产类型分布（设备/设施/房屋/土地数量占比）", "time": "T_NONE", "gran": "G_ZONE", "req": "ownerZone", "tags": ["资产分布", "类型分布", "实物资产"], "note": ""}, {"name": "getOriginalValueDistribution", "intent": "查询各类资产原值分布", "time": "T_NONE", "gran": "G_ZONE", "req": "ownerZone", "tags": ["原值分布", "资产原值"], "note": "区别getRealAssetsDistribution=数量分布"}, {"name": "getDistributionOfImportantAssetNetValueRanges", "intent": "查询重要资产净值区间分布（1000万以下/1000-5000万等）", "time": "T_NONE", "gran": "G_ZONE", "req": "ownerZone", "tags": ["净值区间", "重要资产", "价值分布"], "note": ""}, {"name": "getFinancialAssetsDistribution", "intent": "查询金融资产类型分布（股权/应收款/债券/基金）", "time": "T_NONE", "gran": "G_PORT", "req": "无", "tags": ["金融资产", "股权投资", "应收账款", "分布"], "note": "区别NetValue=净值分布"}, {"name": "getFinancialAssetsNetValueDistribution", "intent": "查询金融资产净值分布（各类型价值占比）", "time": "T_NONE", "gran": "G_PORT", "req": "无", "tags": ["金融资产净值", "价值分布", "股权投资价值"], "note": "区别Distribution=数量分布"}, {"name": "getHistoricalTrends", "intent": "查询港区资产历年变化趋势（2022-2026，数量/原值/净值/新增/报废）", "time": "T_HIST", "gran": "G_ZONE", "req": "ownerZone", "tags": ["历年趋势", "资产变化", "历史数据"], "note": ""}, {"name": "getRealAssetQty", "intent": "查询本年新增实物资产数量和价值", "time": "T_YR", "gran": "G_ZONE", "req": "ownerZone", "tags": ["新增资产", "年度新增", "资产数量"], "note": "区别getMothballingRealAssetQty=报废封存"}, {"name": "getMothballingRealAssetQty", "intent": "查询本年报废/封存资产数量和价值", "time": "T_YR", "gran": "G_ZONE", "req": "ownerZone", "tags": ["报废资产", "封存", "资产减少"], "note": "区别getRealAssetQty=新增"}, {"name": "getTrendNewAssets", "intent": "查询近5年新增资产趋势（数量+价值）", "time": "T_HIST", "gran": "G_ZONE", "req": "ownerZone", "tags": ["新增趋势", "历年新增", "资产新增"], "note": "区别getTrendScrappedAssets=报废趋势"}, {"name": "getTrendScrappedAssets", "intent": "查询近5年报废资产趋势", "time": "T_HIST", "gran": "G_ZONE", "req": "ownerZone", "tags": ["报废趋势", "历年报废"], "note": "区别getTrendNewAssets=新增趋势"}, {"name": "getOriginalQuantity", "intent": "查询本年新增资产原始数量和原值", "time": "T_YR", "gran": "G_ZONE", "req": "ownerZone+dateYear", "tags": ["新增数量", "原值", "年度"], "note": ""}, {"name": "getOriginalValueScrappedQuantity", "intent": "查询本年报废资产数量及原值", "time": "T_YR", "gran": "G_ZONE", "req": "ownerZone+dateYear", "tags": ["报废数量", "原值", "年度报废"], "note": ""}, {"name": "getNewAssetTransparentAnalysis", "intent": "查询各公司新增资产穿透分析（数量/价值/主要类别）", "time": "T_YR", "gran": "G_CMP", "req": "ownerZone+dateYear+asseTypeName", "tags": ["新增穿透", "公司新增", "透明分析"], "note": "区别ScrapAsset=报废穿透"}, {"name": "getScrapAssetTransmitAnalysis", "intent": "查询各公司报废资产穿透分析", "time": "T_YR", "gran": "G_CMP", "req": "ownerZone+dateYear+asseTypeName", "tags": ["报废穿透", "公司报废", "透明分析"], "note": "区别NewAsset=新增穿透"}, {"name": "getPhysicalAssets", "intent": "查询全港实物资产汇总（总数量/原值/净值）", "time": "T_YR", "gran": "G_PORT", "req": "dateYear", "tags": ["实物资产汇总", "总量", "原值净值"], "note": ""}, {"name": "getRegionalAnalysis", "intent": "查询各港区资产数量/原值/净值对比", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["港区资产", "区域对比", "资产分布"], "note": ""}, {"name": "getCategoryAnalysis", "intent": "查询各类别资产数量/原值/净值（设备/设施/房屋/土地）", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear", "tags": ["资产类别", "类型分析", "设备设施房屋土地"], "note": "区别getRegionalAnalysis=按港区"}, {"name": "getRegionalAnalysisTransparentTransmission", "intent": "查询指定港区各类型资产穿透详情", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear+ownerZone", "tags": ["区域穿透", "港区详情", "类型细分"], "note": ""}, {"name": "getCategoryAnalysisTransparentTransmission", "intent": "查询指定类型资产按港区穿透详情", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear+assetTypeName", "tags": ["类型穿透", "资产类型", "港区细分"], "note": ""}, {"name": "getHousingAssertAnalysisTransparentTransmission", "intent": "查询房屋资产穿透分析（按港区/用房类型/面积/价值）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["房屋资产", "房屋穿透", "建筑面积"], "note": ""}, {"name": "getImportantAssetRegionAnalysisPenetrationPage", "intent": "查询重要资产按港区穿透分析（分页）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["重要资产", "区域穿透", "分页"], "note": ""}, {"name": "getEquipmentFacilityStateDistribution", "intent": "查询设备设施运行状态分布（正常/维修/闲置/报废申请）", "time": "T_NONE", "gran": "G_ZONE", "req": "ownerZone", "tags": ["设备状态", "状态分布", "维修", "闲置"], "note": "区别D7的EquipmentUsageRate=利用率指标"}, {"name": "getEquipmentFacilityAnalysisYoy", "intent": "查询设备设施数量和净值同比变化", "time": "T_YOY", "gran": "G_PORT", "req": "dateYear", "tags": ["设备同比", "净值同比", "设施同比"], "note": ""}, {"name": "getEquipmentFacilityAnalysis", "intent": "查询设备或设施分类分析（type=1设备/type=2设施）", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear+type", "tags": ["设备分类", "设施分类", "装卸设备", "运输设备"], "note": "区别StatusAnalysis=按状态；RegionalAnalysis=按港区"}, {"name": "getEquipmentFacilityStatusAnalysis", "intent": "查询设备/设施按状态分布（正常/维修/超期/闲置等）", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear+type", "tags": ["状态分析", "设备状态", "超期服役"], "note": ""}, {"name": "getEquipmentFacilityRegionalAnalysis", "intent": "查询各港区设备/设施数量和净值分布", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear+type", "tags": ["区域分析", "设备区域", "港区设备"], "note": ""}, {"name": "getEquipmentFacilityWorthAnalysis", "intent": "查询设备/设施净值区间分布", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear+type", "tags": ["净值区间", "设备价值", "价值分布"], "note": ""}, {"name": "getEquipmentAnalysisTransparentTransmission", "intent": "查询设备类型分析穿透（按状态和类型筛选）", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear", "tags": ["设备穿透", "设备类型"], "note": "区别ByFirst=二级穿透"}, {"name": "getEquipmentAnalysisTransparentTransmissionByFirst", "intent": "查询设备二级子类穿透分析", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear", "tags": ["设备子类", "设备穿透", "二级分类"], "note": "区别无ByFirst=一级穿透"}, {"name": "getLandMaritimeAnalysisTransparentTransmission", "intent": "查询土地和海域资产穿透分析（面积/价值按港区）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["土地", "海域", "面积", "港区"], "note": ""}, {"name": "getHousingAnalysisYoy", "intent": "查询房屋资产同比（数量/面积/净值）", "time": "T_YOY", "gran": "G_PORT", "req": "dateYear", "tags": ["房屋同比", "建筑面积", "净值同比"], "note": ""}, {"name": "getHousingRegionalAnalysis", "intent": "查询各港区房屋资产（数量/面积/净值）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["房屋资产", "按港区", "建筑面积"], "note": ""}, {"name": "getHousingWorthAnalysis", "intent": "查询房屋资产净值区间分布", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear", "tags": ["房屋净值", "价值区间"], "note": ""}, {"name": "getLandMaritimeAnalysisYoy", "intent": "查询土地海域资产同比（面积/净值）", "time": "T_YOY", "gran": "G_PORT", "req": "dateYear", "tags": ["土地同比", "海域同比", "亩"], "note": ""}, {"name": "getLandMaritimeRegionalAnalysis", "intent": "查询各港区土地海域面积和净值", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["土地按港区", "海域", "面积"], "note": ""}, {"name": "getLandMaritimeWorthAnalysis", "intent": "查询土地海域资产类型价值分析（工业/港口/绿化/海域使用权）", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear", "tags": ["土地类型", "海域价值", "单价"], "note": ""}, {"name": "getImportAssertAnalysisList", "intent": "查询重要资产明细列表（支持多条件筛选，分页）", "time": "T_YR", "gran": "G_ASSET", "req": "dateYear", "tags": ["资产列表", "明细", "分页"], "note": ""}, {"name": "getImportAssetWorthAnalysisByOwnerZone", "intent": "查询各港区重要资产净值分析（按净值区间筛选）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear+type+minNum+maxNum+typeName", "tags": ["重要资产", "净值分析", "港区"], "note": "区别ByCmpName=按公司"}, {"name": "getImportAssetWorthAnalysisByCmpName", "intent": "查询各公司重要资产净值分析", "time": "T_YR", "gran": "G_CMP", "req": "dateYear+type+minNum+maxNum+ownerZone+typeName", "tags": ["重要资产", "净值分析", "公司"], "note": "区别ByOwnerZone=按港区"}, {"name": "getNetValueDistribution", "intent": "查询各港区资产净值区间分布（test路径版）", "time": "T_NONE", "gran": "G_ZONE", "req": "ownerZone", "tags": ["净值分布", "区间分布", "港区"], "note": ""}], "D6": [{"name": "getInvestPlanTypeProjectList", "intent": "查询年度投资计划类型汇总（资本性/成本性/计划外项目数和金额）", "time": "T_YR", "gran": "G_ZONE", "req": "无", "tags": ["投资计划", "资本项目", "成本项目", "计划外"], "note": ""}, {"name": "getPlanProgressByMonth", "intent": "查询年度投资计划月度进度（累计计划vs实际完成）", "time": "T_TREND", "gran": "G_ZONE", "req": "无", "tags": ["投资进度", "月度进度", "计划完成率"], "note": ""}, {"name": "planInvestAndPayYoy", "intent": "查询年度投资计划和付款额同比", "time": "T_YOY", "gran": "G_PORT", "req": "无", "tags": ["投资同比", "付款同比", "年度对比"], "note": ""}, {"name": "getFinishProgressAndDeliveryRate", "intent": "查询年度投资完成进度和资本项目交付率", "time": "T_YR", "gran": "G_ZONE", "req": "无", "tags": ["完成进度", "交付率", "资本项目"], "note": ""}, {"name": "getInvestPlanByYear", "intent": "查询近5年投资计划和完成情况历年对比", "time": "T_HIST", "gran": "G_ZONE", "req": "无", "tags": ["历年投资", "投资趋势", "完成率"], "note": ""}, {"name": "getCostProjectFinishByYear", "intent": "查询近5年成本性项目完成情况", "time": "T_HIST", "gran": "G_ZONE", "req": "无", "tags": ["成本项目", "历年完成", "成本投资"], "note": ""}, {"name": "getCostProjectYoyList", "intent": "查询成本性项目数量和金额同比", "time": "T_YOY", "gran": "G_PORT", "req": "无", "tags": ["成本项目", "同比", "年度对比"], "note": ""}, {"name": "getCostProjectQtyList", "intent": "查询成本性项目分类数量和金额占比", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["成本项目分类", "设备维修", "安全整改"], "note": ""}, {"name": "getCostProjectAmtByOwnerLgZoneName", "intent": "查询各港区成本性项目金额（批复/完成/招标）", "time": "T_YR", "gran": "G_ZONE", "req": "无", "tags": ["成本项目", "按港区", "招标金额"], "note": ""}, {"name": "getCostProjectCurrentStageQtyList", "intent": "查询成本性项目当前阶段数量（立项/招标/施工/竣工等）", "time": "T_YR", "gran": "G_ZONE", "req": "无", "tags": ["项目阶段", "施工阶段", "进度"], "note": ""}, {"name": "getCostProjectQtyByProjectCmp", "intent": "查询各公司成本性项目数量和完成情况", "time": "T_YR", "gran": "G_CMP", "req": "无", "tags": ["成本项目", "按公司", "完成率"], "note": ""}, {"name": "getInvestAmtList", "intent": "查询投资项目金额明细列表（分页，支持多条件筛选）", "time": "T_YR", "gran": "G_PROJ", "req": "dateYear", "tags": ["投资明细", "项目列表", "分页"], "note": ""}, {"name": "getOutOfPlanFinishProgressList", "intent": "查询计划外项目完成进度汇总", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["计划外", "完成进度", "未计划项目"], "note": ""}, {"name": "getOutOfPlanProjectQtyYoy", "intent": "查询计划外项目数量和金额同比", "time": "T_YOY", "gran": "G_PORT", "req": "无", "tags": ["计划外", "同比", "年度对比"], "note": ""}, {"name": "getOutOfPlanProjectInvestFinishList", "intent": "查询计划外项目近5年投资完成历史", "time": "T_HIST", "gran": "G_PORT", "req": "无", "tags": ["计划外", "历年", "投资完成"], "note": ""}, {"name": "getOutOfPlanProjectPayFinishList", "intent": "查询计划外项目近5年付款完成历史", "time": "T_HIST", "gran": "G_PORT", "req": "无", "tags": ["计划外", "付款", "历年"], "note": ""}, {"name": "getPlanFinishByZone", "intent": "查询各港区投资计划完成情况和交付率", "time": "T_YR", "gran": "G_ZONE", "req": "无", "tags": ["各港区", "投资完成", "交付率"], "note": ""}, {"name": "getPlanFinishByProjectType", "intent": "查询各项目类型完成情况（技改/新建/扩建/维护改造/安全环保）", "time": "T_YR", "gran": "G_PROJ", "req": "无", "tags": ["项目类型", "技改", "新建", "完成率"], "note": ""}, {"name": "getPlanExcludedProjectPenetrationAnalysis", "intent": "查询计划外项目按港区/类型的穿透分析", "time": "T_YR", "gran": "G_ZONE", "req": "无", "tags": ["计划外穿透", "按港区", "按类型"], "note": ""}, {"name": "getUnplannedProjectsInquiry", "intent": "查询计划外项目明细查询（分页）", "time": "T_YR", "gran": "G_PROJ", "req": "无", "tags": ["计划外明细", "项目查询", "分页"], "note": ""}, {"name": "getCapitalApprovalAnalysisLimitInquiry", "intent": "查询资本性项目批复金额/完成/付款汇总分析", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["资本项目", "批复金额", "付款率"], "note": ""}, {"name": "getCapitalApprovalAnalysisProject", "intent": "查询各项目类型资本性项目批复分析", "time": "T_YR", "gran": "G_PROJ", "req": "无", "tags": ["资本项目", "项目类型", "批复"], "note": ""}, {"name": "getVisualProgressAnalysisAndStatistics", "intent": "查询资本性项目建设阶段分布（前期/施工/竣工验收/交付）", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["建设阶段", "进度分布", "资本项目"], "note": ""}, {"name": "getCompletionStatus", "intent": "查询资本性项目年度完成状态（金额完成率+项目完成率）", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["完成状态", "资本项目", "完成率"], "note": ""}, {"name": "getDeliveryRate", "intent": "查询资本性项目交付率（已交付/按时交付）", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["交付率", "按时交付", "资本项目"], "note": ""}, {"name": "getNumberCapitalProjectsDelivered", "intent": "查询已交付资本性项目数量和价值", "time": "T_YR", "gran": "G_PORT", "req": "无", "tags": ["已交付", "交付数量", "资本项目"], "note": "区别ByZone=按港区；ByPlan=按类型"}, {"name": "getNumberCapitalProjectsDeliveredZoneName", "intent": "查询各港区当月资本性项目交付数量", "time": "T_MON", "gran": "G_ZONE", "req": "无", "tags": ["交付", "按港区", "月度"], "note": ""}, {"name": "getRegionalInvestmentQuota", "intent": "查询各港区投资额度使用情况（批复/已用/使用率）", "time": "T_MON", "gran": "G_ZONE", "req": "无", "tags": ["投资额度", "按港区", "额度使用"], "note": ""}, {"name": "getNumberCapitalProjectsDeliveredPlanAnalysis", "intent": "查询各计划类型资本性项目交付率", "time": "T_MON", "gran": "G_PROJ", "req": "无", "tags": ["交付分析", "计划类型", "交付率"], "note": ""}, {"name": "getTypeAnalysisInvestmentAmountQuery", "intent": "查询各项目类型投资金额完成情况（月度）", "time": "T_MON", "gran": "G_PROJ", "req": "无", "tags": ["项目类型", "月度金额", "完成率"], "note": ""}, {"name": "getCapitalProjectsList", "intent": "查询资本性项目明细列表（分页，支持多维度筛选）", "time": "T_YR", "gran": "G_PROJ", "req": "无", "tags": ["资本项目", "明细列表", "分页"], "note": ""}], "D7": [{"name": "getEquipmentIndicatorOperationQty", "intent": "查询各港区设备作业量指标（集装箱/散货，月度）", "time": "T_MON", "gran": "G_ZONE", "req": "dateMonth", "tags": ["设备作业量", "指标", "月度", "港区"], "note": "区别getEquipmentIndicatorUseCost=使用成本"}, {"name": "getEquipmentIndicatorUseCost", "intent": "查询各港区设备使用成本指标（燃油/电力/维修，月度）", "time": "T_MON", "gran": "G_ZONE", "req": "dateMonth", "tags": ["设备成本", "燃油", "电力", "维修"], "note": "区别OperationQty=作业量"}, {"name": "getProductionEquipmentFaultNum", "intent": "查询生产设备年度故障次数（重大/一般，含同比）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["故障次数", "设备故障", "维修"], "note": ""}, {"name": "getProductionEquipmentStatistic", "intent": "查询生产设备月度概览（总数/在用/完好率/利用率/平均役龄）", "time": "T_MON", "gran": "G_ZONE", "req": "dateMonth", "tags": ["设备概览", "完好率", "利用率", "役龄"], "note": ""}, {"name": "getProductionEquipmentServiceAgeDistribution", "intent": "查询生产设备役龄分布（0-5年/5-10年/10-15年等）", "time": "T_MON", "gran": "G_ZONE", "req": "dateMonth", "tags": ["役龄分布", "设备年龄", "老化"], "note": ""}, {"name": "getOverviewQuery", "intent": "查询单台设备综合概览（完好率/台时效率/单耗/作业量/成本，单据大屏）", "time": "T_MON", "gran": "G_EQUIP", "req": "date+equipmentNo+ownerLgZoneName+cmpName+firstLevelClassName", "tags": ["单机概览", "设备综合", "单据大屏"], "note": ""}, {"name": "getSingleEquipmentIntegrityRate", "intent": "查询单台设备完好率及月度趋势", "time": "T_MON", "gran": "G_EQUIP", "req": "equipmentNo", "tags": ["单机完好率", "完好率趋势"], "note": "区别getMachineDataDisplayScreenEquipmentIntegrityRate=机种级完好率"}, {"name": "getUnitHourEfficiency", "intent": "查询单台设备台时效率及月度趋势", "time": "T_MON", "gran": "G_EQUIP", "req": "equipmentNo", "tags": ["台时效率", "单机效率", "自然箱/小时"], "note": ""}, {"name": "getUnitConsumption", "intent": "查询单台设备能源单耗及月度趋势（燃油+电力）", "time": "T_MON", "gran": "G_EQUIP", "req": "equipmentNo", "tags": ["单耗", "能耗", "燃油", "电力"], "note": ""}, {"name": "getSingleMachineUtilization", "intent": "查询单台设备利用率及有效利用率月度趋势", "time": "T_MON", "gran": "G_EQUIP", "req": "equipmentNo", "tags": ["利用率", "有效利用率", "单台"], "note": ""}, {"name": "getSingleCost", "intent": "查询单台设备年度成本（燃油/电力/维修/其他及单位成本）", "time": "T_YR", "gran": "G_EQUIP", "req": "equipmentNo", "tags": ["单机成本", "设备成本", "维修费"], "note": ""}, {"name": "getEquipmentUsageRate", "intent": "查询各港区年度设备利用率（含月度分布曲线）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["利用率", "年度利用率", "港区", "月度分布"], "note": "区别getProductEquipmentUsageRateByYear=历年对比；BYMonth=月度版"}, {"name": "getEquipmentServiceableRate", "intent": "查询各港区年度设备完好率（含月度分布）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["完好率", "年度完好率", "港区"], "note": "区别getProductEquipmentIntegrityRateByYear=历年版"}, {"name": "getEquipmentFirstLevelClassNameList", "intent": "查询设备一级分类列表及数量（装卸/运输/起重/输送/特种）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["设备分类", "一级分类", "分类列表"], "note": ""}, {"name": "getEquipmentMachineHourRate", "intent": "查询各港区年度台时效率（含月度曲线）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["台时效率", "年度", "港区", "月度趋势"], "note": "区别getContainerMachineHourRate=集装箱专用"}, {"name": "getContainerMachineHourRate", "intent": "查询集装箱装卸设备台时效率（岸桥/RTG分项，月度曲线）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["集装箱台时", "岸桥", "RTG", "月度"], "note": "区别getEquipmentMachineHourRate=全类设备"}, {"name": "getEquipmentEnergyConsumptionPerUnit", "intent": "查询各港区年度设备能源单耗（含月度趋势）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["能源单耗", "年度", "港区", "kgce"], "note": ""}, {"name": "getEquipmentFuelOilTonCost", "intent": "查询各港区年度燃油吨成本（元/自然箱，月度趋势）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["燃油成本", "吨成本", "元/自然箱"], "note": "区别getEquipmentElectricityTonCost=电量成本"}, {"name": "getEquipmentElectricityTonCost", "intent": "查询各港区年度电量吨成本（元/自然箱，月度趋势）", "time": "T_YR", "gran": "G_ZONE", "req": "dateYear", "tags": ["电量成本", "电费", "元/自然箱"], "note": "区别FuelOil=燃油成本"}, {"name": "getMachineDataDisplayScreenHourlyEfficiency", "intent": "查询指定机种当月台时效率及各台设备明细（机种展示屏）", "time": "T_MON", "gran": "G_EQUIP", "req": "secondLevelClassName+date", "tags": ["机种台时", "机种展示", "月度"], "note": "区别getEquipmentMachineHourRate=港区汇总版"}, {"name": "getModelDataDisplayScreenEnergyConsumptionPerUnit", "intent": "查询指定机种当月能耗单耗（机种展示屏）", "time": "T_MON", "gran": "G_EQUIP", "req": "secondLevelClassName+date", "tags": ["机种能耗", "单耗", "月度"], "note": ""}, {"name": "getFuelTonCostOfAircraftDataDisplay", "intent": "查询指定机种燃油吨成本（机种展示屏）", "time": "T_MON", "gran": "G_EQUIP", "req": "secondLevelClassName+date", "tags": ["机种燃油", "燃油成本", "月度"], "note": "区别getEquipmentFuelOilTonCost=港区汇总版"}, {"name": "getMachineTypeDataDisplayScreenPowerConsumptionCostPerTon", "intent": "查询指定机种电量吨成本（机种展示屏）", "time": "T_MON", "gran": "G_EQUIP", "req": "secondLevelClassName+date", "tags": ["机种电量", "电量成本", "月度"], "note": ""}, {"name": "getModelDataDisplayScreenUtilization", "intent": "查询指定机种年度利用率（机种展示屏）", "time": "T_YR", "gran": "G_EQUIP", "req": "secondLevelClassName+dateYear", "tags": ["机种利用率", "年度", "月度分布"], "note": ""}, {"name": "getModelDataDisplayScreenEffectiveUtilization", "intent": "查询指定机种年度有效利用率（机种展示屏）", "time": "T_YR", "gran": "G_EQUIP", "req": "secondLevelClassName+dateYear", "tags": ["机种有效利用率", "年度"], "note": "区别getModelDataDisplayScreenUtilization=总利用率"}, {"name": "getMachineDataDisplayScreenEquipmentIntegrityRate", "intent": "查询指定机种年度完好率（机种展示屏）", "time": "T_YR", "gran": "G_EQUIP", "req": "secondLevelClassName+dateYear", "tags": ["机种完好率", "年度"], "note": ""}, {"name": "getModelDataDisplayScreenHierarchyRelation", "intent": "查询设备二级分类的层级关系（判断是否属于集装箱设备）", "time": "T_NONE", "gran": "G_EQUIP", "req": "secondLevelClassName", "tags": ["层级关系", "集装箱设备", "分类归属"], "note": ""}, {"name": "getMachineDataDisplayEquipmentReliability", "intent": "查询集装箱设备可靠性指标（MTBF/MTTR/故障次数，机种展示屏）", "time": "T_YR", "gran": "G_EQUIP", "req": "secondLevelClassName+dateYear", "tags": ["可靠性", "MTBF", "MTTR", "集装箱设备"], "note": "区别getNonContainer=非集装箱版"}, {"name": "getNonContainerProductionEquipmentReliability", "intent": "查询非集装箱设备可靠性指标（散货/油化/滚装）", "time": "T_YR", "gran": "G_EQUIP", "req": "secondLevelClassName+dateYear", "tags": ["可靠性", "非集装箱", "散货设备", "MTBF"], "note": "区别getContainer版=集装箱设备"}, {"name": "getMachineDataDisplaySingleUnitEnergyConsumption", "intent": "查询指定机种下各单台设备月度能耗（机种展示屏）", "time": "T_MON", "gran": "G_EQUIP", "req": "secondLevelClassName+date", "tags": ["单台能耗", "机种", "月度"], "note": ""}, {"name": "getProductEquipmentUsageRateByYear", "intent": "查询近5年生产设备有效利用率历年对比", "time": "T_HIST", "gran": "G_ZONE", "req": "无", "tags": ["历年利用率", "有效利用率", "年度趋势"], "note": "区别ByMonth=当年月度分布"}, {"name": "getProductEquipmentUsageRateByMonth", "intent": "查询年度生产设备有效利用率月度分布", "time": "T_TREND", "gran": "G_ZONE", "req": "dateYear", "tags": ["月度利用率", "设备利用率", "月度分布"], "note": "区别ByYear=历年趋势"}, {"name": "getProductEquipmentRateByYear", "intent": "查询近5年生产设备利用率历年对比", "time": "T_HIST", "gran": "G_ZONE", "req": "无", "tags": ["历年利用率", "设备利用率"], "note": "区别UsageRate=有效利用率（更严格）"}, {"name": "getProductEquipmentIntegrityRateByYear", "intent": "查询生产设备年度完好率（当年vs上年同比）", "time": "T_YOY", "gran": "G_ZONE", "req": "dateYear+preYear", "tags": ["完好率", "年度完好率", "同比"], "note": "区别ByMonth=月度版"}, {"name": "getProductEquipmentIntegrityRateByMonth", "intent": "查询生产设备月度完好率（当月vs去年同月同比）", "time": "T_YOY", "gran": "G_ZONE", "req": "dateMonth+preDateMonth", "tags": ["月度完好率", "同比", "当月"], "note": "区别ByYear=年度版"}, {"name": "getQuayEquipmentWorkingAmount", "intent": "查询岸边设备月度作业量及同比（集装箱台数）", "time": "T_MON", "gran": "G_ZONE", "req": "dateMonth", "tags": ["岸边设备", "作业量", "同比", "月度"], "note": ""}, {"name": "getProductEquipmentDataAnalysisList", "intent": "查询生产设备数据分析列表（分页，多指标）", "time": "T_MON", "gran": "G_EQUIP", "req": "dateMonth", "tags": ["设备列表", "分析列表", "分页"], "note": ""}, {"name": "getEquipmentUseList", "intent": "查询设备使用记录列表（时间段内，含作业时间/效率）", "time": "T_TREND", "gran": "G_EQUIP", "req": "startDate+endDate+month", "tags": ["使用记录", "作业记录", "设备使用"], "note": ""}, {"name": "getProductEquipmentWorkingAmountByYear", "intent": "查询近5年生产设备作业量历年对比", "time": "T_HIST", "gran": "G_ZONE", "req": "dateYear", "tags": ["历年作业量", "设备作业", "年度趋势"], "note": "区别ByMonth=当年月度"}, {"name": "getProductEquipmentWorkingAmountByMonth", "intent": "查询生产设备当月作业量及同比", "time": "T_TREND", "gran": "G_ZONE", "req": "dateMonth", "tags": ["月度作业量", "同比", "当月"], "note": "区别ByYear=历年趋势"}, {"name": "getProductEquipmentReliabilityByYear", "intent": "查询近5年生产设备可靠性（MTBF）历年趋势", "time": "T_HIST", "gran": "G_ZONE", "req": "无", "tags": ["可靠性历年", "MTBF趋势"], "note": "区别ByMonth=当年月度"}, {"name": "getProductEquipmentReliabilityByMonth", "intent": "查询年度生产设备可靠性月度趋势", "time": "T_TREND", "gran": "G_ZONE", "req": "dateYear", "tags": ["月度可靠性", "MTBF月度"], "note": "区别ByYear=历年趋势"}, {"name": "getProductEquipmentUnitConsumptionByYear", "intent": "查询近5年生产设备能耗单耗历年对比", "time": "T_HIST", "gran": "G_PORT", "req": "dateYear", "tags": ["历年单耗", "能耗趋势"], "note": "区别ByMonth=当年月度"}, {"name": "getProductEquipmentUnitConsumptionByMonth", "intent": "查询生产设备当月能耗单耗及同比/环比", "time": "T_TREND", "gran": "G_PORT", "req": "dateMonth", "tags": ["月度单耗", "同比", "环比"], "note": "区别ByYear=历年趋势"}]}


@app.get("/api/meta/domains")
async def meta_domains():
    """阶段一：领域路由索引"""
    return JSONResponse({"code": 200, "msg": "success", "data": _DOMAIN_INDEX})


@app.get("/api/meta/domain/{domain_id}")
async def meta_domain_cards(domain_id: str):
    """阶段二：指定领域API卡片列表"""
    cards = _DOMAIN_CARDS.get(domain_id)
    if not cards:
        raise HTTPException(status_code=404, detail=f"Domain {domain_id} not found")
    return JSONResponse({"code": 200, "msg": "success", "data": cards})


@app.get("/api/meta/api/{api_name}")
async def meta_api_detail(api_name: str):
    """阶段三：单个API完整元数据"""
    for api in _META_APIS:
        if api["path"].split("/")[-1] == api_name:
            return JSONResponse({"code": 200, "msg": "success", "data": api})
    raise HTTPException(status_code=404, detail=f"API {api_name} not found")


@app.get("/api/meta/search")
async def meta_search(q: str, domain: str = None):
    """关键词搜索API（可限定领域）"""
    results = []
    for api in _META_APIS:
        if domain and api["domain"] != domain:
            continue
        score = 0
        if q in api["intent"]: score += 3
        if any(q in tag for tag in api["tags"]): score += 2
        if q in api["path"]: score += 1
        if score > 0:
            results.append({
                "name": api["path"].split("/")[-1],
                "domain": api["domain"],
                "intent": api["intent"],
                "time": api["time"],
                "gran": api["granularity"],
                "score": score
            })
    results.sort(key=lambda x: -x["score"])
    return JSONResponse({"code": 200, "msg": "success", "data": results[:10]})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="港口司南 Mock API Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    print(f"\n=== 港口司南 Mock API Server v1.0 ===")
    print(f"=== 监听: http://{args.host}:{args.port}  |  接口数: 220  |  文档: /docs ===\n")
    uvicorn.run("__main__:app", host=args.host, port=args.port, reload=args.reload, log_level="info")
