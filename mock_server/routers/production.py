from fastapi import APIRouter, Depends, Query
from mock_server.utils import (
    verify_token, seeded_rng, calc_throughput_base,
    parse_month, in_data_range, out_of_range_response, success_response,
)
from mock_server.data.constants import (
    ZONE_SHARE, SEGMENT_SHARE, SHIP_NAMES, CARGO_TYPES,
)

router = APIRouter(prefix="/api/v1/production", tags=["生产运营域"])


# M01
@router.get("/throughput/summary")
def throughput_summary(
    date: str = Query(...),
    dateType: int = Query(...),
    regionName: str | None = Query(None),
    _=Depends(verify_token),
):
    if dateType == 0:
        # daily
        parts = date.split("-")
        year, month = int(parts[0]), int(parts[1])
    elif dateType == 1:
        year, month = parse_month(date)
    else:
        year = int(date)
        month = 6

    if not in_data_range(year, month):
        return out_of_range_response()

    rng = seeded_rng("M01", date, dateType, regionName)
    base = calc_throughput_base(year, month)

    if regionName and regionName in ZONE_SHARE:
        base *= ZONE_SHARE[regionName]

    if dateType == 0:
        base /= 30.0

    total = round(base * rng.uniform(0.98, 1.02), 1)
    target = round(total * rng.uniform(1.02, 1.10), 1)
    completion = round(total / target * 100, 1)
    yoy = round(rng.uniform(3.0, 9.5), 1)
    mom = round(rng.uniform(-5.0, 8.0), 1)

    if dateType == 2:
        if year == 2026:
            max_month = 6
        else:
            max_month = 12
        total_annual = 0.0
        for m in range(1, max_month + 1):
            total_annual += calc_throughput_base(year, m) * rng.uniform(0.98, 1.02)
        total = round(total_annual, 1)
        target = round(total * rng.uniform(1.02, 1.08), 1)
        completion = round(total / target * 100, 1)

    period = date
    return success_response({
        "totalThroughput": total,
        "targetThroughput": target,
        "completionRate": completion,
        "yoyGrowthRate": yoy,
        "momGrowthRate": mom,
        "period": period,
    })


# M02
@router.get("/throughput/by-business-type")
def throughput_by_business_type(
    flag: int = Query(...),
    dateMonth: str = Query(...),
    regionName: str | None = Query(None),
    _=Depends(verify_token),
):
    year, month = parse_month(dateMonth)
    if not in_data_range(year, month):
        return out_of_range_response()

    rng = seeded_rng("M02", flag, dateMonth, regionName)
    base = calc_throughput_base(year, month)
    if regionName and regionName in ZONE_SHARE:
        base *= ZONE_SHARE[regionName]

    if flag == 1:
        if year == 2026:
            max_m = min(month, 6)
        else:
            max_m = month
        base = sum(calc_throughput_base(year, m) for m in range(1, max_m + 1))
        if regionName and regionName in ZONE_SHARE:
            base *= ZONE_SHARE[regionName]

    result = []
    shares = {}
    for seg, base_share in SEGMENT_SHARE.items():
        share = base_share + rng.uniform(-0.03, 0.03)
        shares[seg] = share

    total_share = sum(shares.values())
    for seg in shares:
        shares[seg] = shares[seg] / total_share

    for seg, share in shares.items():
        tp = round(base * share * rng.uniform(0.97, 1.03), 1)
        result.append({
            "businessType": seg,
            "throughput": tp,
            "yoyRate": round(rng.uniform(1.0, 12.0), 1),
            "shareRatio": round(share * 100, 1),
        })

    return success_response(result)


