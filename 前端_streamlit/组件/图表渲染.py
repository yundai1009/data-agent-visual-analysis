import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from typing import Dict, Any, List, Optional

# 图表类型选项
# 图表类型选项
图表类型选项 = [
    {"值": "auto", "标签": "🤖 自动推荐", "描述": "根据数据特征自动选择最适合的图表"},
    {"值": "line", "标签": "📈 折线图", "描述": "趋势、时间序列"},
    {"值": "bar", "标签": "📊 柱状图", "描述": "分类对比、排名"},
    {"值": "bar_h", "标签": "📊 横向柱状图", "描述": "分类标签较长时"},
    {"值": "area", "标签": "📈 面积图", "描述": "累积趋势、占比变化"},
    {"值": "scatter", "标签": "🔵 散点图", "描述": "两变量相关性、分布"},
    {"值": "heatmap", "标签": "🔥 热力图", "描述": "相关性矩阵、多维度交叉"},
    {"值": "pie", "标签": "🥧 饼图", "描述": "占比、构成"},
    {"值": "donut", "标签": "🍩 环形图", "描述": "占比（带中心指标）"},
    {"值": "treemap", "标签": "🌳 矩形树图", "描述": "层级占比"},
    {"值": "funnel", "标签": "📉 漏斗图", "描述": "转化率、流失分析"},
    {"值": "gauge", "标签": "🎯 仪表盘", "描述": "KPI 单指标监控"},
    {"值": "kpi_card", "标签": "📋 KPI 卡片", "描述": "核心指标卡片"},
    {"值": "table", "标签": "📋 表格", "描述": "明细数据、排序筛选"},
    {"值": "pivot", "标签": "🔄 透视表", "描述": "多维交叉分析"},
    {"值": "waterfall", "标签": "🌊 瀑布图", "描述": "增量分解、桥接分析"},
    {"值": "box", "标签": "📦 箱线图", "描述": "分布、异常值"},
    {"值": "violin", "标签": "🎻 小提琴图", "描述": "分布密度"},
    {"值": "sunburst", "标签": "☀️ 旭日图", "描述": "多层级占比"},
    {"值": "sankey", "标签": "🌊 桑基图", "描述": "流向、转化路径"},
]

def 渲染图表(
    图表配置: Dict[str, Any],
    数据: Optional[pd.DataFrame] = None,
    key: str = "chart",
    可交互: bool = True,
    显示工具栏: bool = True,
):
    """
    统一图表渲染入口
    
    Args:
        图表配置: {
            "类型": "line|bar|pie|...",
            "标题": "图表标题",
            "X轴": "字段名",
            "Y轴": ["字段名1", "字段名2"],
            "颜色": "字段名",
            "分面": "字段名",
            "聚合": "sum|mean|count",
            "图表选项": {...}
        }
        数据: DataFrame（如果配置中未包含数据）
        key: 唯一标识
        可交互: 是否启用缩放、悬停等交互
        显示工具栏: 是否显示 Plotly 工具栏
    """
    
    if 数据 is None:
        数据 = 图表配置.get("数据")
    
    if 数据 is None or (isinstance(数据, pd.DataFrame) and 数据.empty):
        st.info("暂无数据可视化")
        return
    
    # 确保是 DataFrame
    if isinstance(数据, list):
        数据 = pd.DataFrame(数据)
    
    图表类型 = 图表配置.get("类型", "auto")
    
    # 自动推荐图表类型
    if 图表类型 == "auto":
        图表类型 = 推荐图表类型(数据, 图表配置)
        图表配置["类型"] = 图表类型
    
    # 获取渲染函数
    渲染函数映射 = {
        "line": 渲染折线图,
        "bar": 渲染柱状图,
        "bar_h": 渲染横向柱状图,
        "area": 渲染面积图,
        "scatter": 渲染散点图,
        "heatmap": 渲染热力图,
        "pie": 渲染饼图,
        "donut": 渲染环形图,
        "treemap": 渲染矩形树图,
        "funnel": 渲染漏斗图,
        "gauge": 渲染仪表盘,
        "kpi_card": 渲染KPI卡片,
        "table": 渲染表格图表,
        "pivot": 渲染透视表,
        "waterfall": 渲染瀑布图,
        "box": 渲染箱线图,
        "violin": 渲染小提琴图,
        "sunburst": 渲染旭日图,
        "sankey": 渲染桑基图,
    }
    
    渲染函数 = 渲染函数映射.get(图表类型, 渲染表格图表)
    
    try:
        fig = 渲染函数(数据, 图表配置)
        
        if fig is not None:
            # 通用布局配置
            fig.update_layout(
                template="plotly_white",
                title=图表配置.get("标题", ""),
                title_font_size=14,
                title_x=0.5,
                margin=dict(l=40, r=20, t=50, b=40),
                hovermode="x unified" if 图表类型 in ["line", "area", "bar"] else "closest",
                showlegend=图表配置.get("显示图例", True),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                ) if 图表配置.get("图例位置") == "top" else dict(),
            )
            
            # 响应式配置
            config = {
                "displayModeBar": 显示工具栏,
                "displaylogo": False,
                "modeBarButtonsToRemove": ["pan2d", "lasso2d", "select2d"],
                "responsive": True,
            }
            
            st.plotly_chart(fig, use_container_width=True, config=config, key=key)
        else:
            st.warning(f"不支持的图表类型: {图表类型}")
            
    except Exception as e:
        st.error(f"图表渲染失败: {str(e)}")
        if st.checkbox("显示错误详情", key=f"{key}_error_detail"):
            st.exception(e)


