from fastapi import APIRouter, Depends, Query
from mock_server.utils import (
    verify_token, seeded_rng, calc_throughput_base,
    parse_month, in_data_range, out_of_range_response, success_response,
)
from mock_server.data.constants import (
    ZONE_SHARE, SEGMENT_SHARE, KEY_ENTERPRISES,
)

router = APIRouter(prefix="/api/v1/market", tags=["市场商务域"])


# M10
@router.get("/throughput/monthly")
def market_throughput_monthly(
    curDateMonth: str = Query(...),
    yearDateMonth: str = Query(...),
    _=Depends(verify_token),
):
    cur_y, cur_m = parse_month(curDateMonth)
    prev_y, prev_m = parse_month(yearDateMonth)

    if not in_data_range(cur_y, cur_m):
        return out_of_range_response()

    rng = seeded_rng("M10", curDateMonth, yearDateMonth)

    cur_total = round(calc_throughput_base(cur_y, cur_m) * rng.uniform(0.97, 1.03), 1)
    prev_total = round(
        calc_throughput_base(prev_y, prev_m) * rng.uniform(0.97, 1.03), 1
    ) if in_data_range(prev_y, prev_m) else None

    yoy_diff = round(cur_total - prev_total, 1) if prev_total else None
    yoy_rate = round(yoy_diff / prev_total * 100, 1) if prev_total else None
    completion = round(rng.uniform(85, 105), 1)

    return success_response({
        "curMonthTotal": cur_total,
        "prevYearSame": prev_total,
        "yoyDiff": yoy_diff,
        "yoyRate": yoy_rate,
        "completionRate": completion,
    })


# M11
@router.get("/throughput/cumulative")
def market_throughput_cumulative(
    curDateYear: str = Query(...),
    yearDateYear: str = Query(...),
    _=Depends(verify_token),
):
    cur_year = int(curDateYear)
    prev_year = int(yearDateYear)

    if not in_data_range(cur_year):
        return out_of_range_response()

    rng = seeded_rng("M11", curDateYear, yearDateYear)

    cur_max_m = 6 if cur_year == 2026 else 12
    prev_max_m = 6 if prev_year == 2026 else 12
    # For comparison, use the same month range
    compare_months = min(cur_max_m, prev_max_m)

    cur_cumulative = 0.0
    for m in range(1, cur_max_m + 1):
        cur_cumulative += calc_throughput_base(cur_year, m) * rng.uniform(0.97, 1.03)
    cur_cumulative = round(cur_cumulative, 1)

    prev_cumulative = 0.0
    if in_data_range(prev_year):
        rng2 = seeded_rng("M11_prev", yearDateYear)
        for m in range(1, prev_max_m + 1):
            prev_cumulative += calc_throughput_base(prev_year, m) * rng2.uniform(0.97, 1.03)
        prev_cumulative = round(prev_cumulative, 1)
    else:
        prev_cumulative = None

    yoy_diff = round(cur_cumulative - prev_cumulative, 1) if prev_cumulative else None
    yoy_rate = round(yoy_diff / prev_cumulative * 100, 1) if prev_cumulative else None

    return success_response({
        "curYearCumulative": cur_cumulative,
        "prevYearCumulative": prev_cumulative,
        "yoyDiff": yoy_diff,
        "yoyRate": yoy_rate,
    })


# M12
@router.get("/trend-chart")
def market_trend_chart(
    businessSegment: str = Query(...),
    startDate: str = Query(...),
    endDate: str = Query(...),
    _=Depends(verify_token),
):
    s_y, s_m = parse_month(startDate)
    if not in_data_range(s_y, s_m):
        return out_of_range_response()

    rng = seeded_rng("M12", businessSegment, startDate, endDate)
    e_y, e_m = parse_month(endDate)

    seg_share = SEGMENT_SHARE.get(businessSegment, 1.0)
    if businessSegment == "全货类":
        seg_share = 1.0

    result = []
    y, m = s_y, s_m
    while (y, m) <= (e_y, e_m) and in_data_range(y, m):
        base = calc_throughput_base(y, m) * seg_share
        value = round(base * rng.uniform(0.95, 1.05), 1)
        yoy = round(rng.uniform(1.0, 12.0), 1)
        result.append({
            "month": f"{y}-{m:02d}",
            "value": value,
            "yoyRate": yoy,
        })
        m += 1
        if m > 12:
            m = 1
            y += 1

    return success_response(result)


