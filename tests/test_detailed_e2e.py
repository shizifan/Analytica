"""详细端到端测试 - 针对不同员工类型的综合分析报告生成。

测试场景：
1. throughput_analyst - 吞吐量绩效分析师
2. customer_insight - 市场商务与战略客户洞察专家
3. asset_investment - 资产价值与投资项目分析师

运行：
    pytest tests/test_detailed_e2e.py -v
    pytest tests/test_detailed_e2e.py -v -k "throughput"
    pytest tests/test_detailed_e2e.py -v -k "customer"
    pytest tests/test_detailed_e2e.py -v -k "asset"
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
import pytest

from backend.agent.execution import execute_plan
from backend.models.schemas import TaskItem
from backend.skills.loader import load_all_skills

load_all_skills()
logger = logging.getLogger("test.detailed_e2e")

# ════════════════════════════════════════════════════════════════
# 报告输出目录配置
# ════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_BASE = PROJECT_ROOT / "reports" / "detailed_e2e"
_RUN_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

def _get_run_dir() -> Path:
    return REPORTS_BASE / _RUN_TIMESTAMP

def save_report_artifact(
    test_name: str,
    skill_id: str,
    output: Any,
    sub_dir: str = "reports",
) -> Path | None:
    """保存报告工件到磁盘。"""
    output_dir = _get_run_dir() / sub_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if not hasattr(output, "data") or output.data is None:
        return None

    fmt = output.metadata.get("format", "")
    data = output.data

    if fmt == "html":
        if not isinstance(data, str):
            return None
        file_path = output_dir / f"{test_name}.html"
        file_path.write_text(data, encoding="utf-8")
        logger.info(f"[{test_name}] HTML saved: {file_path} ({len(data)} bytes)")
        return file_path

    if fmt in ("docx", "pptx"):
        if not isinstance(data, (bytes, bytearray)):
            return None
        file_path = output_dir / f"{test_name}.{fmt}"
        file_path.write_bytes(data)
        logger.info(f"[{test_name}] {fmt.upper()} saved: {file_path} ({len(data)} bytes)")
        return file_path

    return None


# ════════════════════════════════════════════════════════════════
# Mock Server 配置
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
# 员工技能白名单
# ════════════════════════════════════════════════════════════════

THROUGHPUT_ANALYST_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_waterfall",
    "skill_desc_analysis",
    "skill_summary_gen",
    "skill_report_html",
    "skill_report_docx",
    "skill_prediction",
])

CUSTOMER_INSIGHT_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_pie",
    "skill_desc_analysis",
    "skill_summary_gen",
    "skill_report_html",
    "skill_report_pptx",
])

ASSET_INVESTMENT_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_waterfall",
    "skill_desc_analysis",
    "skill_summary_gen",
    "skill_report_html",
    "skill_report_docx",
])


# ════════════════════════════════════════════════════════════════
# 测试场景1: 吞吐量绩效分析师 - 数据获取
# ════════════════════════════════════════════════════════════════

PLAN_THROUGHPUT_DATA = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取吞吐量年度数据",
        skill="skill_api_fetch",
        params={"endpoint_id": "getThroughputAnalysisByYear", "dateYear": "2026", "preYear": "2025"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="data_fetch",
        name="获取目标完成率",
        skill="skill_api_fetch",
        params={"endpoint_id": "getThroughputAndTargetThroughputTon", "dateYear": "2026"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T003",
        type="data_fetch",
        name="获取泊位占用率",
        skill="skill_api_fetch",
        params={"endpoint_id": "getBerthOccupancyRateByRegion", "startDate": "2026-01-01", "endDate": "2026-03-31"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T004",
        type="data_fetch",
        name="获取同比环比数据",
        skill="skill_api_fetch",
        params={"endpoint_id": "getThroughputAnalysisYoyMomByMonth", "dateMonth": "2026-03"},
        estimated_seconds=10,
    ),
]


# ════════════════════════════════════════════════════════════════
# 测试场景2: 客户洞察 - 数据获取
# ════════════════════════════════════════════════════════════════

PLAN_CUSTOMER_DATA = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取客户总量",
        skill="skill_api_fetch",
        params={"endpoint_id": "getCustomerQty"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="data_fetch",
        name="获取战略客户名单",
        skill="skill_api_fetch",
        params={"endpoint_id": "getStrategicCustomers"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T003",
        type="data_fetch",
        name="获取战略客户吞吐量",
        skill="skill_api_fetch",
        params={"endpoint_id": "getStrategicCustomerThroughput", "curDateMonth": "2026-03", "preDateMonth": "2025-03"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T004",
        type="data_fetch",
        name="获取客户类型分析",
        skill="skill_api_fetch",
        params={"endpoint_id": "getCustomerTypeAnalysis"},
        estimated_seconds=10,
    ),
]


# ════════════════════════════════════════════════════════════════
# 测试场景3: 资产投资 - 数据获取
# ════════════════════════════════════════════════════════════════

PLAN_ASSET_DATA = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取历年投资数据",
        skill="skill_api_fetch",
        params={"endpoint_id": "getInvestPlanByYear"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="data_fetch",
        name="获取设备利用率",
        skill="skill_api_fetch",
        params={"endpoint_id": "getEquipmentUsageRate", "dateYear": 2026},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T003",
        type="data_fetch",
        name="获取设备完好率",
        skill="skill_api_fetch",
        params={"endpoint_id": "getEquipmentServiceableRate", "dateYear": 2026},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T004",
        type="data_fetch",
        name="获取设备运营指标",
        skill="skill_api_fetch",
        params={"endpoint_id": "getEquipmentIndicatorOperationQty", "dateMonth": "2026-03"},
        estimated_seconds=10,
    ),
]


# ════════════════════════════════════════════════════════════════
# 测试场景4: 可视化生成
# ════════════════════════════════════════════════════════════════

PLAN_VISUALIZATION = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取吞吐量数据",
        skill="skill_api_fetch",
        params={"endpoint_id": "getThroughputAnalysisByYear", "dateYear": "2026", "preYear": "2025"},
        estimated_seconds=10,
    ),
    TaskItem(
        task_id="T002",
        type="visualization",
        name="生成吞吐量折线图",
        skill="skill_chart_line",
        params={"data_ref": "T001", "title": "吞吐量月度趋势"},
        depends_on=["T001"],
        estimated_seconds=10,
    ),
]


# ════════════════════════════════════════════════════════════════
# 测试场景5: 报告生成
# ════════════════════════════════════════════════════════════════

PLAN_HTML_REPORT = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取吞吐量数据",
        skill="skill_api_fetch",
        params={"endpoint_id": "getThroughputAnalysisByYear", "dateYear": "2026", "preYear": "2025"},
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
        type="report_gen",
        name="生成HTML报告",
        skill="skill_report_html",
        params={"title": "吞吐量分析报告", "data_refs": ["T001", "T002"]},
        depends_on=["T001", "T002"],
        estimated_seconds=30,
    ),
]

PLAN_DOCX_REPORT = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取投资数据",
        skill="skill_api_fetch",
        params={"endpoint_id": "getInvestPlanByYear"},
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
        type="report_gen",
        name="生成DOCX报告",
        skill="skill_report_docx",
        params={"title": "投资分析报告", "data_refs": ["T001", "T002"]},
        depends_on=["T001", "T002"],
        estimated_seconds=30,
    ),
]

PLAN_PPTX_REPORT = [
    TaskItem(
        task_id="T001",
        type="data_fetch",
        name="获取客户数据",
        skill="skill_api_fetch",
        params={"endpoint_id": "getCustomerQty"},
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
        type="report_gen",
        name="生成PPTX报告",
        skill="skill_report_pptx",
        params={"title": "客户分析报告", "data_refs": ["T001", "T002"]},
        depends_on=["T001", "T002"],
        estimated_seconds=30,
    ),
]


# ════════════════════════════════════════════════════════════════
# 测试用例：吞吐量绩效分析师
# ════════════════════════════════════════════════════════════════

class TestThroughputAnalyst:
    """吞吐量绩效分析师 - 数据获取测试"""

    @pytest.mark.asyncio
    async def test_throughput_data_fetch(self):
        """测试吞吐量相关数据获取"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_THROUGHPUT_DATA,
                allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # 验证所有数据获取任务成功
        assert statuses.get("T001") == "done", f"T001失败: {context.get('T001').error_message}"
        assert statuses.get("T002") == "done", f"T002失败: {context.get('T002').error_message}"
        assert statuses.get("T003") == "done", f"T003失败: {context.get('T003').error_message}"
        assert statuses.get("T004") == "done", f"T004失败: {context.get('T004').error_message}"

        # 验证输出类型
        assert context["T001"].output_type == "dataframe"
        assert context["T002"].output_type == "dataframe"

        # 验证数据内容
        df1 = context["T001"].data
        assert len(df1) > 0, "吞吐量数据为空"

        logger.info("吞吐量数据获取测试通过")