def 推荐图表类型(数据: pd.DataFrame, 配置: Dict) -> str:
    """根据数据特征自动推荐图表类型"""
    
    数值列 = 数据.select_dtypes(include='number').columns.tolist()
    分类列 = 数据.select_dtypes(include=['object', 'category']).columns.tolist()
    时间列 = 数据.select_dtypes(include=['datetime64']).columns.tolist()
    
    行数 = len(数据)
    列数 = len(数据.columns)
    
    # 单个数值指标 -> KPI 卡片或仪表盘
    if 行数 == 1 and len(数值列) == 1:
        return "kpi_card"
    
    # 有时间列 + 数值列 -> 折线图/面积图
    if 时间列 and 数值列:
        if 行数 > 50:
            return "area"
        return "line"
    
    # 分类列 + 1个数值列 -> 柱状图
    if 分类列 and len(数值列) == 1:
        if 数据[分类列[0]].nunique() > 15:
            return "bar_h"
        return "bar"
    
    # 分类列 + 多个数值列 -> 分组柱状图
    if 分类列 and len(数值列) > 1:
        return "bar"
    
    # 2个数值列 -> 散点图
    if len(数值列) >= 2 and not 分类列:
        return "scatter"
    
    # 多个数值列 -> 热力图（相关性）
    if len(数值列) >= 3:
        return "heatmap"
    
    # 单分类列且行数少 -> 饼图/环形图
    if 分类列 and 行数 <= 10 and not 数值列:
        return "donut"
    
    # 默认表格
    return "table"


# ===== 具体图表渲染函数 =====

