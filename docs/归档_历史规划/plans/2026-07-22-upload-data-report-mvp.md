# 上传数据报表 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Streamlit 项目中新增第一阶段“上传数据报表”闭环，支持 CSV/Excel 上传、数据预览、字段画像、图表类型选择、字段/聚合配置和 Plotly 可视化报表展示。

**Architecture:** 第一阶段保持单体 Streamlit MVP，不新增 FastAPI 上传接口和持久化存储。新增后端核心纯函数模块处理文件读取、数据画像、聚合和图表配置；新增 Streamlit 页面负责交互和展示；修改现有导航接入新页面。

**Tech Stack:** Python 3.11, Streamlit, pandas, plotly, openpyxl via pandas Excel reader.

## Global Constraints

- 支持上传类型：CSV + Excel。
- 不做用户登录、文件持久化、报表历史、分享链接、PDF/HTML 导出、React 前端、多数据集 join、任意 Python 代码执行。
- 复用现有中文命名风格和 Streamlit 页面结构。
- 不把完整数据发送给 LLM；第一阶段用规则生成结论和图表配置。

---

### Task 1: 核心数据读取和画像

**Files:**
- Create: `后端_核心/文件数据服务.py`
- Create: `后端_核心/数据画像.py`

**Interfaces:**
- Produces: `读取上传表格(uploaded_file: Any) -> pandas.DataFrame`
- Produces: `生成数据画像(df: pandas.DataFrame) -> dict[str, Any]`

- [ ] **Step 1: Create file reader**

Implement `读取上传表格` using `uploaded_file.name` suffix. `.csv` uses `pd.read_csv`; `.xlsx` and `.xls` use `pd.read_excel`. Empty data raises `ValueError("上传文件没有读取到数据")`.

- [ ] **Step 2: Create profiler**

Implement field type inference with columns grouped as `数值字段`, `日期字段`, `分类字段`, `文本字段`; include row count, column count, missing counts, numeric describe and categorical top values.

- [ ] **Step 3: Verify imports**

Run: `python -m py_compile 后端_核心\文件数据服务.py 后端_核心\数据画像.py`
Expected: exit code 0.

### Task 2: 报表生成器

**Files:**
- Create: `后端_核心/上传报表生成器.py`

**Interfaces:**
- Consumes: `生成数据画像(df)` from Task 1
- Produces: `生成报表数据(df, 分析需求, 图表类型, x轴, y轴, 分组字段, 聚合方式) -> dict[str, Any]`

- [ ] **Step 1: Implement aggregation**

Map Chinese aggregation labels `求和`, `平均值`, `计数`, `最大值`, `最小值` to pandas groupby aggregation. If chart type is `表格`, return preview data without aggregation.

- [ ] **Step 2: Implement chart recommendation**

For `自动推荐`, choose `折线图` when x-axis is date-like and y-axis exists, `散点图` when two numeric fields are available, `柱状图` when category + numeric fields exist, otherwise `表格`.

- [ ] **Step 3: Implement Plotly config output**

Return dict containing `标题`, `分析需求`, `图表类型`, `图表配置`, `报表数据`, `数据画像`, `结论`.

- [ ] **Step 4: Verify imports**

Run: `python -m py_compile 后端_核心\上传报表生成器.py`
Expected: exit code 0.

### Task 3: Streamlit 上传报表页面

**Files:**
- Create: `前端_streamlit/页面/上传数据报表.py`

**Interfaces:**
- Consumes: `读取上传表格`, `生成数据画像`, `生成报表数据`
- Produces: `上传数据报表() -> None`

- [ ] **Step 1: Build upload UI**

Use `st.file_uploader("上传 CSV 或 Excel 文件", type=["csv", "xlsx", "xls"])`.

- [ ] **Step 2: Display profile**

Show metrics for rows/columns, missing values, field groups, and first 20 rows.

- [ ] **Step 3: Build report controls**

Provide text area for natural-language requirement, chart type selectbox, x-axis/y-axis/group/aggregation selectors.

- [ ] **Step 4: Render report**

Call `生成报表数据`, render `图表配置` using existing `渲染图表`, show data table and conclusion.

- [ ] **Step 5: Verify imports**

Run: `python -m py_compile 前端_streamlit\页面\上传数据报表.py`
Expected: exit code 0.

### Task 4: Navigation integration

**Files:**
- Modify: `前端_streamlit/页面/__init__.py`
- Modify: `前端_streamlit/主入口.py`
- Modify: `前端_streamlit/组件/侧边栏导航.py`

**Interfaces:**
- Consumes: `上传数据报表() -> None`

- [ ] **Step 1: Export page function**

Add `from .上传数据报表 import 上传数据报表` and include it in `__all__`.

- [ ] **Step 2: Add menu item**

Add `上传报表` option and an upload icon to `option_menu`.

- [ ] **Step 3: Add route mapping**

Import `上传数据报表` in `主入口.py` and map `"上传报表": 上传数据报表`.

- [ ] **Step 4: Verify app syntax**

Run: `python -m py_compile 前端_streamlit\主入口.py 前端_streamlit\组件\侧边栏导航.py 前端_streamlit\页面\__init__.py`
Expected: exit code 0.

### Task 5: End-to-end smoke verification

**Files:**
- No new files.

- [ ] **Step 1: Compile all Python files**

Run: `python -m compileall api config 后端_核心 前端_streamlit`
Expected: all project Python files compile.

- [ ] **Step 2: Run core function smoke test**

Create an in-memory DataFrame with date/category/numeric fields and call `生成报表数据` for `柱状图`, `折线图`, and `表格`.
Expected: returns chart configs and non-empty report data.

## Self-Review

- Spec coverage: CSV/Excel upload, preview, field profiling, natural-language requirement, chart type selection, field/aggregation controls, Plotly rendering are covered by Tasks 1-4.
- Placeholder scan: no implementation placeholder remains; deferred features are explicitly listed as out of scope.
- Type consistency: exported function names are consistent across task interfaces.
