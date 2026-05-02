#!/usr/bin/env python3
"""
prod_mock_align_check.py
========================
针对 api_registry.json 中已注册的 141 个 API，逐一对比 prod_data 与 mock server 的响应，
生成结构化不一致报告。

用法:
    python prod_mock_align_check.py [--output DISCREPANCY_REPORT.json]
"""
import json
import os
import sys
import time
import argparse
from typing import Any

import requests

PROD_DATA_DIR = os.path.join(os.path.dirname(__file__), "prod_data")
REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "api_registry.json")
MOCK_URL = "http://localhost:18080"
TIMEOUT = 10


def load_registry() -> list[dict]:
    with open(REGISTRY_PATH) as f:
        reg = json.load(f)
    return reg["endpoints"]


def load_prod_data(api_name: str, domain: str) -> dict | None:
    filepath = os.path.join(PROD_DATA_DIR, f"{domain}_{api_name}.json")
    if not os.path.isfile(filepath):
        return None
    with open(filepath) as f:
        return json.load(f)


def call_mock(path: str, params: dict) -> dict | None:
    """Call the mock server and return the parsed JSON."""
    try:
        resp = requests.get(
            f"{MOCK_URL}{path}",
            params={k: v for k, v in params.items() if v is not None},
            timeout=TIMEOUT,
        )
        return {
            "http_status": resp.status_code,
            "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
        }
    except Exception as e:
        return {"http_status": 0, "error": str(e)}


def get_fields_and_types(data: Any) -> dict[str, str]:
    """Extract field names and their Python types from response data."""
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        return {k: type(v).__name__ for k, v in data[0].items()}
    elif isinstance(data, dict):
        return {k: type(v).__name__ for k, v in data.items()}
    return {}


def get_enum_values(data: Any, fields: set[str]) -> dict[str, set]:
    """Extract unique values for categorical/string fields."""
    enums = {}
    items = data if isinstance(data, list) else [data]
    for field in fields:
        values = set()
        for item in items:
            if isinstance(item, dict) and field in item:
                v = item[field]
                if isinstance(v, str):
                    values.add(v)
        if values:
            enums[field] = values
    return enums


