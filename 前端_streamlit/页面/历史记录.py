import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from 前端_streamlit.样式.自定义样式 import 渲染页面标题, 渲染指标卡片, 渲染徽章
from 前端_streamlit.服务.api客户端 import 获取任务列表, 获取任务详情, 删除任务, 重新执行任务
from 前端_streamlit.组件.结果表格 import 渲染结果表格
from 前端_streamlit.组件.图表渲染 import 渲染图表


# 修改函数名
def 历史记录():
    """历史记录页面"""

    渲染页面标题(
        "分析记录",
        "查看过去提交的问题、生成的 SQL、查询数据和分析结论",
        "📜"
    )

    st.info("这里用于复查已经完成的分析。新用户请先到「开始分析」提交第一个问题。", icon="ℹ️")

    # 筛选器区域
    with st.container():
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 1])

        with col1:
            状态筛选 = st.selectbox(
                "任务状态",
                ["全部", "完成", "运行中", "失败", "取消"],
                index=0
            )

        with col2:
            时间范围 = st.selectbox(
                "时间范围",
                ["最近 24 小时", "最近 7 天", "最近 30 天", "自定义"],
                index=1
            )

        with col3:
            if 时间范围 == "自定义":
                开始日期 = st.date_input("开始日期", value=datetime.now() - timedelta(days=7))
                结束日期 = st.date_input("结束日期", value=datetime.now())
            else:
                结束日期 = datetime.now()
                if 时间范围 == "最近 24 小时":
                    开始日期 = 结束日期 - timedelta(hours=24)
                elif 时间范围 == "最近 7 天":
                    开始日期 = 结束日期 - timedelta(days=7)
                elif 时间范围 == "最近 30 天":
                    开始日期 = 结束日期 - timedelta(days=30)
                开始日期 = 开始日期.date()
                结束日期 = 结束日期.date()

        with col4:
            关键词搜索 = st.text_input("关键词搜索", placeholder="搜索问题、SQL、标签...")

        with col5:
            刷新按钮 = st.button("🔄 刷新", use_container_width=True)

    # 获取任务列表
    if 刷新按钮 or "任务列表缓存" not in st.session_state:
        with st.spinner("加载任务列表..."):
            任务列表 = 获取任务列表(
                状态=状态筛选 if 状态筛选 != "全部" else None,
                开始时间=开始日期,
                结束时间=结束日期,
                关键词=关键词搜索 if 关键词搜索 else None,
                页码=1,
                每页大小=50
            )
            st.session_state.任务列表缓存 = 任务列表
    else:
        任务列表 = st.session_state.任务列表缓存

    # 统计概览
    if 任务列表:
        总数 = 任务列表.get("总数", 0)
        完成数 = len([t for t in 任务列表.get("数据", []) if t.get("状态") == "完成"])
        失败数 = len([t for t in 任务列表.get("数据", []) if t.get("状态") == "失败"])
        平均耗时 = sum(t.get("执行耗时秒", 0) for t in 任务列表.get("数据", []) if t.get("执行耗时秒")) / max(完成数, 1)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            渲染指标卡片("总任务数", f"{总数:,}", 图标="📋")
        with col2:
            渲染指标卡片("完成数", f"{完成数:,}", f"{(完成数 / max(总数, 1) * 100):.1f}%", "正向", "✅")
        with col3:
            渲染指标卡片("失败数", f"{失败数:,}", f"{(失败数 / max(总数, 1) * 100):.1f}%",
                         "负向" if 失败数 > 0 else "正向", "❌")
        with col4:
            渲染指标卡片("平均耗时", f"{平均耗时:.1f}s", 图标="⏱️")

    st.markdown("---")

    # 任务列表表格
    st.markdown("### 任务列表")

    if not 任务列表 or not 任务列表.get("数据"):
        st.info("暂无任务记录")
        return

    # 构建显示用 DataFrame
    显示数据 = []
    for 任务 in 任务列表["数据"]:
        状态 = 任务.get("状态", "未知")
        状态徽章 = {
            "完成": ("完成", "success"),
            "运行中": ("运行中", "info"),
            "失败": ("失败", "danger"),
            "取消": ("取消", "warning"),
        }.get(状态, (状态, "info"))

        显示数据.append({
            "任务ID": 任务.get("任务ID", "")[:8] + "...",
            "完整ID": 任务.get("任务ID", ""),
            "问题": 任务.get("问题", "")[:80] + ("..." if len(任务.get("问题", "")) > 80 else ""),
            "状态": 状态,
            "状态显示": 状态徽章[0],
            "状态类型": 状态徽章[1],
            "创建时间": 任务.get("创建时间", ""),
            "完成时间": 任务.get("完成时间", "") or "-",
            "执行耗时(秒)": 任务.get("执行耗时秒", 0),
            "Token消耗": 任务.get("Token消耗", 0),
            "成本(元)": 任务.get("成本_元", 0),
        })

    df = pd.DataFrame(显示数据)

    # 使用 st.dataframe 显示（支持列配置）
    列配置 = {
        "任务ID": st.column_config.TextColumn("任务ID", width="small"),
        "完整ID": None,  # 隐藏
        "问题": st.column_config.TextColumn("分析问题", width="large"),
        "状态": None,  # 隐藏原始状态
        "状态显示": st.column_config.TextColumn("状态", width="small"),
        "状态类型": None,
        "创建时间": st.column_config.DatetimeColumn("创建时间", width="medium", format="YYYY-MM-DD HH:mm"),
        "完成时间": st.column_config.DatetimeColumn("完成时间", width="medium", format="YYYY-MM-DD HH:mm"),
        "执行耗时(秒)": st.column_config.NumberColumn("耗时(s)", width="small", format="%.1f"),
        "Token消耗": st.column_config.NumberColumn("Token", width="small", format="%d"),
        "成本(元)": st.column_config.NumberColumn("成本(¥)", width="small", format="%.4f"),
    }

    # 交互式表格
    选中行 = st.dataframe(
        df,
        column_config=列配置,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="历史任务表格"
    )

    # 处理行选择
    if 选中行.selection.rows:
        选中索引 = 选中行.selection.rows[0]
        选中任务 = 任务列表["数据"][选中索引]
        显示任务详情(选中任务)