def 渲染折线图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染折线图"""
    
    x轴 = 配置.get("X轴", 数据.columns[0])
    y轴列表 = 配置.get("Y轴", [c for c in 数据.select_dtypes(include='number').columns if c != x轴])
    颜色列 = 配置.get("颜色")
    
    if isinstance(y轴列表, str):
        y轴列表 = [y轴列表]
    
    fig = go.Figure()
    
    for i, y轴 in enumerate(y轴列表):
        if y轴 not in 数据.columns:
            continue
            
        颜色 = px.colors.qualitative.Set1[i % len(px.colors.qualitative.Set1)]
        
        fig.add_trace(go.Scatter(
            x=数据[x轴],
            y=数据[y轴],
            mode="lines+markers",
            name=y轴,
            line=dict(color=颜色, width=2),
            marker=dict(size=6),
            hovertemplate=f"{x轴}: %{{x}}<br>{y轴}: %{{y:,.2f}}<extra></extra>",
        ))
    
    # 如果有颜色分组
    if 颜色列 and 颜色列 in 数据.columns:
        # 这里简化处理，实际应按分组绘制多条线
        pass
    
    fig.update_layout(
        xaxis_title=x轴,
        yaxis_title=" / ".join(y轴列表),
        xaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
        yaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
    )
    
    return fig


def 渲染柱状图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染垂直柱状图"""
    
    x轴 = 配置.get("X轴", 数据.columns[0])
    y轴列表 = 配置.get("Y轴", [c for c in 数据.select_dtypes(include='number').columns if c != x轴])
    颜色列 = 配置.get("颜色")
    堆叠 = 配置.get("堆叠", False)
    
    if isinstance(y轴列表, str):
        y轴列表 = [y轴列表]
    
    fig = go.Figure()
    
    for i, y轴 in enumerate(y轴列表):
        if y轴 not in 数据.columns:
            continue
        
        颜色 = px.colors.qualitative.Set2[i % len(px.colors.qualitative.Set2)]
        
        fig.add_trace(go.Bar(
            x=数据[x轴],
            y=数据[y轴],
            name=y轴,
            marker_color=颜色,
            hovertemplate=f"{x轴}: %{{x}}<br>{y轴}: %{{y:,.2f}}<extra></extra>",
        ))
    
    fig.update_layout(
        xaxis_title=x轴,
        yaxis_title=" / ".join(y轴列表),
        barmode="stack" if 堆叠 else "group",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
    )
    
    return fig


def 渲染横向柱状图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染横向柱状图（适合长标签）"""
    
    y轴 = 配置.get("Y轴", 数据.columns[0])
    x轴列表 = 配置.get("X轴", [c for c in 数据.select_dtypes(include='number').columns if c != y轴])
    
    if isinstance(x轴列表, str):
        x轴列表 = [x轴列表]
    
    fig = go.Figure()
    
    for i, x轴 in enumerate(x轴列表):
        if x轴 not in 数据.columns:
            continue
        
        颜色 = px.colors.qualitative.Set2[i % len(px.colors.qualitative.Set2)]
        
        fig.add_trace(go.Bar(
            y=数据[y轴],
            x=数据[x轴],
            name=x轴,
            orientation='h',
            marker_color=颜色,
            hovertemplate=f"{y轴}: %{{y}}<br>{x轴}: %{{x:,.2f}}<extra></extra>",
        ))
    
    fig.update_layout(
        yaxis_title=y轴,
        xaxis_title=" / ".join(x轴列表),
        barmode="group",
        yaxis=dict(showgrid=False, autorange="reversed"),
        xaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
        height=max(400, len(数据) * 30),
    )
    
    return fig


def 渲染面积图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染堆叠面积图"""
    
    x轴 = 配置.get("X轴", 数据.columns[0])
    y轴列表 = 配置.get("Y轴", [c for c in 数据.select_dtypes(include='number').columns if c != x轴])
    
    if isinstance(y轴列表, str):
        y轴列表 = [y轴列表]
    
    fig = go.Figure()
    
    for i, y轴 in enumerate(y轴列表):
        if y轴 not in 数据.columns:
            continue
        
        颜色 = px.colors.qualitative.Set3[i % len(px.colors.qualitative.Set3)]
        
        fig.add_trace(go.Scatter(
            x=数据[x轴],
            y=数据[y轴],
            mode="lines",
            name=y轴,
            fill='tonexty' if i > 0 else 'tozeroy',
            line=dict(color=颜色, width=1.5),
            hovertemplate=f"{x轴}: %{{x}}<br>{y轴}: %{{y:,.2f}}<extra></extra>",
        ))
    
    fig.update_layout(
        xaxis_title=x轴,
        yaxis_title=" / ".join(y轴列表),
        xaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
        yaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
    )
    
    return fig


