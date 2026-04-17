# Analytica · Phase 3 测试报告

## 测试概况

| 项目 | 数据 |
|------|------|
| 阶段 | Phase 3: 执行层与技能库 |
| 测试日期 | 2026-04-15 |
| Phase 3 新增测试 | 54 |
| Phase 1+2+3 总测试 | 192 |
| 通过率 | 100% (192/192) |
| 耗时 | ~4 分钟 |

---

## 新增文件清单

### 技能框架 (Sprint 6)
| 文件 | 说明 |
|------|------|
| `backend/skills/__init__.py` | 技能包初始化 |
| `backend/skills/base.py` | BaseSkill, SkillInput, SkillOutput, SkillCategory, skill_executor |
| `backend/skills/registry.py` | SkillRegistry 单例 + @register_skill 装饰器 |
| `backend/skills/loader.py` | 统一导入，确保所有技能注册 |
| `backend/skills/data/api_fetch.py` | skill_api_fetch — API 数据获取（httpx + Bearer Token + DataFrame 转换） |
| `backend/skills/data/web_search.py` | skill_web_search — 互联网检索（stub） |
| `backend/skills/data/file_parse.py` | skill_file_parse — 文件解析（CSV/Excel/JSON） |

### 分析技能 (Sprint 7)
| 文件 | 说明 |
|------|------|
| `backend/skills/analysis/descriptive.py` | skill_desc_analysis — 描述性统计 + LLM 叙述 |
| `backend/skills/analysis/attribution.py` | skill_attribution — 归因分析 + LLM 因果推理 |
| `backend/skills/analysis/prediction.py` | skill_prediction — 预测分析（stub） |
| `backend/skills/analysis/anomaly.py` | skill_anomaly — 异常检测（stub） |

### 可视化技能 (Sprint 8)
| 文件 | 说明 |
|------|------|
| `backend/skills/visualization/chart_line.py` | skill_chart_line — ECharts 折线图 |
| `backend/skills/visualization/chart_bar.py` | skill_chart_bar — ECharts 柱状图 |
| `backend/skills/visualization/chart_waterfall.py` | skill_chart_waterfall — ECharts 瀑布图 |
| `backend/skills/visualization/chart_wrapper.py` | skill_dashboard — 多图表组合 HTML |

### 报告生成技能 (Sprint 8)
| 文件 | 说明 |
|------|------|
| `backend/skills/report/pptx_gen.py` | skill_report_pptx — PPTX 报告（python-pptx） |
| `backend/skills/report/docx_gen.py` | skill_report_docx — DOCX 报告（python-docx） |
| `backend/skills/report/html_gen.py` | skill_report_html — HTML 报告（Jinja2 + ECharts CDN） |
| `backend/skills/report/summary_gen.py` | skill_summary_gen — LLM 摘要生成 |

### 执行节点 (Sprint 9)
| 文件 | 说明 |
|------|------|
| `backend/agent/execution.py` | 执行节点（拓扑排序 + asyncio.gather 并行 + 动态重规划） |

### Mock API Fixture (27 个)
| 文件 | 说明 |
|------|------|
| `tests/fixtures/mock_api/m01~m27_*.json` | 27 个端点的 fixture 数据文件 |

---

## 测试详情

### 技能注册中心 (tests/unit/test_skill_registry.py) — 7 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-R01 | 启动后 15 个内置技能全部注册 | PASS |
| TC-R02 | get_skill 不存在时返回 None | PASS |
| TC-R03 | list_skills 按分类过滤 | PASS |
| TC-R04 | get_skills_description 返回 LLM 描述文本 | PASS |
| - | 总技能数 = 15 | PASS |
| TC-R05 | skill_executor 超时返回 failed | PASS |
| - | skill_executor 异常返回 failed | PASS |

### API 数据获取 (tests/unit/test_skill_api_fetch.py) — 9 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-AF01 | M02 正常调用返回 DataFrame（4 板块，占比之和≈100%） | PASS |
| TC-AF02 | 数据行数 < 10 触发 quality_warning | PASS |
| TC-AF03 | 401 认证错误返回 failed | PASS |
| TC-AF04 | 500 服务端错误不崩溃 | PASS |
| TC-AF05 | M12 缺少 businessSegment 必填参数报错 | PASS |
| TC-AF06 | M19 topN > 50 自动截断 | PASS |
| TC-AF07 | Bearer Token 自动注入 | PASS |
| - | M-code 可正确解析为端点名称 | PASS |
| - | 未知端点 ID 返回 failed | PASS |

### 描述性分析 (tests/unit/test_skill_desc_analysis.py) — 7 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-DA01 | 同比增长率计算正确（12% 误差 < 1%） | PASS |
| TC-DA02 | 环比增长率计算正确 | PASS |
| TC-DA03 | 不足 12 个月时 yoy = null | PASS |
| TC-DA04 | narrative 包含数字和关键发现 | PASS |
| TC-DA05 | LLM 输出 `<think>` 标签被剥离 | PASS |
| TC-DA06 | group_by=ioTrade 按内外贸分组统计 | PASS |
| - | summary_stats 包含 mean/median/std/min/max/missing_rate | PASS |

