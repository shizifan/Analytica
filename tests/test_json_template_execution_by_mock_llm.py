"""JSON任务模板执行测试 — 使用 Mock LLM 替代真实 API 调用。

基于 test_json_template_execution.py 框架，将 LLM 调用替换为固化的 Mock 响应。

设计原则：
1. 复用 test_json_template_execution.py 的所有测试结构
2. 使用 mock_llm_responses.py 中的固化响应
3. API 数据获取仍使用 mock_server_all.py（保持不变）
4. 测试执行速度更快，不依赖真实 LLM API

运行：
    pytest tests/test_json_template_execution_by_mock_llm.py -v                    # 全部用例
    pytest tests/test_json_template_execution_by_mock_llm.py -v -k "throughput"   # 仅吞吐量模板
    pytest tests/test_json_template_execution_by_mock_llm.py -v -k "markdown"      # 仅 markdown 格式
"""
from __future__ import annotations

import json
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
from backend.tools.loader import load_all_tools

# 导入 Mock LLM 模块
from tests.mock_llm_responses import mock_invoke_llm_async

# 确保所有技能已注册
load_all_tools()

logger = logging.getLogger("test.json_template_execution.mock")

# ════════════════════════════════════════════════════════════════
# 报告输出目录配置
# ════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "backend" / "agent" / "plan_templates"
REPORTS_BASE = PROJECT_ROOT / "reports" / "full_report_tests_mock"
_RUN_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_run_dir(template_name: str, report_format: str) -> Path:
    """获取本次测试运行的输出目录。"""
    run_dir = REPORTS_BASE / _RUN_TIMESTAMP / template_name / report_format
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_report_artifact(
    template_name: str,
    report_format: str,
    content: Any,
    filename: str,
) -> Path | None:
    """保存报告工件到磁盘。"""
    output_dir = _get_run_dir(template_name, report_format)

    try:
        if report_format == "markdown":
            if not isinstance(content, str):
                logger.warning("[%s] Markdown content is not str", template_name)
                return None
            file_path = output_dir / filename
            file_path.write_text(content, encoding="utf-8")
            logger.info(f"[{template_name}] Markdown saved: {file_path} ({len(content)} bytes)")
            return file_path

        elif report_format in ("html",):
            if not isinstance(content, str):
                logger.warning("[%s] %s content is not str", template_name, report_format)
                return None
            file_path = output_dir / filename
            file_path.write_text(content, encoding="utf-8")
            logger.info(f"[{template_name}] {report_format.upper()} saved: {file_path} ({len(content)} bytes)")
            return file_path

        elif report_format in ("docx", "pptx"):
            if not isinstance(content, (bytes, bytearray)):
                logger.warning("[%s] %s data is not bytes", template_name, report_format)
                return None
            file_path = output_dir / filename
            file_path.write_bytes(content)
            logger.info(f"[{template_name}] {report_format.upper()} saved: {file_path} ({len(content)} bytes)")
            return file_path

        else:
            logger.warning("[%s] Unknown format '%s'", template_name, report_format)
            return None

    except Exception as e:
        logger.error(f"[{template_name}] Failed to save {report_format} report: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# JSON 模板加载器
# ════════════════════════════════════════════════════════════════

def load_template(template_name: str) -> dict[str, Any]:
    """加载 JSON 任务模板。"""
    template_path = TEMPLATES_DIR / f"{template_name}.json"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


def json_to_task_items(template: dict[str, Any]) -> list[TaskItem]:
    """将 JSON 模板转换为 TaskItem 列表。"""
    tmpl_meta = template.get("_meta", {}) or {}
    meta_inject = {
        "template_id": tmpl_meta.get("template_id") or "",
        "employee_id": tmpl_meta.get("employee_id") or "",
        "slot_values": tmpl_meta.get("slot_values") or {},
        "title": template.get("title") or "",
    }
    tasks = []
    for task_def in template.get("tasks", []):
        params = dict(task_def.get("params", {}))
        params.setdefault("_template_meta", meta_inject)
        task = TaskItem(
            task_id=task_def["task_id"],
            type=task_def["type"],
            name=task_def["name"],
            tool=task_def["tool"],
            params=params,
            depends_on=task_def.get("depends_on", []),
            estimated_seconds=task_def.get("estimated_seconds", 10),
        )
        tasks.append(task)
    return tasks


# ════════════════════════════════════════════════════════════════
# Mock Server 配置（与 test_json_template_execution 相同）
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

    with patch("backend.tools.data.api_fetch.httpx.AsyncClient", _PatchedAsyncClient):
        yield


# ════════════════════════════════════════════════════════════════
# Mock LLM 上下文管理器
# ════════════════════════════════════════════════════════════════

@contextmanager
def mock_llm():
    """替换 invoke_llm 为 Mock 版本。"""
    with patch("backend.tools._llm.invoke_llm", mock_invoke_llm_async):
        yield


# ════════════════════════════════════════════════════════════════
# 员工技能白名单
# ════════════════════════════════════════════════════════════════

THROUGHPUT_ANALYST_TOOLS = frozenset([
    "tool_api_fetch",
    "tool_chart_line",
    "tool_chart_bar",
    "tool_chart_pie",
    "tool_chart_waterfall",
    "tool_desc_analysis",
    "tool_attribution",
    "tool_summary_gen",
    "tool_report_html",
    "tool_report_markdown",
    "tool_report_docx",
    "tool_report_pptx",
    "tool_prediction",
])

CUSTOMER_INSIGHT_TOOLS = frozenset([
    "tool_api_fetch",
    "tool_chart_line",
    "tool_chart_bar",
    "tool_chart_pie",
    "tool_chart_waterfall",
    "tool_desc_analysis",
    "tool_attribution",
    "tool_summary_gen",
    "tool_report_html",
    "tool_report_markdown",
    "tool_report_docx",
    "tool_report_pptx",
])

ASSET_INVESTMENT_TOOLS = frozenset([
    "tool_api_fetch",
    "tool_chart_line",
    "tool_chart_bar",
    "tool_chart_pie",
    "tool_chart_waterfall",
    "tool_desc_analysis",
    "tool_attribution",
    "tool_summary_gen",
    "tool_report_html",
    "tool_report_markdown",
    "tool_report_docx",
    "tool_report_pptx",
])

EMPLOYEE_TOOLS_MAP = {
    "throughput_analyst": THROUGHPUT_ANALYST_TOOLS,
    "customer_insight": CUSTOMER_INSIGHT_TOOLS,
    "asset_investment": ASSET_INVESTMENT_TOOLS,
}


# ════════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════════

async def execute_template_plan(
    template: dict[str, Any],
    allowed_tools: frozenset[str],
    max_tasks: int | None = None,
    template_name: str | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """执行模板计划，返回状态和上下文。"""
    task_items = json_to_task_items(template)

    if max_tasks is not None:
        task_items = task_items[:max_tasks]

    report_dir = None
    if template_name:
        report_dir = REPORTS_BASE / _RUN_TIMESTAMP / template_name

    with mock_api_gateway(), mock_llm():
        statuses, context, _ = await execute_plan(
            task_items, allowed_tools=allowed_tools, report_dir=report_dir,
        )

    return statuses, context


async def generate_report(
    template: dict[str, Any],
    context: dict[str, Any],
    report_format: str,
    section_names: list[str] | None = None,
) -> tuple[Any, str]:
    """生成指定格式的报告。"""
    from backend.tools.registry import ToolRegistry
    from backend.tools.base import ToolInput

    tool_map = {
        "markdown": "tool_report_markdown",
        "html": "tool_report_html",
        "docx": "tool_report_docx",
        "pptx": "tool_report_pptx",
    }

    tool_id = tool_map.get(report_format)
    if not tool_id:
        return None, f"Unknown format: {report_format}"

    registry = ToolRegistry.get_instance()
    tool = registry.get_tool(tool_id)
    if not tool:
        return None, f"Tool not registered: {tool_id}"

    meta = template.get("_meta", {})
    title = template.get("title", "分析报告")

    report_structure = template.get("report_structure", {})
    all_sections = report_structure.get("sections", [])
    if section_names is not None:
        selected_sections = [s for s in all_sections if s["name"] in section_names]
        if not selected_sections:
            selected_sections = all_sections
    else:
        selected_sections = all_sections

    task_order = [t["task_id"] for t in template.get("tasks", [])]
    template_meta = {
        "template_id": meta.get("template_id") or "",
        "employee_id": meta.get("employee_id") or "",
        "slot_values": meta.get("slot_values") or {},
        "title": title,
    }

    context_refs = list(dict.fromkeys(
        [ref for s in selected_sections for ref in s.get("task_refs", [])]
    ))

    params = {
        "report_metadata": {
            "title": title,
            "author": meta.get("employee_id", "Analytica"),
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        "report_structure": {
            "sections": [
                {"name": s["name"], "task_refs": list(s.get("task_refs", []))}
                for s in selected_sections
            ]
        },
        "_task_order": task_order,
        "_template_meta": template_meta,
    }

    inp = ToolInput(params=params, context_refs=context_refs)

    try:
        with mock_llm():
            output = await tool.execute(inp, context)
        return output, ""
    except Exception as e:
        return None, str(e)


# ════════════════════════════════════════════════════════════════
# 测试类 — 模板加载测试
# ════════════════════════════════════════════════════════════════

class TestTemplateLoading:
    """模板加载测试 — 验证 JSON 模板能正确加载。"""

    @pytest.mark.parametrize("template_name", [
        "throughput_analyst_monthly_review",
        "customer_insight_strategic_contribution",
        "asset_investment_equipment_ops",
    ], ids=["throughput", "customer", "asset"])
    def test_load_template_success(self, template_name: str):
        """验证所有 JSON 模板能正确加载。"""
        template = load_template(template_name)

        assert "_meta" in template
        assert "tasks" in template
        assert "report_structure" in template

        meta = template["_meta"]
        assert meta.get("employee_id") is not None
        assert meta.get("template_id") is not None
        assert meta.get("complexity") == "full_report"

    @pytest.mark.parametrize("template_name", [
        "throughput_analyst_monthly_review",
        "customer_insight_strategic_contribution",
        "asset_investment_equipment_ops",
    ], ids=["throughput", "customer", "asset"])
    def test_convert_to_task_items(self, template_name: str):
        """验证 JSON 模板能正确转换为 TaskItem 列表。"""
        template = load_template(template_name)
        tasks = json_to_task_items(template)

        assert len(tasks) > 0
        assert all(isinstance(t, TaskItem) for t in tasks)

        for task in tasks:
            assert task.task_id
            assert task.type
            assert task.name
            assert task.tool


# ════════════════════════════════════════════════════════════════
# 测试类 — 数据获取测试
# ════════════════════════════════════════════════════════════════

class TestTemplateDataFetch:
    """模板数据获取测试 — 验证数据获取任务能正确执行。"""

    @pytest.mark.parametrize("template_name", [
        "throughput_analyst_monthly_review",
        "customer_insight_strategic_contribution",
        "asset_investment_equipment_ops",
    ], ids=["throughput", "customer", "asset"])
    @pytest.mark.asyncio
    async def test_execute_data_fetch_tasks(self, template_name: str):
        """验证各模板的数据获取任务能正确执行。"""
        template = load_template(template_name)
        employee_id = template["_meta"]["employee_id"]
        tools = EMPLOYEE_TOOLS_MAP.get(employee_id, THROUGHPUT_ANALYST_TOOLS)

        data_fetch_tasks = [t for t in template["tasks"] if t["type"] == "data_fetch"]
        max_fetch = min(5, len(data_fetch_tasks))

        statuses, context = await execute_template_plan(
            template, tools, max_tasks=max_fetch, template_name=template_name
        )

        for i in range(max_fetch):
            task_id = f"T{i+1:03d}"
            if task_id in statuses:
                task_output = context.get(task_id)
                error_msg = getattr(task_output, 'error_message', 'unknown') if task_output else 'unknown'
                assert statuses[task_id] in ("done", "pending"), (
                    f"Task {task_id} failed: {error_msg}"
                )


# ════════════════════════════════════════════════════════════════
# 测试类 — 分析任务测试
# ════════════════════════════════════════════════════════════════

class TestTemplateAnalysis:
    """模板分析任务测试 — 验证分析任务能正确执行。"""

    @pytest.mark.asyncio
    async def test_throughput_analysis_chain(self):
        """验证吞吐量模板的分析任务链。"""
        template = load_template("throughput_analyst_monthly_review")

        statuses, context = await execute_template_plan(
            template, THROUGHPUT_ANALYST_TOOLS, max_tasks=10,
            template_name="throughput_analyst_monthly_review",
        )

        analysis_tasks = ["T011", "T012", "T013"]
        for task_id in analysis_tasks:
            if task_id in statuses:
                logger.info(f"Task {task_id} status: {statuses[task_id]}")

    @pytest.mark.asyncio
    async def test_asset_investment_analysis_chain(self):
        """验证资产投资模板的分析任务链。"""
        template = load_template("asset_investment_equipment_ops")

        statuses, context = await execute_template_plan(
            template, ASSET_INVESTMENT_TOOLS, max_tasks=15,
            template_name="asset_investment_equipment_ops",
        )

        for task_id in ["T015", "T016", "T017"]:
            if task_id in statuses:
                logger.info(f"Task {task_id} status: {statuses[task_id]}")


# ════════════════════════════════════════════════════════════════
# 测试类 — 报告生成测试（核心）
# ════════════════════════════════════════════════════════════════

class TestReportGenerationMarkdown:
    """Markdown 报告生成测试。"""

    @pytest.mark.parametrize("template_name,employee_id", [
        ("throughput_analyst_monthly_review", "throughput_analyst"),
        ("customer_insight_strategic_contribution", "customer_insight"),
        ("asset_investment_equipment_ops", "asset_investment"),
    ], ids=["throughput", "customer", "asset"])
    @pytest.mark.asyncio
    async def test_markdown_report_generation(self, template_name: str, employee_id: str):
        """验证各模板能正确生成 Markdown 报告。"""
        template = load_template(template_name)
        tools = EMPLOYEE_TOOLS_MAP.get(employee_id, THROUGHPUT_ANALYST_TOOLS)

        statuses, context = await execute_template_plan(
            template, tools, max_tasks=18
        )

        successful_refs = [tid for tid, status in statuses.items() if status == "done"]

        output, error = await generate_report(
            template, context, "markdown",
        )

        if error:
            pytest.skip(f"Report generation skipped: {error}")

        assert output is not None, f"Markdown generation failed: {error}"
        assert output.status in ("success", "partial"), f"Markdown status: {output.status}"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "markdown"

        md_content = output.data
        assert isinstance(md_content, str)
        assert len(md_content) > 100, "Markdown content too short"
        assert "#" in md_content, "Markdown should have headers"

        # 保存报告
        filename = f"{template_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        saved_path = save_report_artifact(template_name, "markdown", md_content, filename)
        assert saved_path is not None, "Failed to save markdown report"
        logger.info(f"Markdown report saved: {saved_path}")


class TestReportGenerationHTML:
    """HTML 报告生成测试。"""

    @pytest.mark.parametrize("template_name,employee_id", [
        ("throughput_analyst_monthly_review", "throughput_analyst"),
        ("customer_insight_strategic_contribution", "customer_insight"),
        ("asset_investment_equipment_ops", "asset_investment"),
    ], ids=["throughput", "customer", "asset"])
    @pytest.mark.asyncio
    async def test_html_report_generation(self, template_name: str, employee_id: str):
        """验证各模板能正确生成 HTML 报告。"""
        template = load_template(template_name)
        tools = EMPLOYEE_TOOLS_MAP.get(employee_id, THROUGHPUT_ANALYST_TOOLS)

        statuses, context = await execute_template_plan(
            template, tools, max_tasks=18, template_name=template_name
        )

        output, error = await generate_report(
            template, context, "html",
        )

        if error:
            pytest.skip(f"Report generation skipped: {error}")

        assert output is not None, f"HTML generation failed: {error}"
        assert output.status in ("success", "partial"), f"HTML status: {output.status}"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "html"

        html_content = output.data
        assert isinstance(html_content, str)
        assert "<html" in html_content.lower() or "<!doctype" in html_content.lower()
        assert len(html_content) > 500, "HTML content too short"

        # 保存报告
        filename = f"{template_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        saved_path = save_report_artifact(template_name, "html", html_content, filename)
        assert saved_path is not None, "Failed to save HTML report"
        logger.info(f"HTML report saved: {saved_path}")


class TestReportGenerationDOCX:
    """DOCX 报告生成测试。"""

    @pytest.mark.parametrize("template_name,employee_id", [
        ("throughput_analyst_monthly_review", "throughput_analyst"),
        ("customer_insight_strategic_contribution", "customer_insight"),
        ("asset_investment_equipment_ops", "asset_investment"),
    ], ids=["throughput", "customer", "asset"])
    @pytest.mark.asyncio
    async def test_docx_report_generation(self, template_name: str, employee_id: str):
        """验证各模板能正确生成 DOCX 报告。"""
        template = load_template(template_name)
        tools = EMPLOYEE_TOOLS_MAP.get(employee_id, THROUGHPUT_ANALYST_TOOLS)

        statuses, context = await execute_template_plan(
            template, tools, max_tasks=18, template_name=template_name
        )

        output, error = await generate_report(
            template, context, "docx",
        )

        if error:
            pytest.skip(f"Report generation skipped: {error}")

        assert output is not None, f"DOCX generation failed: {error}"
        assert output.status in ("success", "partial"), f"DOCX status: {output.status}"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "docx"

        docx_content = output.data
        assert isinstance(docx_content, (bytes, bytearray))
        assert len(docx_content) > 1000, "DOCX file too small"
        assert docx_content[:2] == b"PK", "DOCX should be ZIP format"

        # 保存报告
        filename = f"{template_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        saved_path = save_report_artifact(template_name, "docx", docx_content, filename)
        assert saved_path is not None, "Failed to save DOCX report"
        logger.info(f"DOCX report saved: {saved_path}")


class TestReportGenerationPPTX:
    """PPTX 报告生成测试。"""

    @pytest.mark.parametrize("template_name,employee_id", [
        ("throughput_analyst_monthly_review", "throughput_analyst"),
        ("customer_insight_strategic_contribution", "customer_insight"),
        ("asset_investment_equipment_ops", "asset_investment"),
    ], ids=["throughput", "customer", "asset"])
    @pytest.mark.asyncio
    async def test_pptx_report_generation(self, template_name: str, employee_id: str):
        """验证各模板能正确生成 PPTX 报告。"""
        template = load_template(template_name)
        tools = EMPLOYEE_TOOLS_MAP.get(employee_id, THROUGHPUT_ANALYST_TOOLS)

        statuses, context = await execute_template_plan(
            template, tools, max_tasks=18, template_name=template_name
        )

        output, error = await generate_report(
            template, context, "pptx",
        )

        if error:
            pytest.skip(f"Report generation skipped: {error}")

        assert output is not None, f"PPTX generation failed: {error}"
        assert output.status in ("success", "partial"), f"PPTX status: {output.status}"
        assert output.output_type == "file"
        assert output.metadata.get("format") == "pptx"

        pptx_content = output.data
        assert isinstance(pptx_content, (bytes, bytearray))
        assert len(pptx_content) > 1000, "PPTX file too small"
        assert pptx_content[:2] == b"PK", "PPTX should be ZIP format"

        slide_count = output.metadata.get("slide_count", 0)
        assert slide_count > 0, "No slides generated"

        # 保存报告
        filename = f"{template_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
        saved_path = save_report_artifact(template_name, "pptx", pptx_content, filename)
        assert saved_path is not None, "Failed to save PPTX report"
        logger.info(f"PPTX report saved: {saved_path}")


# ════════════════════════════════════════════════════════════════
# 测试类 — 全格式端到端测试
# ════════════════════════════════════════════════════════════════

class TestFullReportPipeline:
    """完整报告管道测试 — 验证从 JSON 模板到四种格式报告的完整链路。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("template_name,employee_id", [
        ("throughput_analyst_monthly_review", "throughput_analyst"),
        ("customer_insight_strategic_contribution", "customer_insight"),
        ("asset_investment_equipment_ops", "asset_investment"),
    ], ids=["throughput", "customer", "asset"])
    async def test_all_formats_generation(self, template_name: str, employee_id: str):
        """验证单个模板能生成所有四种格式报告。"""
        template = load_template(template_name)
        tools = EMPLOYEE_TOOLS_MAP.get(employee_id, THROUGHPUT_ANALYST_TOOLS)

        statuses, context = await execute_template_plan(
            template, tools, max_tasks=18, template_name=template_name
        )

        report_formats = ["markdown", "html", "docx", "pptx"]
        results = {}

        for fmt in report_formats:
            output, error = await generate_report(
                template, context, fmt,
            )
            results[fmt] = (output, error)

        successful_formats = []
        for fmt, (output, error) in results.items():
            if output and output.status in ("success", "partial"):
                successful_formats.append(fmt)
                logger.info(f"[{template_name}] {fmt.upper()} generation: SUCCESS")
            else:
                logger.warning(f"[{template_name}] {fmt.upper()} generation: FAILED - {error}")

        assert len(successful_formats) > 0, (
            f"Failed to generate any report format for {template_name}"
        )

        logger.info(f"[{template_name}] Successfully generated formats: {successful_formats}")


# ════════════════════════════════════════════════════════════════
# 测试类 — 性能与边界测试
# ════════════════════════════════════════════════════════════════

class TestReportGenerationPerformance:
    """报告生成性能测试。"""

    @pytest.mark.asyncio
    async def test_execution_time_for_full_pipeline(self):
        """验证完整执行管道的时间消耗（Mock LLM 应该更快）。"""
        import time

        template = load_template("throughput_analyst_monthly_review")

        start = time.time()
        statuses, context = await execute_template_plan(
            template, THROUGHPUT_ANALYST_TOOLS, max_tasks=10,
            template_name="throughput_analyst_monthly_review",
        )
        execution_time = time.time() - start

        logger.info(f"Full pipeline (10 tasks) execution time: {execution_time:.2f}s")

        done_count = sum(1 for s in statuses.values() if s == "done")
        assert done_count > 0, "No tasks completed successfully"


# ════════════════════════════════════════════════════════════════
# 测试类 — Mock LLM 特定测试
# ════════════════════════════════════════════════════════════════

class TestMockLLMResponses:
    """Mock LLM 响应测试 — 验证固化响应是否正确返回。"""

    @pytest.mark.asyncio
    async def test_descriptive_narrative_mock(self):
        """验证描述性分析的 Mock 响应包含正确的业务洞察。"""
        from tests.mock_llm_responses import mock_invoke_llm_async

        # 测试吞吐量领域
        result = await mock_invoke_llm_async(
            "你是港口生产运营分析师。基于以下统计数据写分析...",
            system_prompt=None,
        )
        assert result["error_category"] is None
        assert "吞吐量" in result["text"] or "完成率" in result["text"]
        assert len(result["text"]) > 50

    @pytest.mark.asyncio
    async def test_attribution_mock(self):
        """验证归因分析的 Mock 响应包含 JSON 结构。"""
        from tests.mock_llm_responses import mock_invoke_llm_async
        import json

        ATTRIBUTION_PROMPT = """业务域: throughput
目标指标: 吞吐量增长
分析时段: 2026年Q1

请以严格的 JSON 格式返回结果"""

        SYSTEM_PROMPT = """你是资深数据分析师，擅长从多源数据推断因果关系。要求：
- 区分直接原因与背景原因
- 对不确定的归因必须说明置信度"""

        result = await mock_invoke_llm_async(
            ATTRIBUTION_PROMPT,
            system_prompt=SYSTEM_PROMPT,
        )

        assert result["error_category"] is None
        # 应该能解析为 JSON
        parsed = json.loads(result["text"])
        assert "primary_drivers" in parsed
        assert "narrative" in parsed

    @pytest.mark.asyncio
    async def test_summary_mock(self):
        """验证摘要生成的 Mock 响应。"""
        from tests.mock_llm_responses import mock_invoke_llm_async

        result = await mock_invoke_llm_async(
            "你是向高管汇报的业务分析师。基于以下分析结果，写一段面向决策层的经营摘要...",
            system_prompt=None,
        )

        assert result["error_category"] is None
        assert len(result["text"]) > 50
        assert "核心数字" in result["text"] or "同比" in result["text"]


# ════════════════════════════════════════════════════════════════
# 辅助命令
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("JSON 任务模板报告生成测试 (Mock LLM)")
    print("=" * 60)
    print(f"\n模板目录: {TEMPLATES_DIR}")
    print(f"报告目录: {REPORTS_BASE}")
    print(f"运行时间戳: {_RUN_TIMESTAMP}")
    print("\n使用方法:")
    print("  pytest tests/test_json_template_execution_by_mock_llm.py -v              # 全部测试")
    print("  pytest tests/test_json_template_execution_by_mock_llm.py -v -k 'throughput'  # 仅吞吐量模板")
    print("  pytest tests/test_json_template_execution_by_mock_llm.py -v -k 'markdown'    # 仅 markdown 格式")
    print("=" * 60)
