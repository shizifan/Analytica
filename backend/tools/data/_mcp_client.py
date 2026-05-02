"""MCP SSE client — 调用 HiAgent-MCP-Server 的 Web Search Agent 工具。

协议：JSON-RPC 2.0 over SSE (Server-Sent Events)。
响应为流式推送，将逐字符拼接后返回完整 JSON。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("analytica.tools.mcp_client")


async def call_mcp_search(query: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """通过 MCP 协议调用 Web Search Agent，返回结构化搜索结果。

    Args:
        query: 搜索关键词
        timeout: 请求超时秒数

    Returns:
        成功: {"query": "...", "search_time": "...", "total_results": N, "results": [...]}
        失败: {"error": "错误描述"}
    """
    from backend.config import get_settings

    settings = get_settings()
    url = f"{settings.MCP_SEARCH_URL}?api_key={settings.MCP_SEARCH_API_KEY}"

    # JSON-RPC 2.0 请求体
    rpc_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "Web Search Agent",
            "arguments": {"Query": query},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream(
                "POST", url,
                json=rpc_body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    return {"error": f"MCP 服务返回 HTTP {response.status_code}: {body[:500]!r}"}

                # 收集 SSE 流：逐事件解析，拼接流式 JSON
                full_content = ""
                accumulated: dict[str, Any] | None = None

                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            event_data = json.loads(data_str)

                            # 最终响应：result.content[0].text 包含完整 JSON
                            if "result" in event_data:
                                result = event_data["result"]
                                if "content" in result:
                                    for c in result["content"]:
                                        if isinstance(c, dict) and c.get("type") == "text":
                                            try:
                                                accumulated = json.loads(c["text"])
                                            except json.JSONDecodeError:
                                                full_content += c["text"]
                                                try:
                                                    accumulated = json.loads(full_content)
                                                except json.JSONDecodeError:
                                                    pass
                                                continue
                                    # 有结果就跳出
                                    if accumulated:
                                        break

                            # 流式进度事件：逐字符推送
                            elif event_data.get("method") == "notifications/progress":
                                msg = event_data.get("params", {}).get("message", "")
                                if msg:
                                    try:
                                        inner = json.loads(msg)
                                        chunk = inner.get("data", "")
                                        if chunk:
                                            try:
                                                obj = json.loads(chunk)
                                                full_content += obj.get("content", "")
                                            except json.JSONDecodeError:
                                                pass
                                    except json.JSONDecodeError:
                                        pass

                        except json.JSONDecodeError:
                            pass

                # 如果流式事件中没有最终结果，尝试用拼接的 content 解析
                if accumulated is None and full_content:
                    try:
                        accumulated = json.loads(full_content)
                    except json.JSONDecodeError:
                        return {"error": "无法解析 MCP 返回的搜索结果 JSON"}

                if accumulated is None:
                    return {"error": "MCP 未返回搜索结果"}

                return accumulated

    except httpx.TimeoutException:
        logger.warning("MCP search timeout for query=%r", query)
        return {"error": "搜索请求超时，请稍后重试"}
    except httpx.ConnectError as e:
        logger.warning("MCP connection error: %s", e)
        return {"error": f"无法连接到搜索服务: {e}"}
    except Exception as e:
        logger.exception("MCP search error for query=%r", query, exc_info=e)
        return {"error": f"搜索服务异常: {str(e)[:300]}"}
