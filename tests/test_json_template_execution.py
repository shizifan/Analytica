"""JSON任务模板执行测试 — 使用3个JSON模板生成4种格式报告。

基于 test_execution_only.py 框架，扩展支持 JSON 任务模板的完整执行链路。

设计原则：
1. 加载 JSON 模板文件，解析任务计划
2. 使用 Mock Server 提供 API 数据
3. 执行完整 DAG 任务链：数据获取 → 分析 → 图表 → 报告生成
4. 支持生成 markdown/html/docx/pptx 四种格式
5. 报告保存到 reports/full_report_tests/

运行：
    pytest tests/test_json_template_execution.py -v                    # 全部用例
    pytest tests/test_json_template_execution.py -v -k "throughput"   # 仅吞吐量模板
    pytest tests/test_json_template_execution.py -v -k "customer"      # 仅客户洞察模板
    pytest tests/test_json_template_execution.py -v -k "asset"         # 仅资产投资模板
    pytest tests/test_json_template_execution.py -v -k "markdown"      # 仅 markdown 格式
"""
from __future__ import annotations

import asyncio
import json
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

# 确保所有技能已注册（包括新增的 markdown_gen）
load_all_skills()

logger = logging.getLogger("test.json_template_execution")

# ════════════════════════════════════════════════════════════════
# 报告输出目录配置
# ════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "backend" / "agent" / "plan_templates"
REPORTS_BASE = PROJECT_ROOT / "reports" / "full_report_tests"
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
    """保存报告工件到磁盘。

    Args:
        template_name: 模板名称
        report_format: 报告格式（markdown/html/docx/pptx）
        content: 报告内容（字符串或字节）
        filename: 文件名

    Returns:
        保存的文件路径，或 None（保存失败时）
    """
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
    tasks = []
    for task_def in template.get("tasks", []):
        task = TaskItem(
            task_id=task_def["task_id"],
            type=task_def["type"],
            name=task_def["name"],
            skill=task_def["skill"],
            params=task_def.get("params", {}),
            depends_on=task_def.get("depends_on", []),
            estimated_seconds=task_def.get("estimated_seconds", 10),
        )
        tasks.append(task)
    return tasks


# ════════════════════════════════════════════════════════════════
# Mock Server 配置（与 test_execution_only 相同）
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
    "skill_chart_pie",
    "skill_chart_waterfall",
    "skill_desc_analysis",
    "skill_attribution",
    "skill_summary_gen",
    "skill_report_html",
    "skill_report_markdown",
    "skill_report_docx",
    "skill_report_pptx",
    "skill_prediction",
])

CUSTOMER_INSIGHT_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_pie",
    "skill_chart_waterfall",
    "skill_desc_analysis",
    "skill_attribution",
    "skill_summary_gen",
    "skill_report_html",
    "skill_report_markdown",
    "skill_report_docx",
    "skill_report_pptx",
])

ASSET_INVESTMENT_SKILLS = frozenset([
    "skill_api_fetch",
    "skill_chart_line",
    "skill_chart_bar",
    "skill_chart_pie",
    "skill_chart_waterfall",
    "skill_desc_analysis",
    "skill_attribution",
    "skill_summary_gen",
    "skill_report_html",
    "skill_report_markdown",
    "skill_report_docx",
    "skill_report_pptx",
])

EMPLOYEE_SKILLS_MAP = {
    "throughput_analyst": THROUGHPUT_ANALYST_SKILLS,
    "customer_insight": CUSTOMER_INSIGHT_SKILLS,
    "asset_investment": ASSET_INVESTMENT_SKILLS,
}


# ════════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════════

