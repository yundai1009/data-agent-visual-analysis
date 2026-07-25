import streamlit as st
import pandas as pd
from typing import Optional, Dict, Any, List
from 前端_streamlit.样式.自定义样式 import 渲染徽章

def 渲染结果表格(
    df: pd.DataFrame,
    key: str = "result_table",
    最大行数: int = 1000,
    可下载: bool = True,
    可搜索: bool = True,
    可排序: bool = True,
    高亮最大值: bool = False,
    高亮最小值: bool = False,
    条件格式: Optional[Dict] = None,
    默认列宽: str = "auto",
):
    """
    渲染增强版数据表格
    
    Args:
        df: 要显示的 DataFrame
        key: 唯一标识符
        最大行数: 最大显示行数（超过会分页）
        可下载: 是否显示下载按钮
        可搜索: 是否启用搜索/筛选
        可排序: 是否启用排序
        高亮最大值: 是否高亮每列最大值
        高亮最小值: 是否高亮每列最小值
        条件格式: 自定义条件格式规则
        默认列宽: 列宽模式
    """
    
    if df is None or df.empty:
        st.info("暂无数据")
        return
    
    # 限制行数
    显示_df = df.head(最大行数)
    总行数 = len(df)
    
    # 表格信息栏
    col_info, col_download = st.columns([3, 1])
    with col_info:
        if 总行数 > 最大行数:
            st.caption(f"显示前 {最大行数:,} 行 / 共 {总行数:,} 行")
        else:
            st.caption(f"共 {总行数:,} 行 × {len(df.columns)} 列")
    
    with col_download:
        if 可下载:
            csv = 显示_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 下载 CSV",
                csv,
                file_name=f"{key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"{key}_download"
            )
    
    # 列配置
    列配置 = {}
    for col in 显示_df.columns:
        dtype = 显示_df[col].dtype
        
        if pd.api.types.is_numeric_dtype(dtype):
            if pd.api.types.is_integer_dtype(dtype):
                列配置[col] = st.column_config.NumberColumn(
                    col, 
                    format="%d",
                    help=f"整数类型，范围: {显示_df[col].min():,} ~ {显示_df[col].max():,}"
                )
            else:
                列配置[col] = st.column_config.NumberColumn(
                    col,
                    format="%.2f",
                    help=f"浮点数类型，范围: {显示_df[col].min():.2f} ~ {显示_df[col].max():.2f}"
                )
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            列配置[col] = st.column_config.DatetimeColumn(
                col,
                format="YYYY-MM-DD HH:mm:ss",
                help="日期时间类型"
            )
        elif pd.api.types.is_bool_dtype(dtype):
            列配置[col] = st.column_config.CheckboxColumn(col)
        else:
            # 字符串类型：检查是否为长文本
            最大长度 = 显示_df[col].astype(str).str.len().max()
            if 最大长度 > 100:
                列配置[col] = st.column_config.TextColumn(col, width="large")
            else:
                列配置[col] = st.column_config.TextColumn(col, width="medium")
    
    # 渲染表格
    选中行 = st.dataframe(
        显示_df,
        column_config=列配置,
        hide_index=True,
        use_container_width=True,
        on_select="rerun" if 可排序 else "ignore",
        selection_mode="multi-row",
        key=key,
        height=min(400, len(显示_df) * 35 + 40),
    )
    
    # 搜索/筛选功能
    if 可搜索 and len(显示_df) > 20:
        with st.expander("🔍 高级筛选", expanded=False):
            渲染表格筛选器(显示_df, key=f"{key}_filter")
    
    # 统计摘要
    with st.expander("📊 列统计摘要", expanded=False):
        渲染列统计(显示_df)


