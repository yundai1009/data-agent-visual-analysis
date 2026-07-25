import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from typing import Dict, Any, List
from 前端_streamlit.样式.自定义样式 import 渲染页面标题, 渲染指标卡片, 渲染徽章
from 前端_streamlit.服务.api客户端 import 获取可视化配置, 保存可视化配置, 删除可视化配置
from 前端_streamlit.组件.图表渲染 import 渲染图表, 图表类型选项


# 修改函数名
def 可视化看板():
    """可视化看板页面"""

    渲染页面标题(
        "数据看板",
        "把常用分析结果沉淀为固定看板；MVP 阶段建议先从「开始分析」获得结果",
        "📊"
    )

    st.info("看板适合保存高频指标。首次使用请先完成一次分析，再考虑把结果沉淀为看板。", icon="ℹ️")

    # 标签页：我的看板 / 创建看板 / 看板市场
    tab_我的, tab_创建, tab_市场 = st.tabs(["📋 我的看板", "➕ 创建看板", "🏪 看板市场"])

    with tab_我的:
        渲染我的看板列表()

    with tab_创建:
        渲染创建看板()

    with tab_市场:
        渲染看板市场()


def 渲染我的看板列表():
    """渲染用户的看板列表"""

    # 获取看板列表（模拟数据）
    看板列表 = 获取用户看板列表()

    if not 看板列表:
        st.info("暂无看板，点击「创建看板」开始制作")
        return

    # 网格布局展示看板卡片
    cols_per_row = 3
    for i in range(0, len(看板列表), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            if i + j < len(看板列表):
                看板 = 看板列表[i + j]
                with col:
                    渲染看板卡片(看板)


def 渲染看板卡片(看板: Dict[str, Any]):
    """渲染单个看板卡片"""

    with st.container(border=True):
        # 缩略图/预览
        if 看板.get("缩略图"):
            st.image(看板["缩略图"], use_container_width=True)
        else:
            st.markdown(f"""
            <div style="height: 120px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                        border-radius: 8px; display: flex; align-items: center; justify-content: center; color: white; font-size: 1.5rem;">
                📊 {看板.get('图表数量', 0)} 个图表
            </div>
            """, unsafe_allow_html=True)

        # 标题和描述
        st.markdown(f"### {看板.get('标题', '未命名看板')}")
        if 看板.get("描述"):
            st.caption(看板["描述"][:100] + ("..." if len(看板["描述"]) > 100 else ""))

        # 标签
        标签列表 = 看板.get("标签", [])
        if 标签列表:
            标签_html = " ".join([f'<span class="badge badge-primary">{标签}</span>' for 标签 in 标签列表[:3]])
            st.markdown(标签_html, unsafe_allow_html=True)

        # 元信息
        col1, col2, col3 = st.columns(3)
        with col1:
            st.caption(f"👁️ {看板.get('浏览次数', 0)}")
        with col2:
            st.caption(f"🔄 {看板.get('更新时间', '').split('T')[0] if 看板.get('更新时间') else '未知'}")
        with col3:
            st.caption(f"📊 {看板.get('图表数量', 0)} 图表")

        # 操作按钮
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("查看", key=f"查看_{看板['ID']}", use_container_width=True):
                st.session_state.当前查看看板 = 看板
                st.rerun()
        with col_b:
            if st.button("编辑", key=f"编辑_{看板['ID']}", use_container_width=True):
                st.session_state.编辑看板 = 看板
                st.rerun()
        with col_c:
            if st.button("删除", key=f"删除_{看板['ID']}", use_container_width=True, type="secondary"):
                if 删除可视化配置(看板["ID"]):
                    st.success("删除成功")
                    st.rerun()

        # 如果是当前查看的看板，展开显示完整内容
        if st.session_state.get("当前查看看板", {}).get("ID") == 看板.get("ID"):
            st.markdown("---")
            渲染看板完整内容(看板)


def 渲染看板完整内容(看板: Dict[str, Any]):
    """渲染看板的完整内容（全屏展示）"""

    st.markdown(f"## {看板.get('标题', '未命名看板')}")
    if 看板.get("描述"):
        st.markdown(看板["描述"])

    # 全局筛选器
    if 看板.get("全局筛选器"):
        渲染全局筛选器(看板["全局筛选器"])

    # 图表网格
    图表列表 = 看板.get("图表列表", [])
    if not 图表列表:
        st.info("该看板暂无图表")
        return

    # 计算布局
    for 图表配置 in 图表列表:
        渲染图表(图表配置, key=f"看板图表_{看板['ID']}_{图表配置.get('ID', '')}")


def 渲染全局筛选器(筛选器配置: List[Dict]):
    """渲染全局筛选器栏"""

    st.markdown("### 🔍 全局筛选器")
    cols = st.columns(min(len(筛选器配置), 4))

    for i, 筛选器 in enumerate(筛选器配置):
        with cols[i % len(cols)]:
            类型 = 筛选器.get("类型", "select")
            标签 = 筛选器.get("标签", "筛选")
            字段 = 筛选器.get("字段", "")
            选项 = 筛选器.get("选项", [])
            默认值 = 筛选器.get("默认值")

            if 类型 == "select":
                st.selectbox(标签, 选项, index=选项.index(默认值) if 默认值 in 选项 else 0, key=f"全局筛选_{字段}")
            elif 类型 == "multiselect":
                st.multiselect(标签, 选项, default=默认值 or [], key=f"全局筛选_{字段}")
            elif 类型 == "date_range":
                st.date_input(标签, value=默认值, key=f"全局筛选_{字段}")
            elif 类型 == "number_range":
                col_min, col_max = st.columns(2)
                with col_min:
                    st.number_input(f"{标签} (最小)", value=默认值[0] if 默认值 else 0, key=f"全局筛选_{字段}_min")
                with col_max:
                    st.number_input(f"{标签} (最大)", value=默认值[1] if 默认值 else 100, key=f"全局筛选_{字段}_max")


def 渲染创建看板():
    """渲染创建看板页面"""

    st.markdown("### 创建新看板")

    with st.form("创建看板表单"):
        col1, col2 = st.columns([2, 1])

        with col1:
            标题 = st.text_input("看板标题 *", placeholder="例如：月度销售业绩看板")
            描述 = st.text_area("描述", placeholder="简要描述看板用途、核心指标、更新频率...")

        with col2:
            标签输入 = st.text_input("标签（用逗号分隔）", placeholder="销售, 月度, 核心指标")
            是否公开 = st.checkbox("发布到看板市场", value=False)

        st.markdown("#### 全局筛选器配置")
        筛选器数量 = st.number_input("筛选器数量", min_value=0, max_value=10, value=0, key="新建筛选器数量")

        筛选器列表 = []
        for i in range(int(筛选器数量)):
            with st.expander(f"筛选器 {i + 1}", expanded=True):
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    筛选标签 = st.text_input(f"标签", key=f"新建筛选_标签_{i}")
                    筛选字段 = st.text_input(f"字段名", key=f"新建筛选_字段_{i}")
                with col_b:
                    筛选类型 = st.selectbox(f"类型", ["select", "multiselect", "date_range", "number_range"],
                                            key=f"新建筛选_类型_{i}")
                    筛选选项 = st.text_area(f"选项（每行一个，JSON 格式）", key=f"新建筛选_选项_{i}")
                with col_c:
                    筛选默认 = st.text_input(f"默认值", key=f"新建筛选_默认_{i}")

                筛选器列表.append({
                    "标签": 筛选标签,
                    "字段": 筛选字段,
                    "类型": 筛选类型,
                    "选项": [x.strip() for x in 筛选选项.split("\n") if x.strip()],
                    "默认值": 筛选默认
                })

        提交 = st.form_submit_button("创建看板", type="primary", use_container_width=True)

        if 提交:
            if not 标题:
                st.error("请填写看板标题")
            else:
                看板数据 = {
                    "标题": 标题,
                    "描述": 描述,
                    "标签": [x.strip() for x in 标签输入.split(",") if x.strip()],
                    "是否公开": 是否公开,
                    "全局筛选器": 筛选器列表,
                    "图表列表": [],
                    "创建时间": pd.Timestamp.now().isoformat(),
                    "更新时间": pd.Timestamp.now().isoformat(),
                }

                看板ID = 保存可视化配置(看板数据)
                if 看板ID:
                    st.success(f"看板创建成功！ID: {看板ID}")
                    st.session_state.编辑看板 = {"ID": 看板ID, **看板数据}
                    st.rerun()
                else:
                    st.error("创建失败")


def 渲染看板市场():
    """渲染看板市场（公开看板）"""

    st.markdown("### 🏪 看板市场 - 社区共享看板")

    # 搜索和筛选
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        搜索关键词 = st.text_input("搜索看板", placeholder="输入关键词搜索...")
    with col2:
        分类筛选 = st.selectbox("分类", ["全部", "销售", "运营", "产品", "财务", "用户增长"])
    with col3:
        排序方式 = st.selectbox("排序", ["最新", "最热", "评分最高"])

    # 模拟市场看板数据
    市场看板 = 获取市场看板列表()

    if not 市场看板:
        st.info("市场暂无公开看板")
        return

    # 列表展示
    for 看板 in 市场看板:
        with st.container(border=True):
            col_left, col_right = st.columns([3, 1])

            with col_left:
                st.markdown(f"#### {看板.get('标题', '未命名')}")
                if 看板.get("描述"):
                    st.caption(看板["描述"])

                # 作者和统计
                标签列表 = 看板.get("标签", [])
                if 标签列表:
                    标签_html = " ".join([f'<span class="badge badge-info">{标签}</span>' for 标签 in 标签列表[:5]])
                    st.markdown(标签_html, unsafe_allow_html=True)

                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.caption(f"👤 {看板.get('作者', '匿名')}")
                with col_b:
                    st.caption(f"⭐ {看板.get('收藏数', 0)}")
                with col_c:
                    st.caption(f"👁️ {看板.get('浏览数', 0)}")

            with col_right:
                if st.button("复制到我的看板", key=f"复制_{看板['ID']}", use_container_width=True):
                    新ID = 保存可视化配置({**看板, "ID": None, "创建时间": pd.Timestamp.now().isoformat()})
                    if 新ID:
                        st.success("已复制到我的看板")
                        st.rerun()

                if st.button("预览", key=f"预览市场_{看板['ID']}", use_container_width=True):
                    st.session_state.当前查看看板 = 看板
                    st.rerun()


# 模拟数据函数（实际应调用 API）
def 获取用户看板列表() -> List[Dict]:
    """获取当前用户的看板列表"""
    # 实际应从 API 获取
    return [
        {
            "ID": "dash_001",
            "标题": "月度销售业绩看板",
            "描述": "核心销售指标监控：GMV、订单量、客单价、转化率",
            "标签": ["销售", "月度", "核心指标"],
            "图表数量": 6,
            "浏览次数": 1250,
            "更新时间": "2024-01-15T10:30:00",
            "缩略图": None,
        },
        {
            "ID": "dash_002",
            "标题": "用户留存分析看板",
            "描述": "新用户留存、活跃度、流失预警、复购分析",
            "标签": ["用户增长", "留存", "运营"],
            "图表数量": 8,
            "浏览次数": 890,
            "更新时间": "2024-01-14T15:20:00",
            "缩略图": None,
        },
        {
            "ID": "dash_003",
            "标题": "商品类目表现看板",
            "描述": "各类目销售额、毛利率、库存周转、TOP 商品",
            "标签": ["商品", "类目", "库存"],
            "图表数量": 5,
            "浏览次数": 645,
            "更新时间": "2024-01-13T09:15:00",
            "缩略图": None,
        },
    ]


def 获取市场看板列表() -> List[Dict]:
    """获取市场公开看板列表"""
    return [
        {
            "ID": "market_001",
            "标题": "电商 GMV 实时监控大屏",
            "描述": "实时大屏展示：GMV、订单量、客单价、转化漏斗",
            "标签": ["实时", "大屏", "电商", "GMV"],
            "作者": "数据团队-张三",
            "收藏数": 234,
            "浏览数": 5670,
            "评分": 4.8,
        },
        {
            "ID": "market_002",
            "标题": "用户全生命周期分析模板",
            "描述": "从获客到流失的完整漏斗，含 RFM 分层、LTV 预测",
            "标签": ["用户生命周期", "RFM", "LTV", "模板"],
            "作者": "增长团队-李四",
            "收藏数": 189,
            "浏览数": 3420,
            "评分": 4.9,
        },
    ]


if __name__ == "__main__":
    可视化看板()