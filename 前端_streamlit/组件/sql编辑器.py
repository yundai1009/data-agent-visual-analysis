import streamlit as st
import pandas as pd
from streamlit_ace import st_ace
from typing import Optional, Dict, Any
from 前端_streamlit.样式.自定义样式 import 渲染徽章

def 渲染_sql编辑器(
    sql: str,
    只读: bool = False,
    高度: int = 300,
    key: str = "sql_editor",
    语言: str = "sql",
    主题: str = "monokai",
    显示行号: bool = True,
    字体大小: int = 13,
    标签页大小: int = 2,
    自动补全: bool = True,
    实时高亮: bool = True,
) -> Optional[str]:
    """
    渲染 SQL 代码编辑器
    
    Returns:
        编辑后的 SQL 字符串（如果非只读模式）
    """
    
    # 工具栏
    if not 只读:
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 2])
        with col1:
            if st.button("📋 复制", key=f"{key}_copy", use_container_width=True):
                st.code(sql, language=语言)
                st.toast("已复制到代码块，请手动复制")
        with col2:
            if st.button("🔧 格式化", key=f"{key}_format", use_container_width=True):
                格式化后 = 格式化_sql(sql)
                st.session_state[f"{key}_formatted"] = 格式化后
                st.rerun()
        with col3:
            if st.button("📝 模板", key=f"{key}_template", use_container_width=True):
                st.session_state[f"{key}_show_templates"] = True
        with col4:
            if st.button("🔍 解释", key=f"{key}_explain", use_container_width=True):
                st.session_state[f"{key}_show_explain"] = True
    
    # 显示格式化后的 SQL（如果有）
    编辑内容 = st.session_state.get(f"{key}_formatted", sql)
    
    # ACE 编辑器
    编辑结果 = st_ace(
        value=编辑内容,
        language=语言,
        theme=主题,
        key=key,
        height=高度,
        font_size=字体大小,
        tab_size=标签页大小,
        show_gutter=显示行号,
        show_print_margin=False,
        wrap=True,
        auto_update=自动补全,
        readonly=只读,
        min_lines=10,
        max_lines=50,
        annotations=None,
        markers=None,
    )
    
    # 模板选择器
    if st.session_state.get(f"{key}_show_templates", False):
        with st.expander("📝 SQL 模板库", expanded=True):
            模板列表 = 获取_sql模板()
            for 模板 in 模板列表:
                if st.button(f"{模板['名称']} - {模板['描述']}", key=f"{key}_tpl_{模板['ID']}", use_container_width=True):
                    st.session_state[f"{key}_formatted"] = 模板["SQL"]
                    st.session_state[f"{key}_show_templates"] = False
                    st.rerun()
    
    # EXPLAIN 解释
    if st.session_state.get(f"{key}_show_explain", False):
        with st.expander("🔍 执行计划解释", expanded=True):
            st.info("请在后端配置数据库连接后使用 EXPLAIN 功能")
            if st.button("关闭", key=f"{key}_close_explain"):
                st.session_state[f"{key}_show_explain"] = False
                st.rerun()
    
    return 编辑结果 if not 只读 else None