def 渲染表格筛选器(df: pd.DataFrame, key: str = "table_filter"):
    """渲染表格列筛选器"""
    
    st.markdown("**逐列筛选**")
    
    筛选条件 = {}
    
    # 每行最多 3 个筛选器
    cols = st.columns(3)
    for i, col in enumerate(df.columns):
        with cols[i % 3]:
            dtype = df[col].dtype
            
            if pd.api.types.is_numeric_dtype(dtype):
                # 数值范围筛选
                最小值 = float(df[col].min())
                最大值 = float(df[col].max())
                范围 = st.slider(
                    f"{col}",
                    最小值, 最大值,
                    (最小值, 最大值),
                    key=f"{key}_{col}_range"
                )
                筛选条件[col] = ("range", 范围)
                
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                # 日期范围筛选
                最小日期 = df[col].min().date()
                最大日期 = df[col].max().date()
                日期范围 = st.date_input(
                    f"{col}",
                    value=(最小日期, 最大日期),
                    min_value=最小日期,
                    max_value=最大日期,
                    key=f"{key}_{col}_date"
                )
                筛选条件[col] = ("date_range", 日期范围)
                
            else:
                # 字符串：多选或搜索
                唯一值 = df[col].dropna().unique()
                if len(唯一值) <= 50:
                    # 少量唯一值：多选
                    选中值 = st.multiselect(
                        f"{col}",
                        options=sorted(唯一值.astype(str)),
                        default=[],
                        key=f"{key}_{col}_multi"
                    )
                    if 选中值:
                        筛选条件[col] = ("isin", 选中值)
                else:
                    # 大量唯一值：搜索框
                    搜索词 = st.text_input(f"{col} (搜索)", key=f"{key}_{col}_search")
                    if 搜索词:
                        筛选条件[col] = ("contains", 搜索词)
    
    # 应用筛选按钮
    if st.button("应用筛选", key=f"{key}_apply", type="primary"):
        # 实际应用中这里需要重新查询或过滤数据
        st.info("筛选功能需结合后端查询实现，前端仅演示 UI")


def 渲染列统计(df: pd.DataFrame):
    """渲染列统计摘要"""
    
    统计数据 = []
    
    for col in df.columns:
        dtype = df[col].dtype
        缺失数 = int(df[col].isna().sum())
        缺失率 = 缺失数 / len(df) * 100
        
        行数据 = {
            "列名": col,
            "类型": str(dtype),
            "非空数": int(df[col].notna().sum()),
            "缺失数": 缺失数,
            "缺失率": f"{缺失率:.1f}%",
        }
        
        if pd.api.types.is_numeric_dtype(dtype):
            行数据.update({
                "最小值": f"{df[col].min():.2f}" if pd.api.types.is_float_dtype(dtype) else f"{int(df[col].min()):,}",
                "最大值": f"{df[col].max():.2f}" if pd.api.types.is_float_dtype(dtype) else f"{int(df[col].max()):,}",
                "均值": f"{df[col].mean():.2f}",
                "中位数": f"{df[col].median():.2f}",
                "标准差": f"{df[col].std():.2f}",
            })
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            行数据.update({
                "最早": df[col].min().strftime("%Y-%m-%d"),
                "最晚": df[col].max().strftime("%Y-%m-%d"),
                "时间跨度": f"{(df[col].max() - df[col].min()).days} 天",
            })
        else:
            唯一值数 = df[col].nunique()
            行数据.update({
                "唯一值数": f"{唯一值数:,}",
                "基数比": f"{唯一值数/len(df)*100:.1f}%",
            })
        
        统计数据.append(行数据)
    
    统计_df = pd.DataFrame(统计数据)
    st.dataframe(统计_df, hide_index=True, use_container_width=True)


def 渲染数据概览卡片(df: pd.DataFrame, key: str = "data_overview"):
    """渲染数据概览指标卡片"""
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("行数", f"{len(df):,}")
    
    with col2:
        st.metric("列数", f"{len(df.columns)}")
    
    with col3:
        总缺失 = df.isna().sum().sum()
        总单元格 = len(df) * len(df.columns)
        缺失率 = 总缺失 / 总单元格 * 100 if 总单元格 > 0 else 0
        st.metric("缺失率", f"{缺失率:.1f}%")
    
    with col4:
        数值列数 = len(df.select_dtypes(include='number').columns)
        st.metric("数值列", f"{数值列数}")
    
    with col5:
        内存使用 = df.memory_usage(deep=True).sum() / 1024 / 1024
        st.metric("内存占用", f"{内存使用:.2f} MB")