# M03
@router.get("/throughput/monthly-trend")
def throughput_monthly_trend(
    dateYear: str = Query(...),
    preYear: str | None = Query(None),
    regionName: str | None = Query(None),
    _=Depends(verify_token),
):
    cur_year = int(dateYear)
    prev_year = int(preYear) if preYear else cur_year - 1

    if not in_data_range(cur_year):
        return out_of_range_response()

    rng = seeded_rng("M03", dateYear, preYear, regionName)
    max_month = 6 if cur_year == 2026 else 12

    result = []
    prev_val = None
    for m in range(1, max_month + 1):
        cur_base = calc_throughput_base(cur_year, m)
        prev_base = calc_throughput_base(prev_year, m) if in_data_range(prev_year, m) else None

        if regionName and regionName in ZONE_SHARE:
            cur_base *= ZONE_SHARE[regionName]
            if prev_base:
                prev_base *= ZONE_SHARE[regionName]

        cur_val = round(cur_base * rng.uniform(0.96, 1.04), 1)
        prev_v = round(prev_base * rng.uniform(0.96, 1.04), 1) if prev_base else None

        yoy = round((cur_val - prev_v) / prev_v * 100, 1) if prev_v else None
        mom = round((cur_val - prev_val) / prev_val * 100, 1) if prev_val else None

        result.append({
            "month": f"{m:02d}",
            "currentYear": cur_val,
            "prevYear": prev_v,
            "yoyRate": yoy,
            "momRate": mom,
        })
        prev_val = cur_val

    return success_response(result)


# M04
@router.get("/container/throughput")
def container_throughput(
    dateYear: str = Query(...),
    regionName: str | None = Query(None),
    _=Depends(verify_token),
):
    year = int(dateYear)
    if not in_data_range(year):
        return out_of_range_response()

    rng = seeded_rng("M04", dateYear, regionName)
    base_teu = 4_500_000
    from mock_server.data.constants import YOY_GROWTH
    growth = 1.0
    for y in range(2024, year):
        growth *= (1 + YOY_GROWTH.get(y, 0.055))

    max_month = 6 if year == 2026 else 12
    month_factor = max_month / 12.0

    total_teu = int(base_teu * growth * month_factor * rng.uniform(0.95, 1.05))
    if regionName and regionName in ZONE_SHARE:
        total_teu = int(total_teu * ZONE_SHARE[regionName])

    foreign_ratio = rng.uniform(0.65, 0.70)
    foreign_teu = int(total_teu * foreign_ratio)
    domestic_teu = total_teu - foreign_teu

    target_teu = int(total_teu * rng.uniform(1.02, 1.08))
    completion = round(total_teu / target_teu * 100, 1)
    yoy = round(rng.uniform(3.0, 10.0), 1)

    return success_response({
        "totalTeu": total_teu,
        "targetTeu": target_teu,
        "foreignTradeTeu": foreign_teu,
        "domesticTradeTeu": domestic_teu,
        "completionRate": completion,
        "yoyRate": yoy,
    })


# M05
@router.get("/berth/occupancy-rate")
def berth_occupancy_rate(
    startDate: str = Query(...),
    endDate: str = Query(...),
    groupBy: str = Query("region"),
    _=Depends(verify_token),
):
    s_parts = startDate.split("-")
    year, month = int(s_parts[0]), int(s_parts[1])
    if not in_data_range(year, month):
        return out_of_range_response()

    rng = seeded_rng("M05", startDate, endDate, groupBy)

    if groupBy == "region":
        zone_ranges = {
            "大连港区": (75, 88),
            "营口港区": (60, 75),
            "丹东港区": (35, 55),
            "锦州港区": (40, 60),
        }
        result = []
        for zone, (lo, hi) in zone_ranges.items():
            result.append({
                "name": zone,
                "occupancyRate": round(rng.uniform(lo, hi), 1),
                "berthCount": rng.randint(15, 45),
                "avgBerthHours": round(rng.uniform(18, 48), 1),
            })
    else:
        result = []
        for seg in SEGMENT_SHARE:
            result.append({
                "name": seg,
                "occupancyRate": round(rng.uniform(45, 85), 1),
                "berthCount": rng.randint(8, 30),
                "avgBerthHours": round(rng.uniform(20, 50), 1),
            })

    return success_response(result)


