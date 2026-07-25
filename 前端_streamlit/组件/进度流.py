import streamlit as st
from typing import List, Dict, Any, Optional
from 前端_streamlit.样式.自定义样式 import 渲染徽章

def 渲染进度流(
    步骤列表: List[Dict[str, str]],
    当前步骤: int,
    任务ID: str,
    容器: Optional[st.delta_generator.DeltaGenerator] = None,
):
    """
    渲染 Agent 执行进度流（垂直时间轴样式）
    
    Args:
        步骤列表: [{"标题": "...", "描述": "..."}, ...]
        当前步骤: 当前执行到的步骤索引（0-based）
        任务ID: 任务 ID
        容器: 可选的 Streamlit 容器
    """
    
    目标容器 = 容器 if 容器 else st
    
    目标容器.markdown(f"""
    <div style="margin-bottom: 1rem;">
        <span class="badge badge-info">任务 ID: {任务ID[:8]}...</span>
        <span class="badge badge-primary" style="margin-left: 0.5rem;">步骤 {当前步骤 + 1} / {len(步骤列表)}</span>
    </div>
    """, unsafe_allow_html=True)
    
    # 进度条
    进度百分比 = (当前步骤 + 1) / len(步骤列表) if 当前步骤 < len(步骤列表) else 1.0
    目标容器.progress(进度百分比)
    
    # 垂直时间轴
    for i, 步骤 in enumerate(步骤列表):
        是当前 = i == 当前步骤
        是已完成 = i < 当前步骤
        是待执行 = i > 当前步骤
        
        if 是已完成:
            状态图标 = "✅"
            状态颜色 = "#059669"
            线条颜色 = "#059669"
            标题颜色 = "#059669"
        elif 是当前:
            状态图标 = "🔄"
            状态颜色 = "#2563eb"
            线条颜色 = "#2563eb"
            标题颜色 = "#2563eb"
        else:
            状态图标 = "⏳"
            状态颜色 = "#9ca3af"
            线条颜色 = "#e5e7eb"
            标题颜色 = "#6b7280"
        
        目标容器.markdown(f"""
        <div style="display: flex; margin-bottom: 1.5rem; position: relative;">
            <!-- 竖线和圆点 -->
            <div style="display: flex; flex-direction: column; align-items: center; min-width: 40px;">
                <div style="
                    width: 28px; height: 28px; 
                    border-radius: 50%; 
                    background: {状态颜色}; 
                    color: white; 
                    display: flex; 
                    align-items: center; 
                    justify-content: center; 
                    font-size: 14px;
                    z-index: 2;
                    box-shadow: 0 0 0 4px white, 0 0 0 6px {线条颜色};
                ">{状态图标}</div>
                <div style="
                    width: 3px; 
                    height: 100%; 
                    background: {线条颜色}; 
                    margin-top: -8px;
                    position: relative;
                    z-index: 1;
                "></div>
            </div>
            
            <!-- 步骤内容 -->
            <div style="flex: 1; padding-left: 1.5rem; padding-top: 2px;">
                <div style="
                    font-weight: 600; 
                    color: {标题颜色}; 
                    font-size: 0.9375rem;
                    margin-bottom: 0.25rem;
                ">{步骤['标题']}</div>
                <div style="
                    color: {标题颜色}; 
                    font-size: 0.8125rem; 
                    opacity: 0.8;
                ">{步骤['描述']}</div>
                {f'<div style="margin-top: 0.5rem; font-size: 0.75rem; color: {状态颜色};">{"✅ 已完成" if 是已完成 else "🔄 执行中..." if 是当前 else "⏳ 等待中"}</div>' if 是当前 or 是已完成 else ''}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # 最后一步不需要竖线
    目标容器.markdown("""
    <style>
    .progress-timeline::after {
        display: none;
    }
    </style>
    """, unsafe_allow_html=True)


def 渲染步骤详情(
    步骤名称: str,
    步骤状态: str,  # "running", "completed", "failed", "skipped"
    详情: Dict[str, Any],
    展开: bool = True,
):
    """渲染单个步骤的详细信息"""
    
    状态配置 = {
        "running": ("🔄 执行中", "#2563eb"),
        "completed": ("✅ 已完成", "#059669"),
        "failed": ("❌ 失败", "#dc2626"),
        "skipped": ("⏭️ 已跳过", "#9ca3af"),
    }
    
    状态文本, 状态颜色 = 状态配置.get(步骤状态, ("未知", "#6b7280"))
    
    with st.expander(f"{状态文本} | {步骤名称}", expanded=展开):
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem;">
            <span style="font-weight: 600; color: {状态颜色};">{状态文本}</span>
        </div>
        """, unsafe_allow_html=True)
        
        # 显示详情
        if 详情:
            for key, value in 详情.items():
                if key in ["输入", "输出", "SQL", "错误信息", "执行计划", "Token使用"]:
                    st.markdown(f"**{key}**")
                    if key == "SQL":
                        st.code(value, language="sql")
                    elif isinstance(value, (dict, list)):
                        st.json(value)
                    else:
                        st.text(str(value))
                    st.markdown("---")


