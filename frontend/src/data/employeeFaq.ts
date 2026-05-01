/**
 * Universal FAQs shown in "通用模式" or while an employee profile is loading.
 *
 * Per-employee FAQs are sourced from the backend (`GET /api/employees/{id}.faqs`,
 * defined in `employees/*.yaml`). Universal FAQs are paginated: the welcome screen
 * starts on page 1 and users can rotate through pages via "换一批".
 *
 * Page 1 highlights cross-domain analytical scenarios that match the three digital
 * employees' specialties (生产运营专家 / 市场客户专家 / 资产设备专家).
 * Page 2 retains the original quick-look summary questions.
 */

export interface FAQ {
  id: string;
  question: string;
}

export const universalFAQPages: FAQ[][] = [
  [
    {
      id: 'p1-1',
      question: '2026年3月油化品、散杂货、商品车吞吐量结构对比，按港区拆解，以堆叠柱状图展示',
    },
    {
      id: 'p1-2',
      question: '2026年集装箱吞吐量目标完成率月度趋势，当年与上年对比，以折线图展示',
    },
    {
      id: 'p1-3',
      question: '2026年3月战略客户TOP10吞吐贡献排名及环比变化，识别新晋与掉队客户，以表格+柱状图展示',
    },
    {
      id: 'p1-4',
      question: '2026年资本项目计划完成情况，按港区与项目类型拆解，识别进度滞后项目，以表格+柱状图展示',
    },
    {
      id: 'p1-5',
      question: '2026年3月各机种生产设备利用率与完好率对比，识别低效机种并归因，以柱状图展示',
    },
  ],
  [
    {
      id: 'p2-1',
      question: '2026年1-4月全港吞吐量数据，以图文形式展示各月趋势',
    },
    {
      id: 'p2-2',
      question: '2026年3月市场数据汇总，吞吐量、同比、环比，以表格+图表展示',
    },
    {
      id: 'p2-3',
      question: '近6个月战略客户贡献趋势，分析稳定性，以折线图展示',
    },
    {
      id: 'p2-4',
      question: '2026年3月各港区吞吐量对比，以柱状图展示',
    },
    {
      id: 'p2-5',
      question: '当前设备运行状态，正常、维修、停用数量统计，以表格列出',
    },
  ],
];

/** Backwards-compatible flat list (page 1) for any caller that doesn't paginate. */
export const universalFAQs: FAQ[] = universalFAQPages[0];
