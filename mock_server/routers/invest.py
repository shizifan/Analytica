from fastapi import APIRouter, Depends, Query
from mock_server.utils import (
    verify_token, seeded_rng, parse_month, in_data_range,
    out_of_range_response, success_response,
)
from mock_server.data.constants import (
    ZONE_SHARE, CAPITAL_PROJECTS,
)

router = APIRouter(prefix="/api/v1/invest", tags=["投资管理域"])


# M25
@router.get("/plan/summary")
def invest_plan_summary(
    currYear: str = Query(...),
    ownerLgZoneName: str | None = Query(None),
    _=Depends(verify_token),
):
    year = int(currYear)
    if not in_data_range(year):
        return out_of_range_response()

    rng = seeded_rng("M25", currYear, ownerLgZoneName)

    approved = round(rng.uniform(80000, 150000), 2)

    if year == 2026:
        current_month = 6
    else:
        current_month = 12

    # Completion rate increases with month
    base_rate = current_month / 12.0
    completion_rate = round(base_rate * rng.uniform(0.82, 0.97) * 100, 1)
    completed = round(approved * completion_rate / 100, 2)
    paid = round(completed * rng.uniform(0.85, 0.95), 2)
    delivery_rate = round(rng.uniform(75, 95), 1)

    capital_count = rng.randint(15, 22)
    cost_count = rng.randint(5, 10)
    unplanned_count = rng.randint(1, 4)

    if ownerLgZoneName and ownerLgZoneName in ZONE_SHARE:
        z = ZONE_SHARE[ownerLgZoneName]
        approved = round(approved * z, 2)
        completed = round(completed * z, 2)
        paid = round(paid * z, 2)
        capital_count = max(1, int(capital_count * z))
        cost_count = max(1, int(cost_count * z))

    return success_response({
        "approvedAmount": approved,
        "completedAmount": completed,
        "paidAmount": paid,
        "completionRate": completion_rate,
        "deliveryRate": delivery_rate,
        "projectCount": {
            "capital": capital_count,
            "cost": cost_count,
            "unplanned": unplanned_count,
        },
    })


# M26
@router.get("/plan/monthly-progress")
def invest_monthly_progress(
    startMonth: str = Query(...),
    endMonth: str = Query(...),
    ownerLgZoneName: str | None = Query(None),
    _=Depends(verify_token),
):
    s_y, s_m = parse_month(startMonth)
    if not in_data_range(s_y, s_m):
        return out_of_range_response()

    rng = seeded_rng("M26", startMonth, endMonth, ownerLgZoneName)
    e_y, e_m = parse_month(endMonth)

    annual_plan = rng.uniform(80000, 150000)
    if ownerLgZoneName and ownerLgZoneName in ZONE_SHARE:
        annual_plan *= ZONE_SHARE[ownerLgZoneName]

    result = []
    cum_plan = 0.0
    cum_actual = 0.0

    y, m = s_y, s_m
    while (y, m) <= (e_y, e_m):
        if not in_data_range(y, m):
            break
        monthly_plan = annual_plan / 12 * rng.uniform(0.7, 1.3)
        monthly_actual = monthly_plan * rng.uniform(0.85, 0.98)
        cum_plan += monthly_plan
        cum_actual += monthly_actual

        progress = round(cum_actual / annual_plan * 100, 1) if annual_plan > 0 else 0

        result.append({
            "month": f"{y}-{m:02d}",
            "plannedAmount": round(monthly_plan, 2),
            "actualAmount": round(monthly_actual, 2),
            "cumulativePlan": round(cum_plan, 2),
            "cumulativeActual": round(cum_actual, 2),
            "progressRatio": progress,
        })

        m += 1
        if m > 12:
            m = 1
            y += 1

    return success_response(result)


# M27
@router.get("/capital-projects")
def invest_capital_projects(
    dateYear: str = Query(...),
    investProjectType: str | None = Query(None),
    regionName: str | None = Query(None),
    _=Depends(verify_token),
):
    year = int(dateYear)
    if not in_data_range(year):
        return out_of_range_response()

    rng = seeded_rng("M27", dateYear, investProjectType, regionName)

    projects = list(CAPITAL_PROJECTS)
    rng.shuffle(projects)
    count = rng.randint(20, 30)
    projects = projects[:min(count, len(projects))]

    # Generate extra if needed
    while len(projects) < count:
        projects.append((f"港口建设项目{len(projects)+1}", rng.choice(["资本类", "成本类"])))

    regions = list(ZONE_SHARE.keys())
    delivery_statuses = ["已交付", "在建", "未开工"]

    result = []
    for name, ptype in projects:
        if investProjectType and ptype != investProjectType:
            continue
        region = rng.choice(regions)
        if regionName and region != regionName:
            # Still include but reassign region
            region = regionName

        approved = round(rng.uniform(2000, 25000), 2)
        if year == 2026:
            progress_factor = rng.uniform(0.1, 0.6)
        else:
            progress_factor = rng.uniform(0.3, 1.0)
        completed = round(approved * progress_factor, 2)
        visual_progress = round(progress_factor * 100, 1)

        status_roll = rng.random()
        if progress_factor > 0.9:
            d_status = "已交付"
        elif progress_factor > 0.1:
            d_status = "在建"
        else:
            d_status = "未开工"

        delivery_month = rng.randint(1, 12)
        delivery_year = year if d_status == "已交付" else year + rng.randint(0, 2)

        result.append({
            "projectName": name,
            "investProjectType": ptype,
            "approvedAmount": approved,
            "completedAmount": completed,
            "visualProgress": visual_progress,
            "deliveryStatus": d_status,
            "deliveryDate": f"{delivery_year}-{delivery_month:02d}",
        })

    return success_response(result)