def 渲染实时日志流(
    日志列表: List[Dict],
    最大显示: int = 50,
    key: str = "log_stream",
):
    """渲染实时日志流（类似终端输出）"""
    
    st.markdown("### 📋 实时执行日志")
    
    # 控制栏
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        自动滚动 = st.checkbox("自动滚动", value=True, key=f"{key}_autoscroll")
    with col2:
        显示级别 = st.selectbox("日志级别", ["全部", "DEBUG", "INFO", "WARN", "ERROR"], key=f"{key}_level")
    with col3:
        if st.button("🗑️ 清空", key=f"{key}_clear"):
            st.session_state[f"{key}_logs"] = []
            st.rerun()
    
    # 日志容器
    日志容器 = st.container(height=400, border=True)
    
    with 日志容器:
        for 日志 in 日志列表[-最大显示:]:
            级别 = 日志.get("级别", "INFO")
            时间 = 日志.get("时间", "")
            消息 = 日志.get("消息", "")
            步骤 = 日志.get("步骤", "")
            
            级别颜色 = {
                "DEBUG": "#6b7280",
                "INFO": "#2563eb",
                "WARN": "#d97706",
                "ERROR": "#dc2626",
            }.get(级别, "#374151")
            
            级别图标 = {
                "DEBUG": "🔍",
                "INFO": "ℹ️",
                "WARN": "⚠️",
                "ERROR": "❌",
            }.get(级别, "📝")
            
            st.markdown(f"""
            <div style="font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 12px; line-height: 1.5; padding: 0.25rem 0;">
                <span style="color: #9ca3af;">{时间}</span>
                <span style="color: {级别颜色}; margin-left: 0.5rem;">{级别图标} {级别}</span>
                <span style="color: #2563eb; margin-left: 0.5rem;">[{步骤}]</span>
                <span style="color: #374151; margin-left: 0.5rem;">{消息}</span>
            </div>
            """, unsafe_allow_html=True)
    
    # 自动滚动脚本
    if 自动滚动 and 日志列表:
        st.markdown(f"""
        <script>
            const container = window.parent.document.querySelector('[data-testid="stContainer"]:has([key="{key}"])');
            if (container) {{
                container.scrollTop = container.scrollHeight;
            }}
        </script>
        """, unsafe_allow_html=True)


def 渲染Agent思维链(
    思维链: List[Dict],
    key: str = "thought_chain",
):
    """渲染 Agent 的思维链"""
    
    st.markdown("### 🧠 Agent 思维链")
    
    for i, 思维 in enumerate(思维链):
        类型 = 思维.get("类型", "thought")  # thought, action, observation
        内容 = 思维.get("内容", "")
        
        if 类型 == "thought":
            图标 = "💭"
            颜色 = "#2563eb"
            标签 = "思考"
        elif 类型 == "action":
            图标 = "🎯"
            颜色 = "#059669"
            标签 = "行动"
        elif 类型 == "observation":
            图标 = "👁️"
            颜色 = "#d97706"
            标签 = "观察"
        else:
            图标 = "📝"
            颜色 = "#6b7280"
            标签 = 类型
        
        with st.expander(f"{图标} {标签} #{i+1}", expanded=(i == len(思维链) - 1)):
            st.markdown(f"""
            <div style="border-left: 3px solid {颜色}; padding-left: 1rem; margin-left: 0.5rem;">
                {内容}
            </div>
            """, unsafe_allow_html=True)


def 渲染进度步骤简化版(
    步骤列表: List[str],
    当前索引: int,
    完成索引: List[int] = None,
):
    """简化版进度步骤指示器（水平）"""
    
    if 完成索引 is None:
        完成索引 = list(range(当前索引))
    
    步骤数 = len(步骤列表)
    
    cols = st.columns(步骤数)
    for i, (col, 步骤) in enumerate(zip(cols, 步骤列表)):
        with col:
            if i in 完成索引:
                状态 = "completed"
                图标 = "✅"
            elif i == 当前索引:
                状态 = "current"
                图标 = "🔄"
            else:
                状态 = "pending"
                图标 = "⏳"
            
            st.markdown(f"""
            <div style="text-align: center; padding: 0.5rem;">
                <div style="
                    width: 32px; height: 32px; 
                    border-radius: 50%; 
                    margin: 0 auto 0.5rem;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 14px;
                    background: {'#059669' if 状态 == 'completed' else '#2563eb' if 状态 == 'current' else '#e5e7eb'};
                    color: {'white' if 状态 != 'pending' else '#9ca3af'};
                ">{图标}</div>
                <div style="font-size: 0.75rem; color: {'#059669' if 状态 == 'completed' else '#2563eb' if 状态 == 'current' else '#9ca3af'}; font-weight: 500;">
                    {步骤}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # 连接线（最后一个不画）
            if i < 步骤数 - 1:
                st.markdown(f"""
                <div style="text-align: center; margin-top: -2rem; margin-bottom: 1.5rem;">
                    <div style="
                        height: 3px; 
                        background: {'#059669' if 状态 == 'completed' else '#e5e7eb'}; 
                        margin: 0 auto;
                        width: 100%;
                    "></div>
                </div>
                """, unsafe_allow_html=True)


if __name__ == "__main__":
    # 测试
    st.set_page_config(layout="wide")
    
    步骤 = [
        {"标题": "理解需求", "描述": "解析自然语言，识别意图与实体"},
        {"标题": "检索上下文", "描述": "从知识库获取指标口径、历史 SQL、分析模板"},
        {"标题": "生成 SQL", "描述": "基于 Schema 和 Few-shot 生成可执行 SQL"},
        {"标题": "三层守卫", "描述": "语法校验 → 成本预估 → 运行时熔断"},
        {"标题": "执行查询", "描述": "在数据库中执行 SQL，返回原始数据"},
        {"标题": "自动清洗", "描述": "缺失值填补、异常值检测、字段标准化"},
        {"标题": "聚合分析", "描述": "多维聚合、透视表、趋势计算、同比环比"},
        {"标题": "指标计算", "描述": "调用注册指标函数，产出业务指标值"},
        {"标题": "可视化渲染", "描述": "根据数据特征自动选择图表类型"},
        {"标题": "生成报告", "描述": "结构化输出：结论 + 图表 + 数据 + SQL"},
    ]
    
    渲染进度流(步骤, 当前步骤=3, 任务ID="task_abc12345")