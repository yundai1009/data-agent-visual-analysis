# -*- coding: utf-8 -*-
"""阶段 55 · Task1 标识符/编码字段识别器测试。

约束 2 的基石：标识符/编码 ID 类字段严禁作 Y 轴/数值度量，仅可作分类 X 轴。
- 字段名命中 id/编号/编码/code/序号/单号/uuid/标识 等模式 → 识别为标识符
- 高基数数值字段（唯一值数 ≈ 行数，如 user_id/score 类）→ 识别为标识符
"""
import pytest

from 后端_核心 import refine_report


def test_字段名模式_识别ID字段():
    画像 = {
        "字段列表": ["订单ID", "客户编号", "金额", "地区", "切入股票代码", "用户名"],
        "数值字段": ["金额"],
        "分类字段": ["地区", "切入股票代码"],
        "文本字段": ["用户名"],
        "行数": 100,
    }
    识别 = set(refine_report.标识符字段(画像))
    # 字段名模式命中
    assert {"订单ID", "客户编号", "切入股票代码"} <= 识别
    # 普通字段不应误判
    assert "金额" not in 识别
    assert "地区" not in 识别


def test_英文大小写ID字段():
    画像 = {
        "字段列表": ["user_id", "userId", "sales", "region"],
        "数值字段": ["sales"], "分类字段": ["region"], "文本字段": [],
        "行数": 50,
    }
    识别 = set(refine_report.标识符字段(画像))
    assert "user_id" in 识别
    assert "userId" in 识别
    assert "sales" not in 识别


def test_高基数数值字段_是标识符():
    # 唯一值数 ≈ 行数（高基数）= 标识符，如 user_id 类数值 ID 列
    画像 = {
        "字段列表": ["user_id", "score"],
        "数值字段": ["user_id", "score"],
        "分类字段": [], "文本字段": [],
        "行数": 9000,
        "唯一值数": {"user_id": 9000, "score": 120},
    }
    assert "user_id" in refine_report.标识符字段(画像)
    assert "score" not in refine_report.标识符字段(画像)


def test_无标识符_返回空():
    画像 = {
        "字段列表": ["地区", "销售额", "日期"],
        "数值字段": ["销售额"], "分类字段": ["地区"], "日期字段": ["日期"],
        "文本字段": [], "行数": 30,
    }
    assert refine_report.标识符字段(画像) == []


def test_唯一值数缺失时_仅按字段名模式():
    # 无唯一值数信息时不能崩溃，且只按名字判断
    画像 = {
        "字段列表": ["ID", "金额"],
        "数值字段": ["ID", "金额"], "分类字段": [], "文本字段": [],
        "行数": 10,
    }
    识别 = refine_report.标识符字段(画像)
    assert "ID" in 识别
    assert "金额" not in 识别
