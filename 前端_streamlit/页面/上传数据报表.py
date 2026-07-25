from __future__ import annotations

import pandas as pd
import streamlit as st

from 后端_核心.文件数据服务 import 读取上传表格
from 后端_核心.数据画像 import 生成数据画像
from 后端_核心.上传报表生成器 import 生成报表数据
from 前端_streamlit.组件.图表渲染 import 渲染图表
from 前端_streamlit.组件.结果表格 import 渲染结果表格
from 前端_streamlit.样式.自定义样式 import 渲染指标卡片, 渲染页面标题


图表类型选项 = ["自动推荐", "柱状图", "折线图", "饼图", "散点图", "表格"]
聚合方式选项 = ["求和", "平均值", "计数", "最大值", "最小值"]


def _展示字段列表(title: str, fields: list[str]) -> None:
    if fields:
        st.markdown(f"**{title}**：" + "、".join(f"`{field}`" for field in fields))
    else:
        st.markdown(f"**{title}**：无")


def _渲染数据画像(画像: dict) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        渲染指标卡片("数据行数", f"{画像.get('行数', 0):,}", 图标="📄")
    with col2:
        渲染指标卡片("字段数量", f"{画像.get('列数', 0):,}", 图标="🧩")
    with col3:
        渲染指标卡片("缺失值", f"{画像.get('总缺失值', 0):,}", 图标="⚠️")

    with st.expander("字段画像", expanded=True):
        _展示字段列表("数值字段", 画像.get("数值字段", []))
        _展示字段列表("日期字段", 画像.get("日期字段", []))
        _展示字段列表("分类字段", 画像.get("分类字段", []))
        _展示字段列表("文本字段", 画像.get("文本字段", []))

        缺失值 = 画像.get("缺失值", {})
        if 缺失值:
            st.markdown("**缺失值统计**")
            st.dataframe(
                pd.DataFrame([{"字段": key, "缺失值": value} for key, value in 缺失值.items()]),
                use_container_width=True,
                hide_index=True,
            )


def _默认_x轴(画像: dict) -> str:
    for group in ["日期字段", "分类字段", "文本字段", "字段列表"]:
        fields = 画像.get(group, [])
        if fields:
            return fields[0]
    return "无"


def _默认_y轴(画像: dict) -> list[str]:
    fields = 画像.get("数值字段", [])
    return fields[:1]


def 上传数据报表() -> None:
    """上传 CSV/Excel 并生成第一阶段可视化报表。"""
    渲染页面标题(
        "上传报表",
        "上传自己的 CSV 或 Excel 数据，用自然语言描述目标，并选择图表类型生成可视化报表。",
        "📤",
    )

    st.info("第一阶段版本：数据只在当前会话中读取和展示，不会持久化保存。", icon="ℹ️")

    uploaded_file = st.file_uploader(
        "上传 CSV 或 Excel 文件",
        type=["csv", "xlsx", "xls"],
        help="建议上传一张结构化表格，第一行作为字段名。",
    )

    if uploaded_file is None:
        st.markdown("### 使用步骤")
        st.markdown(
            "1. 上传 `.csv`、`.xlsx` 或 `.xls` 文件\n"
            "2. 查看数据预览和字段画像\n"
            "3. 输入自然语言分析需求\n"
            "4. 选择图表类型、字段和聚合方式\n"
            "5. 点击生成可视化报表"
        )
        return

    try:
        df = 读取上传表格(uploaded_file)
        画像 = 生成数据画像(df)
    except Exception as exc:
        st.error(f"文件读取失败：{exc}")
        return

    st.markdown("### ① 数据预览")
    _渲染数据画像(画像)
    st.dataframe(df.head(20), use_container_width=True)

    st.markdown("---")
    st.markdown("### ② 配置报表")

    分析需求 = st.text_area(
        "你想分析什么？",
        placeholder="例如：按月份分析销售额趋势，并找出销售额最高的地区。",
        height=110,
    )

    all_fields = 画像.get("字段列表", [])
    numeric_fields = 画像.get("数值字段", [])
    x_default = _默认_x轴(画像)
    y_default = _默认_y轴(画像)

    col_chart, col_x, col_y = st.columns(3)
    with col_chart:
        图表类型 = st.selectbox("图表类型", 图表类型选项, index=0)
    with col_x:
        x轴 = st.selectbox(
            "X轴 / 分类字段",
            all_fields,
            index=all_fields.index(x_default) if x_default in all_fields else 0,
        )
    with col_y:
        y轴 = st.multiselect("Y轴 / 数值字段", numeric_fields, default=y_default)

    col_group, col_agg = st.columns(2)
    with col_group:
        分组字段 = st.selectbox("分组字段（可选）", ["无"] + all_fields, index=0)
    with col_agg:
        聚合方式 = st.selectbox("聚合方式", 聚合方式选项, index=0)

    if 图表类型 != "表格" and not y轴:
        st.warning("请选择至少一个数值字段作为 Y轴，或将图表类型改为表格。")

    if st.button("生成可视化报表", type="primary", use_container_width=True):
        try:
            报表 = 生成报表数据(
                df=df,
                分析需求=分析需求,
                图表类型=图表类型,
                x轴=x轴,
                y轴=y轴,
                分组字段=分组字段,
                聚合方式=聚合方式,
            )
            st.session_state["上传报表结果"] = 报表
        except Exception as exc:
            st.error(f"报表生成失败：{exc}")
            return

    报表 = st.session_state.get("上传报表结果")
    if not 报表:
        return

    st.markdown("---")
    st.markdown("### ③ 可视化报表")
    st.caption(f"图表类型：{报表.get('图表类型', '未知')}")

    tab_chart, tab_data, tab_summary = st.tabs(["图表", "报表数据", "结论"])
    with tab_chart:
        渲染图表(报表["图表配置"], key="上传报表图表")
    with tab_data:
        渲染结果表格(报表["报表数据"], key="上传报表数据表格")
    with tab_summary:
        st.markdown(报表["结论"])