# M13
@router.get("/throughput/by-zone")
def market_throughput_by_zone(
    curDateMonth: str = Query(...),
    yearDateMonth: str = Query(...),
    _=Depends(verify_token),
):
    cur_y, cur_m = parse_month(curDateMonth)
    if not in_data_range(cur_y, cur_m):
        return out_of_range_response()

    rng = seeded_rng("M13", curDateMonth, yearDateMonth)
    total_base = calc_throughput_base(cur_y, cur_m)

    result = []
    shares = {}
    for zone, base_share in ZONE_SHARE.items():
        s = base_share + rng.uniform(-0.02, 0.02)
        shares[zone] = s
    total_s = sum(shares.values())
    for z in shares:
        shares[z] /= total_s

    for zone, share in shares.items():
        tp = round(total_base * share * rng.uniform(0.97, 1.03), 1)
        result.append({
            "zoneName": zone,
            "throughput": tp,
            "yoyRate": round(rng.uniform(1.0, 12.0), 1),
            "shareRatio": round(share * 100, 1),
        })

    return success_response(result)


# M14
@router.get("/key-enterprise")
def market_key_enterprise(
    businessSegment: str = Query(...),
    curDateMonth: str = Query(...),
    statisticType: int = Query(...),
    _=Depends(verify_token),
):
    cur_y, cur_m = parse_month(curDateMonth)
    if not in_data_range(cur_y, cur_m):
        return out_of_range_response()

    rng = seeded_rng("M14", businessSegment, curDateMonth, statisticType)
    available = list(KEY_ENTERPRISES)
    rng.shuffle(available)
    top10 = available[:10]

    result = []
    remaining = 100.0
    for i, name in enumerate(top10):
        if i == 0:
            contrib = round(rng.uniform(12, 18), 1)
        elif i < 5:
            contrib = round(rng.uniform(5, 12), 1)
        else:
            contrib = round(rng.uniform(2, 4), 1)
        remaining -= contrib
        base = calc_throughput_base(cur_y, cur_m)
        if statisticType == 1:
            max_m = min(cur_m, 6 if cur_y == 2026 else 12)
            base = sum(calc_throughput_base(cur_y, m) for m in range(1, max_m + 1))
        tp = round(base * contrib / 100 * rng.uniform(0.9, 1.1), 1)
        result.append({
            "rank": i + 1,
            "enterpriseName": name,
            "throughput": tp,
            "contribution": contrib,
            "yoyRate": round(rng.uniform(-5, 15), 1),
        })

    return success_response(result)


# M15
@router.get("/business-segment")
def market_business_segment(
    curDateMonth: str = Query(...),
    yearDateMonth: str = Query(...),
    statisticType: int = Query(...),
    _=Depends(verify_token),
):
    cur_y, cur_m = parse_month(curDateMonth)
    if not in_data_range(cur_y, cur_m):
        return out_of_range_response()

    rng = seeded_rng("M15", curDateMonth, yearDateMonth, statisticType)
    base = calc_throughput_base(cur_y, cur_m)
    if statisticType == 1:
        max_m = min(cur_m, 6 if cur_y == 2026 else 12)
        base = sum(calc_throughput_base(cur_y, m) for m in range(1, max_m + 1))

    shares = {}
    for seg, base_share in SEGMENT_SHARE.items():
        s = base_share + rng.uniform(-0.03, 0.03)
        shares[seg] = s
    total_s = sum(shares.values())
    for seg in shares:
        shares[seg] /= total_s

    result = []
    for seg, share in shares.items():
        tp = round(base * share * rng.uniform(0.97, 1.03), 1)
        result.append({
            "segmentName": seg,
            "throughput": tp,
            "shareRatio": round(share * 100, 1),
            "yoyRate": round(rng.uniform(1.0, 12.0), 1),
        })

    return success_response(result)
