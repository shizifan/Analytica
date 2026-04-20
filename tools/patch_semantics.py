"""
对 api_registry.py 中29个缺失语义信息的 Cookbook API 补充
field_schema / use_cases / chain_with / analysis_note。
用法: python tools/patch_semantics.py backend/agent/api_registry.py
"""
import re, sys

PATCHES = {
    "getBerthOccupancyRateByRegion": dict(
        field_schema=(("regionName","str",""),("dateMonth","str",""),("rate","float","")),
        use_cases=("各港区泊位占用率月度趋势","泊位资源利用率对比分析",),
        chain_with=("getProductViewShipOperationRateTrend",),
        analysis_note="有startDate/endDate参数可做时间区间趋势，rate为小数，多港区×多月",
    ),
    "getCategoryAnalysis": dict(
        field_schema=(("num","float",""),("typeName","str",""),("assetTypeName","str","")),
        use_cases=("资产按类别对比分析","各类资产价值及数量结构",),
        chain_with=("getRegionalAnalysis",),
        analysis_note="三维透视：num/typeName/assetTypeName，需按typeName×assetTypeName分组",
    ),
    "getContainerAnalysisYoyMomByYear": dict(
        field_schema=(("regionName","str",""),("qty","float",""),("statType","str",""),("dateType","str","")),
        use_cases=("集装箱TEU年度同比分析","多港区集装箱量结构对比",),
        chain_with=("getContainerThroughputAnalysisByYear",),
        analysis_note="透视格式：regionName×statType×dateType，结构同getThroughputAnalysisYoyMomByYear",
    ),
    "getContainerByBusinessType": dict(
        field_schema=(("regionName","str",""),("targetQty","float",""),("finishQty","float","")),
        use_cases=("各港区集装箱目标完成对比","港区集装箱量分布",),
        chain_with=("getOilsChemBreakBulkByBusinessType",),
        analysis_note="按港区返回集装箱targetQty/finishQty，适合目标vs完成柱状对比图",
    ),
    "getContainerMachineHourRate": dict(
        field_schema=(("machineHourRate","float",""),("dateMonth","str","")),
        use_cases=("集装箱装卸台时效率月度趋势","台时效率历史对比",),
        chain_with=("getEquipmentUsageRate","getEquipmentServiceableRate",),
        analysis_note="月度序列machineHourRate/dateMonth，可做趋势折线",
    ),
    "getCostProjectAmtByOwnerLgZoneName": dict(
        field_schema=(("ownerLgZoneName","str",""),("investAmt","float",""),("finishPayAmt","float","")),
        use_cases=("各港区成本项目金额对比","港区成本支付完成率分析",),
        chain_with=("getPlanFinishByZone",),
        analysis_note="按港区返回investAmt/finishPayAmt，适合港区间对比柱状图",
    ),
    "getCostProjectCurrentStageQtyList": dict(
        field_schema=(("projectQty","int",""),("projectCurrentStage","str",""),("ownerLgZoneName","str","")),
        use_cases=("成本项目阶段分布分析","各港区在建/完工项目数量",),
        chain_with=("getCostProjectFinishByYear",),
        analysis_note="按projectCurrentStage×ownerLgZoneName分布，适合分组柱状图",
    ),
    "getCostProjectFinishByYear": dict(
        field_schema=(("dateYear","int",""),("projectQty","int",""),("realFinishPayAmt","float",""),("costApplyInvestAmt","float","")),
        use_cases=("成本项目历年完成趋势","年度成本投资完成量对比",),
        chain_with=("getInvestPlanByYear",),
        analysis_note="年度序列，包含projectQty/realFinishPayAmt，可做趋势折线",
    ),
    "getCumulativeRegionalThroughput": dict(
        field_schema=(("num","float",""),("typeName","str",""),("zoneName","str","")),
        use_cases=("各港区年累计吞吐量对比","港区业务结构占比分析",),
        chain_with=("getCurBusinessDashboardThroughput",),
        analysis_note="三维透视：num/typeName/zoneName，需按typeName和zoneName分组",
    ),
    "getCumulativeTrendChart": dict(
        field_schema=(("throughput","float",""),("businessSegment","str",""),("dateYear","str","")),
        use_cases=("某业务板块年累计吞吐趋势","板块历年吞吐量对比",),
        chain_with=("getTrendChart",),
        analysis_note="必填businessSegment+curDateYear+yearDateYear，返回throughput/businessSegment/dateYear",
    ),
    "getCurStrategicCustomerContributionByCargoTypeThroughput": dict(
        field_schema=(("num","float",""),("categoryName","str","")),
        use_cases=("当月战略客户按货类贡献分析","各货类战略客户吞吐占比",),
        chain_with=("getSumStrategicCustomerContributionByCargoTypeThroughput",),
        analysis_note="按货类categoryName返回num（战略客户吞吐量），适合饼图/柱状图",
    ),
    "getCurStrategyCustomerTrendAnalysis": dict(
        field_schema=(("num","float",""),("dateMonth","str",""),("typeName","str","")),
        use_cases=("战略客户当期月度多指标趋势","战略客户各维度月度走势",),
        chain_with=("getSumStrategyCustomerTrendAnalysis",),
        analysis_note="透视格式：num/dateMonth/typeName，多月×多指标，需按typeName分组",
    ),
    "getEquipmentEnergyConsumptionPerUnit": dict(
        field_schema=(("workingAmount","int",""),("dateMonth","str","")),
        use_cases=("设备单耗月度趋势","能耗效率历史对比",),
        chain_with=("getEquipmentUsageRate",),
        analysis_note="月度序列workingAmount/dateMonth，可做能耗趋势折线",
    ),
    "getEquipmentFacilityAnalysisYoy": dict(
        field_schema=(("num","int",""),("typeName","str",""),("dateYear","float","")),
        use_cases=("设备设施年度同比分析","各类设备设施历年数量变化",),
        chain_with=("getRegionalAnalysis",),
        analysis_note="透视格式：num/typeName/dateYear，需按typeName×dateYear分组解读",
    ),
    "getEquipmentIndicatorOperationQty": dict(
        field_schema=(("num","float",""),("firstLevelName","str","")),
        use_cases=("设备作业量指标概览","各类设备作业量对比",),
        chain_with=("getEquipmentIndicatorUseCost",),
        analysis_note="透视格式：num/firstLevelName，按设备一级分类汇总作业量指标",
    ),
    "getEquipmentIndicatorUseCost": dict(
        field_schema=(("num","float",""),("firstLevelName","str","")),
        use_cases=("设备使用成本指标概览","各类设备成本效益分析",),
        chain_with=("getEquipmentIndicatorOperationQty",),
        analysis_note="透视格式：num/firstLevelName，按设备一级分类汇总成本指标",
    ),
    "getHousingAnalysisYoy": dict(
        field_schema=(("num","float",""),("typeName","str",""),("dateYear","float","")),
        use_cases=("房屋资产年度同比分析","房屋建筑面积历年变化",),
        chain_with=("getLandMaritimeAnalysisYoy",),
        analysis_note="透视格式：num/typeName/dateYear，按typeName×dateYear分组解读",
    ),
    "getLandMaritimeRegionalAnalysis": dict(
        field_schema=(("num","float",""),("typeName","str",""),("ownerZone","str","")),
        use_cases=("各港区土地海域分布对比","港区土地海域面积及净值分析",),
        chain_with=("getRegionalAnalysis",),
        analysis_note="三维透视：num/typeName/ownerZone，按港区比较土地海域资产",
    ),
    "getOilsChemBreakBulkByBusinessType": dict(
        field_schema=(("regionName","str",""),("targetQty","float",""),("finishQty","float","")),
        use_cases=("各港区油化散杂货目标完成对比","散杂货港区分布分析",),
        chain_with=("getContainerByBusinessType",),
        analysis_note="按港区返回油化品/散杂货targetQty/finishQty，适合对比柱状图",
    ),
    "getPortCompanyThroughput": dict(
        field_schema=(("num","float",""),("businessType","str",""),("dateYear","int","")),
        use_cases=("指定公司吞吐量按业务类型分析","港口公司业务结构对比",),
        chain_with=("getThroughputAnalysisByYear",),
        analysis_note="必填date+cmpName，返回该公司按businessType的吞吐量分布",
    ),
    "getProductEquipmentUsageRateByYear": dict(
        field_schema=(("usageRate","float",""),("dateYear","int","")),
        use_cases=("设备利用率历年趋势","年度利用率同比分析",),
        chain_with=("getEquipmentUsageRate",),
        analysis_note="年度序列约4行(2023-2026)，usageRate/dateYear，可做历年趋势折线",
    ),
    "getProductViewShipOperationRateTrend": dict(
        field_schema=(("monthId","str",""),("monthStr","str",""),("statCargoKind","str",""),("tonQ","float",""),("workTh","float","")),
        use_cases=("船舶作业效率月度趋势","各货类作业效率对比",),
        chain_with=("getBerthOccupancyRateByRegion",),
        analysis_note="月度×货类矩阵：monthId/statCargoKind/tonQ/workTh，需按statCargoKind分组",
    ),
    "getProductionEquipmentFaultNum": dict(
        field_schema=(("num","int",""),("dateMonth","str","")),
        use_cases=("设备故障次数月度趋势","设备可靠性历史分析",),
        chain_with=("getEquipmentUsageRate",),
        analysis_note="透视格式：num/dateMonth，需按分组字段解析各类设备故障分布",
    ),
    "getStrategicCustomerThroughput": dict(
        field_schema=(("clientName","str",""),("ttlNum","str",""),("cargoCategoryName","str",""),("ttlDate","str","")),
        use_cases=("战略客户吞吐量明细查询","指定客户历史吞吐记录",),
        chain_with=("getCurContributionRankOfStrategicCustomer",),
        analysis_note="返回clientName/ttlNum/cargoCategoryName/ttlDate，数据量大（约297行），建议筛选客户后使用",
    ),
    "getStrategicCustomers": dict(
        field_schema=(("displayCode","str",""),("displayName","str","")),
        use_cases=("获取战略客户名单","战略客户列表查询",),
        chain_with=("getCurContributionRankOfStrategicCustomer",),
        analysis_note="仅返回displayCode/displayName，无业绩数据，约37个战略客户，可做后续分析的客户筛选源",
    ),
    "getSumBusinessDashboardThroughput": dict(
        field_schema=(("typeName","str",""),("num","float","")),
        use_cases=("年累计全港各业务板块吞吐概览","业务板块年度汇总对比",),
        chain_with=("getCurBusinessDashboardThroughput",),
        analysis_note="透视格式typeName/num，需按typeName分组，对应当月版getCurBusinessDashboardThroughput",
    ),
    "getSumStrategicCustomerContributionByCargoTypeThroughput": dict(
        field_schema=(("num","float",""),("categoryName","str","")),
        use_cases=("战略客户年累计按货类贡献分析","各货类战略客户年度吞吐占比",),
        chain_with=("getCurStrategicCustomerContributionByCargoTypeThroughput",),
        analysis_note="累计版，按categoryName返回num，结构同当月版",
    ),
    "getThroughputAndTargetThroughputTeu": dict(
        field_schema=(("targetQty","float",""),("finishQty","float","")),
        use_cases=("查询年度集装箱TEU目标完成率",),
        chain_with=("getThroughputAndTargetThroughputTon",),
        analysis_note="仅返回1行KPI：targetQty/finishQty（TEU版），不可用于趋势分析",
    ),
    "planInvestAndPayYoy": dict(
        field_schema=(("dateYear","int",""),("planInvestAmt","float",""),("planPayAmt","float","")),
        use_cases=("年度投资计划同比快照","年度计划金额对比",),
        chain_with=("getInvestPlanByYear",),
        analysis_note="同比快照：dateYear/planInvestAmt/planPayAmt，仅2行年度对比",
    ),
}