def 渲染散点图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染散点图"""
    
    x轴 = 配置.get("X轴", 数据.select_dtypes(include='number').columns[0])
    y轴 = 配置.get("Y轴", 数据.select_dtypes(include='number').columns[1] if len(数据.select_dtypes(include='number').columns) > 1 else 数据.select_dtypes(include='number').columns[0])
    颜色列 = 配置.get("颜色")
    大小列 = 配置.get("大小")
    趋势线 = 配置.get("趋势线", False)
    
    fig = go.Figure()
    
    if 颜色列 and 颜色列 in 数据.columns:
        # 按分类着色
        for i, (分类, 子数据) in enumerate(数据.groupby(颜色列)):
            颜色 = px.colors.qualitative.Set1[i % len(px.colors.qualitative.Set1)]
            fig.add_trace(go.Scatter(
                x=子数据[x轴],
                y=子数据[y轴],
                mode="markers",
                name=str(分类),
                marker=dict(color=颜色, size=8, opacity=0.7),
                hovertemplate=f"{x轴}: %{{x:,.2f}}<br>{y轴}: %{{y:,.2f}}<br>{颜色列}: {分类}<extra></extra>",
            ))
    else:
        大小 = 数据[大小列] if 大小列 and 大小列 in 数据.columns else 8
        fig.add_trace(go.Scatter(
            x=数据[x轴],
            y=数据[y轴],
            mode="markers",
            marker=dict(size=大小, color=px.colors.qualitative.Set1[0], opacity=0.6),
            hovertemplate=f"{x轴}: %{{x:,.2f}}<br>{y轴}: %{{y:,.2f}}<extra></extra>",
        ))
    
    # 趋势线
    if 趋势线:
        import numpy as np
        z = np.polyfit(数据[x轴].dropna(), 数据[y轴].dropna(), 1)
        p = np.poly1d(z)
        fig.add_trace(go.Scatter(
            x=数据[x轴],
            y=p(数据[x轴]),
            mode="lines",
            name="趋势线",
            line=dict(color="red", dash="dash", width=2),
        ))
    
    fig.update_layout(
        xaxis_title=x轴,
        yaxis_title=y轴,
        xaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
        yaxis=dict(showgrid=True, gridcolor="#e5e7eb"),
    )
    
    return fig


def 渲染热力图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染热力图（相关性矩阵或交叉表）"""
    
    数值数据 = 数据.select_dtypes(include='number')
    
    if 数值数据.shape[1] < 2:
        # 如果不是相关性矩阵，尝试透视表
        if 配置.get("行") and 配置.get("列") and 配置.get("数值"):
            透视 = 数据.pivot_table(
                index=配置["行"],
                columns=配置["列"],
                values=配置["数值"],
                aggfunc=配置.get("聚合", "mean")
            )
            矩阵 = 透视.fillna(0)
        else:
            st.warning("热力图需要至少 2 个数值列或指定行/列/数值")
            return None
    else:
        矩阵 = 数值数据.corr()
    
    fig = go.Figure(data=go.Heatmap(
        z=矩阵.values,
        x=矩阵.columns,
        y=矩阵.index,
        colorscale="RdBu",
        zmid=0,
        text=矩阵.values.round(2),
        texttemplate="%{text}",
        textfont={"size": 10},
        hovertemplate="行: %{y}<br>列: %{x}<br>相关性: %{z:.3f}<extra></extra>",
    ))
    
    fig.update_layout(
        xaxis_title="",
        yaxis_title="",
        height=max(400, len(矩阵) * 30),
    )
    
    return fig