# M06
@router.get("/vessel/efficiency")
def vessel_efficiency(
    startMonth: str = Query(...),
    endMonth: str = Query(...),
    cmpName: str | None = Query(None),
    _=Depends(verify_token),
):
    s_year, s_month = parse_month(startMonth)
    if not in_data_range(s_year, s_month):
        return out_of_range_response()

    rng = seeded_rng("M06", startMonth, endMonth, cmpName)

    s_y, s_m = parse_month(startMonth)
    e_y, e_m = parse_month(endMonth)

    result = []
    y, m = s_y, s_m
    while (y, m) <= (e_y, e_m):
        if in_data_range(y, m):
            companies = ["中远海运", "马士基", "地中海航运", "达飞轮船", "长荣海运"]
            result.append({
                "period": f"{y}-{m:02d}",
                "avgEfficiency": round(rng.uniform(12, 22), 1),
                "topCompany": rng.choice(companies),
                "yoyChange": round(rng.uniform(-3.0, 5.0), 1),
            })
        m += 1
        if m > 12:
            m = 1
            y += 1

    return success_response(result)


# M07
@router.get("/port-inventory")
def port_inventory(
    date: str = Query(...),
    businessType: str = Query(...),
    regionName: str | None = Query(None),
    _=Depends(verify_token),
):
    parts = date.split("-")
    year, month = int(parts[0]), int(parts[1])
    if not in_data_range(year, month):
        return out_of_range_response()

    rng = seeded_rng("M07", date, businessType, regionName)

    cargo_map = {
        "集装箱": ["标准箱", "冷藏箱", "特种箱"],
        "散杂货": ["散粮", "煤炭", "矿石", "钢材"],
        "油化品": ["原油", "成品油", "液体化工品"],
        "商品车": ["乘用车", "商用车"],
    }
    cargos = cargo_map.get(businessType, ["通用货物"])

    result = []
    for cargo in cargos:
        cap_ratio = round(rng.uniform(40, 75), 1)
        if rng.random() < 0.1:
            cap_ratio = round(rng.uniform(85, 95), 1)

        trend = round(rng.uniform(-5, 8), 1)
        result.append({
            "cargoType": cargo,
            "inventoryTon": round(rng.uniform(5000, 80000), 1),
            "capacityRatio": cap_ratio,
            "trend3d": trend,
        })

    return success_response(result)


# M08
@router.get("/daily-dynamic")
def daily_dynamic(
    dispatchDate: str = Query(...),
    scope: str = Query("port"),
    _=Depends(verify_token),
):
    parts = dispatchDate.split("-")
    year, month = int(parts[0]), int(parts[1])
    if not in_data_range(year, month):
        return out_of_range_response()

    rng = seeded_rng("M08", dispatchDate, scope)
    day_tp = round(rng.uniform(60, 150), 1)
    night_tp = round(day_tp * rng.uniform(0.75, 0.85), 1)
    day_ships = rng.randint(8, 25)
    night_ships = rng.randint(5, 18)

    return success_response({
        "dayShift": {"throughput": day_tp, "shipCount": day_ships},
        "nightShift": {"throughput": night_tp, "shipCount": night_ships},
        "totalForDay": round(day_tp + night_tp, 1),
        "activeShips": day_ships + night_ships,
    })


# M09
@router.get("/ships/status")
def ships_status(
    shipStatus: str = Query(...),
    regionName: str | None = Query(None),
    _=Depends(verify_token),
):
    rng = seeded_rng("M09", shipStatus, regionName)

    if shipStatus == "D":
        count = rng.randint(15, 35)
    else:
        count = rng.randint(3, 12)

    regions = list(ZONE_SHARE.keys())
    if regionName:
        regions = [regionName]

    result = []
    available_names = list(SHIP_NAMES)
    rng.shuffle(available_names)

    for i in range(count):
        ship_name = available_names[i % len(available_names)]
        region = rng.choice(regions)
        cargo = rng.choice(CARGO_TYPES)
        dep_day = rng.randint(1, 28)
        result.append({
            "shipName": ship_name,
            "status": "在泊" if shipStatus == "D" else "锚地",
            "region": region,
            "expectedDeparture": f"2026-04-{dep_day:02d}",
            "cargoType": cargo,
        })

    return success_response(result)
