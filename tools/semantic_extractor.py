"""从 prod_data 自动提取 field_schema，输出可粘贴的代码片段。"""
import json
from pathlib import Path

PROD_DATA = Path("mock_server/prod_data")
ENRICHED  = Path("mock_server/prod_data/enriched")

def infer_type(val) -> str:
    if isinstance(val, bool):  return "bool"
    if isinstance(val, int):   return "int"
    if isinstance(val, float): return "float"
    return "str"

def get_schema(rows: list[dict]) -> list[tuple]:
    seen = {}
    for row in rows[:20]:
        for k, v in row.items():
            if k not in seen and v is not None:
                seen[k] = infer_type(v)
    return list(seen.items())

def best_sample(api_name: str) -> list[dict]:
    best = []
    if ENRICHED.exists():
        for f in ENRICHED.glob(f"*_{api_name}_*.json"):
            try:
                rows = json.loads(f.read_text("utf-8")).get("data", [])
                if len(rows) > len(best):
                    best = rows
            except Exception:
                pass
    for d in ["D1","D2","D3","D4","D5","D6","D7"]:
        f = PROD_DATA / f"{d}_{api_name}.json"
        if f.exists():
            try:
                rows = json.loads(f.read_text("utf-8")).get("data", [])
                if len(rows) > len(best):
                    best = rows
            except Exception:
                pass
    return best

api_names = sorted(set(
    f.stem.split("_", 1)[1]
    for f in PROD_DATA.glob("D?_*.json") if f.is_file()
))

for name in api_names:
    rows = best_sample(name)
    if not rows:
        print(f"# {name}: NO DATA\n")
        continue
    schema = get_schema(rows)
    parts = ", ".join(f'("{f}", "{t}", "")' for f, t in schema)
    print(f"# {name}  ({len(rows)} rows)")
    print(f'    field_schema=(({parts}),),')
    print()