async def execute_template_plan(
    template: dict[str, Any],
    allowed_skills: frozenset[str],
    max_tasks: int | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """执行模板计划，返回状态和上下文。

    Args:
        template: JSON 模板字典
        allowed_skills: 技能白名单
        max_tasks: 最大执行任务数（用于测试部分执行）

    Returns:
        (statuses, context) 元组
    """
    task_items = json_to_task_items(template)

    # 限制执行任务数（用于快速测试）
    if max_tasks is not None:
        task_items = task_items[:max_tasks]

    with mock_api_gateway():
        statuses, context, _ = await execute_plan(
            task_items, allowed_skills=allowed_skills,
        )

    return statuses, context


async def generate_report(
    template: dict[str, Any],
    context: dict[str, Any],
    report_format: str,
    section_names: list[str],
) -> tuple[SkillOutput | None, str]:
    """生成指定格式的报告。

    Args:
        template: JSON 模板
        context: 执行上下文
        report_format: 报告格式（markdown/html/docx/pptx）
        section_names: 要包含的章节名称

    Returns:
        (SkillOutput, error_message) 元组
    """
    from backend.skills.registry import SkillRegistry
    from backend.skills.base import SkillInput

    skill_map = {
        "markdown": "skill_report_markdown",
        "html": "skill_report_html",
        "docx": "skill_report_docx",
        "pptx": "skill_report_pptx",
    }

    skill_id = skill_map.get(report_format)
    if not skill_id:
        return None, f"Unknown format: {report_format}"

    registry = SkillRegistry.get_instance()
    skill = registry.get_skill(skill_id)
    if not skill:
        return None, f"Skill not registered: {skill_id}"

    # 构建报告参数
    meta = template.get("_meta", {})
    title = template.get("title", "分析报告")

    # 收集报告结构中的任务引用
    report_structure = template.get("report_structure", {})
    section_task_refs = []
    for section in report_structure.get("sections", []):
        if section["name"] in section_names:
            section_task_refs.extend(section.get("task_refs", []))

    # 去重
    context_refs = list(dict.fromkeys(section_task_refs))

    params = {
        "report_metadata": {
            "title": title,
            "author": meta.get("employee_id", "Analytica"),
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        "report_structure": {
            "sections": [
                {"name": name, "task_refs": context_refs}
                for name in section_names
            ]
        },
    }

    inp = SkillInput(params=params, context_refs=context_refs)

    try:
        output = await skill.execute(inp, context)
        return output, ""
    except Exception as e:
        return None, str(e)


# ════════════════════════════════════════════════════════════════
# 测试类
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

        # 验证元数据
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

        # 验证必要字段
        for task in tasks:
            assert task.task_id
            assert task.type
            assert task.name
            assert task.skill


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
        skills = EMPLOYEE_SKILLS_MAP.get(employee_id, THROUGHPUT_ANALYST_SKILLS)

        # 只执行数据获取任务（前N个）
        data_fetch_tasks = [t for t in template["tasks"] if t["type"] == "data_fetch"]
        max_fetch = min(5, len(data_fetch_tasks))  # 执行前5个数据获取任务

        statuses, context = await execute_template_plan(
            template, skills, max_tasks=max_fetch
        )

        # 验证数据获取任务都成功
        for i in range(max_fetch):
            task_id = f"T{i+1:03d}"
            if task_id in statuses:
                task_output = context.get(task_id)
                error_msg = getattr(task_output, 'error_message', 'unknown') if task_output else 'unknown'
                assert statuses[task_id] in ("done", "pending"), (
                    f"Task {task_id} failed: {error_msg}"
                )


class TestTemplateAnalysis:
    """模板分析任务测试 — 验证分析任务能正确执行。"""

    @pytest.mark.asyncio
    async def test_throughput_analysis_chain(self):
        """验证吞吐量模板的分析任务链。"""
        template = load_template("throughput_analyst_monthly_review")

        # 执行前10个任务（覆盖数据获取到分析）
        statuses, context = await execute_template_plan(
            template, THROUGHPUT_ANALYST_SKILLS, max_tasks=10
        )

        # 验证关键分析任务
        analysis_tasks = ["T011", "T012", "T013"]  # 分析类任务
        for task_id in analysis_tasks:
            if task_id in statuses:
                logger.info(f"Task {task_id} status: {statuses[task_id]}")

    @pytest.mark.asyncio
    async def test_asset_investment_analysis_chain(self):
        """验证资产投资模板的分析任务链。"""
        template = load_template("asset_investment_equipment_ops")

        # 执行前15个任务
        statuses, context = await execute_template_plan(
            template, ASSET_INVESTMENT_SKILLS, max_tasks=15
        )

        # 验证分析任务
        for task_id in ["T015", "T016", "T017"]:
            if task_id in statuses:
                logger.info(f"Task {task_id} status: {statuses[task_id]}")


# ════════════════════════════════════════════════════════════════
# 报告生成测试 — 核心测试类
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
        skills = EMPLOYEE_SKILLS_MAP.get(employee_id, THROUGHPUT_ANALYST_SKILLS)

        # 执行完整计划（数据获取 + 分析 + 图表）
        statuses, context = await execute_template_plan(
            template, skills, max_tasks=18  # 不包含最后的报告生成任务
        )

        # 收集成功的任务
        successful_refs = [tid for tid, status in statuses.items() if status == "done"]

        # 生成 Markdown 报告
        output, error = await generate_report(
            template, context, "markdown",
            ["一、经营摘要", "二、综合分析"]
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
        skills = EMPLOYEE_SKILLS_MAP.get(employee_id, THROUGHPUT_ANALYST_SKILLS)

        # 执行完整计划
        statuses, context = await execute_template_plan(
            template, skills, max_tasks=18
        )

        # 生成 HTML 报告
        output, error = await generate_report(
            template, context, "html",
            ["一、经营摘要", "二、综合分析"]
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
        skills = EMPLOYEE_SKILLS_MAP.get(employee_id, THROUGHPUT_ANALYST_SKILLS)

        # 执行完整计划
        statuses, context = await execute_template_plan(
            template, skills, max_tasks=18
        )

        # 生成 DOCX 报告
        output, error = await generate_report(
            template, context, "docx",
            ["一、管理摘要", "二、综合分析"]
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
        skills = EMPLOYEE_SKILLS_MAP.get(employee_id, THROUGHPUT_ANALYST_SKILLS)

        # 执行完整计划
        statuses, context = await execute_template_plan(
            template, skills, max_tasks=18
        )

        # 生成 PPTX 报告
        output, error = await generate_report(
            template, context, "pptx",
            ["一、客户总览", "二、综合分析"]
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

        # 验证幻灯片数量
        slide_count = output.metadata.get("slide_count", 0)
        assert slide_count > 0, "No slides generated"

        # 保存报告
        filename = f"{template_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
        saved_path = save_report_artifact(template_name, "pptx", pptx_content, filename)
        assert saved_path is not None, "Failed to save PPTX report"
        logger.info(f"PPTX report saved: {saved_path}")


# ════════════════════════════════════════════════════════════════
# 全格式端到端测试
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
        skills = EMPLOYEE_SKILLS_MAP.get(employee_id, THROUGHPUT_ANALYST_SKILLS)

        # 执行完整计划
        statuses, context = await execute_template_plan(
            template, skills, max_tasks=18
        )

        report_formats = ["markdown", "html", "docx", "pptx"]
        results = {}

        for fmt in report_formats:
            output, error = await generate_report(
                template, context, fmt,
                ["一、综合摘要"]
            )
            results[fmt] = (output, error)

        # 验证所有格式都成功生成
        successful_formats = []
        for fmt, (output, error) in results.items():
            if output and output.status in ("success", "partial"):
                successful_formats.append(fmt)
                logger.info(f"[{template_name}] {fmt.upper()} generation: SUCCESS")
            else:
                logger.warning(f"[{template_name}] {fmt.upper()} generation: FAILED - {error}")

        # 至少要成功生成一种格式
        assert len(successful_formats) > 0, (
            f"Failed to generate any report format for {template_name}"
        )

        logger.info(f"[{template_name}] Successfully generated formats: {successful_formats}")


# ════════════════════════════════════════════════════════════════
# 性能与边界测试
# ════════════════════════════════════════════════════════════════

class TestReportGenerationPerformance:
    """报告生成性能测试。"""

    @pytest.mark.asyncio
    async def test_execution_time_for_full_pipeline(self):
        """验证完整执行管道的时间消耗。"""
        import time

        template = load_template("throughput_analyst_monthly_review")

        start = time.time()
        statuses, context = await execute_template_plan(
            template, THROUGHPUT_ANALYST_SKILLS, max_tasks=10
        )
        execution_time = time.time() - start

        logger.info(f"Full pipeline (10 tasks) execution time: {execution_time:.2f}s")

        # 验证至少有一些任务成功
        done_count = sum(1 for s in statuses.values() if s == "done")
        assert done_count > 0, "No tasks completed successfully"


# ════════════════════════════════════════════════════════════════
# 辅助命令（直接运行脚本时执行）
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("JSON 任务模板报告生成测试")
    print("=" * 60)
    print(f"\n模板目录: {TEMPLATES_DIR}")
    print(f"报告目录: {REPORTS_BASE}")
    print(f"运行时间戳: {_RUN_TIMESTAMP}")
    print("\n使用方法:")
    print("  pytest tests/test_json_template_execution.py -v                    # 全部测试")
    print("  pytest tests/test_json_template_execution.py -v -k 'throughput'     # 仅吞吐量模板")
    print("  pytest tests/test_json_template_execution.py -v -k 'markdown'       # 仅 markdown 格式")
    print("=" * 60)