def 渲染饼图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染饼图"""
    
    名称列 = 配置.get("名称", 数据.columns[0])
    数值列 = 配置.get("数值", 数据.select_dtypes(include='number').columns[0])
    
    fig = go.Figure(data=[go.Pie(
        labels=数据[名称列],
        values=数据[数值列],
        hole=0,
        textinfo="label+percent",
        textposition="inside",
        hovertemplate="%{label}: %{value:,.2f} (%{percent})<extra></extra>",
        marker=dict(colors=px.colors.qualitative.Set3),
    )])
    
    fig.update_layout(
        showlegend=True,
    )
    
    return fig


def 渲染环形图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染环形图（带中心指标）"""
    
    名称列 = 配置.get("名称", 数据.columns[0])
    数值列 = 配置.get("数值", 数据.select_dtypes(include='number').columns[0])
    中心标题 = 配置.get("中心标题", "总计")
    中心数值 = 配置.get("中心数值", f"{数据[数值列].sum():,.0f}")
    
    fig = go.Figure(data=[go.Pie(
        labels=数据[名称列],
        values=数据[数值列],
        hole=0.6,
        textinfo="label+percent",
        textposition="inside",
        hovertemplate="%{label}: %{value:,.2f} (%{percent})<extra></extra>",
        marker=dict(colors=px.colors.qualitative.Set3),
    )])
    
    fig.add_annotation(
        text=f"<b>{中心标题}</b><br><span style='font-size:24px'>{中心数值}</span>",
        x=0.5, y=0.5,
        font_size=14,
        showarrow=False,
    )
    
    fig.update_layout(
        showlegend=True,
        annotations=[dict(text=中心标题, x=0.5, y=0.55, font_size=12, showarrow=False),
                     dict(text=中心数值, x=0.5, y=0.45, font_size=20, showarrow=False)],
    )
    
    return fig


def 渲染矩形树图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染矩形树图"""
    
    路径 = 配置.get("路径", [数据.columns[0]])
    数值列 = 配置.get("数值", 数据.select_dtypes(include='number').columns[0])
    
    fig = px.treemap(
        数据,
        path=路径,
        values=数值列,
        color=数值列,
        color_continuous_scale="Blues",
    )
    
    return fig


def 渲染漏斗图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染漏斗图"""
    
    阶段列 = 配置.get("阶段", 数据.columns[0])
    数值列 = 配置.get("数值", 数据.select_dtypes(include='number').columns[0])
    
    # 确保按数值降序
    数据 = 数据.sort_values(数值列, ascending=True)
    
    fig = go.Figure(go.Funnel(
        y=数据[阶段列],
        x=数据[数值列],
        textinfo="value+percent initial",
        textposition="inside",
        marker=dict(color=px.colors.sequential.Blues_r),
    ))
    
    return fig


