"""API Registry — 运行时容器（所有数据来自 DB）。

模块只持有 dataclass 定义、全局索引容器、和 DB → 索引的填充逻辑。
真实数据由 ``data/api_registry.json`` 出厂；通过 ``tools.seed_api_endpoints``
灌入 ``api_endpoints`` / ``domains`` 表；FastAPI 启动时调用
``lifespan_apply_source`` 拉到内存全局变量供运行时使用。

后续运维通过管理平台改 DB，写操作后调用 ``reload_from_db`` 立即生效。

注意:
- import 时全局变量是空的——必须先跑 lifespan 或 reload_from_db 才有数据
- 测试通过 conftest session-scope fixture 自动 seed + reload
- 启动时 DB 空表会 raise（fail-fast，强制部署流程跑过 seed）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("analytica.api_registry")


@dataclass(frozen=True)
class ApiEndpoint:
    """单个 API 端点定义。"""
    name: str           # 主键: 真实 API 函数名, e.g. getWeatherForecast
    path: str           # 完整 API 路径: /api/gateway/getWeatherForecast
    domain: str         # 域代码: D1-D7
    intent: str         # 语义描述（中文）
    time: str           # 时间类型: T_RT/T_MON/T_TREND/...
    granularity: str    # 粒度: G_ZONE/G_PORT/G_CMP/...
    tags: tuple[str, ...]      # 语义标签
    required: tuple[str, ...]  # 必填参数
    optional: tuple[str, ...]  # 可选参数
    param_note: str     # 参数说明
    returns: str        # 返回字段说明
    disambiguate: str   # 消歧说明
    # ── 语义增强字段（可选，有默认值）──
    field_schema: tuple[tuple[str, ...], ...] = ()
    # 每元素 3 或 4 项:
    #   3: (字段名, 类型, 含义)
    #   4: (字段名, 类型, 含义, 中文显示名)
    use_cases: tuple[str, ...] = ()
    chain_with: tuple[str, ...] = ()
    analysis_note: str = ""
    method: str = "GET"

    def label_for(self, col_name: str) -> str | None:
        """Return the per-endpoint Chinese label for ``col_name``, or ``None``.

        Looks up this endpoint's ``field_schema`` for a row whose first element
        matches ``col_name`` and returns its 4th element (``label_zh``) when
        present. Returning ``None`` lets callers fall back to the global
        ``_field_labels.col_label()`` map.
        """
        for row in self.field_schema:
            if row and row[0] == col_name and len(row) >= 4 and row[3]:
                return row[3]
        return None


@dataclass(frozen=True)
class DomainInfo:
    """域元信息。"""
    code: str           # D1-D7
    name: str           # 生产运营/市场商务/...
    desc: str           # 域描述
    api_count: int
    top_tags: tuple[str, ...]


# ════════════════════════════════════════════════════════════════
# 运行时容器 — 由 reload_from_db 填充，import 时为空
# ════════════════════════════════════════════════════════════════

DOMAIN_INDEX: dict[str, DomainInfo] = {}
ALL_ENDPOINTS: tuple[ApiEndpoint, ...] = ()

BY_NAME: dict[str, ApiEndpoint] = {}
BY_PATH: dict[str, ApiEndpoint] = {}
BY_DOMAIN: dict[str, list[ApiEndpoint]] = {}
BY_TIME: dict[str, list[ApiEndpoint]] = {}
# Mutable set so reload via _rebuild_derived_indices is visible to
# ``from backend.agent.api_registry import VALID_ENDPOINT_IDS`` callers
# (a frozenset reassignment would only update the module attribute,
# not pinned import references). Same in-place pattern as BY_NAME above.
VALID_ENDPOINT_IDS: set[str] = set()


def _rebuild_derived_indices() -> None:
    """Recompute ``BY_*`` / ``VALID_ENDPOINT_IDS`` from the current
    ``ALL_ENDPOINTS``. All mutations are in place so any ``from ... import``
    pinned references see the new content."""
    BY_NAME.clear()
    BY_PATH.clear()
    BY_DOMAIN.clear()
    BY_TIME.clear()
    VALID_ENDPOINT_IDS.clear()
    for ep in ALL_ENDPOINTS:
        BY_NAME[ep.name] = ep
        BY_PATH[ep.path] = ep
        BY_DOMAIN.setdefault(ep.domain, []).append(ep)
        BY_TIME.setdefault(ep.time, []).append(ep)
        VALID_ENDPOINT_IDS.add(ep.name)


# ════════════════════════════════════════════════════════════════
# DB → 内存装载
# ════════════════════════════════════════════════════════════════

async def reload_from_db(session: Any | None = None) -> tuple[int, int]:
    """Pull endpoints + domains from DB into the in-memory registry.

    Always replaces ``ALL_ENDPOINTS`` and ``DOMAIN_INDEX`` atomically.
    Caller controls the session: pass one in (for fixture/admin reload
    flows), or omit to spin up a one-shot session via the global factory.

    Returns ``(endpoint_count, domain_count)`` actually loaded.

    Raises on DB failure — the registry stays empty rather than silently
    serving stale or partial data.
    """
    global ALL_ENDPOINTS, DOMAIN_INDEX

    from backend.memory import admin_store

    async def _load(db: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        endpoints = await admin_store.list_api_endpoints(db, limit=10_000)
        domains = await admin_store.list_domains(db)
        return endpoints, domains

    if session is None:
        from backend.database import get_session_factory
        factory = get_session_factory()
        async with factory() as db:
            ep_rows, dom_rows = await _load(db)
    else:
        ep_rows, dom_rows = await _load(session)

    rebuilt_eps: list[ApiEndpoint] = []
    for row in ep_rows:
        try:
            rebuilt_eps.append(_endpoint_from_db_row(row))
        except Exception as e:
            logger.warning(
                "[reload_from_db] skipping malformed endpoint %r (%s)",
                row.get("name"), e,
            )

    rebuilt_doms: dict[str, DomainInfo] = {}
    for row in dom_rows:
        try:
            rebuilt_doms[row["code"]] = _domain_from_db_row(row)
        except Exception as e:
            logger.warning(
                "[reload_from_db] skipping malformed domain %r (%s)",
                row.get("code"), e,
            )

    ALL_ENDPOINTS = tuple(rebuilt_eps)
    DOMAIN_INDEX = rebuilt_doms
    _rebuild_derived_indices()
    logger.info(
        "[reload_from_db] loaded %d endpoints + %d domains",
        len(ALL_ENDPOINTS), len(DOMAIN_INDEX),
    )
    return len(ALL_ENDPOINTS), len(DOMAIN_INDEX)


def _endpoint_from_db_row(row: dict[str, Any]) -> ApiEndpoint:
    """DB column names (``time_type`` / ``required_params`` / ...) differ
    from the dataclass — this is the single bridge."""
    return ApiEndpoint(
        name=row["name"],
        path=row["path"],
        domain=row["domain"],
        intent=row.get("intent") or "",
        time=row.get("time_type") or "",
        granularity=row.get("granularity") or "",
        tags=tuple(row.get("tags") or ()),
        required=tuple(row.get("required_params") or ()),
        optional=tuple(row.get("optional_params") or ()),
        param_note=row.get("param_note") or "",
        returns=row.get("returns") or "",
        disambiguate=row.get("disambiguate") or "",
        field_schema=tuple(tuple(r) for r in (row.get("field_schema") or ())),
        use_cases=tuple(row.get("use_cases") or ()),
        chain_with=tuple(row.get("chain_with") or ()),
        analysis_note=row.get("analysis_note") or "",
        method=row.get("method") or "GET",
    )


def _domain_from_db_row(row: dict[str, Any]) -> DomainInfo:
    """``description`` (DB) → ``desc`` (dataclass); ``api_count`` is a
    SUM-computed column from ``admin_store.list_domains``."""
    return DomainInfo(
        code=row["code"],
        name=row["name"],
        desc=row.get("description") or "",
        api_count=int(row.get("api_count") or 0),
        top_tags=tuple(row.get("top_tags") or ()),
    )


async def lifespan_apply_source() -> None:
    """FastAPI lifespan hook — load registry from DB.

    Empty DB or any failure raises immediately. This is intentional:
    a backend running with an empty registry would silently break LLM
    planning, so we'd rather refuse to start and force the operator
    to run ``tools.seed_api_endpoints``.
    """
    ep_count, dom_count = await reload_from_db()
    if ep_count == 0:
        raise RuntimeError(
            "api_endpoints table is empty — run "
            "`uv run python -m tools.seed_api_endpoints` after applying migrations"
        )
    if dom_count == 0:
        raise RuntimeError(
            "domains table is empty — run "
            "`uv run python -m tools.seed_api_endpoints` after applying migrations"
        )
    logger.info(
        "[lifespan] api_registry loaded from DB (%d endpoints, %d domains)",
        ep_count, dom_count,
    )


# ── 槽位 → 注册表维度映射 ──

COMPARISON_TO_TIME: dict[str, set[str]] = {
    "yoy": {"T_YOY"},
    "mom": {"T_MON", "T_YOY"},
    "cumulative": {"T_CUM"},
    "trend": {"T_TREND"},
    "snapshot": {"T_RT"},
    "historical": {"T_HIST"},
    "none": {"T_NONE", "T_YR"},
}

GRANULARITY_MAP: dict[str, str] = {
    "port": "G_PORT",
    "zone": "G_ZONE",
    "company": "G_CMP",
    "customer": "G_CLIENT",
    "equipment": "G_EQUIP",
    "project": "G_PROJ",
    "cargo": "G_CARGO",
    "asset": "G_ASSET",
    "business": "G_BIZ",
}


# ════════════════════════════════════════════════════════════════
# 工具函数 — 调用方通过这些访问 registry，不直接读全局变量
# ════════════════════════════════════════════════════════════════

def resolve_endpoint_id(raw_id: str) -> str | None:
    """验证是否为合法 API 函数名，是则返回，否则 None。"""
    if raw_id in VALID_ENDPOINT_IDS:
        return raw_id
    return None


def get_endpoint(name: str) -> ApiEndpoint | None:
    """按函数名查找端点。"""
    return BY_NAME.get(name)


def get_endpoint_path(name: str) -> str | None:
    """快速获取端点的 API 路径。"""
    ep = BY_NAME.get(name)
    return ep.path if ep else None


def is_valid_endpoint(name: str) -> bool:
    """检查是否为合法端点名。"""
    return name in VALID_ENDPOINT_IDS


def list_endpoints(domain: str | None = None, tags: set[str] | None = None) -> list[ApiEndpoint]:
    """按域或标签筛选端点列表。"""
    result = list(ALL_ENDPOINTS)
    if domain:
        result = [ep for ep in result if ep.domain == domain]
    if tags:
        result = [ep for ep in result if tags & set(ep.tags)]
    return result


def get_endpoints_description(
    domain_hint: str | None = None,
    time_hint: set[str] | None = None,
    granularity_hint: str | None = None,
    max_per_domain: int | None = 8,
    allowed_endpoints: frozenset[str] | None = None,
) -> str:
    """生成 LLM Prompt 注入用的端点描述文本。

    域过滤策略：
    - 有域提示时: 该域全量展示，其他域仅展示摘要
    - 无域提示时: 每域最多展示 max_per_domain 个 API + 摘要

    软筛选策略（time_hint / granularity_hint）：
    - 匹配的端点加 ★ 前缀并优先排列
    - 不隐藏任何端点，仅标注相关性

    硬过滤策略（allowed_endpoints）：
    - 非 None 时，仅保留白名单内的端点，域中无端点的域不显示
    """

    def _ep_matches(ep: ApiEndpoint) -> bool:
        if time_hint and ep.time in time_hint:
            return True
        if granularity_hint and ep.granularity == granularity_hint:
            return True
        return False

    def _semantic_score(ep: ApiEndpoint) -> int:
        """语义完整度评分：field_schema(4) > analysis_note(3) > use_cases(2) > chain_with(1)"""
        return (
            bool(ep.field_schema) * 4 +
            bool(ep.analysis_note) * 3 +
            bool(ep.use_cases) * 2 +
            bool(ep.chain_with) * 1
        )

    has_hints = bool(time_hint or granularity_hint)

    def _format_ep_detail(ep: ApiEndpoint, mark: bool = False) -> str:
        prefix = "★ " if mark else "  - "
        line = f"  {prefix}{ep.name}: {ep.intent}"
        if ep.required:
            line += f"\n    必填参数: {', '.join(ep.required)}"
        if ep.optional:
            line += f"\n    可选参数: {', '.join(ep.optional)}"
        if ep.param_note:
            line += f"\n    参数说明: {ep.param_note}"
        if ep.returns:
            line += f"\n    返回字段: {ep.returns}"
        if ep.field_schema:
            schema_str = " | ".join(f"{row[0]}({row[1]})" for row in ep.field_schema)
            line += f"\n    字段结构: {schema_str}"
        if ep.analysis_note:
            line += f"\n    分析要点: {ep.analysis_note}"
        if ep.use_cases:
            line += "\n    典型用例: " + "; ".join(ep.use_cases)
        if ep.chain_with:
            line += "\n    建议组合: " + ", ".join(ep.chain_with)
        if ep.disambiguate:
            line += f"\n    消歧: {ep.disambiguate}"
        return line

    def _format_ep_condensed(ep: ApiEndpoint) -> str:
        return f"  - {ep.name}: {ep.intent}"

    sections = []

    # 当有白名单时，按域重新分组
    if allowed_endpoints is not None:
        filtered_by_domain: dict[str, list[ApiEndpoint]] = {}
        for code, eps_list in BY_DOMAIN.items():
            filtered = [ep for ep in eps_list if ep.name in allowed_endpoints]
            if filtered:
                filtered_by_domain[code] = filtered
        active_domains = filtered_by_domain
    else:
        active_domains = BY_DOMAIN

    # Always show domain index (only for active domains)
    sections.append("【可用数据域索引】")
    for code in sorted(active_domains):
        di = DOMAIN_INDEX.get(code)
        if di:
            ep_count = len(active_domains[code])
            sections.append(f"  {code} {di.name} ({ep_count}个API): {di.desc}")
    sections.append("")

    for code in sorted(active_domains):
        di = DOMAIN_INDEX.get(code)
        eps = active_domains[code]
        domain_name = di.name if di else code

        if domain_hint and code == domain_hint:
            # Full detail for hinted domain — with soft filtering + semantic sort
            sections.append(f"【{domain_name}域 ({code}, {len(eps)}个API) — 详细】")
            eps_sorted = sorted(eps, key=_semantic_score, reverse=True)
            if has_hints:
                matched = [ep for ep in eps_sorted if _ep_matches(ep)]
                unmatched = [ep for ep in eps_sorted if not _ep_matches(ep)]
                for ep in matched:
                    sections.append(_format_ep_detail(ep, mark=True))
                for ep in unmatched:
                    sections.append(_format_ep_detail(ep, mark=False))
            else:
                for ep in eps_sorted:
                    sections.append(_format_ep_detail(ep))

        elif domain_hint:
            # Summary only for other domains
            desc = di.desc if di else ""
            summary = f"【{domain_name}域 ({code}, {len(eps)}个API) — 摘要: {desc}】"
            if has_hints:
                match_count = sum(1 for ep in eps if _ep_matches(ep))
                if match_count > 0:
                    summary = f"【{domain_name}域 ({code}, {len(eps)}个API, 其中{match_count}个匹配当前查询类型) — 摘要: {desc}】"
            sections.append(summary)

        else:
            # No domain hint — sort by semantic completeness
            sections.append(f"【{domain_name}域 ({code}, {len(eps)}个API)】")
            eps_sorted = sorted(eps, key=_semantic_score, reverse=True)
            if has_hints:
                matched = [ep for ep in eps_sorted if _ep_matches(ep)]
                unmatched = [ep for ep in eps_sorted if not _ep_matches(ep)]
                # Show all matched in full detail
                for ep in matched:
                    sections.append(_format_ep_detail(ep, mark=True))
                # Show unmatched in condensed form, respect max_per_domain
                show_unmatched = unmatched[:max_per_domain] if max_per_domain else unmatched
                for ep in show_unmatched:
                    sections.append(_format_ep_condensed(ep))
                remaining = len(unmatched) - len(show_unmatched)
                if remaining > 0:
                    sections.append(f"  ... 还有 {remaining} 个API")
            else:
                show_eps = eps_sorted[:max_per_domain] if max_per_domain else eps_sorted
                for ep in show_eps:
                    line = f"  - {ep.name}: {ep.intent}"
                    if ep.required:
                        line += f"\n    必填参数: {', '.join(ep.required)}"
                    sections.append(line)
                if max_per_domain and len(eps) > max_per_domain:
                    sections.append(f"  ... 还有 {len(eps) - max_per_domain} 个API")

        sections.append("")

    return "\n".join(sections)