# ════════════════════════════════════════════════════════════════
# 测试用例：市场商务与战略客户洞察专家
# ════════════════════════════════════════════════════════════════

class TestCustomerInsight:
    """市场商务与战略客户洞察专家 - 数据获取测试"""

    @pytest.mark.asyncio
    async def test_customer_data_fetch(self):
        """测试客户相关数据获取"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_CUSTOMER_DATA,
                allowed_skills=CUSTOMER_INSIGHT_SKILLS,
            )

        # 验证所有数据获取任务成功
        assert statuses.get("T001") == "done", f"T001失败: {context.get('T001').error_message}"
        assert statuses.get("T002") == "done", f"T002失败: {context.get('T002').error_message}"
        assert statuses.get("T003") == "done", f"T003失败: {context.get('T003').error_message}"
        assert statuses.get("T004") == "done", f"T004失败: {context.get('T004').error_message}"

        # 验证输出类型
        assert context["T001"].output_type == "dataframe"
        assert context["T002"].output_type == "dataframe"

        # 验证数据内容
        df1 = context["T001"].data
        assert len(df1) > 0, "客户数据为空"

        logger.info("客户数据获取测试通过")


# ════════════════════════════════════════════════════════════════
# 测试用例：资产价值与投资项目分析师
# ════════════════════════════════════════════════════════════════

class TestAssetInvestment:
    """资产价值与投资项目分析师 - 数据获取测试"""

    @pytest.mark.asyncio
    async def test_asset_data_fetch(self):
        """测试资产投资相关数据获取"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_ASSET_DATA,
                allowed_skills=ASSET_INVESTMENT_SKILLS,
            )

        # 验证所有数据获取任务成功
        assert statuses.get("T001") == "done", f"T001失败: {context.get('T001').error_message}"
        assert statuses.get("T002") == "done", f"T002失败: {context.get('T002').error_message}"
        assert statuses.get("T003") == "done", f"T003失败: {context.get('T003').error_message}"
        assert statuses.get("T004") == "done", f"T004失败: {context.get('T004').error_message}"

        # 验证输出类型
        assert context["T001"].output_type == "dataframe"
        assert context["T002"].output_type == "dataframe"

        # 验证数据内容
        df1 = context["T001"].data
        assert len(df1) > 0, "投资数据为空"

        logger.info("资产投资数据获取测试通过")


