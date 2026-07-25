import streamlit as st

def 应用全局样式():
    """应用全局 CSS 样式"""
    st.markdown("""
    <style>
    /* ===== 全局变量 ===== */
    :root {
        --primary-color: #2563eb;
        --primary-hover: #1d4ed8;
        --success-color: #059669;
        --warning-color: #d97706;
        --danger-color: #dc2626;
        --bg-primary: #ffffff;
        --bg-secondary: #f8fafc;
        --bg-tertiary: #f1f5f9;
        --text-primary: #1e293b;
        --text-secondary: #64748b;
        --border-color: #e2e8f0;
        --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
        --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
        --radius-sm: 0.375rem;
        --radius-md: 0.5rem;
        --radius-lg: 0.75rem;
        --transition-fast: 150ms ease;
        --transition-normal: 250ms ease;
    }

    /* ===== 隐藏 Streamlit 默认元素 ===== */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}

    /* ===== 页面容器 ===== */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1400px;
    }

    /* ===== 侧边栏样式 ===== */
    .css-1d391kg, .css-1lcbmhc {
        background-color: var(--bg-secondary);
        border-right: 1px solid var(--border-color);
    }

    .css-1d391kg .stRadio > label,
    .css-1lcbmhc .stRadio > label {
        background: transparent;
    }

    /* ===== 卡片组件 ===== */
    .metric-card {
        background: var(--bg-primary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        box-shadow: var(--shadow-sm);
        transition: box-shadow var(--transition-normal), transform var(--transition-fast);
    }
    .metric-card:hover {
        box-shadow: var(--shadow-md);
        transform: translateY(-2px);
    }
    .metric-card .metric-label {
        font-size: 0.875rem;
        color: var(--text-secondary);
        font-weight: 500;
        margin-bottom: 0.5rem;
    }
    .metric-card .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--text-primary);
        line-height: 1.2;
    }
    .metric-card .metric-delta {
        font-size: 0.875rem;
        font-weight: 600;
        margin-top: 0.5rem;
    }
    .metric-card .metric-delta.positive { color: var(--success-color); }
    .metric-card .metric-delta.negative { color: var(--danger-color); }

    /* ===== 代码编辑器区域 ===== */
    .stCodeBlock {
        border-radius: var(--radius-md) !important;
        border: 1px solid var(--border-color) !important;
        background-color: #1e1e1e !important;
    }
    .stCodeBlock code {
        font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
        font-size: 0.875rem !important;
        line-height: 1.6 !important;
    }

    /* ===== 按钮样式 ===== */
    .stButton > button {
        border-radius: var(--radius-md) !important;
        font-weight: 500 !important;
        transition: all var(--transition-fast) !important;
        border: none !important;
    }
    .stButton > button[kind="primary"] {
        background: var(--primary-color) !important;
        color: white !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: var(--primary-hover) !important;
        box-shadow: var(--shadow-md) !important;
    }
    .stButton > button[kind="secondary"] {
        background: var(--bg-tertiary) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border-color) !important;
    }
    .stButton > button[kind="secondary"]:hover {
        background: var(--border-color) !important;
    }

    /* ===== 表单输入 ===== */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div > div,
    .stNumberInput > div > div > input {
        border-radius: var(--radius-md) !important;
        border: 1px solid var(--border-color) !important;
        transition: border-color var(--transition-fast), box-shadow var(--transition-fast) !important;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: var(--primary-color) !important;
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1) !important;
    }

    /* ===== 表格样式 ===== */
    .stDataFrame {
        border-radius: var(--radius-md) !important;
        overflow: hidden !important;
        border: 1px solid var(--border-color) !important;
    }
    .stDataFrame [data-testid="stTable"] {
        font-size: 0.875rem !important;
    }
    .stDataFrame th {
        background-color: var(--bg-secondary) !important;
        font-weight: 600 !important;
        color: var(--text-primary) !important;
        border-bottom: 2px solid var(--border-color) !important;
    }
    .stDataFrame td {
        border-bottom: 1px solid var(--border-color) !important;
    }
    .stDataFrame tr:hover td {
        background-color: var(--bg-tertiary) !important;
    }

    /* ===== 进度条 ===== */
    .stProgress > div > div > div {
        background: linear-gradient(90deg, var(--primary-color), #3b82f6) !important;
        border-radius: var(--radius-sm) !important;
    }
    .stProgress > div > div {
        background-color: var(--bg-tertiary) !important;
        border-radius: var(--radius-sm) !important;
    }

    /* ===== 标签页 ===== */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: var(--radius-md) !important;
        padding: 0.75rem 1.5rem !important;
        font-weight: 500 !important;
        background-color: var(--bg-tertiary) !important;
        border: 1px solid var(--border-color) !important;
        color: var(--text-secondary) !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: var(--primary-color) !important;
        color: white !important;
        border-color: var(--primary-color) !important;
    }

    /* ===== 展开器 ===== */
    .streamlit-expanderHeader {
        border-radius: var(--radius-md) !important;
        border: 1px solid var(--border-color) !important;
        background-color: var(--bg-primary) !important;
        font-weight: 500 !important;
    }
    .streamlit-expanderContent {
        border: 1px solid var(--border-color) !important;
        border-top: none !important;
        border-radius: 0 0 var(--radius-md) var(--radius-md) !important;
        background-color: var(--bg-secondary) !important;
    }

    /* ===== 消息提示 ===== */
    .stAlert {
        border-radius: var(--radius-md) !important;
        border: none !important;
    }
    .stAlert[data-baseweb="notification"][kind="success"] {
        background-color: #ecfdf5 !important;
        color: #065f46 !important;
        border-left: 4px solid var(--success-color) !important;
    }
    .stAlert[data-baseweb="notification"][kind="error"] {
        background-color: #fef2f2 !important;
        color: #991b1b !important;
        border-left: 4px solid var(--danger-color) !important;
    }
    .stAlert[data-baseweb="notification"][kind="warning"] {
        background-color: #fffbeb !important;
        color: #92400e !important;
        border-left: 4px solid var(--warning-color) !important;
    }
    .stAlert[data-baseweb="notification"][kind="info"] {
        background-color: #eff6ff !important;
        color: #1e40af !important;
        border-left: 4px solid var(--primary-color) !important;
    }

    /* ===== 加载动画 ===== */
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
    .spinner {
        display: inline-block;
        width: 1.25rem;
        height: 1.25rem;
        border: 2px solid var(--border-color);
        border-top-color: var(--primary-color);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        margin-right: 0.5rem;
        vertical-align: middle;
    }

    /* ===== 徽章 ===== */
    .badge {
        display: inline-flex;
        align-items: center;
        padding: 0.25rem 0.625rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 9999px;
        line-height: 1;
    }
    .badge-primary { background: #dbeafe; color: #1e40af; }
    .badge-success { background: #d1fae5; color: #065f46; }
    .badge-warning { background: #fef3c7; color: #92400e; }
    .badge-danger { background: #fee2e2; color: #991b1b; }
    .badge-info { background: #e0e7ff; color: #3730a3; }

    /* ===== 进度流步骤 ===== */
    .progress-step {
        display: flex;
        align-items: center;
        padding: 0.75rem 1rem;
        background: var(--bg-primary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md);
        margin-bottom: 0.5rem;
        transition: all var(--transition-fast);
    }
    .progress-step.active {
        border-color: var(--primary-color);
        background: #eff6ff;
    }
    .progress-step.completed {
        border-color: var(--success-color);
        background: #f0fdf4;
    }
    .progress-step.failed {
        border-color: var(--danger-color);
        background: #fef2f2;
    }
    .progress-step-icon {
        width: 2rem;
        height: 2rem;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 1rem;
        font-size: 1rem;
    }
    .progress-step-icon.pending { background: var(--bg-tertiary); color: var(--text-secondary); }
    .progress-step-icon.active { background: var(--primary-color); color: white; animation: pulse 1.5s ease-in-out infinite; }
    .progress-step-icon.completed { background: var(--success-color); color: white; }
    .progress-step-icon.failed { background: var(--danger-color); color: white; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    .progress-step-content { flex: 1; }
    .progress-step-title { font-weight: 600; color: var(--text-primary); }
    .progress-step-desc { font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.25rem; }

    /* ===== 结果表格工具栏 ===== */
    .result-toolbar {
        display: flex;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-md) var(--radius-md) 0 0;
        flex-wrap: wrap;
    }
    .result-toolbar .stButton > button {
        padding: 0.375rem 0.875rem;
        font-size: 0.8125rem;
    }

    /* ===== 响应式调整 ===== */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }
        .metric-card .metric-value {
            font-size: 1.5rem;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 0.5rem 1rem !important;
            font-size: 0.875rem !important;
        }
    }

    /* ===== 滚动条美化 ===== */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: var(--bg-secondary);
    }
    ::-webkit-scrollbar-thumb {
        background: var(--border-color);
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: var(--text-secondary);
    }
    </style>
    """, unsafe_allow_html=True)


