"""Tests for search query sanitizer."""
from __future__ import annotations

import pytest

from backend.tools.data._search_sanitizer import sanitize_query


class TestSanitizeQuery:
    """Verify sanitize_query removes internal patterns while preserving intent."""

    def test_removes_employee_id(self):
        assert sanitize_query("辽港 EMP_0012 吞吐量") == "辽港 [内部ID已移除] 吞吐量"

    def test_removes_employee_id_lowercase(self):
        assert sanitize_query("emp_9999 数据") == "[内部ID已移除] 数据"

    def test_removes_long_hex_code(self):
        assert sanitize_query("辽港 a1b2c3d4e5f6a7b8 吞吐量") == "辽港 吞吐量"

    def test_removes_auth_token(self):
        assert sanitize_query("辽港 token=deadbeef 吞吐量") == "辽港 吞吐量"

    def test_removes_auth_token_case_insensitive(self):
        assert sanitize_query("AUTH=secret123 辽港") == "辽港"

    def test_removes_api_method_name(self):
        assert sanitize_query("getThroughputAnalysisByYear 辽港") == "辽港"

    def test_removes_internal_table_ref(self):
        assert sanitize_query("dwd_throughput_summary 辽港") == "辽港"

    def test_preserves_normal_query(self):
        original = "辽港集团 2026年 集装箱吞吐量"
        assert sanitize_query(original) == original

    def test_collapses_whitespace(self):
        assert sanitize_query("辽港   集团  吞吐量") == "辽港 集团 吞吐量"

    def test_idempotent(self):
        q = "辽港 emp_0001 a1b2c3d4e5f6a7b8 token=abc 吞吐量"
        once = sanitize_query(q)
        twice = sanitize_query(once)
        assert once == twice
