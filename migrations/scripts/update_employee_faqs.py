"""Phase 5.6 — canonical FAQ set per employee.

Each employee gets 5 FAQs covering three complexity tiers:

  - 2 × **simple_table** (data query)  — tag "数据查询" / type "数据"
  - 2 × **chart_text**   (chart + text) — tag "图文分析" / type "图表"
  - 1 × **full_report**  (L3 report)    — tag "深度报告" / type "报告"

Every question explicitly spells out (subject × time range × output
format) so the perception node can fill all required slots without
asking clarification rounds.

Idempotent — always overwrites the `faqs` column with the canonical
set below. Safe to re-run.

Run:
    uv run python -m migrations.scripts.update_employee_faqs
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import text

from backend.database import get_session_factory


SIMPLE = {"tag": "数据查询", "type": "数据"}
CHART = {"tag": "图文分析", "type": "图表"}
REPORT = {"tag": "深度报告", "type": "报告"}


FAQ_SETS: dict[str, list[dict[str, Any]]] = {
    # D1 生产运营 / D2 市场商务
    "throughput_analyst": [
        {
            "id": "tp-simple-1",
            **SIMPLE,
            "question": "2026年3月全港吞吐量总量及各港区数量，以表格列出",
        },
        {
            "id": "tp-simple-2",
            **SIMPLE,
            "question": "2026年3月各业务板块（集装箱、散杂货、油化品、商品车）吞吐量，以表格列出",
        },
        {
            "id": "tp-chart-1",
            **CHART,
            "question": "2026年1-4月全港吞吐量月度趋势，以折线图展示各月变化",
        },
        {
            "id": "tp-chart-2",
            **CHART,
            "question": "2026年3月各港区吞吐量对比，以柱状图展示各港区差异",
        },
        {
            "id": "tp-report-q1",
            **REPORT,
            "question": "生成2026年Q1港口经营综合分析报告（吞吐量、结构占比、同比环比），以 HTML 格式交付",
        },
    ],
    # D2 市场商务 / D3 战略客户 / D4 营销
    "customer_insight": [
        {
            "id": "ci-simple-1",
            **SIMPLE,
            "question": "当前战略客户总数及客户等级分布，以表格列出各等级客户数量",
        },
        {
            "id": "ci-simple-2",
            **SIMPLE,
            "question": "2026年3月 TOP10 战略客户吞吐量，以表格列出客户名称与数值",
        },
        {
            "id": "ci-chart-1",
            **CHART,
            "question": "2026年1-4月战略客户贡献度月度趋势，以折线图展示稳定性",
        },
        {
            "id": "ci-chart-2",
            **CHART,
            "question": "2026年3月各业务板块吞吐量占比，以饼图展示结构分布",
        },
        {
            "id": "ci-report-q1",
            **REPORT,
            "question": "生成2026年Q1战略客户洞察综合报告（客户画像、贡献度、流失风险、结构变化），以 HTML 格式交付",
        },
    ],
    # D5 资产 / D6 投资 / D7 设备
    "asset_investment": [
        {
            "id": "ai-simple-1",
            **SIMPLE,
            "question": "当前资产净值及资产类型分布，以表格列出各类资产金额",
        },
        {
            "id": "ai-simple-2",
            **SIMPLE,
            "question": "当前设备运行状态统计（正常、维修、停用数量），以表格列出各类数量",
        },
        {
            "id": "ai-chart-1",
            **CHART,
            "question": "2026年投资项目进度，以柱状图展示各项目完成率",
        },
        {
            "id": "ai-chart-2",
            **CHART,
            "question": "2026年1-4月设备故障次数月度趋势，以折线图展示各月变化",
        },
        {
            "id": "ai-report-q1",
            **REPORT,
            "question": "生成2026年Q1资产投资运营综合报告（资产价值、投资进度、设备健康度），以 HTML 格式交付",
        },
    ],
}


async def _reload_running_backend(host: str = "127.0.0.1", port: int = 8000) -> bool:
    """Best-effort POST to /api/employees/reload so a running uvicorn
    instance picks up the new FAQs without a restart."""
    try:
        import httpx
    except ImportError:
        return False
    url = f"http://{host}:{port}/api/employees/reload"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(url)
            return resp.status_code == 200
    except Exception:
        return False


async def main() -> int:
    factory = get_session_factory()
    updated = 0
    async with factory() as db:
        for employee_id, faqs in FAQ_SETS.items():
            result = await db.execute(
                text("UPDATE employees SET faqs = :faqs WHERE employee_id = :eid"),
                {
                    "eid": employee_id,
                    "faqs": json.dumps(faqs, ensure_ascii=False),
                },
            )
            if result.rowcount:
                updated += 1
                print(f"  ✓ {employee_id}: {len(faqs)} FAQs")
            else:
                print(f"  · {employee_id}: not found (skipped)")
        await db.commit()
    print(f"\nUpdated {updated} employee(s).")

    if await _reload_running_backend():
        print("Signalled running backend to reload employee cache.")
    else:
        print("(Backend not reachable — restart uvicorn to see new FAQs.)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