def 渲染页面标题(标题: str, 副标题: str = "", 图标: str = ""):
    """渲染统一风格的页面标题"""
    st.markdown(f"""
    <div style="margin-bottom: 2rem;">
        <h1 style="margin: 0; font-size: 2rem; font-weight: 700; color: var(--text-primary);">
            {图标} {标题}
        </h1>
        {f'<p style="margin: 0.5rem 0 0; color: var(--text-secondary); font-size: 1rem;">{副标题}</p>' if 副标题 else ''}
    </div>
    """, unsafe_allow_html=True)


def 渲染指标卡片(标签: str, 数值: str, 变化: str = "", 变化类型: str = "", 图标: str = ""):
    """渲染指标卡片"""
    变化_html = ""
    if 变化:
        变化_class = "positive" if 变化类型 == "正向" else "negative" if 变化类型 == "负向" else ""
        变化_html = f'<div class="metric-delta {变化_class}">{变化}</div>'
    
    图标_html = f'<span style="font-size: 1.5rem; margin-right: 0.5rem;">{图标}</span>' if 图标 else ''
    
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{图标_html}{标签}</div>
        <div class="metric-value">{数值}</div>
        {变化_html}
    </div>
    """, unsafe_allow_html=True)


def 渲染徽章(文本: str, 类型: str = "primary"):
    """渲染徽章"""
    st.markdown(f'<span class="badge badge-{类型}">{文本}</span>', unsafe_allow_html=True)


def 渲染进度步骤(步骤列表: list, 当前步骤索引: int):
    """渲染进度流步骤"""
    for i, 步骤 in enumerate(步骤列表):
        状态 = "pending"
        if i < 当前步骤索引:
            状态 = "completed"
        elif i == 当前步骤索引:
            状态 = "active"
        
        图标_map = {
            "pending": "⏳",
            "active": "🔄",
            "completed": "✅",
            "failed": "❌"
        }
        
        st.markdown(f"""
        <div class="progress-step {状态}">
            <div class="progress-step-icon {状态}">{图标_map[状态]}</div>
            <div class="progress-step-content">
                <div class="progress-step-title">{步骤['标题']}</div>
                <div class="progress-step-desc">{步骤.get('描述', '')}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)