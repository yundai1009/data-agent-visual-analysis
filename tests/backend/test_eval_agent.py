"""评测闭环回归测试：golden set 完整性与脚本可运行性。

不锁定具体分数（规则改进会让分数变化，锁分会制造脆弱测试），
只保证：36 条结构完整、评测函数可离线跑通、统计字段齐全。
"""
from __future__ import annotations

import pytest

from scripts.eval_agent import DEFAULT_GOLDEN, 评测

GOLDEN_KEYS = {"需求", "画像", "期望"}
EXPECT_KEYS = {"图表类型", "x轴", "y轴", "聚合方式"}
PROFILE_KEYS = {"字段列表", "数值字段", "分类字段"}


def test_golden_set_数量与结构():
    """36 条，每条含 需求/画像/期望，期望含四维字段。"""
    assert len(DEFAULT_GOLDEN) == 36, f"golden 条数应为 36，实际 {len(DEFAULT_GOLDEN)}"
    for i, case in enumerate(DEFAULT_GOLDEN):
        assert GOLDEN_KEYS <= set(case.keys()), f"第 {i + 1} 条缺字段: {case.keys()}"
        画像 = case["画像"]
        assert "字段列表" in 画像, f"第 {i + 1} 条画像缺 字段列表"
        assert all(
            k in case["期望"] for k in EXPECT_KEYS
        ), f"第 {i + 1} 条期望缺字段: {case['期望'].keys()}"


def test_评测_规则路径可离线跑通():
    """规则路径评测不抛异常，返回统计字段齐全（无 LLM key 也秒级完成）。"""
    result = 评测(verbose=False, enable_llm=False)
    assert result["总用例"] == 36
    for key in ("完全匹配率", "图表类型准确率", "X轴命中率", "Y轴命中率", "聚合方式命中率"):
        assert key in result, f"缺统计字段 {key}"
    # 不锁定具体分数，但完全匹配率应是可解析的百分比字符串
    assert result["完全匹配率"].endswith("%")
