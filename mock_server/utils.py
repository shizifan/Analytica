import hashlib
import random
from fastapi import Header, HTTPException


def get_seed(*args) -> int:
    key = "|".join(str(a) for a in args if a is not None)
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)


def seeded_rng(*args) -> random.Random:
    return random.Random(get_seed(*args))


def verify_token(authorization: str = Header(...)):
    if authorization != "Bearer TEST_TOKEN_2024":
        raise HTTPException(status_code=401, detail="Invalid token")


def parse_month(date_str: str) -> tuple[int, int]:
    parts = date_str.split("-")
    return int(parts[0]), int(parts[1])


def in_data_range(year: int, month: int = 1) -> bool:
    start = (2024, 1)
    end = (2026, 6)
    current = (year, month)
    return start <= current <= end


def calc_throughput_base(year: int, month: int, base_annual: float = 33600.0) -> float:
    from mock_server.data.constants import SEASONAL_FACTOR, YOY_GROWTH
    base_monthly = base_annual / 12
    seasonal = SEASONAL_FACTOR.get(month, 1.0)
    growth = 1.0
    for y in range(2024, year):
        growth *= (1 + YOY_GROWTH.get(y, 0.055))
    return base_monthly * seasonal * growth


def out_of_range_response():
    return {"code": 404, "data": None, "msg": "数据不存在：超出可查询范围"}


def success_response(data):
    return {"code": 200, "data": data, "msg": "success"}