def 格式化_sql(sql: str) -> str:
    """简单的 SQL 格式化（实际应使用 sqlparse 或 sqlfmt）"""
    import re
    
    # 关键字大写
    关键字 = [
        "SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN",
        "ON", "AND", "OR", "GROUP BY", "ORDER BY", "HAVING", "LIMIT",
        "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER",
        "WITH", "AS", "UNION", "EXCEPT", "INTERSECT",
        "CASE", "WHEN", "THEN", "ELSE", "END",
        "DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX",
        "IN", "NOT IN", "EXISTS", "NOT EXISTS", "BETWEEN", "LIKE", "ILIKE",
        "IS NULL", "IS NOT NULL", "NULL", "TRUE", "FALSE",
    ]
    
    结果 = sql
    for kw in 关键字:
        # 使用正则替换，保持边界
        pattern = r'\b' + re.escape(kw) + r'\b'
        结果 = re.sub(pattern, kw, 结果, flags=re.IGNORECASE)
    
    # 简单缩进
    行列表 = 结果.split('\n')
    缩进级别 = 0
    格式化行 = []
    
    for 行 in 行列表:
        行 = 行.strip()
        if not 行:
            格式化行.append("")
            continue
        
        # 减少缩进的关键字
        if any(行.upper().startswith(kw) for kw in ["GROUP BY", "ORDER BY", "HAVING", "LIMIT", "UNION", "EXCEPT", "INTERSECT", "WHERE", "ON"]):
            缩进级别 = max(0, 缩进级别 - 1)
        
        格式化行.append("  " * 缩进级别 + 行)
        
        # 增加缩进的关键字
        if any(行.upper().startswith(kw) for kw in ["SELECT", "FROM", "JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "WITH", "CASE"]):
            缩进级别 += 1
    
    return "\n".join(格式化行)


def 获取_sql模板() -> list:
    """获取常用 SQL 模板"""
    return [
        {
            "ID": "tpl_001",
            "名称": "基础查询模板",
            "描述": "简单的 SELECT 查询",
            "SQL": "SELECT {{columns}}\nFROM {{table}}\nWHERE {{conditions}}\nLIMIT {{limit}};"
        },
        {
            "ID": "tpl_002",
            "名称": "聚合分组查询",
            "描述": "GROUP BY 聚合分析",
            "SQL": "SELECT {{group_columns}}, {{aggregations}}\nFROM {{table}}\nWHERE {{conditions}}\nGROUP BY {{group_columns}}\nORDER BY {{order_column}} {{order_dir}}\nLIMIT {{limit}};"
        },
        {
            "ID": "tpl_003",
            "名称": "多表 JOIN 查询",
            "描述": "标准的多表关联",
            "SQL": "SELECT {{columns}}\nFROM {{main_table}} t1\n{{join_clauses}}\nWHERE {{conditions}}\nLIMIT {{limit}};"
        },
        {
            "ID": "tpl_004",
            "名称": "CTE 递归查询",
            "描述": "层级结构递归查询",
            "SQL": "WITH RECURSIVE {{cte_name}} AS (\n  SELECT {{base_columns}}\n  FROM {{table}}\n  WHERE {{base_condition}}\n  UNION ALL\n  SELECT {{recursive_columns}}\n  FROM {{table}} t\n  JOIN {{cte_name}} cte ON t.{{parent_col}} = cte.{{child_col}}\n)\nSELECT * FROM {{cte_name}};"
        },
        {
            "ID": "tpl_005",
            "名称": "窗口函数分析",
            "描述": "ROW_NUMBER, RANK, LAG 等",
            "SQL": "SELECT {{columns}},\n       ROW_NUMBER() OVER (PARTITION BY {{partition}} ORDER BY {{order}}) as rn,\n       LAG({{value_col}}) OVER (PARTITION BY {{partition}} ORDER BY {{order}}) as prev_value\nFROM {{table}}\nWHERE {{conditions}};"
        },
        {
            "ID": "tpl_006",
            "名称": "同比环比计算",
            "描述": "YoY / MoM 对比",
            "SQL": "WITH current_period AS (\n  SELECT {{metrics}}\n  FROM {{table}}\n  WHERE {{current_condition}}\n),\nprevious_period AS (\n  SELECT {{metrics}}\n  FROM {{table}}\n  WHERE {{previous_condition}}\n)\nSELECT c.*, p.*,\n       (c.{{metric}} - p.{{metric}}) / NULLIF(p.{{metric}}, 0) * 100 as yoy_pct\nFROM current_period c\nJOIN previous_period p ON c.{{group_col}} = p.{{group_col}};"
        },
    ]


def 渲染_sql_diff(旧_sql: str, 新_sql: str, key: str = "sql_diff"):
    """渲染 SQL 差异对比（类似 git diff）"""
    import difflib
    
    diff = list(difflib.unified_diff(
        旧_sql.splitlines(keepends=True),
        新_sql.splitlines(keepends=True),
        fromfile="旧版本",
        tofile="新版本",
        lineterm=""
    ))
    
    if not diff:
        st.info("无差异")
        return
    
    # 高亮显示
    diff_html = "<pre style='font-family: monospace; font-size: 13px; line-height: 1.6;'>"
    for line in diff:
        if line.startswith("+"):
            diff_html += f"<span style='color: #059669; background: #d1fae5;'>{line}</span>"
        elif line.startswith("-"):
            diff_html += f"<span style='color: #dc2626; background: #fee2e2;'>{line}</span>"
        elif line.startswith("@@"):
            diff_html += f"<span style='color: #2563eb; background: #dbeafe;'>{line}</span>"
        else:
            diff_html += line
    diff_html += "</pre>"
    
    st.markdown(diff_html, unsafe_allow_html=True)


def 渲染参数化_sql_编辑器(
    sql模板: str,
    参数Schema: Dict[str, Any],
    key: str = "param_sql_editor",
) -> str:
    """渲染参数化 SQL 编辑器：左侧模板，右侧参数输入，中间实时预览"""
    
    st.markdown("### 参数化 SQL 编辑器")
    
    col_template, col_params, col_preview = st.columns([1.2, 1, 1.2])
    
    with col_template:
        st.markdown("**SQL 模板**")
        模板内容 = st_ace(
            value=sql模板,
            language="sql",
            theme="monokai",
            key=f"{key}_template",
            height=300,
            font_size=12,
            readonly=True,
        )
    
    with col_params:
        st.markdown("**参数输入**")
        参数值 = {}
        for 参数名, Schema in 参数Schema.items():
            参数类型 = Schema.get("type", "string")
            参数描述 = Schema.get("description", 参数名)
            默认值 = Schema.get("default", "")
            
            if 参数类型 == "string":
                if "enum" in Schema:
                    参数值[参数名] = st.selectbox(参数描述, Schema["enum"], key=f"{key}_param_{参数名}")
                else:
                    参数值[参数名] = st.text_input(参数描述, value=默认值, key=f"{key}_param_{参数名}")
            elif 参数类型 == "integer":
                参数值[参数名] = st.number_input(参数描述, value=int(默认值) if 默认值 else 0, key=f"{key}_param_{参数名}")
            elif 参数类型 == "number":
                参数值[参数名] = st.number_input(参数描述, value=float(默认值) if 默认值 else 0.0, key=f"{key}_param_{参数名}")
            elif 参数类型 == "boolean":
                参数值[参数名] = st.checkbox(参数描述, value=默认值, key=f"{key}_param_{参数名}")
            elif 参数类型 == "array":
                输入值 = st.text_area(参数描述, value=",".join(默认值) if isinstance(默认值, list) else "", key=f"{key}_param_{参数名}")
                参数值[参数名] = [x.strip() for x in 输入值.split(",") if x.strip()]
            elif 参数类型 == "date":
                参数值[参数名] = st.date_input(参数描述, key=f"{key}_param_{参数名}")
    
    with col_preview:
        st.markdown("**实时预览**")
        # 简单的参数替换
        预览sql = sql模板
        for 参数名, 值 in 参数值.items():
            占位符 = f"{{{{{参数名}}}}}"
            if isinstance(值, list):
                替换值 = ", ".join([f"'{v}'" if isinstance(v, str) else str(v) for v in 值])
            elif isinstance(值, str):
                替换值 = f"'{值}'"
            else:
                替换值 = str(值)
            预览sql = 预览sql.replace(占位符, 替换值)
        
        st_ace(
            value=预览sql,
            language="sql",
            theme="monokai",
            key=f"{key}_preview",
            height=300,
            font_size=12,
            readonly=True,
        )
    
    return 预览sql


if __name__ == "__main__":
    # 测试
    st.set_page_config(layout="wide")
    渲染_sql编辑器("SELECT * FROM users WHERE id = 1;", 只读=False, 高度=200)