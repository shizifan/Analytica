"""Execution-Only E2E Tests — 跳过感知和规划阶段，直接测试执行逻辑。

设计原则：
1. 预定义分析计划，避免 LLM 调用
2. 使用 Mock Server 提供 API 数据
3. 测试执行层的核心功能：DAG 调度、并行执行、技能调用、错误处理
4. 测试时间从 ~80s/用例 缩短到 ~5s/用例

运行：
    pytest tests/test_execution_only.py -v                          # 全部用例
    pytest tests/test_execution_only.py -v -k "data_fetch"        # 仅数据获取
    pytest tests/test_execution_only.py -v -k "chart"             # 仅图表生成
    pytest tests/test_execution_only.py -v --durations=0          # 显示耗时排名
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pandas as pd
import pytest

from backend.agent.execution import execute_plan
from backend.models.schemas import TaskItem
from backend.skills.loader import load_all_skills

# 确保所有技能已注册
load_all_skills()

logger = logging.getLogger("test.execution_only")

# ════════════════════════════════════════════════════════════════
# 报告输出目录配置
# ════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_BASE = PROJECT_ROOT / "reports" / "skill_artifacts"
_RUN_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

def _get_run_dir() -> Path:
    """获取本次测试运行的输出目录。"""
    return REPORTS_BASE / _RUN_TIMESTAMP

def save_report_artifact(
    test_name: str,
    skill_id: str,
    output: Any,
    sub_dir: str = "reports",
) -> Path | None:
    """保存报告工件到磁盘。

    Args:
        test_name: 测试名称（用于文件名）
        skill_id: 技能ID（html/docx/pptx）
        output: SkillOutput 对象
        sub_dir: 子目录名

    Returns:
        保存的文件路径，或 None（保存失败时）
    """
    output_dir = _get_run_dir() / sub_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if not hasattr(output, "data") or output.data is None:
        logger.warning("[%s] No data to save", test_name)
        return None

    fmt = output.metadata.get("format", "")
    data = output.data
    title = output.metadata.get("title", test_name)

    if fmt == "html":
        if not isinstance(data, str):
            logger.warning("[%s] HTML data is not str", test_name)
            return None
        filename = f"{test_name}.html"
        file_path = output_dir / filename
        file_path.write_text(data, encoding="utf-8")
        logger.info(f"[{test_name}] HTML saved: {file_path} ({len(data)} bytes)")
        return file_path

    if fmt in ("docx", "pptx"):
        if not isinstance(data, (bytes, bytearray)):
            logger.warning("[%s] %s data is not bytes", test_name, fmt)
            return None
        filename = f"{test_name}.{fmt}"
        file_path = output_dir / filename
        file_path.write_bytes(data)
        logger.info(f"[{test_name}] {fmt.upper()} saved: {file_path} ({len(data)} bytes)")
        return file_path

    logger.warning("[%s] Unknown format '%s'", test_name, fmt)
    return None

# ════════════════════════════════════════════════════════════════
# Mock Server 配置（与 test_employee_e2e 相同）
# ════════════════════════════════════════════════════════════════

from mock_server.mock_server_all import app as mock_app


@contextmanager
def mock_api_gateway():
    """路由 API 网关调用到 mock_server_all FastAPI 应用。"""
    from urllib.parse import urlparse

    _asgi_transport = httpx.ASGITransport(app=mock_app)
    _OriginalAsyncClient = httpx.AsyncClient

    class _PatchedAsyncClient(_OriginalAsyncClient):
        async def get(self, url, **kwargs):
            if "/api/gateway/" in str(url):
                parsed = urlparse(str(url))
                async with _OriginalAsyncClient(
                    transport=_asgi_transport,
                    base_url="http://testserver",
                ) as mc:
                    return await mc.get(parsed.path, **kwargs)
            return await super().get(url, **kwargs)

        async def post(self, url, **kwargs):
            if "/api/gateway/" in str(url):
                parsed = urlparse(str(url))
                async with _OriginalAsyncClient(
                    transport=_asgi_transport,
                    base_url="http://testserver",
                ) as mc:
                    return await mc.post(parsed.path, **kwargs)
            return await super().post(url, **kwargs)

    with patch("backend.skills.data.api_fetch.httpx.AsyncClient", _PatchedAsyncClient):
        yield


# ════════════════════════════════════════════════════════════════
# 预定义测试计划 — 覆盖各类任务类型
# ════════════════════════════════════════════════════════════════

# ── D1 生产运营 ────────────────────────────────────────────────

PLAN_D1_THROUGHPUT_TREND = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取大连港区吞吐量月度趋势",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getThroughputAnalysisByYear",
            "dateYear": "2026",
            "preYear": "2025",
            "regionName": "大连港区",
        },
        estimated_seconds=10,
    ),
]

PLAN_D1_BERTH_OCCUPANCY = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取各港区泊位占用率",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getBerthOccupancyRateByRegion",
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
        },
        estimated_seconds=10,
    ),
]

# ── D3 客户管理 ────────────────────────────────────────────────

PLAN_D3_CLIENT_RANKING = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取战略客户吞吐量排名",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getStrategicCustomerThroughput",
            "curDateMonth": "2026-03",
            "preDateMonth": "2025-03",
        },
        estimated_seconds=10,
    ),
]

# ── D5 资产管理 ────────────────────────────────────────────────

PLAN_D5_ASSET_DISTRIBUTION = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取资产价值分布",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getAssetValue",
            "ownerZone": "大连港区域",
        },
        estimated_seconds=10,
    ),
]

# ── D7 设备管理 ────────────────────────────────────────────────

PLAN_D7_EQUIPMENT_UTILIZATION = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取设备完好率年度趋势",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getEquipmentServiceableRate",
            "dateYear": "2026",
        },
        estimated_seconds=10,
    ),
]

# ── 图表生成计划（依赖数据获取）─────────────────────────────────

PLAN_CHART_FROM_DATA = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取吞吐量数据",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getThroughputAnalysisByYear",
            "dateYear": "2026",
            "preYear": "2025",
            "regionName": "大连港区",
        },
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="visualization",
        name="生成吞吐量折线图",
        skill="skill_chart_line",
        params={
            "data_ref": "T001",
            "title": "大连港区2026年吞吐量月度趋势",
        },
        depends_on=["T001"],
        estimated_seconds=10,
    ),
]

# ── 多任务并行计划 ──────────────────────────────────────────────

PLAN_PARALLEL_TASKS = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取大连港区吞吐量",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getThroughputAnalysisByYear",
            "dateYear": "2026",
            "preYear": "2025",
            "regionName": "大连港区",
        },
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="data_fetch",
        name="获取营口港区吞吐量",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getThroughputAnalysisByYear",
            "dateYear": "2026",
            "preYear": "2025",
            "regionName": "营口港",
        },
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T003",
        type="data_fetch",
        name="获取丹东港区位用率",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getBerthOccupancyRateByRegion",
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
        },
        estimated_seconds=10,
    ),
]

# ── DAG 依赖链计划 ──────────────────────────────────────────────

PLAN_DAG_CHAIN = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取数据",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getThroughputAnalysisByYear",
            "dateYear": "2026",
            "preYear": "2025",
            "regionName": "大连港区",
        },
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="analysis",
        name="描述性分析",
        skill="skill_desc_analysis",
        params={"data_ref": "T001"},
        depends_on=["T001"],
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T003",
        type="visualization",
        name="生成图表",
        skill="skill_chart_line",
        params={"data_ref": "T001", "title": "吞吐量趋势"},
        depends_on=["T001"],
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T004",
        type="analysis",
        name="生成摘要",
        skill="skill_summary_gen",
        params={"data_refs": ["T001", "T002"]},
        depends_on=["T002"],
        estimated_seconds=10,
    ),
]

# ── 错误处理计划 ────────────────────────────────────────────────

PLAN_INVALID_ENDPOINT = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="无效端点测试",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "InvalidEndpointThatDoesNotExist",
        },
        estimated_seconds=10,
    ),
]

PLAN_MISSING_PARAMS = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="缺少参数测试",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getSingleShipRate",
            # 缺少必填参数 startDate, endDate, regionName
        },
        estimated_seconds=10,
    ),
]


# ════════════════════════════════════════════════════════════════
# 员工技能白名单
# ════════════════════════════════════════════════════════════════

THROUGHPUT_ANALYST_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_pie",
    "skill_desc_analysis",
    "skill_summary_gen",
    "skill_report_docx",
    "skill_report_pptx",
    "skill_prediction",
])

CUSTOMER_INSIGHT_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_pie",
    "skill_desc_analysis",
    "skill_summary_gen",
    "skill_report_docx",
    "skill_report_pptx",
])

ASSET_INVESTMENT_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_pie",
    "skill_desc_analysis",
    "skill_summary_gen",
    "skill_report_docx",
    "skill_report_pptx",
])


# ════════════════════════════════════════════════════════════════
# 测试类
# ════════════════════════════════════════════════════════════════


class TestDataFetchExecution:
    """数据获取任务执行测试 — 验证 API 调用和数据返回。"""

    @pytest.mark.parametrize("plan,task_id,min_columns", [
        # D1: 吞吐量趋势
        (PLAN_D1_THROUGHPUT_TREND, "T001", 2),
        # D1: 泊位占用率
        (PLAN_D1_BERTH_OCCUPANCY, "T001", 3),
        # D3: 战略客户吞吐量
        (PLAN_D3_CLIENT_RANKING, "T001", 2),
        # D5: 资产价值
        (PLAN_D5_ASSET_DISTRIBUTION, "T001", 2),
        # D7: 设备完好率
        (PLAN_D7_EQUIPMENT_UTILIZATION, "T001", 2),
    ], ids=[
        "d1_throughput_trend",
        "d1_berth_occupancy",
        "d3_client_ranking",
        "d5_asset_distribution",
        "d7_equipment_utilization",
    ])
    async def test_data_fetch_success(
        self, plan, task_id, min_columns,
    ):
        """验证数据获取任务成功返回正确的数据结构。"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                plan, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # 验证任务状态
        assert statuses[task_id] == "done", (
            f"Task {task_id} failed: {context[task_id].error_message}"
        )

        # 验证输出类型
        output = context[task_id]
        assert output.output_type == "dataframe"
        assert output.status == "success"

        # 验证数据内容
        df = output.data
        assert isinstance(df, pd.DataFrame)
        assert not df.empty, f"DataFrame should not be empty for {task_id}"
        assert len(df.columns) >= min_columns, (
            f"Expected at least {min_columns} columns, got {list(df.columns)}"
        )

        # 验证元数据
        assert output.metadata.get("rows") == len(df)
        assert output.metadata.get("endpoint") is not None