def 显示任务详情(任务: dict):
    """在侧边弹窗或展开区显示任务详情"""

    with st.expander(f"📋 任务详情: {任务.get('任务ID', '')[:8]}...", expanded=True):
        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown("**原始问题**")
            st.markdown(f"> {任务.get('问题', '无')}")

            st.markdown("**生成的 SQL**")
            if 任务.get("SQL"):
                st.code(任务["SQL"], language="sql")
            else:
                st.info("暂无 SQL")

            st.markdown("**结构化结论**")
            if 任务.get("结论"):
                st.markdown(任务["结论"])
            else:
                st.info("暂无结论")

        with col2:
            st.markdown("**执行指标**")
            渲染指标卡片("状态", 任务.get("状态", "未知"), 图标="📌")
            渲染指标卡片("执行耗时", f"{任务.get('执行耗时秒', 0):.1f}s", 图标="⏱️")
            渲染指标卡片("返回行数", f"{任务.get('返回行数', 0):,}", 图标="📋")
            渲染指标卡片("Token 消耗", f"{任务.get('Token消耗', 0):,}", 图标="🔤")
            渲染指标卡片("预估成本", f"¥{任务.get('成本_元', 0):.4f}", 图标="💰")
            渲染指标卡片("创建时间", 任务.get("创建时间", "-"), 图标="🕐")
            渲染指标卡片("完成时间", 任务.get("完成时间", "-"), 图标="✅")

            st.markdown("---")

            # 操作按钮
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔄 重新执行", use_container_width=True, key=f"重跑_{任务['任务ID']}"):
                    新任务ID = 重新执行任务(任务["任务ID"])
                    if 新任务ID:
                        st.success(f"已创建新任务: {新任务ID[:8]}...")
                        st.session_state.pop("任务列表缓存", None)
                        st.rerun()

            with col_b:
                if st.button("🗑️ 删除记录", use_container_width=True, type="secondary", key=f"删除_{任务['任务ID']}"):
                    if 删除任务(任务["任务ID"]):
                        st.success("删除成功")
                        st.session_state.pop("任务列表缓存", None)
                        st.rerun()

            # 数据预览
            if 任务.get("数据"):
                st.markdown("**数据预览 (前 10 行)**")
                df = pd.DataFrame(任务["数据"]).head(10)
                渲染结果表格(df, key=f"详情数据_{任务['任务ID']}")

            # 图表预览
            if 任务.get("图表"):
                st.markdown("**图表预览**")
                for i, 图表配置 in enumerate(任务["图表"]):
                    渲染图表(图表配置, key=f"详情图表_{任务['任务ID']}_{i}")


if __name__ == "__main__":
    历史记录()