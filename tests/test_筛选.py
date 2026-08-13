"""阶段 29 · 条件筛选 + TopN 单元测试：不依赖网络与 LLM key。

覆盖目标
========
- ``数据筛选.应用筛选``：等于/不等于/包含/大于/为空、值类型自动转换、非法条件跳过
- ``数据筛选.提取TopN``：Top 10 / 前5 / 排名前 3，无排名返回 None
- ``数据筛选.匹配筛选条件``：显式"字段=值"、只看X、排除X、非值短语不误触发
- ``上传报表生成器.生成报表数据``：筛选在画像前应用、空结果抛 ValueError、TopN 截断
- ``上传报表生成器._意图驱动配置``：规则层"只看华东区"产出筛选条件（无 LLM key 路径）

设计原则
========
- 全部用受控 DataFrame，秒级跑完；
- 验证"筛选后画像/报表数据与全量不同"，保证筛选真正影响全链路。
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.数据筛选 import 应用筛选, 提取TopN, 匹配筛选条件
from 后端_核心.上传报表生成器 import 生成报表数据, _意图驱动配置


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "地区": ["华东", "华东", "华南", "华北", "华北"],
        "销售额": [100, 200, 300, 400, 500],
        "订单数": [5, 10, 15, 20, 25],
        "月份": ["2024-01", "2024-02", "2024-01", "2024-02", "2024-03"],
    })


@pytest.fixture
def 画像() -> dict:
    return {
        "行数": 5,
        "列数": 4,
        "字段列表": ["地区", "销售额", "订单数", "月份"],
        "数值字段": ["销售额", "订单数"],
        "日期字段": ["月份"],
        "分类字段": ["地区"],
    }


# ============================================================================
# 1. 应用筛选
# ============================================================================

class Test应用筛选:
    def test_数值大于(self, df):
        out, desc = 应用筛选(df, [{"字段": "销售额", "操作": "大于", "值": "250"}])
        assert len(out) == 3
        assert (out["销售额"] > 250).all()
        assert desc == ["销售额 大于 250"]

    def test_字符串等于(self, df):
        out, _ = 应用筛选(df, [{"字段": "地区", "操作": "等于", "值": "华东"}])
        assert len(out) == 2
        assert (out["地区"] == "华东").all()

    def test_包含(self, df):
        out, _ = 应用筛选(df, [{"字段": "地区", "操作": "包含", "值": "华"}])
        assert len(out) == 5  # 华东/华南/华北都含"华"

    def test_不为空(self, df):
        df2 = df.copy()
        df2.loc[0, "销售额"] = None
        out, _ = 应用筛选(df2, [{"字段": "销售额", "操作": "不为空"}])
        assert len(out) == 4

    def test_多条件AND(self, df):
        out, _ = 应用筛选(df, [
            {"字段": "地区", "操作": "不等于", "值": "华东"},
            {"字段": "销售额", "操作": "大于", "值": "350"},
        ])
        assert len(out) == 2  # 华北两条（400/500）

    def test_非法字段跳过(self, df):
        out, _ = 应用筛选(df, [{"字段": "不存在的列", "操作": "等于", "值": "x"}])
        assert len(out) == 5  # 非法条件被跳过，不阻断

    def test_空条件返回原样(self, df):
        out, desc = 应用筛选(df, [])
        assert out.equals(df)
        assert desc == []


# ============================================================================
# 2. 提取TopN
# ============================================================================

class Test提取TopN:
    def test_top10(self):
        assert 提取TopN("销量Top 10的商品") == 10

    def test_前5(self):
        assert 提取TopN("按地区统计前5名") == 5

    def test_排名前3(self):
        assert 提取TopN("排名前 3 的品类") == 3

    def test_无排名(self):
        assert 提取TopN("按地区统计销售额") is None

    def test_上限截断(self):
        assert 提取TopN("Top 99999") == 200


# ============================================================================
# 3. 匹配筛选条件（规则层自然语言）
# ============================================================================

class Test匹配筛选条件:
    def test_显式字段等值(self, df, 画像):
        conds = 匹配筛选条件("按地区=华东统计", df, 画像)
        assert {"字段": "地区", "操作": "等于", "值": "华东"} in conds

    def test_只看短语(self, df, 画像):
        conds = 匹配筛选条件("只看华东区", df, 画像)
        assert {"字段": "地区", "操作": "等于", "值": "华东"} in conds

    def test_排除短语(self, df, 画像):
        conds = 匹配筛选条件("排除华北", df, 画像)
        assert {"字段": "地区", "操作": "不等于", "值": "华北"} in conds

    def test_非值短语不误触发(self, df, 画像):
        # "趋势"不是任何字段的取值 → 不产生筛选条件
        assert 匹配筛选条件("只看趋势", df, 画像) == []


# ============================================================================
# 4. 生成报表数据：筛选与 TopN 真实生效
# ============================================================================

class Test生成报表数据:
    def test_筛选影响报表数据(self, df, 画像):
        report = 生成报表数据(
            df, "按地区统计销售额", 图表类型="柱状图",
            x轴="地区", y轴=["销售额"], 聚合方式="求和",
            筛选条件=[{"字段": "地区", "操作": "等于", "值": "华东"}],
        )
        rows = report["报表数据"]
        # 只剩华东一行（100+200=300）
        assert len(rows) == 1
        assert rows[0]["地区"] == "华东"
        assert rows[0]["销售额"] == 300
        # 画像反映筛选后数据（行数 2，不再是 5）
        assert report["数据画像"]["行数"] == 2
        # 图表配置记录筛选（供 replay/前端展示）
        assert report["图表配置"]["筛选说明"] == ["地区 等于 华东"]

    def test_筛选空结果报错(self, df):
        with pytest.raises(ValueError, match="筛选后没有数据"):
            生成报表数据(
                df, "按地区统计销售额",
                筛选条件=[{"字段": "地区", "操作": "等于", "值": "不存在"}],
            )

    def test_topN截断(self, df):
        report = 生成报表数据(
            df, "按地区统计销售额Top 3", 图表类型="柱状图",
            x轴="地区", y轴=["销售额"], 聚合方式="求和",
        )
        rows = report["报表数据"]
        assert len(rows) == 3  # 5 个地区聚合 → Top 3
        # 降序：华北(900) 华南(300) 华东(300)
        assert rows[0]["销售额"] >= rows[-1]["销售额"]
        assert report["图表配置"]["TopN"] == 3

    def test_规则意图只看华东(self, df, 画像):
        # 无 LLM key 的规则路径：需求文本直接产出筛选条件
        override = _意图驱动配置(画像, "只看华东区", df)
        assert override.get("筛选条件") == [{"字段": "地区", "操作": "等于", "值": "华东"}]

    def test_规则意图TopN(self, df, 画像):
        override = _意图驱动配置(画像, "统计销售额Top 10", df)
        assert override.get("TopN") == 10