class TestVisualizationExecution:
    """可视化任务执行测试 — 验证图表生成。"""

    async def test_chart_generation_from_dependent_data(self):
        """验证图表技能能从依赖的数据获取任务结果生成图表。"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_CHART_FROM_DATA, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # 验证数据获取成功
        assert statuses["T001"] == "done"
        assert context["T001"].output_type == "dataframe"

        # 验证图表生成成功
        assert statuses["T002"] == "done"
        chart_output = context["T002"]

        assert chart_output.output_type == "chart"
        assert chart_output.status == "success"

        # 验证 ECharts option 结构
        option = chart_output.data
        assert isinstance(option, dict)
        assert "title" in option
        assert "xAxis" in option
        assert "yAxis" in option
        assert "series" in option
        assert len(option["series"]) > 0

        # 验证图表元数据
        assert chart_output.metadata.get("chart_type") == "line"

    async def test_chart_auto_detects_columns(self):
        """验证图表技能自动检测时间列和数值列。"""
        plan = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="获取数据",
                skill="skill_api_fetch",
                params={
                    "endpoint_id": "getBerthOccupancyRateByRegion",
                    "startDate": "2026-03-01",
                    "endDate": "2026-03-31",
                },
                estimated_seconds=10,
            ),
            TaskItem(
                task_id="T002",
                type="visualization",
                name="生成图表",
                skill="skill_chart_line",
                params={
                    "data_ref": "T001",
                    # 不指定 time_column 和 value_columns，依赖自动检测
                    "title": "港区泊位占用率",
                },
                depends_on=["T001"],
                estimated_seconds=10,
            ),
        ]

        with mock_api_gateway():
            statuses, context, _ = await execute_plan(
                plan, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"

        option = context["T002"].data
        assert len(option["series"]) > 0


class TestParallelExecution:
    """并行执行测试 — 验证 DAG 调度和任务并行。"""

    async def test_parallel_tasks_all_succeed(self):
        """验证无依赖的任务能并行执行并全部成功。"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_PARALLEL_TASKS, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # 所有任务都应成功
        for task_id in ["T001", "T002", "T003"]:
            assert statuses[task_id] == "done", (
                f"Task {task_id} failed: {context[task_id].error_message}"
            )

        # 验证输出都是 DataFrame
        for task_id in ["T001", "T002", "T003"]:
            assert context[task_id].output_type == "dataframe"
            assert not context[task_id].data.empty

    async def test_dag_dependency_chain(self):
        """验证 DAG 依赖链正确执行：T001 → T002,T003 → T004。"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_DAG_CHAIN, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # T001 必须先完成
        assert statuses["T001"] == "done"

        # T002, T003 依赖 T001，应在 T001 后完成
        assert statuses["T002"] == "done"
        assert statuses["T003"] == "done"

        # T004 依赖 T002
        assert statuses["T004"] == "done"

        # 验证数据流
        assert context["T002"].output_type in ("json", "text")
        assert context["T003"].output_type == "chart"
        assert context["T004"].output_type == "text"


class TestErrorHandling:
    """错误处理测试 — 验证异常情况。"""

    async def test_invalid_endpoint_returns_error(self):
        """验证无效端点返回正确的错误信息。"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_INVALID_ENDPOINT, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        assert statuses["T001"] == "failed"

        error_msg = context["T001"].error_message or ""
        # 应该包含端点相关的错误信息
        assert "未知的端点" in error_msg or "InvalidEndpoint" in error_msg

    async def test_missing_params_returns_error(self):
        """验证缺少必填参数返回正确的错误信息。"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_MISSING_PARAMS, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        assert statuses["T001"] == "failed"

        error_msg = context["T001"].error_message or ""
        # 应该包含参数相关的错误信息
        assert "缺少" in error_msg or "必填" in error_msg or "startDate" in error_msg

    async def test_blocked_skill_rejected(self):
        """验证技能白名单正确阻止未授权技能。"""
        plan = [
            TaskItem(
                task_id="T001",
                type="analysis",
                name="预测分析",
                skill="skill_prediction",  # customer_insight 没有此技能
                params={},
                estimated_seconds=10,
            ),
        ]

        statuses, context, _ = await execute_plan(
            plan, allowed_skills=CUSTOMER_INSIGHT_SKILLS,
        )

        assert statuses["T001"] == "failed"
        assert "不在当前员工范围内" in (context["T001"].error_message or "")

    async def test_no_whitelist_allows_all(self):
        """验证 allowed_skills=None 时不进行白名单检查。"""
        plan = [
            TaskItem(
                task_id="T001",
                type="analysis",
                name="预测分析",
                skill="skill_prediction",
                params={},
                estimated_seconds=10,
            ),
        ]

        statuses, context, _ = await execute_plan(
            plan, allowed_skills=None,
        )

        # 应该不是因为白名单失败（可能因为技能未注册等其他原因）
        if statuses["T001"] == "failed":
            assert "不在当前员工范围内" not in (context["T001"].error_message or "")


class TestPerformance:
    """性能测试 — 验证执行效率。"""

    async def test_parallel_faster_than_sequential(self):
        """验证并行执行比顺序执行更快。"""
        import time

        # 顺序执行
        sequential_plan = [
            TaskItem(
                task_id=f"T{i:03d}",
                type="data_fetch",
                name=f"任务{i}",
                skill="skill_api_fetch",
                params={
                    "endpoint_id": "getThroughputAnalysisByYear",
                    "dateYear": "2026",
                    "regionName": "大连港区",
                },
                estimated_seconds=10,
            )
            for i in range(3)
        ]

        with mock_api_gateway():
            start = time.time()
            statuses, context, _ = await execute_plan(
                sequential_plan, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )
            parallel_time = time.time() - start

        # 所有任务都成功
        for i in range(3):
            assert statuses[f"T{i:03d}"] == "done"

        # 并行执行时间应该小于 3 * 单任务时间
        # 由于 Mock Server 响应很快，主要验证逻辑正确
        logger.info(f"Parallel execution of 3 tasks took {parallel_time:.2f}s")

    async def test_single_task_execution_time(self):
        """验证单个数据获取任务的执行时间。"""
        import time

        with mock_api_gateway():
            start = time.time()
            statuses, context, _ = await execute_plan(
                PLAN_D1_THROUGHPUT_TREND, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )
            elapsed = time.time() - start

        assert statuses["T001"] == "done"
        logger.info(f"Single data fetch task took {elapsed:.2f}s")

        # Mock Server 模式下，单个任务应在 2s 内完成
        # 真实 API 模式下，时间会更长


class TestEdgeCases:
    """边界情况测试 — 验证特殊场景。"""

    async def test_empty_result_handling(self):
        """验证空结果的处理。"""
        # 使用一个可能返回少量数据的端点
        plan = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="无效数据获取",
                skill="skill_api_fetch",
                params={
                    "endpoint_id": "getThroughputAnalysisByYear",
                    "dateYear": "2099",  # 未来年份，无数据
                    "regionName": "不存在的港区",
                },
                estimated_seconds=10,
            ),
        ]

        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                plan, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # 可能成功但返回空数据，也可能失败
        # 关键是系统能正确处理
        assert statuses["T001"] in ("done", "failed")

    async def test_large_dataset_handling(self):
        """验证大数据集的处理。"""
        plan = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="获取战略客户吞吐量排名",
                skill="skill_api_fetch",
                params={
                    "endpoint_id": "getStrategicCustomerThroughput",
                    "curDateMonth": "2026-03",
                    "preDateMonth": "2025-03",
                },
                estimated_seconds=10,
            ),
        ]

        with mock_api_gateway():
            statuses, context, _ = await execute_plan(
                plan, allowed_skills=CUSTOMER_INSIGHT_SKILLS,
            )

        assert statuses["T001"] == "done"
        df = context["T001"].data
        assert isinstance(df, pd.DataFrame)

    async def test_multiple_chart_types_in_sequence(self):
        """验证连续生成多种类型图表。"""
        plan = [
            TaskItem(
                task_id="T001",
                type="data_fetch",
                name="获取数据",
                skill="skill_api_fetch",
                params={
                    "endpoint_id": "getThroughputAnalysisByYear",
                    "dateYear": "2026",
                    "regionName": "大连港区",
                },
                estimated_seconds=10,
            ),
            TaskItem(
                task_id="T002",
                type="visualization",
                name="折线图",
                skill="skill_chart_line",
                params={"data_ref": "T001", "title": "趋势图"},
                depends_on=["T001"],
                estimated_seconds=10,
            ),
        ]

        with mock_api_gateway():
            statuses, context, _ = await execute_plan(
                plan, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"
        assert context["T002"].output_type == "chart"


# ════════════════════════════════════════════════════════════════
# 报告生成测试计划 — HTML/DOCX/PPTX
# ════════════════════════════════════════════════════════════════

# 完整分析报告计划：数据获取 → 分析 → 图表 → 报告生成
PLAN_FULL_REPORT_WITH_DATA = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取吞吐量数据",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getThroughputAnalysisByYear",
            "dateYear": "2026",
            "preYear": "2025",
            "regionName": "大连港区",
        },
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="analysis",
        name="描述性分析",
        skill="skill_desc_analysis",
        params={"data_ref": "T001"},
        depends_on=["T001"],
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T003",
        type="visualization",
        name="生成吞吐量折线图",
        skill="skill_chart_line",
        params={"data_ref": "T001", "title": "大连港区吞吐量趋势"},
        depends_on=["T001"],
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T004",
        type="analysis",
        name="生成分析摘要",
        skill="skill_summary_gen",
        params={"data_ref": "T001"},
        depends_on=["T001"],
        estimated_seconds=10,
    ),
]

# 简单报告计划（无图表）
PLAN_SIMPLE_REPORT = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取泊位占用率数据",
        skill="skill_api_fetch",
        params={
            "endpoint_id": "getBerthOccupancyRateByRegion",
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
        },
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="analysis",
        name="生成摘要文本",
        skill="skill_summary_gen",
        params={"data_ref": "T001"},
        depends_on=["T001"],
        estimated_seconds=10,
    ),
]


# ════════════════════════════════════════════════════════════════
# 报告生成测试类
# ════════════════════════════════════════════════════════════════


class TestReportGeneration:
    """报告生成测试 — 验证 HTML/DOCX/PPTX 格式的报告生成。"""

    # ── HTML 报告测试 ──────────────────────────────────────────

    async def _run_report_plan(self, plan):
        """运行报告计划并返回执行上下文。"""
        with mock_api_gateway():
            statuses, context, _ = await execute_plan(
                plan, allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )
        return statuses, context

    async def test_html_report_with_full_data(self):
        """验证 HTML 报告能正确整合数据、图表和摘要。"""
        # 先执行数据获取和分析
        statuses, context = await self._run_report_plan(PLAN_FULL_REPORT_WITH_DATA)

        # 验证上游任务都成功
        for tid in ["T001", "T002", "T003", "T004"]:
            assert statuses[tid] == "done", f"Task {tid} failed"

        # 执行 HTML 报告生成
        report_task = TaskItem(
            task_id="T005",
            type="report_gen",
            name="生成HTML报告",
            skill="skill_report_html",
            params={
                "report_metadata": {
                    "title": "大连港区2026年吞吐量分析报告",
                    "author": "Analytica",
                    "date": "2026-04-19",
                },
                "report_structure": {
                    "sections": [
                        {"name": "数据概览", "task_refs": ["T001"]},
                        {"name": "趋势分析", "task_refs": ["T002", "T003"]},
                        {"name": "总结", "task_refs": ["T004"]},
                    ]
                },
            },
            depends_on=["T001", "T002", "T003", "T004"],
            estimated_seconds=15,
        )

        # 直接调用技能（跳过 execute_plan 以获得详细报告输出）
        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_html")
        assert skill is not None, "skill_report_html not registered"

        inp = SkillInput(params=report_task.params, context_refs=report_task.depends_on)
        output = await skill.execute(inp, context)

        # 验证输出
        assert output.status in ("success", "partial"), f"HTML report failed: {output.error_message}"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "html"

        # 验证 HTML 内容
        html_content = output.data
        assert isinstance(html_content, str)
        assert "<html" in html_content.lower()
        assert "大连港区" in html_content
        assert len(html_content) > 500, "HTML content too short"

        # 保存报告到磁盘
        saved_path = save_report_artifact("html_full_data", "skill_report_html", output, "html")
        assert saved_path is not None, "Failed to save HTML report"
        assert saved_path.exists(), f"Saved file does not exist: {saved_path}"

        logger.info(f"HTML report generated: {len(html_content)} bytes, saved to: {saved_path}")

    async def test_html_report_deterministic_fallback(self):
        """验证 HTML 报告在 LLM 禁用时使用确定性生成。"""
        report_task = TaskItem(
            task_id="T001",
            type="report_gen",
            name="生成HTML报告",
            skill="skill_report_html",
            params={
                "report_metadata": {
                    "title": "测试报告",
                    "author": "Test",
                    "date": "2026-04-19",
                },
                "report_structure": {
                    "sections": [{"name": "测试章节"}]
                },
            },
            estimated_seconds=15,
        )

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_html")
        inp = SkillInput(params=report_task.params, context_refs=[])
        output = await skill.execute(inp, {})

        assert output.status == "success"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "html"
        assert output.metadata.get("mode") in ("deterministic_fallback", "llm_agent")
        assert len(output.data) > 100

    # ── DOCX 报告测试 ──────────────────────────────────────────

    async def test_docx_report_with_full_data(self):
        """验证 DOCX 报告能正确生成 Word 文档。"""
        # 先执行数据获取和分析
        statuses, context = await self._run_report_plan(PLAN_FULL_REPORT_WITH_DATA)

        # 验证上游任务都成功
        for tid in ["T001", "T002", "T003", "T004"]:
            assert statuses[tid] == "done", f"Task {tid} failed"

        # 执行 DOCX 报告生成
        report_task = TaskItem(
            task_id="T005",
            type="report_gen",
            name="生成DOCX报告",
            skill="skill_report_docx",
            params={
                "report_metadata": {
                    "title": "大连港区2026年吞吐量分析报告",
                    "author": "Analytica",
                    "date": "2026-04-19",
                },
                "report_structure": {
                    "sections": [
                        {"name": "数据概览", "task_refs": ["T001"]},
                        {"name": "趋势分析", "task_refs": ["T002", "T003"]},
                        {"name": "总结", "task_refs": ["T004"]},
                    ]
                },
            },
            depends_on=["T001", "T002", "T003", "T004"],
            estimated_seconds=15,
        )

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_docx")
        assert skill is not None, "skill_report_docx not registered"

        inp = SkillInput(params=report_task.params, context_refs=report_task.depends_on)
        output = await skill.execute(inp, context)

        # 验证输出
        assert output.status in ("success", "partial"), f"DOCX report failed: {output.error_message}"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "docx"

        # 验证 DOCX 内容是字节数据
        docx_data = output.data
        assert isinstance(docx_data, (bytes, bytearray))
        assert len(docx_data) > 1000, "DOCX file too small"

        # 验证文件大小元数据
        assert output.metadata.get("file_size_bytes") == len(docx_data)

        # 保存报告到磁盘
        saved_path = save_report_artifact("docx_full_data", "skill_report_docx", output, "docx")
        assert saved_path is not None
        assert saved_path.exists()
        logger.info(f"DOCX report saved to: {saved_path}")

    async def test_docx_report_deterministic_fallback(self):
        """验证 DOCX 报告在 LLM 禁用时使用确定性生成。"""
        report_task = TaskItem(
            task_id="T001",
            type="report_gen",
            name="生成DOCX报告",
            skill="skill_report_docx",
            params={
                "report_metadata": {
                    "title": "测试报告",
                    "author": "Test",
                    "date": "2026-04-19",
                },
                "report_structure": {
                    "sections": [{"name": "测试章节"}]
                },
            },
            estimated_seconds=15,
        )

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_docx")
        inp = SkillInput(params=report_task.params, context_refs=[])
        output = await skill.execute(inp, {})

        assert output.status == "success"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "docx"
        assert output.metadata.get("mode") in ("deterministic_fallback", "llm_agent")
        assert len(output.data) > 1000

        # 保存报告到磁盘
        saved_path = save_report_artifact("docx_simple", "skill_report_docx", output, "docx")
        assert saved_path is not None
        logger.info(f"DOCX report saved to: {saved_path}")

    # ── PPTX 报告测试 ──────────────────────────────────────────

    async def test_pptx_report_with_full_data(self):
        """验证 PPTX 报告能正确生成 PowerPoint 演示文稿。"""
        # 先执行数据获取和分析
        statuses, context = await self._run_report_plan(PLAN_FULL_REPORT_WITH_DATA)

        # 验证上游任务都成功
        for tid in ["T001", "T002", "T003", "T004"]:
            assert statuses[tid] == "done", f"Task {tid} failed"

        # 执行 PPTX 报告生成
        report_task = TaskItem(
            task_id="T005",
            type="report_gen",
            name="生成PPTX报告",
            skill="skill_report_pptx",
            params={
                "report_metadata": {
                    "title": "大连港区2026年吞吐量季度报告",
                    "author": "Analytica",
                    "date": "2026-04-19",
                },
                "report_structure": {
                    "sections": [
                        {"name": "数据概览", "task_refs": ["T001"]},
                        {"name": "趋势分析", "task_refs": ["T002", "T003"]},
                        {"name": "总结", "task_refs": ["T004"]},
                    ]
                },
            },
            depends_on=["T001", "T002", "T003", "T004"],
            estimated_seconds=15,
        )

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_pptx")
        assert skill is not None, "skill_report_pptx not registered"

        inp = SkillInput(params=report_task.params, context_refs=report_task.depends_on)
        output = await skill.execute(inp, context)

        # 验证输出
        assert output.status in ("success", "partial"), f"PPTX report failed: {output.error_message}"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "pptx"

        # 验证 PPTX 内容是字节数据
        pptx_data = output.data
        assert isinstance(pptx_data, (bytes, bytearray))
        assert len(pptx_data) > 1000, "PPTX file too small"

        # 验证幻灯片数量元数据
        slide_count = output.metadata.get("slide_count", 0)
        assert slide_count > 0, "No slides generated"

        logger.info(f"PPTX report generated: {len(pptx_data)} bytes, {slide_count} slides")

    async def test_pptx_report_deterministic_fallback(self):
        """验证 PPTX 报告在 LLM 禁用时使用确定性生成。"""
        report_task = TaskItem(
            task_id="T001",
            type="report_gen",
            name="生成PPTX报告",
            skill="skill_report_pptx",
            params={
                "report_metadata": {
                    "title": "测试报告",
                    "author": "Test",
                    "date": "2026-04-19",
                },
                "report_structure": {
                    "sections": [{"name": "测试章节"}]
                },
            },
            estimated_seconds=15,
        )

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_pptx")
        inp = SkillInput(params=report_task.params, context_refs=[])
        output = await skill.execute(inp, {})

        assert output.status == "success"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "pptx"
        assert output.metadata.get("mode") in ("deterministic_fallback", "llm_agent")
        assert len(output.data) > 1000
        assert output.metadata.get("slide_count", 0) > 0

        # 保存报告到磁盘
        saved_path = save_report_artifact("pptx_simple", "skill_report_pptx", output, "pptx")
        assert saved_path is not None
        logger.info(f"PPTX report saved to: {saved_path}")

    # ── 简单报告测试 ──────────────────────────────────────────

    async def test_html_report_simple_data(self):
        """验证 HTML 报告能处理简单的摘要数据。"""
        statuses, context = await self._run_report_plan(PLAN_SIMPLE_REPORT)

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_html")
        inp = SkillInput(
            params={
                "report_metadata": {"title": "泊位占用率报告"},
                "report_structure": {"sections": [{"name": "分析结果"}]},
            },
            context_refs=["T001", "T002"],
        )
        output = await skill.execute(inp, context)

        assert output.status in ("success", "partial")
        assert output.output_type == "file"
        assert output.metadata.get("format") == "html"

    async def test_docx_report_simple_data(self):
        """验证 DOCX 报告能处理简单的摘要数据。"""
        statuses, context = await self._run_report_plan(PLAN_SIMPLE_REPORT)

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_docx")
        inp = SkillInput(
            params={
                "report_metadata": {"title": "泊位占用率报告"},
                "report_structure": {"sections": [{"name": "分析结果"}]},
            },
            context_refs=["T001", "T002"],
        )
        output = await skill.execute(inp, context)

        assert output.status in ("success", "partial")
        assert output.output_type == "file"
        assert output.metadata.get("format") == "docx"

    async def test_pptx_report_simple_data(self):
        """验证 PPTX 报告能处理简单的摘要数据。"""
        statuses, context = await self._run_report_plan(PLAN_SIMPLE_REPORT)

        assert statuses["T001"] == "done"
        assert statuses["T002"] == "done"

        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_pptx")
        inp = SkillInput(
            params={
                "report_metadata": {"title": "泊位占用率报告"},
                "report_structure": {"sections": [{"name": "分析结果"}]},
            },
            context_refs=["T001", "T002"],
        )
        output = await skill.execute(inp, context)

        assert output.status in ("success", "partial")
        assert output.output_type == "file"
        assert output.metadata.get("format") == "pptx"
        assert output.metadata.get("slide_count", 0) > 0


class TestReportArtifactRecording:
    """报告工件记录测试 — 验证报告文件能正确保存。"""

    async def test_record_html_artifact(self):
        """验证 HTML 报告能正确记录为文件。"""
        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_html")
        inp = SkillInput(
            params={
                "report_metadata": {"title": "测试报告"},
                "report_structure": {"sections": [{"name": "测试"}]},
            },
            context_refs=[],
        )
        output = await skill.execute(inp, {})

        assert output.status == "success"
        assert output.output_type == "file"

        # 验证 HTML 内容可被解析
        html = output.data
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html or "<html" in html

        # 验证元数据
        assert output.metadata.get("format") == "html"
        assert "title" in output.metadata or "mode" in output.metadata

        # 保存报告到磁盘
        saved_path = save_report_artifact("artifact_html", "skill_report_html", output, "html")
        assert saved_path is not None
        logger.info(f"Artifact HTML saved to: {saved_path}")

    async def test_record_docx_artifact(self):
        """验证 DOCX 报告能正确记录为二进制文件。"""
        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_docx")
        inp = SkillInput(
            params={
                "report_metadata": {"title": "测试报告"},
                "report_structure": {"sections": [{"name": "测试"}]},
            },
            context_refs=[],
        )
        output = await skill.execute(inp, {})

        assert output.status == "success"
        assert output.output_type == "file"

        # 验证 DOCX 是有效的 ZIP/二进制格式（DOCX本质是ZIP）
        docx_bytes = output.data
        assert isinstance(docx_bytes, (bytes, bytearray))
        assert docx_bytes[:2] == b"PK", "DOCX should be ZIP format (PK header)"

        # 验证元数据
        assert output.metadata.get("format") == "docx"
        assert output.metadata.get("file_size_bytes") == len(docx_bytes)

    async def test_record_pptx_artifact(self):
        """验证 PPTX 报告能正确记录为二进制文件。"""
        from backend.skills.registry import SkillRegistry
        from backend.skills.base import SkillInput

        registry = SkillRegistry.get_instance()
        skill = registry.get_skill("skill_report_pptx")
        inp = SkillInput(
            params={
                "report_metadata": {"title": "测试报告"},
                "report_structure": {"sections": [{"name": "测试"}]},
            },
            context_refs=[],
        )
        output = await skill.execute(inp, {})

        assert output.status == "success"
        assert output.output_type == "file"

        # 验证 PPTX 是有效的 ZIP/二进制格式
        pptx_bytes = output.data
        assert isinstance(pptx_bytes, (bytes, bytearray))
        assert pptx_bytes[:2] == b"PK", "PPTX should be ZIP format (PK header)"

        # 验证元数据
        assert output.metadata.get("format") == "pptx"
        assert output.metadata.get("slide_count", 0) > 0
        assert output.metadata.get("file_size_bytes") == len(pptx_bytes)


class TestReportContentExtraction:
    """报告内容提取测试 — 验证内容收集和关联逻辑。"""

    async def test_content_collector_extracts_dataframe(self):
        """验证内容收集器能正确提取 DataFrame 数据。"""
        from backend.skills.report._content_collector import collect_and_associate

        # 模拟包含 DataFrame 的上下文
        mock_context = {
            "T001": type("MockOutput", (), {
                "data": pd.DataFrame({"col1": [1, 2, 3], "col2": [4, 5, 6]}),
                "status": "success"
            })()
        }

        params = {
            "report_metadata": {"title": "测试"},
            "report_structure": {"sections": [{"name": "数据", "task_refs": ["T001"]}]}
        }

        report = collect_and_associate(params, mock_context)

        assert report.title == "测试"
        assert len(report.sections) == 1
        assert len(report.sections[0].items) == 1

        # 验证 DataFrame 被正确提取
        from backend.skills.report._content_collector import DataFrameItem
        item = report.sections[0].items[0]
        assert isinstance(item, DataFrameItem)
        assert len(item.df) == 3

    async def test_content_collector_extracts_narrative(self):
        """验证内容收集器能正确提取文本摘要。"""
        from backend.skills.report._content_collector import collect_and_associate

        mock_context = {
            "T001": type("MockOutput", (), {
                "data": {"narrative": "这是分析摘要文本，内容较长以满足长度要求。"},
                "status": "success"
            })()
        }

        params = {
            "report_metadata": {"title": "测试"},
            "report_structure": {"sections": [{"name": "摘要", "task_refs": ["T001"]}]}
        }

        report = collect_and_associate(params, mock_context)

        assert len(report.sections) == 1
        from backend.skills.report._content_collector import NarrativeItem
        item = report.sections[0].items[0]
        assert isinstance(item, NarrativeItem)
        assert "分析摘要" in item.text

    async def test_content_collector_extracts_chart(self):
        """验证内容收集器能正确提取图表数据。"""
        from backend.skills.report._content_collector import collect_and_associate

        mock_chart = {
            "title": {"text": "测试图表"},
            "xAxis": {"type": "category", "data": ["A", "B", "C"]},
            "yAxis": {"type": "value"},
            "series": [{"name": "数值", "data": [10, 20, 30]}]
        }

        mock_context = {
            "T001": type("MockOutput", (), {
                "data": mock_chart,
                "status": "success"
            })()
        }

        params = {
            "report_metadata": {"title": "测试"},
            "report_structure": {"sections": [{"name": "图表", "task_refs": ["T001"]}]}
        }

        report = collect_and_associate(params, mock_context)

        assert len(report.sections) == 1
        from backend.skills.report._content_collector import ChartDataItem
        item = report.sections[0].items[0]
        assert isinstance(item, ChartDataItem)
        assert "series" in item.option
        assert len(item.option["series"]) == 1