def 渲染仪表盘(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染仪表盘（单指标 KPI）"""
    
    数值 = 配置.get("数值", 数据.select_dtypes(include='number').iloc[0, 0])
    标题 = 配置.get("标题", "指标")
    最小值 = 配置.get("最小值", 0)
    最大值 = 配置.get("最大值", 数值 * 1.5)
    阈值 = 配置.get("阈值", {})  # {"warning": 80, "critical": 90}
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=数值,
        title={"text": 标题, "font": {"size": 20}},
        delta={"reference": 配置.get("目标值", 最大值 * 0.8)},
        gauge={
            "axis": {"range": [最小值, 最大值], "tickwidth": 1},
            "bar": {"color": "#2563eb"},
            "bgcolor": "white",
            "borderwidth": 2,
            "bordercolor": "#e5e7eb",
            "steps": [
                {"range": [最小值, 最大值 * 0.6], "color": "#d1fae5"},
                {"range": [最大值 * 0.6, 最大值 * 0.8], "color": "#fef3c7"},
                {"range": [最大值 * 0.8, 最大值], "color": "#fee2e2"},
            ],
            "threshold": {
                "line": {"color": "red", "width": 4},
                "thickness": 0.75,
                "value": 阈值.get("critical", 最大值 * 0.9)
            }
        }
    ))
    
    fig.update_layout(height=300)
    return fig


def 渲染KPI卡片(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染 KPI 卡片（使用 Plotly Indicator）"""
    
    # 如果数据有多行，取第一行或聚合
    if len(数据) > 1:
        数值 = 数据.select_dtypes(include='number').iloc[0, 0]
    else:
        数值 = 数据.select_dtypes(include='number').iloc[0, 0]
    
    标题 = 配置.get("标题", "KPI")
    前缀 = 配置.get("前缀", "")
    后缀 = 配置.get("后缀", "")
    
    fig = go.Figure(go.Indicator(
        mode="number+delta",
        value=数值,
        number={"prefix": 前缀, "suffix": 后缀, "font": {"size": 48}},
        delta={"reference": 配置.get("对比值"), "relative": True} if 配置.get("对比值") else None,
        title={"text": 标题, "font": {"size": 18}},
    ))
    
    fig.update_layout(height=150, margin=dict(l=20, r=20, t=40, b=20))
    return fig


def 渲染表格图表(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染表格（作为图表的一种）"""
    
    # 这里返回 None，实际表格渲染由 st.dataframe 处理
    # 这个函数仅为了兼容接口
    return None


def 渲染透视表(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染透视表热力图"""
    
    行 = 配置.get("行", 数据.columns[0])
    列 = 配置.get("列", 数据.columns[1] if len(数据.columns) > 1 else 数据.columns[0])
    数值 = 配置.get("数值", 数据.select_dtypes(include='number').columns[0])
    聚合 = 配置.get("聚合", "mean")
    
    透视 = 数据.pivot_table(
        index=行,
        columns=列,
        values=数值,
        aggfunc=聚合,
        fill_value=0
    )
    
    return 渲染热力图(透视.reset_index(), {"行": 行, "列": 列, "数值": 数值})


def 渲染瀑布图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染瀑布图"""
    
    类别列 = 配置.get("类别", 数据.columns[0])
    数值列 = 配置.get("数值", 数据.select_dtypes(include='number').columns[0])
    
    # 计算累积值
    数值列表 = 数据[数值列].tolist()
    累积 = [sum(数值列表[:i+1]) for i in range(len(数值列表))]
    
    fig = go.Figure()
    
    for i, (类别, 数值, 累积值) in enumerate(zip(数据[类别列], 数值列表, 累积)):
        if i == 0:
            底色 = "rgba(37, 99, 235, 0.6)"
            测量 = "absolute"
            底部 = 0
        elif i == len(数值列表) - 1:
            底色 = "rgba(37, 99, 235, 1)"
            测量 = "total"
            底部 = 0
        else:
            底色 = "rgba(37, 99, 235, 0.6)" if 数值 >= 0 else "rgba(220, 38, 38, 0.6)"
            测量 = "relative"
            底部 = 累积值 - 数值
        
        fig.add_trace(go.Waterfall(
            name=类别,
            orientation="v",
            measure=[测量],
            x=[类别],
            y=[数值],
            base=底部,
            connector={"line": {"color": "#9ca3af"}},
            increasing={"marker": {"color": "#059669"}},
            decreasing={"marker": {"color": "#dc2626"}},
            totals={"marker": {"color": "#2563eb"}},
        ))
    
    fig.update_layout(
        xaxis_title=类别列,
        yaxis_title=数值列,
        showlegend=False,
    )
    
    return fig


def 渲染箱线图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染箱线图"""
    
    x轴 = 配置.get("X轴")
    y轴 = 配置.get("Y轴", 数据.select_dtypes(include='number').columns[0])
    
    fig = go.Figure()
    
    if x轴 and x轴 in 数据.columns:
        # 分组箱线图
        for i, (分类, 子数据) in enumerate(数据.groupby(x轴)):
            颜色 = px.colors.qualitative.Set2[i % len(px.colors.qualitative.Set2)]
            fig.add_trace(go.Box(
                y=子数据[y轴],
                name=str(分类),
                marker_color=颜色,
                boxpoints="outliers",
            ))
    else:
        fig.add_trace(go.Box(
            y=数据[y轴],
            name=y轴,
            marker_color=px.colors.qualitative.Set1[0],
            boxpoints="outliers",
        ))
    
    fig.update_layout(
        yaxis_title=y轴,
        xaxis_title=x轴 or "",
    )
    
    return fig


def 渲染小提琴图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染小提琴图"""
    
    x轴 = 配置.get("X轴")
    y轴 = 配置.get("Y轴", 数据.select_dtypes(include='number').columns[0])
    
    fig = go.Figure()
    
    if x轴 and x轴 in 数据.columns:
        for i, (分类, 子数据) in enumerate(数据.groupby(x轴)):
            颜色 = px.colors.qualitative.Set2[i % len(px.colors.qualitative.Set2)]
            fig.add_trace(go.Violin(
                y=子数据[y轴],
                name=str(分类),
                marker_color=颜色,
                box_visible=True,
                meanline_visible=True,
            ))
    else:
        fig.add_trace(go.Violin(
            y=数据[y轴],
            name=y轴,
            marker_color=px.colors.qualitative.Set1[0],
            box_visible=True,
            meanline_visible=True,
        ))
    
    fig.update_layout(
        yaxis_title=y轴,
        xaxis_title=x轴 or "",
    )
    
    return fig


def 渲染旭日图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染旭日图"""
    
    路径 = 配置.get("路径", [数据.columns[0]])
    数值列 = 配置.get("数值", 数据.select_dtypes(include='number').columns[0])
    
    fig = px.sunburst(
        数据,
        path=路径,
        values=数值列,
        color=数值列,
        color_continuous_scale="Blues",
    )
    
    return fig


def 渲染桑基图(数据: pd.DataFrame, 配置: Dict) -> go.Figure:
    """渲染桑基图"""
    
    源列 = 配置.get("源", "source")
    目标列 = 配置.get("目标", "target")
    数值列 = 配置.get("数值", "value")
    
    if not all(c in 数据.columns for c in [源列, 目标列, 数值列]):
        st.warning("桑基图需要 source、target、value 三列")
        return None
    
    # 构建节点
    所有节点 = list(set(数据[源列].tolist() + 数据[目标列].tolist()))
    节点索引 = {节点: i for i, 节点 in enumerate(所有节点)}
    
    源索引 = [节点索引[s] for s in 数据[源列]]
    目标索引 = [节点索引[t] for t in 数据[目标列]]
    数值列表 = 数据[数值列].tolist()
    
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=所有节点,
            color="#2563eb"
        ),
        link=dict(
            source=源索引,
            target=目标索引,
            value=数值列表,
            color="rgba(37, 99, 235, 0.3)"
        )
    )])
    
    fig.update_layout(height=500)
    return fig


