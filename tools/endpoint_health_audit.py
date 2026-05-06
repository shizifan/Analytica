"""endpoint_health_audit.py — 基于 prod_data 真实快照的全 API 健康度审计.

覆盖范围:
  - 141 个 ``data/api_registry.json`` 注册端点
  - 73 个未注册但 prod_data 有快照的端点（先前判断"线上无数据"，本次复核）

健康度评级:
  - A : 数据完整、字段语义清晰、可直接消费
  - B : 数据可用但需要二次处理（pivot/alias/单位归一）
  - C : 数据部分有效（含 null / 部分字段为 0 / 单位异常）
  - D : 数据完全为空或全 0 — 实施前必须先做数据治理

未注册端点的二次决策:
  - A/B 级 → "建议补注册"（先前判断有误）
  - C/D 级 → "确认无价值，维持未注册"

用法::

    .venv/bin/python tools/endpoint_health_audit.py
    .venv/bin/python tools/endpoint_health_audit.py --output data/endpoint_health.json
    .venv/bin/python tools/endpoint_health_audit.py --domain D7
    .venv/bin/python tools/endpoint_health_audit.py --grade D       # 只看 D 级

输出:
  - 默认写入 ``data/endpoint_health.json``
  - 控制台打印 summary
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROD_DATA_DIR = Path("mock_server/prod_data")
REGISTRY_PATH = Path("data/api_registry.json")
DEFAULT_OUTPUT_PATH = Path("data/endpoint_health.json")

# ---------------------------------------------------------------------------
# Sanity rules — 基于 spec §9.1 的 12 个常见问题
# ---------------------------------------------------------------------------

RATE_FIELDS = {
    "usageRate", "serviceableRate", "machineHourRate", "rate", "ratio",
    "occupancyRate", "deliveryRate", "completionRate",
}

# 字段名 → 业务语义判断
RELIABILITY_INTENT_KEYWORDS = ("MTBF", "MTTR", "可靠性", "故障次数")

QUANTITY_HINT_FIELDS = {"firstLevelName", "firstLevelClassName", "secondLevelName"}

FIELD_ALIASES = {
    "firstLevelName": "firstLevelClassName",  # CQ-6
    "secondLevelName": "secondLevelClassName",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _profile_field(values: list[Any]) -> dict[str, Any]:
    """统计单个字段的分布特征."""
    total = len(values)
    nulls = sum(1 for v in values if v is None)
    non_null = [v for v in values if v is not None]
    numeric_vals = [v for v in non_null if _is_numeric(v)]
    string_vals = [v for v in non_null if isinstance(v, str)]

    profile: dict[str, Any] = {
        "count": total,
        "null_count": nulls,
        "null_ratio": round(nulls / total, 4) if total else 0.0,
    }

    if numeric_vals:
        profile["type"] = "numeric"
        profile["min"] = min(numeric_vals)
        profile["max"] = max(numeric_vals)
        profile["mean"] = round(statistics.fmean(numeric_vals), 4)
        profile["variance"] = (
            round(statistics.pvariance(numeric_vals), 4)
            if len(numeric_vals) > 1 else 0.0
        )
        profile["zero_count"] = sum(1 for v in numeric_vals if v == 0)
    elif string_vals:
        profile["type"] = "string"
        distinct = sorted(set(string_vals))
        profile["distinct_count"] = len(distinct)
        profile["samples"] = distinct[:5]
    else:
        profile["type"] = "unknown"
    return profile


def _detect_long_format(rows: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """检测长表格式（CQ-9）.

    特征: 行数显著多于列数, 且某个 string 列的 distinct 值少（典型透视维度）.
    """
    if not rows or not isinstance(rows[0], dict):
        return False, None
    cols = list(rows[0].keys())
    string_cols = [c for c in cols if any(isinstance(r.get(c), str) for r in rows)]
    for col in string_cols:
        if col in {"dateMonth", "dateYear", "date"}:
            continue
        distinct = {r.get(col) for r in rows if r.get(col) is not None}
        # 重复出现 >= 2 次的 string 列, 且 distinct < 行数的 50%
        if 2 <= len(distinct) < len(rows) * 0.5 and len(rows) >= 6:
            return True, col
    return False, None


def _has_keyword(text: str | None, keywords: tuple[str, ...]) -> bool:
    if not text:
        return False
    return any(k in text for k in keywords)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def check_endpoint(
    snapshot: dict[str, Any],
    registry_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """对单个 endpoint 跑健康度检查."""
    api = snapshot.get("api", "")
    domain = snapshot.get("domain", "?")
    intent = snapshot.get("intent") or (registry_meta.get("intent") if registry_meta else "")
    params_sent = snapshot.get("params_sent", {})
    data = snapshot.get("data", [])
    data_count = snapshot.get("data_count", len(data) if isinstance(data, list) else 0)

    warnings: list[dict[str, str]] = []

    # ── 致命级 (D) ─────────────────────────────────────────────────
    if data_count == 0 or (isinstance(data, list) and not data):
        warnings.append({
            "code": "D_EMPTY",
            "severity": "FATAL",
            "msg": "data 数组为空，端点完全无数据 (CQ-2)",
        })
        return _finalize(snapshot, registry_meta, warnings, fields=[], long_format=False, pivot_col=None)

    if not isinstance(data, list) or not isinstance(data[0], dict):
        warnings.append({
            "code": "D_NON_TABULAR",
            "severity": "FATAL",
            "msg": f"data 非表格结构 (type={type(data).__name__})",
        })
        return _finalize(snapshot, registry_meta, warnings, fields=[], long_format=False, pivot_col=None)

    # 字段画像
    cols = list(data[0].keys())
    fields = []
    for col in cols:
        values = [r.get(col) for r in data]
        prof = _profile_field(values)
        prof["name"] = col
        fields.append(prof)

    numeric_fields = [f for f in fields if f.get("type") == "numeric"]

    # D_ALL_ZERO: 所有数值字段全 0
    if numeric_fields and all(
        f.get("max", 0) == 0 and f.get("min", 0) == 0 for f in numeric_fields
    ):
        warnings.append({
            "code": "D_ALL_ZERO",
            "severity": "FATAL",
            "msg": "所有数值字段全部为 0，无业务信号 (CQ-2)",
        })

    # ── P0 严重 ──────────────────────────────────────────────────────
    for f in numeric_fields:
        if f["null_ratio"] > 0.30:
            warnings.append({
                "code": "P0_HIGH_NULL",
                "severity": "P0",
                "msg": f"字段 {f['name']} null 比例 {f['null_ratio']*100:.0f}% > 30% (CQ-1)",
            })
        if data_count > 1 and f.get("variance", 0) == 0 and f.get("max", 0) != 0:
            warnings.append({
                "code": "P0_NO_VARIANCE",
                "severity": "P0",
                "msg": f"字段 {f['name']} 方差为 0（{data_count} 行全部 = {f['max']}），无趋势信号 (CQ-4)",
            })

    # P0_RANGE_RATE: 利用率/完好率类字段不在合理区间
    for f in numeric_fields:
        if f["name"] in RATE_FIELDS:
            mx, mn = f.get("max", 0), f.get("min", 0)
            # 合理: [0, 1] 小数 OR [0, 100] 百分点
            in_decimal = 0 <= mn and mx <= 1.5
            in_percent = 0 <= mn and mx <= 105
            if not (in_decimal or in_percent):
                warnings.append({
                    "code": "P0_RANGE_RATE",
                    "severity": "P0",
                    "msg": f"rate 字段 {f['name']} 值域 [{mn}, {mx}] 既不像小数也不像百分比 (CQ-3)",
                })

    # ── P1 警告 ──────────────────────────────────────────────────────
    # P1_NAME_VS_INTENT: usageRate 字段但 intent 是可靠性/MTBF
    if "usageRate" in cols and _has_keyword(intent, RELIABILITY_INTENT_KEYWORDS):
        warnings.append({
            "code": "P1_NAME_VS_INTENT",
            "severity": "P1",
            "msg": "字段名 usageRate 但 endpoint intent 是可靠性/MTBF/MTTR — 字段名错用 (CQ-5)",
        })

    # P1_QUANTITY_LOW: 数量类字段值异常小
    if "num" in cols and any(qf in cols for qf in QUANTITY_HINT_FIELDS):
        num_field = next((f for f in numeric_fields if f["name"] == "num"), None)
        if num_field and num_field.get("min", 0) > 0 and num_field.get("min", 0) < 10:
            warnings.append({
                "code": "P1_QUANTITY_LOW",
                "severity": "P1",
                "msg": f"num 字段最小值 {num_field['min']} < 10，疑似单位错误或数据缺失 (CQ-8)",
            })

    # ── P2 注意 ──────────────────────────────────────────────────────
    long_format, pivot_col = _detect_long_format(data)
    if long_format:
        warnings.append({
            "code": "P2_LONG_FORMAT",
            "severity": "P2",
            "msg": f"长表格式（{pivot_col} 列重复出现），渲染前需 pivot (CQ-9)",
        })

    # P2_FIELD_ALIAS: 字段名混用
    for col in cols:
        if col in FIELD_ALIASES:
            warnings.append({
                "code": "P2_FIELD_ALIAS",
                "severity": "P2",
                "msg": f"使用了 alias 字段 {col}，标准名应为 {FIELD_ALIASES[col]} (CQ-6)",
            })
            break  # 一个端点只标一次

    # P2_PARAMS_DRIVEN: 必传单值参数（如 secondLevelClassName）
    if registry_meta:
        required = registry_meta.get("required", [])
        if any(p in required for p in ("secondLevelClassName", "cmpName")):
            warnings.append({
                "code": "P2_PARAMS_DRIVEN",
                "severity": "P2",
                "msg": f"端点必须指定单值参数 {required}，无法直接聚合 (CQ-12)",
            })

    return _finalize(snapshot, registry_meta, warnings, fields=fields,
                     long_format=long_format, pivot_col=pivot_col)


def _finalize(
    snapshot: dict[str, Any],
    registry_meta: dict[str, Any] | None,
    warnings: list[dict[str, str]],
    fields: list[dict[str, Any]],
    long_format: bool,
    pivot_col: str | None,
) -> dict[str, Any]:
    grade = _decide_grade(warnings)
    return {
        "endpoint": snapshot.get("api", ""),
        "domain": snapshot.get("domain") or (registry_meta.get("domain") if registry_meta else "?"),
        "registered": registry_meta is not None,
        "grade": grade,
        "data_count": snapshot.get("data_count", 0),
        "fetched_at": snapshot.get("fetched_at", ""),
        "intent": snapshot.get("intent") or (registry_meta.get("intent") if registry_meta else ""),
        "params_sent": snapshot.get("params_sent", {}),
        "registry_meta": {
            "time": registry_meta.get("time") if registry_meta else None,
            "granularity": registry_meta.get("granularity") if registry_meta else None,
            "required": registry_meta.get("required", []) if registry_meta else None,
            "optional": registry_meta.get("optional", []) if registry_meta else None,
        } if registry_meta else None,
        "long_format": long_format,
        "pivot_col": pivot_col,
        "fields": fields,
        "warnings": warnings,
        "recommendation": _recommendation(grade, registry_meta is not None, warnings),
    }


def _decide_grade(warnings: list[dict[str, str]]) -> str:
    sevs = {w["severity"] for w in warnings}
    codes = {w["code"] for w in warnings}
    if any(c.startswith("D_") for c in codes):
        return "D"
    if "FATAL" in sevs or "P0" in sevs or "P1" in sevs:
        return "C"
    if "P2" in sevs:
        return "B"
    return "A"


def _recommendation(grade: str, registered: bool, warnings: list[dict[str, str]]) -> str:
    if grade == "D":
        return "数据治理: 端点不可用，必须排查后端逻辑或权限"
    if grade == "C":
        codes = {w["code"] for w in warnings}
        if "P0_HIGH_NULL" in codes:
            return "降级使用: KPI 类场景需 fallback chain，缺值显示 '—'"
        if "P0_NO_VARIANCE" in codes:
            return "降级使用: 不画趋势图，改为单一数值卡片"
        if "P0_RANGE_RATE" in codes:
            return "数据治理: 单位口径与 API 文档不符，需确认"
        if "P1_NAME_VS_INTENT" in codes:
            return "字段映射层修复: A.3 必须按 (field, endpoint) 二元 key 映射"
        return "降级使用: 渲染前先跑 sanity check"
    if grade == "B":
        codes = {w["code"] for w in warnings}
        if "P2_LONG_FORMAT" in codes:
            return "二次处理: collector 阶段 melt → pivot 后再交给 LLM"
        if "P2_FIELD_ALIAS" in codes:
            return "字段映射层补 alias 表: firstLevelName ↔ firstLevelClassName"
        if "P2_PARAMS_DRIVEN" in codes:
            return "两阶段查询: 先 list 候选 → 循环查每个"
        return "可用，需轻量预处理"
    # A 级
    if not registered:
        return "建议补注册: prod_data 数据完整，应纳入 api_registry.json"
    return "可直接消费"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def load_registry() -> dict[str, dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"{REGISTRY_PATH} 不存在")
    with open(REGISTRY_PATH) as f:
        r = json.load(f)
    return {e["name"]: e for e in r.get("endpoints", [])}


def load_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return {"_load_error": str(exc), "api": path.stem.split("_", 1)[-1]}


def audit_all() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    registry = load_registry()

    files = sorted(PROD_DATA_DIR.glob("D*_*.json"))
    results: list[dict[str, Any]] = []

    for fp in files:
        snap = load_snapshot(fp)
        if snap is None or "_load_error" in (snap or {}):
            continue
        api_name = snap.get("api") or fp.stem.split("_", 1)[-1]
        snap.setdefault("api", api_name)
        meta = registry.get(api_name)
        results.append(check_endpoint(snap, meta))

    summary = build_summary(results, registry)
    return results, summary


def build_summary(results: list[dict[str, Any]], registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_grade: Counter[str] = Counter()
    by_grade_reg: Counter[str] = Counter()
    by_grade_unreg: Counter[str] = Counter()
    by_domain: dict[str, Counter[str]] = defaultdict(Counter)

    for r in results:
        by_grade[r["grade"]] += 1
        if r["registered"]:
            by_grade_reg[r["grade"]] += 1
        else:
            by_grade_unreg[r["grade"]] += 1
        by_domain[r["domain"]][r["grade"]] += 1

    audited_names = {r["endpoint"] for r in results}
    missing_from_prod = sorted(set(registry.keys()) - audited_names)

    critical_d = sorted(
        [{"endpoint": r["endpoint"], "domain": r["domain"], "registered": r["registered"]}
         for r in results if r["grade"] == "D"],
        key=lambda x: (x["domain"], x["endpoint"]),
    )

    unreg_recommend_add = sorted(
        [{"endpoint": r["endpoint"], "domain": r["domain"], "grade": r["grade"],
          "data_count": r["data_count"], "intent": r["intent"]}
         for r in results
         if not r["registered"] and r["grade"] in ("A", "B")],
        key=lambda x: (x["domain"], x["endpoint"]),
    )

    unreg_correctly_excluded = sorted(
        [{"endpoint": r["endpoint"], "domain": r["domain"], "grade": r["grade"],
          "data_count": r["data_count"]}
         for r in results
         if not r["registered"] and r["grade"] in ("C", "D")],
        key=lambda x: (x["domain"], x["endpoint"]),
    )

    return {
        "total_audited": len(results),
        "registered": sum(1 for r in results if r["registered"]),
        "unregistered": sum(1 for r in results if not r["registered"]),
        "missing_from_prod_data": missing_from_prod,
        "by_grade": dict(by_grade),
        "by_grade_registered": dict(by_grade_reg),
        "by_grade_unregistered": dict(by_grade_unreg),
        "by_domain": {dom: dict(c) for dom, c in by_domain.items()},
        "critical_endpoints_d": critical_d,
        "unregistered_recommended_to_add": unreg_recommend_add,
        "unregistered_correctly_excluded": unreg_correctly_excluded,
    }


def render_console(summary: dict[str, Any], filter_grade: str | None = None,
                   filter_domain: str | None = None, results: list[dict[str, Any]] | None = None) -> None:
    print("=" * 78)
    print(f"ENDPOINT HEALTH AUDIT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 78)
    print(f"\n总计: {summary['total_audited']} 端点 (注册 {summary['registered']} + 未注册 {summary['unregistered']})\n")

    print("Grade 分布:")
    for g in ("A", "B", "C", "D"):
        n = summary["by_grade"].get(g, 0)
        nr = summary["by_grade_registered"].get(g, 0)
        nu = summary["by_grade_unregistered"].get(g, 0)
        bar = "█" * int(n * 40 / max(summary["total_audited"], 1))
        print(f"  {g}: {n:>3}  (reg={nr}, unreg={nu})  {bar}")

    print("\nDomain × Grade:")
    print(f"  {'dom':<6} {'A':>4} {'B':>4} {'C':>4} {'D':>4}  {'total':>6}")
    for dom in sorted(summary["by_domain"].keys()):
        cnts = summary["by_domain"][dom]
        total = sum(cnts.values())
        print(f"  {dom:<6} {cnts.get('A',0):>4} {cnts.get('B',0):>4} {cnts.get('C',0):>4} {cnts.get('D',0):>4}  {total:>6}")

    print(f"\n🚨 D 级（数据无效，必须治理）: {len(summary['critical_endpoints_d'])} 个")
    for d in summary["critical_endpoints_d"][:20]:
        flag = "[未注册]" if not d["registered"] else "[已注册]"
        print(f"  {flag} {d['domain']}/{d['endpoint']}")
    if len(summary["critical_endpoints_d"]) > 20:
        print(f"  ... 还有 {len(summary['critical_endpoints_d'])-20} 个")

    add_list = summary["unregistered_recommended_to_add"]
    print(f"\n✅ 建议补注册（未注册但数据完整）: {len(add_list)} 个")
    for d in add_list[:15]:
        print(f"  [{d['grade']}] {d['domain']}/{d['endpoint']}  ({d['data_count']} 行) — {d['intent'][:60]}")
    if len(add_list) > 15:
        print(f"  ... 还有 {len(add_list)-15} 个")

    excl = summary["unregistered_correctly_excluded"]
    print(f"\n⚪ 维持未注册（先前判断正确）: {len(excl)} 个")
    grade_breakdown = Counter(d["grade"] for d in excl)
    print(f"  按 grade: {dict(grade_breakdown)}")

    if filter_grade or filter_domain:
        print("\n" + "─" * 78)
        print(f"明细（filter: grade={filter_grade or '*'}, domain={filter_domain or '*'}）:")
        for r in (results or []):
            if filter_grade and r["grade"] != filter_grade:
                continue
            if filter_domain and r["domain"] != filter_domain:
                continue
            tag = "[reg]" if r["registered"] else "[unreg]"
            print(f"\n  {tag} [{r['grade']}] {r['domain']}/{r['endpoint']} ({r['data_count']} 行)")
            print(f"    intent: {r['intent'][:80]}")
            print(f"    建议: {r['recommendation']}")
            for w in r["warnings"]:
                print(f"      • [{w['code']}] {w['msg']}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="API 健康度审计")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--grade", choices=["A", "B", "C", "D"], help="只显示某 grade 明细")
    parser.add_argument("--domain", help="只显示某 domain 明细 (如 D7)")
    parser.add_argument("--no-write", action="store_true", help="只打印不落盘")
    args = parser.parse_args()

    results, summary = audit_all()

    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "endpoints": sorted(results, key=lambda r: (r["domain"], r["endpoint"])),
        }
        with open(args.output, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n📁 已写入: {args.output}")

    render_console(summary, args.grade, args.domain, results)


if __name__ == "__main__":
    main()
