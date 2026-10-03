# -*- coding: utf-8 -*-
"""阶段 52：结论生成的 Top-N 事实必须**按数值降序**喂给 LLM。

缺陷（真实用户走查发现，P1 正确性）：
    数据集「中文销售5万行.csv」按城市汇总销量后，真实排名是
    杭州 1093921 > 广州 1068419 > 成都 1059348 > 天津 1058745 > 北京 1055460 …
    但原实现 ``_build_report_summary`` 直接取 ``report_df.head(3)``——
    即"聚合结果的原始前 3 行"（上海/北京/南京），既不是最大也不是最小。
    LLM 只拿到这 3 行，于是写下"北京以 1055460 的销量位居首位"，
    与报表数据表（杭州最高）直接矛盾，用户据此做决策会被误导。

修复纪律：
    1. 排序由代码算（pandas sort_values 降序），不把排名判断交给 LLM；
    2. prompt 明确声明"以下行已按数值降序排列，第 1 行即最大值"，
       并禁止 LLM 在数据之外断言排名；
    3. 无数值列时如实说明未排序。

本测试直接断言 prompt 摘要的顺序与声明语，不依赖真实 LLM。
"""
import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.agent import conclusion as conclusion_mod


def _城市汇总() -> pd.DataFrame:
    """复刻 walkthrough 里 report_df 的形态：首列分类、后列数值。"""
    return pd.DataFrame({
        "城市": ["上海", "北京", "南京", "天津", "广州", "成都", "杭州", "武汉", "深圳", "苏州", "西安", "重庆"],
        "销量": [1030496, 1055460, 1034634, 1058745, 1068419, 1059348, 1093921, 1038557, 1026773, 1024526, 1042777, 1031244],
    })


def test_摘要按数值降序_首行是最大值():
    summary = conclusion_mod._build_report_summary(_城市汇总())
    assert summary.splitlines()[3].strip().startswith("- 城市: 杭州"), (
        f"Top 摘要第 1 行必须是最大值（杭州），实际摘要：\n{summary}"
    )
    # 北京（1055460）真实排名靠后，不应再出现在"前3行"里
    assert "北京" not in summary, f"真实第 5 名不应挤进 Top3 摘要：\n{summary}"
    assert "销量: 1068419" in summary and "销量: 1059348" in summary


def test_摘要显式声明已降序():
    summary = conclusion_mod._build_report_summary(_城市汇总())
    assert "降序" in summary, f"摘要必须声明排序方式，避免 LLM 自行推断排名：\n{summary}"
    assert "第 1 行" in summary or "第一行" in summary


def test_多数值列按最大数值列排序():
    df = pd.DataFrame({
        "城市": ["A", "B", "C"],
        "销量": [10, 300, 20],
        "利润": [5, 7, 900],
    })
    summary = conclusion_mod._build_report_summary(df)
    # 利润最大值在 C 行，应排在首位
    assert summary.index("城市: C, 销量: 20, 利润: 900") < summary.index("城市: B, 销量: 300, 利润: 7")


def test_无聚合行时优雅返回():
    assert "空" in conclusion_mod._build_report_summary(pd.DataFrame())
    assert "空" in conclusion_mod._build_report_summary(None)


def test_系统提示禁止越界断言排名():
    prompt = conclusion_mod._SYSTEM_PROMPT
    assert "降序" in prompt or "排名" in prompt, "系统提示需约束排名表述"
    assert "不要" in prompt or "禁止" in prompt


def test_用户提示携带排序声明():
    """捕获发给 LLM 的 user_content，断言含排序说明。"""
    captured = {}

    def _fake_chat_completion(messages=None, tools=None, tool_choice=None, llm_config=None):
        captured["messages"] = messages
        return {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "生成结论",
                            "arguments": json_dumps({"结论": "杭州最高"}),
                        },
                    }],
                },
            }],
        }

    def json_dumps(obj):
        import json
        return json.dumps(obj, ensure_ascii=False)

    original = conclusion_mod.chat_completion
    conclusion_mod.chat_completion = _fake_chat_completion
    try:
        result = conclusion_mod.润色结论(
            分析需求="按城市统计销售额占比",
            画像={"行数": 50000, "列数": 6, "数据质量": {"等级": "A"}},
            report_df=_城市汇总(),
            推荐说明={"图表类型": "饼图", "理由": ["需求含占比语义"]},
            风险提示=[],
            llm_config=type("Cfg", (), {"api_key": "test-key"})(),
        )
    finally:
        conclusion_mod.chat_completion = original

    assert result == "杭州最高"
    user_msg = captured["messages"][-1]["content"]
    assert "降序" in user_msg, f"user_content 必须声明排序：\n{user_msg}"
    assert "城市: 杭州, 销量: 1093921" in user_msg, f"user_content 必须含真实最大值：\n{user_msg}"