# ===== 图表配置编辑器 =====

def 渲染图表配置编辑器(现有配置: Dict = None, key: str = "chart_config"):
    """渲染图表配置编辑器"""
    
    配置 = 现有配置 or {}
    
    with st.expander("⚙️ 图表配置", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            配置["标题"] = st.text_input("图表标题", value=配置.get("标题", ""), key=f"{key}_title")
            
            图表类型 = st.selectbox(
                "图表类型",
                options=[t["值"] for t in 图表类型选项],
                format_func=lambda x: next(t["标签"] for t in 图表类型选项 if t["值"] == x),
                index=[t["值"] for t in 图表类型选项].index(配置.get("类型", "auto")),
                key=f"{key}_type"
            )
            配置["类型"] = 图表类型
            
            配置["显示图例"] = st.checkbox("显示图例", value=配置.get("显示图例", True), key=f"{key}_legend")
        
        with col2:
            # 根据图表类型动态显示字段选择
            if 图表类型 not in ["kpi_card", "gauge", "table"]:
                数值列 = st.session_state.get(f"{key}_numeric_cols", [])
                分类列 = st.session_state.get(f"{key}_categorical_cols", [])
                时间列 = st.session_state.get(f"{key}_datetime_cols", [])
                
                所有列 = 数值列 + 分类列 + 时间列
                
                if 所有列:
                    if 图表类型 in ["line", "area"]:
                        配置["X轴"] = st.selectbox("X 轴 (时间/序列)", 选项=时间列 + 分类列 + 数值列, 
                                                   index=0 if 时间列 else 0, key=f"{key}_x")
                        配置["Y轴"] = st.multiselect("Y 轴 (数值)", 选项=数值列, 
                                                    default=配置.get("Y轴", 数值列[:2]), key=f"{key}_y")
                    elif 图表类型 in ["bar", "bar_h"]:
                        配置["X轴"] = st.selectbox("分类轴", 选项=分类列 + 时间列, key=f"{key}_x_cat")
                        配置["Y轴"] = st.multiselect("数值轴", 选项=数值列, 
                                                    default=配置.get("Y轴", 数值列[:1]), key=f"{key}_y_num")
                    elif 图表类型 in ["scatter"]:
                        配置["X轴"] = st.selectbox("X 轴", 选项=数值列, key=f"{key}_x_scatter")
                        配置["Y轴"] = st.selectbox("Y 轴", 选项=[c for c in 数值列 if c != 配置.get("X轴")], key=f"{key}_y_scatter")
                        配置["颜色"] = st.selectbox("颜色分组 (可选)", 选项=["无"] + 分类列, key=f"{key}_color")
                        配置["趋势线"] = st.checkbox("显示趋势线", key=f"{key}_trend")
        
        # 高级选项
        if 图表类型 in ["bar", "bar_h"]:
            配置["堆叠"] = st.checkbox("堆叠柱状图", value=配置.get("堆叠", False), key=f"{key}_stack")
        
        if 图表类型 == "heatmap":
            配置["行"] = st.selectbox("行维度", 选项=["相关性矩阵"] + 分类列, key=f"{key}_heatmap_row")
            配置["列"] = st.selectbox("列维度", 选项=["相关性矩阵"] + 分类列, key=f"{key}_heatmap_col")
            配置["数值"] = st.selectbox("数值指标", 选项=数值列, key=f"{key}_heatmap_val")
            配置["聚合"] = st.selectbox("聚合方式", 选项=["mean", "sum", "count", "min", "max"], key=f"{key}_heatmap_agg")
        
        if 图表类型 == "funnel":
            配置["阶段"] = st.selectbox("阶段字段", 选项=分类列, key=f"{key}_funnel_stage")
            配置["数值"] = st.selectbox("数值字段", 选项=数值列, key=f"{key}_funnel_val")
        
        if 图表类型 in ["treemap", "sunburst"]:
            配置["路径"] = st.multiselect("层级路径", 选项=分类列, default=配置.get("路径", [分类列[0]]), key=f"{key}_path")
            配置["数值"] = st.selectbox("数值指标", 选项=数值列, key=f"{key}_treemap_val")
        
        if 图表类型 == "sankey":
            配置["源"] = st.selectbox("源节点", 选项=分类列, key=f"{key}_sankey_source")
            配置["目标"] = st.selectbox("目标节点", 选项=分类列, key=f"{key}_sankey_target")
            配置["数值"] = st.selectbox("流量数值", 选项=数值列, key=f"{key}_sankey_val")
    
    return 配置


if __name__ == "__main__":
    # 测试
    st.set_page_config(layout="wide")
    
    import numpy as np
    测试数据 = pd.DataFrame({
        "日期": pd.date_range("2024-01-01", periods=30, freq="D"),
        "GMV": np.random.lognormal(12, 0.3, 30),
        "订单量": np.random.poisson(1000, 30),
        "客单价": np.random.normal(150, 20, 30),
        "渠道": np.random.choice(["App", "小程序", "H5", "PC"], 30),
    })
    
    st.markdown("### 自动推荐图表")
    渲染图表({"类型": "auto", "标题": "自动推荐"}, 数据=测试数据)
    
    st.markdown("---")
    st.markdown("### 指定折线图")
    渲染图表({"类型": "line", "标题": "GMV 趋势", "X轴": "日期", "Y轴": ["GMV", "订单量"]}, 数据=测试数据)
    
    st.markdown("---")
    st.markdown("### 柱状图")
    清单数据 = 测试数据.groupby("渠道").agg({"GMV": "sum", "订单量": "sum"}).reset_index()
    渲染图表({"类型": "bar", "标题": "渠道 GMV 对比", "X轴": "渠道", "Y轴": ["GMV"]}, 数据=清单数据)