def 渲染数据类型推断(df: pd.DataFrame, key: str = "dtype_inference"):
    """渲染数据类型推断与转换建议"""
    
    st.markdown("### 🔍 数据类型推断")
    
    建议列表 = []
    
    for col in df.columns:
        dtype = df[col].dtype
        样本值 = df[col].dropna().head(5).tolist()
        
        建议 = {"列名": col, "当前类型": str(dtype), "样本值": str(样本值)[:80], "建议操作": ""}
        
        # 检查是否应为日期
        if dtype == 'object':
            try:
                pd.to_datetime(df[col].dropna().head(100))
                建议["建议操作"] = "🔄 转为 datetime"
            except:
                pass
            
            # 检查是否为数值
            try:
                pd.to_numeric(df[col].dropna().head(100))
                if not 建议["建议操作"]:
                    建议["建议操作"] = "🔄 转为 numeric"
                else:
                    建议["建议操作"] += " / numeric"
            except:
                pass
            
            # 检查是否为布尔
            唯一值 = set(df[col].dropna().unique())
            if 唯一值.issubset({'true', 'false', 'True', 'False', '1', '0', 'yes', 'no', 'Y', 'N'}):
                建议["建议操作"] += " / boolean" if 建议["建议操作"] else "🔄 转为 boolean"
        
        if 建议["建议操作"]:
            建议列表.append(建议)
    
    if 建议列表:
        建议_df = pd.DataFrame(建议列表)
        st.dataframe(建议_df, hide_index=True, use_container_width=True)
    else:
        st.info("所有列类型均已正确推断，无需转换")


def 渲染数据质量报告(df: pd.DataFrame, key: str = "data_quality"):
    """渲染简易数据质量报告"""
    
    st.markdown("### 📋 数据质量报告")
    
    问题列表 = []
    
    for col in df.columns:
        dtype = df[col].dtype
        
        # 1. 高缺失率
        缺失率 = df[col].isna().mean()
        if 缺失率 > 0.5:
            问题列表.append({"列名": col, "问题类型": "高缺失率", "严重程度": "🔴 高", "详情": f"缺失率 {缺失率:.1%}"})
        elif 缺失率 > 0.1:
            问题列表.append({"列名": col, "问题类型": "中等缺失", "严重程度": "🟡 中", "详情": f"缺失率 {缺失率:.1%}"})
        
        # 2. 单一值（常数列）
        if df[col].nunique() == 1:
            问题列表.append({"列名": col, "问题类型": "常数列", "严重程度": "🟡 中", "详情": f"唯一值: {df[col].iloc[0]}"})
        
        # 3. 高基数分类列
        if dtype == 'object' and df[col].nunique() > len(df) * 0.9:
            问题列表.append({"列名": col, "问题类型": "高基数 ID 列", "严重程度": "🔵 低", "详情": f"唯一值 {df[col].nunique():,}"})
        
        # 4. 数值异常（简单检测）
        if pd.api.types.is_numeric_dtype(dtype):
            Q1 = df[col].quantile(0.25)
            Q3 = df[col].quantile(0.75)
            IQR = Q3 - Q1
            下界 = Q1 - 1.5 * IQR
            上界 = Q3 + 1.5 * IQR
            异常数 = ((df[col] < 下界) | (df[col] > 上界)).sum()
            if 异常数 > 0:
                问题列表.append({"列名": col, "问题类型": "潜在异常值", "严重程度": "🟡 中", "详情": f"IQR 法检出 {异常数} 个异常值"})
    
    if 问题列表:
        问题_df = pd.DataFrame(问题列表)
        st.dataframe(
            问题_df,
            column_config={
                "严重程度": st.column_config.TextColumn("严重程度", width="small"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("✅ 未发现明显数据质量问题")


if __name__ == "__main__":
    # 测试
    st.set_page_config(layout="wide")
    
    import numpy as np
    测试数据 = pd.DataFrame({
        "ID": range(1, 101),
        "姓名": [f"用户_{i}" for i in range(1, 101)],
        "年龄": np.random.randint(18, 65, 100),
        "收入": np.random.lognormal(10, 0.5, 100).astype(int),
        "城市": np.random.choice(["北京", "上海", "广州", "深圳", "杭州"], 100),
        "注册日期": pd.date_range("2023-01-01", periods=100, freq="D"),
        "是否VIP": np.random.choice([True, False], 100),
    })
    
    # 人为制造一些问题
    测试数据.loc[0:10, "收入"] = None
    测试数据["常数列"] = "固定值"
    
    渲染结果表格(测试数据, key="test_table")
    st.markdown("---")
    渲染数据概览卡片(测试数据)
    st.markdown("---")
    渲染数据质量报告(测试数据)