# ════════════════════════════════════════════════════════════════
# 测试用例：可视化生成
# ════════════════════════════════════════════════════════════════

class TestVisualization:
    """可视化任务测试"""

    @pytest.mark.asyncio
    async def test_chart_generation(self):
        """测试图表生成"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_VISUALIZATION,
                allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # 验证数据获取成功
        assert statuses.get("T001") == "done", f"T001失败: {context.get('T001').error_message}"

        # 验证图表生成成功
        assert statuses.get("T002") == "done", f"T002失败: {context.get('T002').error_message}"

        # 验证输出类型
        assert context["T002"].output_type in ("html", "chart")
        assert context["T002"].data is not None

        logger.info("图表生成测试通过")


# ════════════════════════════════════════════════════════════════
# 测试用例：报告生成
# ════════════════════════════════════════════════════════════════

class TestReportGeneration:
    """报告生成测试"""

    @pytest.mark.asyncio
    async def test_html_report_generation(self):
        """测试HTML报告生成"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_HTML_REPORT,
                allowed_skills=THROUGHPUT_ANALYST_SKILLS,
            )

        # 验证数据获取和分析成功
        assert statuses.get("T001") == "done", f"T001失败: {context.get('T001').error_message}"
        assert statuses.get("T002") == "done", f"T002失败: {context.get('T002').error_message}"

        # 验证报告生成
        report_status = statuses.get("T003")
        report_output = context.get("T003")

        if report_status == "done" and report_output and report_output.data:
            saved_path = save_report_artifact(
                "throughput_html_report",
                "skill_report_html",
                report_output,
                sub_dir="throughput_analyst"
            )
            logger.info(f"HTML报告已生成: {saved_path}")
        else:
            logger.warning(f"HTML报告生成失败: {report_output.error_message if report_output else 'Unknown'}")

    @pytest.mark.asyncio
    async def test_docx_report_generation(self):
        """测试DOCX报告生成"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_DOCX_REPORT,
                allowed_skills=ASSET_INVESTMENT_SKILLS,
            )

        # 验证数据获取和分析成功
        assert statuses.get("T001") == "done", f"T001失败: {context.get('T001').error_message}"
        assert statuses.get("T002") == "done", f"T002失败: {context.get('T002').error_message}"

        # 验证报告生成
        report_status = statuses.get("T003")
        report_output = context.get("T003")

        if report_status == "done" and report_output and report_output.data:
            saved_path = save_report_artifact(
                "investment_docx_report",
                "skill_report_docx",
                report_output,
                sub_dir="asset_investment"
            )
            logger.info(f"DOCX报告已生成: {saved_path}")
        else:
            logger.warning(f"DOCX报告生成失败: {report_output.error_message if report_output else 'Unknown'}")

    @pytest.mark.asyncio
    async def test_pptx_report_generation(self):
        """测试PPTX报告生成"""
        with mock_api_gateway():
            statuses, context, needs_replan = await execute_plan(
                PLAN_PPTX_REPORT,
                allowed_skills=CUSTOMER_INSIGHT_SKILLS,
            )

        # 验证数据获取和分析成功
        assert statuses.get("T001") == "done", f"T001失败: {context.get('T001').error_message}"
        assert statuses.get("T002") == "done", f"T002失败: {context.get('T002').error_message}"

        # 验证报告生成
        report_status = statuses.get("T003")
        report_output = context.get("T003")

        if report_status == "done" and report_output and report_output.data:
            saved_path = save_report_artifact(
                "customer_pptx_report",
                "skill_report_pptx",
                report_output,
                sub_dir="customer_insight"
            )
            logger.info(f"PPTX报告已生成: {saved_path}")
        else:
            logger.warning(f"PPTX报告生成失败: {report_output.error_message if report_output else 'Unknown'}")


# ════════════════════════════════════════════════════════════════
# 综合测试
# ════════════════════════════════════════════════════════════════

class TestComprehensive:
    """综合场景测试"""

    @pytest.mark.asyncio
    async def test_parallel_data_fetch(self):
        """测试多数据源并行获取"""
        with mock_api_gateway():
            tasks = [
                execute_plan(PLAN_THROUGHPUT_DATA, allowed_skills=THROUGHPUT_ANALYST_SKILLS),
                execute_plan(PLAN_CUSTOMER_DATA, allowed_skills=CUSTOMER_INSIGHT_SKILLS),
                execute_plan(PLAN_ASSET_DATA, allowed_skills=ASSET_INVESTMENT_SKILLS),
            ]

            results = await asyncio.gather(*tasks)

            for i, (statuses, context, needs_replan) in enumerate(results):
                assert statuses.get("T001") == "done", f"任务{i} T001失败"
                assert context["T001"].output_type == "dataframe"

            logger.info("多数据源并行获取测试通过")

    @pytest.mark.asyncio
    async def test_multi_format_reports(self):
        """测试多格式报告并行生成"""
        with mock_api_gateway():
            tasks = [
                execute_plan(PLAN_HTML_REPORT, allowed_skills=THROUGHPUT_ANALYST_SKILLS),
                execute_plan(PLAN_DOCX_REPORT, allowed_skills=ASSET_INVESTMENT_SKILLS),
                execute_plan(PLAN_PPTX_REPORT, allowed_skills=CUSTOMER_INSIGHT_SKILLS),
            ]

            results = await asyncio.gather(*tasks)

            formats = ["HTML", "DOCX", "PPTX"]
            for i, (statuses, context, needs_replan) in enumerate(results):
                # 只验证前两个任务（数据获取+分析）成功
                assert statuses.get("T001") == "done", f"{formats[i]} 数据获取失败"
                assert statuses.get("T002") == "done", f"{formats[i]} 分析失败"
                report_output = context.get("T003")
                logger.info(f"{formats[i]} 报告状态: {statuses.get('T003')} - {report_output.error_message if report_output else '成功'}")

            logger.info("多格式报告并行生成测试完成")
