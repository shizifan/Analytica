from fastapi import APIRouter, Depends, Query
from mock_server.utils import (
    verify_token, seeded_rng, calc_throughput_base,
    parse_month, in_data_range, out_of_range_response, success_response,
)
from mock_server.data.constants import (
    STRATEGIC_CLIENTS, CUSTOMER_TYPES, CUSTOMER_FIELDS,
    CREDIT_LEVELS, CARGO_TYPES,
)

router = APIRouter(prefix="/api/v1/customer", tags=["客户管理域"])


# M16
@router.get("/basic-info")
def customer_basic_info(
    _=Depends(verify_token),
):
    rng = seeded_rng("M16")
    total = rng.randint(580, 680)

    type_dist = []
    remaining = total
    for i, (t, ratio) in enumerate(CUSTOMER_TYPES):
        if i == len(CUSTOMER_TYPES) - 1:
            count = remaining
        else:
            count = int(total * ratio + rng.randint(-5, 5))
            remaining -= count
        type_dist.append({
            "type": t,
            "count": count,
            "ratio": round(count / total * 100, 1),
        })

    field_dist = []
    for field in CUSTOMER_FIELDS:
        field_dist.append({
            "field": field,
            "count": rng.randint(30, 120),
        })

    return success_response({
        "totalCustomers": total,
        "typeDistribution": type_dist,
        "fieldDistribution": field_dist,
    })


# M17
@router.get("/strategic/throughput")
def strategic_throughput(
    curDate: str = Query(...),
    statisticType: int = Query(...),
    clientName: str | None = Query(None),
    _=Depends(verify_token),
):
    if "-" in curDate:
        year, month = parse_month(curDate)
    else:
        year = int(curDate)
        month = 12

    if not in_data_range(year, min(month, 6 if year == 2026 else 12)):
        return out_of_range_response()

    rng = seeded_rng("M17", curDate, statisticType, clientName)
    client_count = rng.randint(35, 45)
    clients = list(STRATEGIC_CLIENTS[:client_count])

    if statisticType == 1:
        max_m = 6 if year == 2026 else 12
        total_base = sum(calc_throughput_base(year, m) for m in range(1, max_m + 1))
    else:
        if "-" in curDate:
            total_base = calc_throughput_base(year, month)
        else:
            total_base = calc_throughput_base(year, 6 if year == 2026 else 12)

    result = []
    contrib_remaining = 100.0
    for i, name in enumerate(clients):
        if clientName and name != clientName:
            continue
        if i == 0:
            contrib = round(rng.uniform(8, 12), 1)
        elif i < 5:
            contrib = round(rng.uniform(5, 9), 1)
        elif i < 10:
            contrib = round(rng.uniform(3, 5), 1)
        elif i < 20:
            contrib = round(rng.uniform(1.5, 3), 1)
        else:
            contrib = round(rng.uniform(0.5, 1.5), 1)
        contrib_remaining -= contrib

        tp = round(total_base * contrib / 100 * rng.uniform(0.95, 1.05), 1)
        result.append({
            "clientName": name,
            "throughput": tp,
            "contributionRate": contrib,
            "yoyRate": round(rng.uniform(-5, 15), 1),
            "rank": i + 1,
        })

    return success_response(result)


# M18
@router.get("/strategic/revenue")
def strategic_revenue(
    curDate: str = Query(...),
    statisticType: int = Query(...),
    clientName: str | None = Query(None),
    _=Depends(verify_token),
):
    if "-" in curDate:
        year, month = parse_month(curDate)
    else:
        year = int(curDate)
        month = 12

    if not in_data_range(year, min(month, 6 if year == 2026 else 12)):
        return out_of_range_response()

    rng = seeded_rng("M18", curDate, statisticType, clientName)
    client_count = rng.randint(35, 45)
    clients = list(STRATEGIC_CLIENTS[:client_count])

    # Total annual revenue ~ 1.5-2.5 billion yuan (in 万元)
    if statisticType == 1:
        max_m = 6 if year == 2026 else 12
        total_revenue = rng.uniform(150000, 250000) * max_m / 12
    else:
        total_revenue = rng.uniform(150000, 250000) / 12

    result = []
    for i, name in enumerate(clients):
        if clientName and name != clientName:
            continue
        if i == 0:
            share = rng.uniform(8, 14)
        elif i < 5:
            share = rng.uniform(4, 8)
        elif i < 10:
            share = rng.uniform(2, 4)
        elif i < 20:
            share = rng.uniform(1, 2)
        else:
            share = rng.uniform(0.3, 1)
        revenue = round(total_revenue * share / 100, 2)
        result.append({
            "clientName": name,
            "revenue": revenue,
            "revenueShare": round(share, 1),
            "yoyRate": round(rng.uniform(-8, 20), 1),
        })

    return success_response(result)


