# -*- coding: utf-8 -*-
"""规则意图层（阶段 2a 解耦循环依赖：从 上传报表生成器.py 提取的纯规则函数）。

职责：不依赖 编排器/上传报表生成器 的任何"规则层意图解析"函数——
  1. 字段语义匹配（_匹配意图字段 / 自动选字段 / _合并显式字段 / _合法字段 / _提取模板字段）
  2. 受控语句解析（_受控语句配置：【字段】模板 + 图表关键词）
  3. 意图兜底（_意图驱动配置：占比/筛选/TopN/同比环比 三合一）
  4. 图表推荐（_推荐图表类型）
  5. 意图关键词常量（占比关键词 / 字段意图关键词）

解耦原由：编排器.py 与 多智能体.py 曾靠「延迟 import 上传报表生成器」来规避循环
（上传报表生成器 → 编排器 → 上传报表生成器）。把这些规则函数独立成模块后，
编排器/多智能体/上传报表生成器 三者都依赖本模块，消除互相 import。

对外依赖：仅 后端_核心/数据筛选.py（匹配筛选条件 / 提取TopN）——同为纯规则层。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from 后端_核心.data_filter import 匹配筛选条件, 提取TopN


# ════════════════════════════════════════════════════════════
# 意图关键词常量
# ════════════════════════════════════════════════════════════

占比关键词 = ["占比", "比例", "分布", "构成", "占比图", "占比分布", "占比分析"]
# 数值意图关键词（“价格占比”→y轴=价格字段，不再固定“记录数”）
# 用于在占比/比例/构成意图里识别用户想按哪个数值指标计算占比；
# 命中后从画像「数值字段」里匹配字段名，未命中才回退计数兜底。
数值意图关键词 = [
    "价格", "均价", "最高价", "最低价", "开盘价", "收盘价", "成交额", "成交量",
    "金额", "总额", "市值", "收益", "营收", "利润", "工资", "收入", "销量", "数量",
    "销售额", "营业额", "销售数量", "成本", "费用", "净利润", "毛利率", "增速", "增长",
]
# 维度/字段意图关键词（按优先级排列；命中后按“关键词 in 字段名”子串匹配字段）
字段意图关键词 = [
    # 时间/时长类（用户常用“工作时间/工时/时长/小时”描述占比需求）
    "工作时间", "工作时长", "加班", "工时", "时长", "小时", "时间", "日期", "月份", "年份",
    # 个人/组织维度
    "工作经验", "经验", "年龄", "年限", "学历", "性别", "薪资", "工资", "收入",
    # 地理/岗位维度
    "地区", "国家", "城市", "地点", "岗位", "职位", "分类", "类型", "行业", "部门", "公司",
    # 股票/金融维度（阶段 42 补：用户上传股票数据说"按股票占比"，要选股票代码/名称）
    "股票", "代码", "名称", "基金", "债券", "板块", "行业板块",
]


# ════════════════════════════════════════════════════════════
# 字段语义匹配
# ════════════════════════════════════════════════════════════

def _匹配意图字段(画像: Dict[str, Any], 关键词列表: List[str], 需求文本: str = "") -> Optional[str]:
    """从数据画像中挑出与用户需求语义最匹配的字段名（规则引擎的核心匹配器）。

    作用：用户说"按工作时间统计占比"，这句话里没有直接出现列名，
    这个函数负责把"工作时间"这类关键词映射到数据集中真实的列名（如"工作时长"）。

    入参：
      - 画像：数据画像 dict（字段列表 = 全部可用列名；分类字段 = 适合做维度的列）
      - 关键词列表：按优先级排列的候选关键词（命中顺序决定字段优先级）
      - 需求文本：用户原始需求；非空时优先匹配"需求里真实出现的关键词"，
        避免固定顺序导致"工作经验"被"时间"抢先（如"工作经验要求占比图"）
    返回：
      - 找到：字段名 str
      - 没找到：None
    业务定位：规则降级引擎的"翻译官"——把用户口语翻译成真实列名；
    是 _受控语句配置 / _意图驱动配置 两个规则函数的公共依赖。
    """
    可用字段 = 画像.get("字段列表", [])
    分类字段 = 画像.get("分类字段", [])
    日期字段 = set(画像.get("日期字段", []))
    候选字段 = [*可用字段, *分类字段]
    # 第一优先：需求文本中真正出现的关键词所匹配的字段
    if 需求文本:
        for 关键词 in 关键词列表:
            if 关键词 and 关键词 in 需求文本:
                for field in 候选字段:
                    if 关键词 in field:
                        return field
    # 第二优先：固定顺序，但优先分类字段（占比/趋势/TopN 等场景的 x 轴更合理），
    # 避免"日期"字段被固定顺序抢先选中导致"按股票价格占比 x=日期"的问题。
    # 分类字段没匹配上时再退回到任意字段（含日期），保证向后兼容。
    分类集合 = set(分类字段)
    for 关键词 in 关键词列表:
        for field in 候选字段:
            if 关键词 and 关键词 in field and field in 分类集合:
                return field
    for 关键词 in 关键词列表:
        for field in 候选字段:
            if 关键词 and 关键词 in field:
                return field
    if 分类字段:
        return 分类字段[0]
    if 可用字段:
        return 可用字段[0]
    return None


def _匹配数值字段(画像: Dict[str, Any], 需求文本: str) -> Optional[str]:
    """从需求文本中识别用户想按哪个数值字段计算占比。

    作用：用户说“按股票价格占比”，价格是数值字段；规则层以前固定
    y轴=记录数（计数），导致“价格占比图”变成“各股票出现次数占比”。
    这里按 数值意图关键词 → 画像数值字段名 子串匹配，命中即返回该字段。

    入参：
      - 画像：数据画像（含 数值字段 列表）
      - 需求文本：用户原始需求
    返回：
      - 命中：数值字段名 str
      - 未命中：None（调用方回退计数兜底）
    """
    if not 需求文本:
        return None
    数值字段 = 画像.get("数值字段") or []
    if not 数值字段 or not 需求文本:
        return None
    # 第一优先：精确匹配（"收盘价" in "收盘价"）
    for 关键词 in 数值意图关键词:
        if 关键词 in 需求文本:
            for field in 数值字段:
                if 关键词 in field:
                    return field
    # 第二优先：泛化匹配（用户说"价格"，字段名是"开盘价/收盘价"——没有"价格"二字，
    # 但都含核心字"价"；"金额/总额"→"额"，"销量/数量"→"量"）
    for 关键词, 核心字 in (("价格", "价"), ("金额", "额"), ("总额", "额"),
                            ("销量", "量"), ("数量", "量")):
        if 关键词 in 需求文本:
            for field in 数值字段:
                if 核心字 in field:
                    return field
    return None


# 占比维度选择：需求里提到时间词才优先日期字段，否则优先分类字段
_时间类词 = ("日期", "时间", "月份", "年份", "年度", "每日", "按月", "按年", "按日", "每周")


def _占比维度字段(画像: Dict[str, Any], 需求文本: str) -> Optional[str]:
    """占比图的维度（x 轴）选择：保留原字段名匹配能力，只修正误选日期的情况。

    作用：`_匹配意图字段` 第二优先按固定关键词顺序扫字段名，容易把
    "日期"字段选成占比维度（用户说"按股票价格占比"，x 轴却成了日期）。
    本函数先走原匹配（能正确识别"工作时间"等字段名），只有当匹配结果
    是日期字段、且需求文本没有明确时间语义时，才改用分类字段。

    入参：
      - 画像：数据画像
      - 需求文本：用户原始需求
    返回：
      - 字段名 str；找不到返回 None
    """
    # 第一步：用原有的字段名匹配（能正确识别"工作时间"等具体字段名）
    匹配结果 = _匹配意图字段(画像, 字段意图关键词, 需求文本)
    if not 需求文本 or not 匹配结果:
        return 匹配结果

    日期字段 = list(画像.get("日期字段") or [])
    分类字段 =画像.get("分类字段") or []
    日期集合 = set(日期字段)

    # 第二步：双向修正
    # - 匹配到日期字段但需求没有时间语义（如"按股票价格占比"→日期字段被固定顺序选中）
    #   → 改用分类字段（占比语义 x 轴通常是分类维度）
    # - 需求有时间语义但匹配到非日期字段（如"按月份占比"→分类字段优先返回了股票代码）
    #   → 改用日期字段（用户明确说月份/日期，x 轴应该是时间维度）
    if 匹配结果 in 日期集合:
        if not any(w in 需求文本 for w in _时间类词) and 分类字段:
            return 分类字段[0]
    elif any(w in 需求文本 for w in _时间类词) and 日期字段:
        return 日期字段[0]

    return 匹配结果


def _提取模板字段(文本: str) -> List[str]:
    fields: List[str] = []
    start = 0
    while True:
        left = 文本.find("【", start)
        right = 文本.find("】", left + 1)
        if left == -1 or right == -1:
            break
        value = 文本[left + 1:right].strip()
        if value:
            fields.append(value)
        start = right + 1
    return fields


def _合法字段(画像: Dict[str, Any], field: Optional[str]) -> Optional[str]:
    if field and field in 画像.get("字段列表", []):
        return field
    return None


def 自动选字段(画像: Dict[str, Any], 图表类型: str) -> Dict[str, Any]:
    """按图表类型返回语义正确的字段组合（自然语言自动选择，零手动）。

    优先级：文本字段(词云) > 分类 > 日期 > 数值；字段不足时自动降级。
    返回 {图表类型, x轴, y轴, 分组字段, 聚合方式}。
    """
    分类 = 画像.get("分类字段") or []
    数值 = 画像.get("数值字段") or []
    日期 = 画像.get("日期字段") or []
    文本 = 画像.get("文本字段") or []
    字段列表 = 画像.get("字段列表") or []

    def _x() -> Optional[str]:
        return 分类[0] if 分类 else (日期[0] if 日期 else (字段列表[0] if 字段列表 else None))

    def _x2() -> Optional[str]:
        return 分类[1] if len(分类) > 1 else None

    def _y() -> List[str]:
        return [数值[0]] if 数值 else ["记录数"]

    def _agg() -> str:
        return "求和" if 数值 else "计数"

    base = {"图表类型": 图表类型}

    if 图表类型 == "词云图":
        x = 文本[0] if 文本 else (max(分类, key=lambda f: len(str(f)), default=None) if 分类 else None)
        return {**base, "x轴": x, "y轴": [], "分组字段": None, "聚合方式": "计数"}
    if 图表类型 == "散点图":
        x = 数值[0] if 数值 else None
        y = [数值[1]] if len(数值) > 1 else ([数值[0]] if 数值 else [])
        return {**base, "x轴": x, "y轴": y, "分组字段": None, "聚合方式": "求和"}
    if 图表类型 in ("箱线图", "K线图"):
        if 图表类型 == "K线图" and 日期:
            x = 日期[0]
        else:
            x = _x()
        y = _y()
        if x == (y[0] if y else None):
            x = 日期[0] if 日期 else (分类[1] if len(分类) > 1 else None)
        return {**base, "x轴": x, "y轴": y, "分组字段": None, "聚合方式": "求和"}
    if 图表类型 in ("热力图", "堆积柱状图", "桑基图", "旭日图"):
        return {**base, "x轴": _x(), "y轴": _y(), "分组字段": _x2(), "聚合方式": _agg()}
    if 图表类型 == "雷达图":
        y = 数值[:3] if 数值 else []
        return {**base, "x轴": _x(), "y轴": y, "分组字段": None, "聚合方式": "平均值"}
    if 图表类型 == "直方图":
        target = 数值[0] if 数值 else None
        return {**base, "x轴": target, "y轴": [target] if target else [], "分组字段": None, "聚合方式": "计数"}
    if 图表类型 in ("折线图", "面积图"):
        x = 日期[0] if 日期 else _x()
        return {**base, "x轴": x, "y轴": _y(), "分组字段": None, "聚合方式": _agg()}
    return {**base, "x轴": _x(), "y轴": _y(), "分组字段": None, "聚合方式": _agg()}


def _合并显式字段(selected: Dict[str, Any], first: Optional[str], second: Optional[str]) -> Dict[str, Any]:
    """用户显式指定字段时覆盖自动选择（【字段】模板优先）。

    作用：用户在需求文本里用【字段A】【字段B】模板语法手动指定字段时，
    把自动选的字段替换成用户指定的值；这是"用户显式意图 > 系统自动推荐"的体现。

    入参：
      - selected：自动选字段函数返回的默认配置（已含图表类型、x轴、y轴等）
      - first：用户模板里指定的第一个字段名（→ X 轴）
      - second：用户模板里指定的第二个字段名：
        · 对热力图/堆积柱状图/桑基图/旭日图（分组类图表）→ 设为「分组字段」
        · 对其他图表 → 加入「Y 轴」指标列表
    返回：合并后的新 dict（不修改原 selected）
    """
    result = dict(selected)
    if first:
        result["x轴"] = first
    if second:
        分组类图表 = ("热力图", "堆积柱状图", "桑基图", "旭日图")
        if result.get("图表类型") in 分组类图表:
            result["分组字段"] = second
        else:
            y_list = result.get("y轴") or []
            if second not in y_list:
                result["y轴"] = [second] + [f for f in y_list if f != second]
    return result


# ════════════════════════════════════════════════════════════
# 受控语句解析：图表关键词 + 【字段】模板 → 报表配置
# ════════════════════════════════════════════════════════════

def _受控语句配置(画像: Dict[str, Any], 分析需求: str) -> Dict[str, Any]:
    文本 = 分析需求.strip()
    fields = _提取模板字段(文本)

    first = _合法字段(画像, fields[0] if fields else None)
    second = _合法字段(画像, fields[1] if len(fields) > 1 else None)

    if "交叉分布" in 文本 or "热力图" in 文本 or "矩阵" in 文本 or "交叉分析" in 文本:
        return _合并显式字段(自动选字段(画像, "热力图"), first, second)
    if "直方图" in 文本 or "分布情况" in 文本 or "数值分布" in 文本:
        return _合并显式字段(自动选字段(画像, "直方图"), first, second)
    if "堆积" in 文本:
        return _合并显式字段(自动选字段(画像, "堆积柱状图"), first, second)
    if "柱状" in 文本 or "条形" in 文本:
        return _合并显式字段(自动选字段(画像, "柱状图"), first, second)
    if "关系" in 文本 or "相关" in 文本 or "散点" in 文本:
        return _合并显式字段(自动选字段(画像, "散点图"), first, second)
    if "雷达" in 文本:
        return _合并显式字段(自动选字段(画像, "雷达图"), first, second)
    if "词云" in 文本:
        return _合并显式字段(自动选字段(画像, "词云图"), first, second)
    if "漏斗" in 文本 or "转化" in 文本:
        return _合并显式字段(自动选字段(画像, "漏斗图"), first, second)
    if "桑基" in 文本 or "流向" in 文本:
        return _合并显式字段(自动选字段(画像, "桑基图"), first, second)
    if "箱线" in 文本 or "异常" in 文本 or "分布对比" in 文本:
        return _合并显式字段(自动选字段(画像, "箱线图"), first, second)
    if "环形" in 文本 or "甜甜圈" in 文本:
        return _合并显式字段(自动选字段(画像, "环形图"), first, second)
    if "瀑布" in 文本:
        return _合并显式字段(自动选字段(画像, "瀑布图"), first, second)
    if "旭日" in 文本 or "多层" in 文本:
        return _合并显式字段(自动选字段(画像, "旭日图"), first, second)
    if "K线" in 文本 or "行情" in 文本 or "蜡烛" in 文本:
        return _合并显式字段(自动选字段(画像, "K线图"), first, second)
    # 通用意图词（放在具体图表词之前）
    if "占比" in 文本 or "比例" in 文本 or "构成" in 文本:
        # 修复：占比 x 轴优先分类字段（用户说"按股票价格占比"→x=股票代码，不再误选日期），
        # y 轴优先需求提到的数值字段（如"价格占比"→y=价格），未提到才回退"记录数"计数兜底。
        intent_field = _占比维度字段(画像, 文本)
        数值字段 = _匹配数值字段(画像, 文本)
        if intent_field and _合法字段(画像, intent_field):
            if 数值字段:
                override = {"图表类型": "饼图", "x轴": intent_field, "y轴": [数值字段],
                            "分组字段": None, "聚合方式": "求和"}
            else:
                override = {"图表类型": "饼图", "x轴": intent_field, "y轴": ["记录数"],
                            "分组字段": None, "聚合方式": "计数"}
        else:
            override = 自动选字段(画像, "饼图")
        return _合并显式字段(override, first, second)
    if "趋势" in 文本 or "变化" in 文本 or "面积图" in 文本:
        chart = "面积图" if "面积图" in 文本 else "折线图"
        return _合并显式字段(自动选字段(画像, chart), first, second)
    if "统计" in 文本 and "数量" in 文本:
        return _合并显式字段(自动选字段(画像, "柱状图"), first, second)
    if "比较" in 文本 or "对比" in 文本:
        return _合并显式字段(自动选字段(画像, "柱状图"), first, second)
    return {}


def _意图驱动配置(画像: Dict[str, Any], 分析需求: str, df: Optional[Any] = None) -> Dict[str, Any]:
    """规则层意图配置（图表类型 + 筛选 + TopN 三合一）。

    df 可选：传入时额外识别"只看X/排除X/字段=值"筛选与"Top N"排名
    （无 df 的调用方（如编排器降级路径）只拿图表配置，不拿筛选）。
    """
    controlled = _受控语句配置(画像, 分析需求)
    chart_part = (
        {key: value for key, value in controlled.items() if value not in (None, [None])}
        if controlled
        else {}
    )

    需求文本 = 分析需求.strip()
    # 占比意图（与受控语句互斥，保留原逻辑）
    if not chart_part and any(keyword in 需求文本 for keyword in 占比关键词):
        # 修复：占比 x 轴优先分类字段（避免误选日期），y 轴优先需求提到的数值字段。
        目标字段 = _占比维度字段(画像, 需求文本)
        if 目标字段:
            数值字段 = _匹配数值字段(画像, 需求文本)
            if 数值字段:
                chart_part = {"图表类型": "饼图", "x轴": 目标字段, "y轴": [数值字段], "聚合方式": "求和"}
            else:
                chart_part = {"图表类型": "饼图", "x轴": 目标字段, "y轴": ["记录数"], "聚合方式": "计数"}

    if df is not None:
        筛选 = 匹配筛选条件(需求文本, df, 画像)
        topn = 提取TopN(需求文本)
        if 筛选:
            chart_part["筛选条件"] = 筛选
        if topn:
            chart_part["TopN"] = topn
        # 阶段 30：同比环比关键词（"按月环比"→环比，"同比"→同比）
        if "环比" in 需求文本:
            chart_part["对比"] = "环比"
        elif "同比" in 需求文本:
            chart_part["对比"] = "同比"
    return chart_part


def _推荐图表类型(画像: Dict[str, Any], x轴: Optional[str], y轴列表: List[str], 分析需求: str = "") -> str:
    日期字段 = set(画像.get("日期字段", []))
    数值字段 = set(画像.get("数值字段", []))
    分类字段 = set(画像.get("分类字段", []))
    需求文本 = 分析需求.strip()
    # 阶段 34 修复：y轴列表 可能为 None（LLM/规则 override 未给 y轴），统一归一化为 []
    y轴列表 = y轴列表 or []

    if any(keyword in 需求文本 for keyword in 占比关键词):
        return "饼图"
    if x轴 in 日期字段 and y轴列表:
        return "折线图"
    if len(y轴列表) >= 2 and all(field in 数值字段 for field in y轴列表[:2]):
        return "散点图"
    if x轴 in 分类字段 and y轴列表:
        return "柱状图"
    if x轴 and y轴列表:
        return "柱状图"
    return "表格"