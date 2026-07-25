from __future__ import annotations

import streamlit as st

from 前端_streamlit.组件.侧边栏导航 import 渲染侧边栏
from 前端_streamlit.页面 import 上传数据报表
from 前端_streamlit.样式.自定义样式 import 应用全局样式


st.set_page_config(
    page_title="数据分析 Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

应用全局样式()

渲染侧边栏()
上传数据报表()