def check_one(ep: dict) -> dict:
    """Compare one registered API between registry, prod_data, and mock."""
    name = ep["name"]
    domain = ep["domain"]
    path = ep["path"]
    registry_required = set(ep.get("required", []))
    registry_optional = set(ep.get("optional", []))
    registry_field_schema = ep.get("field_schema", [])

    issues = []

    # 1. Load prod_data
    prod = load_prod_data(name, domain)
    if not prod:
        issues.append({"type": "NO_PROD_DATA", "detail": "prod_data file not found", "severity": "P1"})
        return {"api": name, "domain": domain, "issues": issues, "status": "no_prod_data"}

    prod_params = set(prod.get("params_sent", {}).keys())
    prod_data = prod.get("data")
    prod_fields = get_fields_and_types(prod_data)

    # 2. Compare registry params vs prod params
    if prod_params:
        # PARAM_NAME: registry required/optional use different names than prod
        registry_all = registry_required | registry_optional
        registry_only = registry_all - prod_params
        prod_only = prod_params - registry_all

        if registry_only:
            issues.append({
                "type": "PARAM_NAME",
                "detail": f"registry has params not in prod: {sorted(registry_only)}",
                "registry_params": sorted(registry_all),
                "prod_params": sorted(prod_params),
                "severity": "P2",
            })
        if prod_only:
            issues.append({
                "type": "PARAM_NAME",
                "detail": f"prod has params not in registry: {sorted(prod_only)}",
                "registry_params": sorted(registry_all),
                "prod_params": sorted(prod_params),
                "severity": "P2",
            })

    # 3. Call mock with prod params
    mock_resp = call_mock(path, prod.get("params_sent", {}))
    mock_http = mock_resp.get("http_status", 0)
    mock_body = mock_resp.get("body")
    mock_fields = {}
    mock_enums = {}

    if mock_http >= 400:
        # Mock returned an error
        error_detail = ""
        if isinstance(mock_body, dict):
            error_detail = mock_body.get("detail", json.dumps(mock_body, ensure_ascii=False)[:200])
        issues.append({
            "type": "MOCK_BUG",
            "detail": f"mock returned HTTP {mock_http}: {error_detail}",
            "severity": "P0",
            "mock_params_sent": prod.get("params_sent", {}),
        })
    elif mock_http == 0:
        issues.append({
            "type": "MOCK_BUG",
            "detail": f"mock unreachable: {mock_resp.get('error', 'unknown')}",
            "severity": "P0",
        })
    else:
        # Extract mock data from response wrapper
        if isinstance(mock_body, dict):
            mock_data = mock_body.get("data", mock_body)
        else:
            mock_data = mock_body

        mock_fields = get_fields_and_types(mock_data)
        mock_enums = get_enum_values(mock_data, mock_fields.keys())

        # 4. Compare fields (field names and types)
        prod_field_names = set(prod_fields.keys())
        mock_field_names = set(mock_fields.keys())

        if prod_field_names and mock_field_names:
            missing_in_mock = prod_field_names - mock_field_names
            extra_in_mock = mock_field_names - prod_field_names
            type_mismatches = {
                f: f"prod={prod_fields[f]}, mock={mock_fields[f]}"
                for f in prod_field_names & mock_field_names
                if prod_fields[f] != mock_fields[f]
            }

            if missing_in_mock:
                issues.append({
                    "type": "MOCK_FIELD",
                    "detail": f"fields in prod but missing in mock: {sorted(missing_in_mock)}",
                    "severity": "P1",
                })
            if extra_in_mock:
                issues.append({
                    "type": "MOCK_FIELD",
                    "detail": f"fields in mock but not in prod: {sorted(extra_in_mock)}",
                    "severity": "P2",
                })
            if type_mismatches:
                issues.append({
                    "type": "MOCK_FIELD",
                    "detail": f"type mismatches: {type_mismatches}",
                    "severity": "P1",
                })

            # 5. Compare enum values for string fields
            common_str_fields = {
                f for f in prod_field_names & mock_field_names
                if prod_fields[f] == "str" and mock_fields[f] == "str"
            }
            prod_str_enums = get_enum_values(prod_data, common_str_fields)
            for field in sorted(common_str_fields):
                prod_vals = prod_str_enums.get(field, set())
                mock_vals = mock_enums.get(field, set())
                if prod_vals and mock_vals and prod_vals != mock_vals:
                    only_prod = prod_vals - mock_vals
                    only_mock = mock_vals - prod_vals
                    issues.append({
                        "type": "MOCK_VALUE",
                        "detail": f"enum mismatch on '{field}': prod_only={sorted(only_prod)[:15]}, mock_only={sorted(only_mock)[:15]}",
                        "severity": "P1",
                    })

            # 6. Compare registry field_schema vs prod fields
            if registry_field_schema:
                schema_names = {str(row[0]) for row in registry_field_schema if row}
                schema_only = schema_names - prod_field_names
                prod_only_in_schema = prod_field_names - schema_names
                if schema_only:
                    issues.append({
                        "type": "REGISTRY_SCHEMA",
                        "detail": f"field_schema has fields not in prod: {sorted(schema_only)}",
                        "severity": "P2",
                    })
                if prod_only_in_schema:
                    issues.append({
                        "type": "REGISTRY_SCHEMA",
                        "detail": f"prod has fields not in field_schema: {sorted(prod_only_in_schema)}",
                        "severity": "P2",
                    })

    # Determine overall status
    if not issues:
        status = "aligned"
    elif any(i["severity"] == "P0" for i in issues):
        status = "blocked"
    elif any(i["severity"] == "P1" for i in issues):
        status = "misaligned"
    else:
        status = "minor"

    return {
        "api": name,
        "domain": domain,
        "issues": issues,
        "status": status,
        "prod_params": sorted(prod_params),
        "registry_params": sorted(registry_required | registry_optional),
        "prod_fields": sorted(prod_fields.keys()) if prod_fields else [],
        "mock_fields": sorted(mock_fields.keys()) if mock_fields else [],
    }


def main():
    parser = argparse.ArgumentParser(description="Prod-Mock alignment checker for registered APIs")
    parser.add_argument("--output", default="DISCREPANCY_REPORT.json", help="Output JSON file")
    parser.add_argument("--domain", help="Filter by domain (e.g. D7)")
    parser.add_argument("--api", help="Check a single API by name")
    args = parser.parse_args()

    endpoints = load_registry()
    if args.domain:
        endpoints = [ep for ep in endpoints if ep["domain"] == args.domain]
    if args.api:
        endpoints = [ep for ep in endpoints if ep["name"] == args.api]

    total = len(endpoints)
    print(f"Checking {total} APIs...")

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_checked": total,
        "summary": {"aligned": 0, "blocked": 0, "misaligned": 0, "minor": 0, "no_prod_data": 0},
        "by_type": {"P0": 0, "P1": 0, "P2": 0},
        "results": [],
    }

    for i, ep in enumerate(endpoints):
        result = check_one(ep)
        report["results"].append(result)
        report["summary"][result["status"]] += 1
        for issue in result["issues"]:
            sev = issue["severity"]
            report["by_type"][sev] = report["by_type"].get(sev, 0) + 1

        status_icon = {"aligned": "✓", "blocked": "✗", "misaligned": "!", "minor": "~", "no_prod_data": "?"}
        print(f"  [{i+1:3d}/{total}] {status_icon.get(result['status'], '?')} {result['api']} - {result['status']} ({len(result['issues'])} issues)")

    # Save report
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=== Summary ===")
    print(f"Aligned:     {report['summary']['aligned']}")
    print(f"Blocked(P0): {report['summary']['blocked']}")
    print(f"Misaligned:  {report['summary']['misaligned']}")
    print(f"Minor(P2):   {report['summary']['minor']}")
    print(f"No prod_data:{report['summary']['no_prod_data']}")
    print(f"\nIssues by severity: P0={report['by_type'].get('P0',0)}, P1={report['by_type'].get('P1',0)}, P2={report['by_type'].get('P2',0)}")
    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
