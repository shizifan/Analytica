/**
 * 数字员工常见问题配置
 * 为每个员工定义5个匹配的常见问题
 * 原则：每个问题都包含完整的时间范围、数据维度和输出格式要求，AI可直接回答无需追问
 */

export interface FAQ {
  id: string;
  question: string;
}

export interface EmployeeFAQ {
  employee_id: string;
  faqs: FAQ[];
}

// 吞吐量绩效分析师 (D1, D2)
const throughputAnalystFAQs: EmployeeFAQ = {
  employee_id: 'throughput_analyst',
  faqs: [
    {
      id: 'tp-1',
      question: '2026年4月各港区吞吐量数据，以柱状图展示各港区对比',
    },
    {
      id: 'tp-2',
      question: '2026年集装箱吞吐量目标与完成情况，目标量、完成量、完成率，以折线图展示月度趋势',
    },
    {
      id: 'tp-3',
      question: '2026年4月各港区泊位占用率，以折线图展示近6个月变化趋势',
    },
    {
      id: 'tp-4',
      question: '2026年1-4月全港吞吐量同比、环比数据，以表格+柱状图展示',
    },
    {
      id: 'tp-5',
      question: '2026年4月散杂货和集装箱吞吐量结构占比，以饼图展示',
    },
  ],
};

// 市场商务与战略客户洞察专家 (D2, D3)
const customerInsightFAQs: EmployeeFAQ = {
  employee_id: 'customer_insight',
  faqs: [
    {
      id: 'ci-1',
      question: '当前战略客户总数，2026年4月贡献占比前10名客户及占比，以表格列出',
    },
    {
      id: 'ci-2',
      question: '2026年4月重点企业吞吐量排名，前10名企业名称和吞吐量，以表格+柱状图展示',
    },
    {
      id: 'ci-3',
      question: '近6个月战略客户贡献趋势，分析贡献占比变化和稳定性，判断是否有流失风险',
    },
    {
      id: 'ci-4',
      question: '2026年4月全港吞吐量与2025年4月同比数据，与2026年3月环比数据，以表格对比',
    },
    {
      id: 'ci-5',
      question: '2026年4月各业务板块（集装箱、散杂货、油化品、商品车）吞吐量及占比，以饼图展示',
    },
  ],
};

// 资产价值与投资项目分析师 (D5, D6, D7)
const assetInvestmentFAQs: EmployeeFAQ = {
  employee_id: 'asset_investment',
  faqs: [
    {
      id: 'ai-1',
      question: '全港资产净值最新数据，相比2025年底变化金额和变化率，以表格列出各类资产明细',
    },
    {
      id: 'ai-2',
      question: '2026年投资计划总额、已投资额、完成进度，以表格列出主要项目进展',
    },
    {
      id: 'ai-3',
      question: '当前设备总数、正常运行数量、维修中数量，以表格列出维修中设备明细',
    },
    {
      id: 'ai-4',
      question: '房屋和土地资产分布，各类型资产数量和面积，以表格+饼图展示',
    },
    {
      id: 'ai-5',
      question: '2026年主要成本项目支出，以表格列出各项目支出金额和占比',
    },
  ],
};

// 通用问题（未选择员工时）
const universalFAQs: FAQ[] = [
  {
    id: 'uni-1',
    question: '2026年1-4月全港吞吐量数据，以图文形式展示各月趋势',
  },
  {
    id: 'uni-2',
    question: '2026年4月市场数据汇总，吞吐量、同比、环比，以表格+图表展示',
  },
  {
    id: 'uni-3',
    question: '近6个月战略客户贡献趋势，分析稳定性，以折线图展示',
  },
  {
    id: 'uni-4',
    question: '2026年4月各港区吞吐量对比，以柱状图展示',
  },
  {
    id: 'uni-5',
    question: '当前设备运行状态，正常、维修、停用数量统计，以表格列出',
  },
];

// 所有员工FAQ配置
export const employeeFAQMap: Record<string, EmployeeFAQ> = {
  [throughputAnalystFAQs.employee_id]: throughputAnalystFAQs,
  [customerInsightFAQs.employee_id]: customerInsightFAQs,
  [assetInvestmentFAQs.employee_id]: assetInvestmentFAQs,
};

// 获取指定员工的FAQ
export function getEmployeeFAQs(employeeId: string | null): FAQ[] {
  if (!employeeId) {
    return universalFAQs;
  }
  const employeeFAQ = employeeFAQMap[employeeId];
  return employeeFAQ ? employeeFAQ.faqs : universalFAQs;
}
