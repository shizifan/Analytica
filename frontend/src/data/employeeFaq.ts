/**
 * Loading-state FAQ fallback.
 *
 * Per-employee FAQs are now sourced from the backend (`GET /api/employees/{id}.faqs`,
 * defined in `employees/*.yaml`). This module only provides the universal list shown
 * briefly while the employee detail is still being fetched, or if no employee is
 * selected.
 */

export interface FAQ {
  id: string;
  question: string;
}

export const universalFAQs: FAQ[] = [
  {
    id: 'uni-1',
    question: '2026年1-4月全港吞吐量数据，以图文形式展示各月趋势',
  },
  {
    id: 'uni-2',
    question: '2026年3月市场数据汇总，吞吐量、同比、环比，以表格+图表展示',
  },
  {
    id: 'uni-3',
    question: '近6个月战略客户贡献趋势，分析稳定性，以折线图展示',
  },
  {
    id: 'uni-4',
    question: '2026年3月各港区吞吐量对比，以柱状图展示',
  },
  {
    id: 'uni-5',
    question: '当前设备运行状态，正常、维修、停用数量统计，以表格列出',
  },
];