def fmt_tuple_of_tuples(t):
    inner = ", ".join(f'("{a}", "{b}", "{c}")' for a, b, c in t)
    return f"({inner},)"


def fmt_str_tuple(t):
    inner = ", ".join(f'"{s}"' for s in t)
    return f"({inner},)"


def build_insertion(patch):
    lines = []
    lines.append(f'        field_schema={fmt_tuple_of_tuples(patch["field_schema"])},')
    lines.append(f'        use_cases={fmt_str_tuple(patch["use_cases"])},')
    if patch.get("chain_with"):
        lines.append(f'        chain_with={fmt_str_tuple(patch["chain_with"])},')
    lines.append(f'        analysis_note="{patch["analysis_note"]}",')
    return "\n".join(lines)


def patch_file(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()

    count = 0
    for name, patch in PATCHES.items():
        pattern = rf'(ApiEndpoint\(name="{re.escape(name)}".*?disambiguate="[^"]*"\))'

        def replacer(m, _patch=patch):
            block = m.group(1)
            if "field_schema=" in block or "use_cases=" in block:
                return block
            insertion = build_insertion(_patch)
            return block[:-1] + ",\n" + insertion + ")"

        new_src, n = re.subn(pattern, replacer, src, flags=re.DOTALL)
        if n > 0:
            src = new_src
            count += 1
            print(f"✓ {name}")
        else:
            print(f"✗ {name}: pattern not matched")

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\nDone: {count}/{len(PATCHES)} APIs patched")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/patch_semantics.py backend/agent/api_registry.py")
        sys.exit(1)
    patch_file(sys.argv[1])
