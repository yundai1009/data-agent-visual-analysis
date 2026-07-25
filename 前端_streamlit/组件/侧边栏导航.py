from __future__ import annotations

import streamlit as st


def 渲染侧边栏() -> str:
    """渲染上传数据报表的简化侧边栏。"""
    with st.sidebar:
        st.markdown(
            """
            <div style="padding:1.25rem .75rem 1rem; border-bottom:1px solid #E2E8F0; margin-bottom:1rem;">
                <div style="font-size:1.35rem; font-weight:800; color:#0F172A; letter-spacing:-.02em;">数据报表 Agent</div>
                <div style="font-size:.82rem; color:#64748B; margin-top:.35rem; line-height:1.45;">上传 CSV / Excel，自动生成可视化报表。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div style="font-size:.82rem; color:#64748B; line-height:1.65;">
                ① 上传文件<br>
                ② 选择字段和图表类型<br>
                ③ 生成可视化报表
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div style="margin-top:1.5rem; font-size:.75rem; color:#94A3B8;">
                CSV/Excel + Plotly
            </div>
            """,
            unsafe_allow_html=True,
        )

    return "上传报表"