### 归因分析 (tests/unit/test_skill_attribution.py) — 3 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-AT01 | 归因结果包含 primary_drivers | PASS |
| TC-AT02 | 无外部检索数据时仍可执行，uncertainty_note 说明局限 | PASS |
| TC-AT03 | waterfall_data 包含基准值和因素 | PASS |

### 可视化技能 (tests/unit/test_skill_visualization.py) — 5 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-V01 | 折线图 option 包含 series + xAxis | PASS |
| TC-V02 | 多系列折线图（2 条线） | PASS |
| TC-V03 | 瀑布图正值/负值颜色区分 | PASS |
| TC-V04 | ECharts option 可 JSON 序列化 | PASS |
| - | 柱状图基本功能 | PASS |

### PPTX/HTML 报告 (tests/unit/test_skill_report_pptx.py) — 6 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-PT01 | PPTX 生成成功，幻灯片 >= 4 页 | PASS |
| TC-PT02 | 封面包含标题文字 | PASS |
| TC-PT03 | 无图表数据时降级不崩溃 | PASS |
| TC-PT04 | 中文字体正确（Microsoft YaHei） | PASS |
| TC-PT05 | HTML 报告包含 `<html>` + `echarts` | PASS |
| - | HTML 报告包含标题 | PASS |

### Mock API Fixture (tests/unit/test_mock_api_fixtures.py) — 9 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-FX01 | 27 个 fixture 文件存在且 JSON 合法 | PASS |
| - | fixture 目录共 27 个文件 | PASS |
| TC-FX02 | M02 包含 4 板块，占比之和≈100% | PASS |
| TC-FX03 | M12 时间序列完整有序（12 个月） | PASS |
| TC-AF08 | M25 投资完成率/金额关系正确 | PASS |
| TC-AF09 | M21 净值 <= 原值 | PASS |
| TC-AF10 | M23 设备状态比例之和 = 1.0 | PASS |
| TC-AF11 | M09 在泊船舶数量合理（15-35） | PASS |
| TC-AF12 | M20 信用等级合法，额度关系正确 | PASS |

### 执行节点集成测试 (tests/integration/test_execution_node.py) — 8 tests
| TC | 名称 | 结果 |
|----|------|------|
| TC-EN01 | simple_table 场景 E2E | PASS |
| TC-EN02 | 并行任务确实并行执行（耗时 < 4s） | PASS |
| TC-EN03 | 单任务失败不阻塞其他任务 | PASS |
| TC-EN04 | 数据量不足触发 needs_replan | PASS |
| TC-EN05 | WebSocket 回调推送 running + done 状态 | PASS |
| TC-EN06 | 所有任务完成后 next_action = reflection | PASS |
| - | 依赖链按序执行（T001 → T002） | PASS |
| - | 未注册技能返回 failed | PASS |

---

## 验收检查单

| 验收项 | 判断标准 | 状态 |
|--------|----------|------|
| 技能注册中心：15 个内置技能全部注册 | TC-R01 | PASS |
| API 数据获取：27 个 Mock API 可正常调用 | TC-AF01~AF12 | PASS |
| 描述性分析：同比/环比/分组统计正确 | TC-DA01~DA06 | PASS |
| 归因分析：primary_drivers 可解释 | TC-AT01~AT03 | PASS |
| PPTX 报告：可打开，幻灯片 >= 4 页 | TC-PT01~PT04 | PASS |
| HTML 报告：合法 HTML，含 ECharts | TC-PT05 | PASS |
| 执行节点：simple_table E2E | TC-EN01 | PASS |
| 并行执行验证 | TC-EN02 | PASS |
| 单任务失败不阻塞全链路 | TC-EN03 | PASS |
| 数据量不足触发重规划 | TC-EN04 | PASS |
| 27 个 Mock API fixture 完整 | TC-FX01 | PASS |
| 单元测试 >= 30 个 | 54 个（Phase 3 新增） | PASS |

---

## 技术决策记录

1. **技能注册机制**：使用 `@register_skill` 装饰器 + `SkillRegistry` 单例，技能在 import 时自动注册，`backend/skills/loader.py` 统一触发导入。

2. **执行并行策略**：基于 Kahn 算法做拓扑分层，每层内用 `asyncio.gather` 并行执行（上限 MAX_CONCURRENT=3），单任务失败不阻塞同层其他任务。

3. **数据质量检查**：API 返回 < 10 行时在 metadata 中标记 `quality_warning: low_data_volume`，执行节点检测到后设置 `needs_replan=True`。

4. **LLM 输出容错**：`_strip_think_tags()` 剥离 `<think>` 标签，`_extract_json()` 支持直接 JSON / markdown 代码块 / 首尾花括号三种解析策略。

5. **PPTX 主题**：深蓝 `#1E3A5F`（背景/标题）、白色（正文）、琥珀 `#F0A500`（强调色），字体 Microsoft YaHei。

6. **graph.py 集成**：将 execution_node stub 替换为真实实现，通过延迟导入 `backend.agent.execution.execution_node` 避免循环依赖。
