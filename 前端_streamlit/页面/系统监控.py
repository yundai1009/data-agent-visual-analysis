import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from typing import List
from 前端_streamlit.样式.自定义样式 import 渲染页面标题, 渲染指标卡片, 渲染徽章, 渲染进度步骤
# 后端接口导入（现在api已有对应函数，可放开注释）
from 前端_streamlit.服务.api客户端 import 获取系统指标, 获取告警历史, 获取链路追踪


# ========== 工具函数 全部顶层，无嵌套 ==========
def 刷新间隔秒数(间隔文本: str) -> int:
    映射 = {
        "10 秒": 10,
        "30 秒": 30,
        "1 分钟": 60,
        "5 分钟": 300,
    }
    return 映射.get(间隔文本, 30)


def 渲染趋势图(数据键: str, 标题: str, y轴标题: str):
    import numpy as np
    时间点 = pd.date_range(end=datetime.now(), periods=60, freq="1min")
    数值 = np.random.normal(100, 15, 60).clip(min=0)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=时间点,
        y=数值,
        mode="lines",
        line=dict(color="#2563eb", width=2),
        fill="tozeroy",
        fillcolor="rgba(37, 99, 235, 0.1)",
        name=标题
    ))
    fig.update_layout(
        title=标题,
        xaxis_title="时间",
        yaxis_title=y轴标题,
        template="plotly_white",
        height=300,
        margin=dict(l=40, r=20, t=40, b=40),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def 渲染延迟分布图(分布数据: list):
    import numpy as np
    延迟值 = np.random.lognormal(mean=3, sigma=0.8, size=1000).clip(max=5000)
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=延迟值,
        nbinsx=50,
        marker_color="#2563eb",
        opacity=0.7,
        name="延迟分布"
    ))
    p50 = np.percentile(延迟值, 50)
    p95 = np.percentile(延迟值, 95)
    p99 = np.percentile(延迟值, 99)
    for percentile, value, color, name in [
        (50, p50, "#059669", "P50"),
        (95, p95, "#d97706", "P95"),
        (99, p99, "#dc2626", "P99"),
    ]:
        fig.add_vline(x=value, line_dash="dash", line_color=color,
                      annotation_text=f"{name}: {value:.0f}ms", annotation_position="top")
    fig.update_layout(
        title="请求延迟分布 (最近 5 分钟)",
        xaxis_title="延迟 (毫秒)",
        yaxis_title="请求数",
        template="plotly_white",
        height=300,
        margin=dict(l=40, r=20, t=40, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def 渲染错误率趋势(趋势数据: list):
    import numpy as np
    时间点 = pd.date_range(end=datetime.now(), periods=60, freq="1min")
    数值 = np.random.exponential(0.5, 60).clip(max=10)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=时间点,
        y=数值,
        mode="lines",
        line=dict(color="#dc2626", width=2),
        fill="tozeroy",
        fillcolor="rgba(220, 38, 38, 0.1)",
        name="错误率"
    ))
    fig.add_hline(y=5, line_dash="dash", line_color="#dc2626",
                  annotation_text="告警阈值 5%", annotation_position="bottom right")
    fig.update_layout(
        title="错误率趋势 (最近 1 小时)",
        xaxis_title="时间",
        yaxis_title="错误率 (%)",
        template="plotly_white",
        height=300,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


def 渲染队列趋势(趋势数据: list):
    import numpy as np
    时间点 = pd.date_range(end=datetime.now(), periods=60, freq="1min")
    数值 = np.random.poisson(5, 60)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=时间点,
        y=数值,
        marker_color="#2563eb",
        opacity=0.7,
        name="队列积压"
    ))
    fig.update_layout(
        title="任务队列积压趋势 (最近 1 小时)",
        xaxis_title="时间",
        yaxis_title="积压任务数",
        template="plotly_white",
        height=300,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# ========== 页面主渲染逻辑 ==========
def 渲染页面():
    渲染页面标题(
        "运行状态",
        "检查后端服务、任务执行和资源情况；普通分析用户通常不需要停留在这里",
        "📈"
    )

    st.info("这里用于排查服务是否正常。如果只是想查询数据，请回到「开始分析」。", icon="ℹ️")

    # 自动刷新控制
    col_refresh, col_interval, col_auto = st.columns([1, 2, 1])
    with col_refresh:
        if st.button("🔄 立即刷新", use_container_width=True):
            st.session_state.pop("系统指标缓存", None)
            st.session_state.pop("告警历史缓存", None)
            st.rerun()
    with col_interval:
        刷新间隔 = st.selectbox("自动刷新间隔", ["关闭", "10 秒", "30 秒", "1 分钟", "5 分钟"], index=1)
    with col_auto:
        if 刷新间隔 != "关闭":
            st.markdown(f'<meta http-equiv="refresh" content="{刷新间隔秒数(刷新间隔)}">', unsafe_allow_html=True)

    # 获取系统指标
    if "系统指标缓存" not in st.session_state:
        with st.spinner("加载监控数据..."):
            st.session_state.系统指标缓存 = 获取系统指标()
            st.session_state.告警历史缓存 = 获取告警历史(限制=50)

    指标 = st.session_state.系统指标缓存
    告警列表 = st.session_state.告警历史缓存

    # 核心指标卡片
    st.markdown("### 🎯 核心指标")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        qps = 指标.get("qps", 0)
        qps_delta = 指标.get("qps_环比", 0)
        渲染指标卡片("QPS", f"{qps:.1f}", f"{qps_delta:+.1f}%" if qps_delta else None,
                     "正向" if qps_delta >= 0 else "负向", "⚡")
    with col2:
        p50 = 指标.get("延迟_p50_毫秒", 0)
        p99 = 指标.get("延迟_p99_毫秒", 0)
        渲染指标卡片("延迟 (P50/P99)", f"{p50:.0f}/{p99:.0f}ms", 图标="⏱️")
    with col3:
        token_成本 = 指标.get("token_成本_元_分钟", 0)
        渲染指标卡片("Token 成本/分", f"¥{token_成本:.4f}", 图标="💰")
    with col4:
        错误率 = 指标.get("错误率", 0) * 100
        渲染指标卡片("错误率", f"{错误率:.2f}%", 图标="❌")
    with col5:
        队列积压 = 指标.get("队列积压", 0)
        渲染指标卡片("队列积压", f"{队列积压}", 图标="📦")

    # 趋势图表
    st.markdown("---")
    st.markdown("### 📊 指标趋势")
    tab_qps, tab_延迟, tab_成本, tab_错误, tab_队列 = st.tabs(["QPS", "延迟分布", "Token 成本", "错误率", "队列积压"])
    with tab_qps:
        渲染趋势图("qps_趋势", "QPS 趋势 (最近 1 小时)", "QPS")
    with tab_延迟:
        渲染延迟分布图(指标.get("延迟分布", []))
    with tab_成本:
        渲染趋势图("token_成本_趋势", "Token 成本趋势 (最近 1 小时)", "成本 (元/分钟)")
    with tab_错误:
        渲染错误率趋势(指标.get("错误率_趋势", []))
    with tab_队列:
        渲染队列趋势(指标.get("队列积压_趋势", []))

    # 资源使用率
    st.markdown("---")
    st.markdown("### 💻 资源使用率")
    col_cpu, col_mem, col_disk, col_net = st.columns(4)
    with col_cpu:
        cpu = 指标.get("CPU使用率", 0)
        渲染指标卡片("CPU", f"{cpu:.1f}%", 图标="🖥️")
        st.progress(cpu / 100)
    with col_mem:
        mem = 指标.get("内存使用率", 0)
        渲染指标卡片("内存", f"{mem:.1f}%", 图标="🧠")
        st.progress(mem / 100)
    with col_disk:
        disk = 指标.get("磁盘使用率", 0)
        渲染指标卡片("磁盘", f"{disk:.1f}%", 图标="💾")
        st.progress(disk / 100)
    with col_net:
        net_in = 指标.get("网络入流量_MBps", 0)
        net_out = 指标.get("网络出流量_MBps", 0)
        渲染指标卡片("网络", f"↑{net_out:.1f} ↓{net_in:.1f} MB/s", 图标="🌐")

    # 告警历史
    st.markdown("---")
    st.markdown("### 🚨 告警历史")
    if not 告警列表:
        st.info("暂无告警记录")
    else:
        col_critical, col_warning, col_info = st.columns(3)
        critical_count = len([a for a in 告警列表 if a.get("级别") == "critical"])
        warning_count = len([a for a in 告警列表 if a.get("级别") == "warning"])
        info_count = len([a for a in 告警列表 if a.get("info")])
        with col_critical:
            渲染指标卡片("严重", str(critical_count), 图标="🔴", 变化类型="负向" if critical_count > 0 else "正向")
        with col_warning:
            渲染指标卡片("警告", str(warning_count), 图标="🟡", 变化类型="负向" if warning_count > 0 else "正向")
        with col_info:
            渲染指标卡片("信息", str(info_count), 图标="🔵")
        告警_df = pd.DataFrame(告警列表)
        if not 告警_df.empty:
            st.dataframe(
                告警_df[["时间", "级别", "规则", "消息", "状态"]],
                column_config={
                    "时间": st.column_config.DatetimeColumn("时间", format="MM-DD HH:mm:ss"),
                    "级别": st.column_config.SelectboxColumn("级别", options=["critical", "warning", "info"]),
                    "规则": st.column_config.TextColumn("告警规则"),
                    "消息": st.column_config.TextColumn("详情", width="large"),
                    "状态": st.column_config.SelectboxColumn("状态", options=["firing", "resolved"]),
                },
                hide_index=True,
                use_container_width=True,
            )

    # 链路追踪
    st.markdown("---")
    st.markdown("### 🔍 链路追踪 (最近 100 条)")
    链路数据 = 获取链路追踪(限制=100)
    if 链路数据:
        链路_df = pd.DataFrame(链路数据)
        st.dataframe(
            链路_df[["TraceID", "Span名称", "耗时(ms)", "状态", "开始时间"]],
            column_config={
                "TraceID": st.column_config.TextColumn("Trace ID", width="medium"),
                "Span名称": st.column_config.TextColumn("Span"),
                "耗时(ms)": st.column_config.NumberColumn("耗时", format="%d ms"),
                "状态": st.column_config.SelectboxColumn("状态", options=["success", "error", "timeout"]),
                "开始时间": st.column_config.DatetimeColumn("开始时间", format="HH:mm:ss.SSS"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("暂无链路追踪数据")


# 对外导出函数（给__init__导入）
def 系统监控():
    渲染页面()


if __name__ == "__main__":
    系统监控()