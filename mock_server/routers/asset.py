from fastapi import APIRouter, Depends, Query
from mock_server.utils import (
    verify_token, seeded_rng, in_data_range,
    out_of_range_response, success_response,
)
from mock_server.data.constants import (
    ZONE_SHARE, ASSET_TYPES, EQUIPMENT_STATUS, YOY_GROWTH,
)

router = APIRouter(prefix="/api/v1/asset", tags=["资产管理域"])


# M21
@router.get("/overview")
def asset_overview(
    dateYear: str = Query(...),
    ownerZone: str | None = Query(None),
    _=Depends(verify_token),
):
    year = int(dateYear)
    if not in_data_range(year):
        return out_of_range_response()

    rng = seeded_rng("M21", dateYear, ownerZone)

    base_count = 20000
    base_original = 580000  # 万元
    growth = 1.0
    for y in range(2024, year):
        growth *= 1.02

    total_count = int(base_count * growth + rng.randint(-500, 500))
    total_original = round(base_original * growth * rng.uniform(0.97, 1.03), 2)
    depreciation_rate = round(rng.uniform(35, 45), 1)
    total_net = round(total_original * (1 - depreciation_rate / 100), 2)

    if ownerZone and ownerZone in ZONE_SHARE:
        zone_share = ZONE_SHARE[ownerZone]
        total_count = int(total_count * zone_share)
        total_original = round(total_original * zone_share, 2)
        total_net = round(total_net * zone_share, 2)

    by_zone = []
    for zone, share in ZONE_SHARE.items():
        z_rng = seeded_rng("M21_zone", dateYear, zone)
        z_count = int(total_count * share * z_rng.uniform(0.95, 1.05))
        z_original = round(total_original * share * z_rng.uniform(0.95, 1.05), 2)
        z_net = round(z_original * (1 - depreciation_rate / 100) * z_rng.uniform(0.95, 1.05), 2)
        by_zone.append({
            "zoneName": zone,
            "assetCount": z_count,
            "originalValue": z_original,
            "netValue": z_net,
        })

    return success_response({
        "totalAssetCount": total_count,
        "totalOriginalValue": total_original,
        "totalNetValue": total_net,
        "depreciationRate": depreciation_rate,
        "byZone": by_zone,
    })


# M22
@router.get("/distribution/by-type")
def asset_distribution_by_type(
    dateYear: str = Query(...),
    ownerZone: str | None = Query(None),
    _=Depends(verify_token),
):
    year = int(dateYear)
    if not in_data_range(year):
        return out_of_range_response()

    rng = seeded_rng("M22", dateYear, ownerZone)

    base_count = 20000
    base_original = 580000
    growth = 1.0
    for y in range(2024, year):
        growth *= 1.02

    total_count = int(base_count * growth + rng.randint(-500, 500))
    total_original = round(base_original * growth * rng.uniform(0.97, 1.03), 2)

    if ownerZone and ownerZone in ZONE_SHARE:
        z = ZONE_SHARE[ownerZone]
        total_count = int(total_count * z)
        total_original = round(total_original * z, 2)

    result = []
    for asset_type, count_share, value_share in ASSET_TYPES:
        c = int(total_count * (count_share + rng.uniform(-0.02, 0.02)))
        ov = round(total_original * (value_share + rng.uniform(-0.02, 0.02)), 2)
        dep = rng.uniform(30, 50)
        nv = round(ov * (1 - dep / 100), 2)
        result.append({
            "assetType": asset_type,
            "count": c,
            "originalValue": ov,
            "netValue": nv,
            "shareRatio": round(c / total_count * 100, 1) if total_count > 0 else 0,
        })

    return success_response(result)


# M23
@router.get("/equipment/status")
def equipment_status(
    dateYear: str = Query(...),
    type: int = Query(...),
    ownerZone: str | None = Query(None),
    _=Depends(verify_token),
):
    year = int(dateYear)
    if not in_data_range(year):
        return out_of_range_response()

    rng = seeded_rng("M23", dateYear, type, ownerZone)

    if type == 1:
        base_count = 11000
    else:
        base_count = 5000

    growth = 1.0
    for y in range(2024, year):
        growth *= 1.02
    total = int(base_count * growth)

    if ownerZone and ownerZone in ZONE_SHARE:
        total = int(total * ZONE_SHARE[ownerZone])

    result = []
    remaining = total
    for i, (status, base_ratio) in enumerate(EQUIPMENT_STATUS):
        ratio = base_ratio + rng.uniform(-0.015, 0.015)
        ratio = max(0.01, ratio)
        if i == len(EQUIPMENT_STATUS) - 1:
            count = remaining
        else:
            count = int(total * ratio)
            remaining -= count
        actual_ratio = round(count / total, 4) if total > 0 else 0
        result.append({
            "status": status,
            "count": count,
            "ratio": actual_ratio,
            "yoyChange": round(rng.uniform(-2, 2), 1),
        })

    return success_response(result)


# M24
@router.get("/historical-trend")
def asset_historical_trend(
    startYear: str = Query(...),
    endYear: str = Query(...),
    ownerZone: str | None = Query(None),
    _=Depends(verify_token),
):
    s_year = int(startYear)
    e_year = int(endYear)
    if not in_data_range(s_year):
        return out_of_range_response()

    rng = seeded_rng("M24", startYear, endYear, ownerZone)

    result = []
    for year in range(s_year, e_year + 1):
        if not in_data_range(year):
            continue
        invest_base = rng.uniform(80000, 150000)
        new_value = round(invest_base * 0.8, 2)
        new_count = rng.randint(800, 2000)
        scrap_count = rng.randint(200, 600)

        base_net = 350000
        growth = 1.0
        for y in range(2024, year):
            growth *= 1.02
        end_net = round(base_net * growth * rng.uniform(0.95, 1.05), 2)

        if ownerZone and ownerZone in ZONE_SHARE:
            z = ZONE_SHARE[ownerZone]
            new_value = round(new_value * z, 2)
            new_count = int(new_count * z)
            scrap_count = int(scrap_count * z)
            end_net = round(end_net * z, 2)

        result.append({
            "year": str(year),
            "newAssetCount": new_count,
            "newAssetValue": new_value,
            "scrapAssetCount": scrap_count,
            "endNetValue": end_net,
        })

    return success_response(result)