# M19
@router.get("/contribution/ranking")
def customer_contribution_ranking(
    date: str = Query(...),
    statisticType: int = Query(...),
    cargoCategoryName: str | None = Query(None),
    topN: int = Query(10),
    _=Depends(verify_token),
):
    if "-" in date:
        year, month = parse_month(date)
    else:
        year = int(date)
        month = 12

    if not in_data_range(year, min(month, 6 if year == 2026 else 12)):
        return out_of_range_response()

    rng = seeded_rng("M19", date, statisticType, cargoCategoryName, topN)
    topN = min(topN, 50)

    all_clients = list(STRATEGIC_CLIENTS) + list(
        f"客户{chr(65 + i)}" for i in range(20)
    )
    rng.shuffle(all_clients)

    if statisticType == 1:
        max_m = 6 if year == 2026 else 12
        total_base = sum(calc_throughput_base(year, m) for m in range(1, max_m + 1))
    else:
        if "-" in date:
            total_base = calc_throughput_base(year, month)
        else:
            total_base = calc_throughput_base(year, 6 if year == 2026 else 12)

    result = []
    for i in range(topN):
        if i == 0:
            contrib = round(rng.uniform(10, 16), 1)
        elif i < 5:
            contrib = round(rng.uniform(5, 10), 1)
        elif i < 10:
            contrib = round(rng.uniform(2, 5), 1)
        else:
            contrib = round(rng.uniform(0.5, 2), 1)
        tp = round(total_base * contrib / 100, 1)
        result.append({
            "rank": i + 1,
            "clientName": all_clients[i % len(all_clients)],
            "throughput": tp,
            "contributionRate": contrib,
            "yoyChange": round(rng.uniform(-5, 10), 1),
        })

    return success_response(result)


# M20
@router.get("/credit-info")
def customer_credit_info(
    orgName: str | None = Query(None),
    customerName: str | None = Query(None),
    _=Depends(verify_token),
):
    rng = seeded_rng("M20", orgName, customerName)

    if customerName:
        level_roll = rng.random()
        cumulative = 0.0
        level = "A"
        for lv, ratio in CREDIT_LEVELS:
            cumulative += ratio
            if level_roll <= cumulative:
                level = lv
                break
        limit = round(rng.uniform(1000, 50000), 2)
        used = round(limit * rng.uniform(0.2, 0.85), 2)
        return success_response([{
            "customerName": customerName,
            "creditLevel": level,
            "creditLimit": limit,
            "usedCredit": used,
            "availableCredit": round(limit - used, 2),
        }])

    all_clients = list(STRATEGIC_CLIENTS) + [f"普通客户{i:03d}" for i in range(1, 201)]
    result = []
    for client in all_clients:
        c_rng = seeded_rng("M20_client", client)
        level_roll = c_rng.random()
        cumulative = 0.0
        level = "A"
        for lv, ratio in CREDIT_LEVELS:
            cumulative += ratio
            if level_roll <= cumulative:
                level = lv
                break
        limit = round(c_rng.uniform(1000, 50000), 2)
        used = round(limit * c_rng.uniform(0.2, 0.85), 2)
        result.append({
            "customerName": client,
            "creditLevel": level,
            "creditLimit": limit,
            "usedCredit": used,
            "availableCredit": round(limit - used, 2),
        })

    return success_response(result)
