# HTML + FastAPI + ECharts 轻量化数据分析 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前项目收敛为“HTML 前端 + FastAPI 后端 + ECharts 图表”的轻量化数据分析 Agent，支持上传 CSV/Excel、自然语言描述分析目标、选择图表类型，并自动生成可视化报表。

**Architecture:** 前端使用原生 HTML + CSS + JavaScript 负责上传、字段选择、图表切换和结果展示；后端使用 FastAPI 负责文件接收、表格解析、字段画像、报表生成和 JSON API 输出。分析逻辑全部在 Python/pandas 中完成，前端只消费结构化结果并渲染 ECharts，不再依赖 Streamlit，也不再依赖 MySQL/NL2SQL 主链路。

**Tech Stack:** Python 3.11, FastAPI, pandas, openpyxl, HTML, CSS, JavaScript, ECharts, Jinja2, multipart file upload.

## Global Constraints

- 主入口只保留“上传文件生成报表”链路，不再依赖 MySQL 作为用户数据源。
- 支持上传类型：CSV、XLSX、XLS。
- 前端必须可直接部署为静态页面或模板渲染页面，不依赖 Streamlit 会话状态。
- 图表渲染使用 ECharts，不引入重型前端框架作为第一版必需项。
- 后端返回 JSON-safe 结构，前端不得依赖 pandas 对象直接渲染。
- 自然语言用于分析意图、标题和结论生成，不允许执行任意代码。
- 第二阶段目标是可上线、可维护、可继续演进的轻量化产品骨架，而不是一次性做成复杂 BI 平台。

---

### Task 1: 后端补齐文件上传与报表接口

**Files:**
- Modify: `api/contracts.py`
- Create: `api/routes/datasets.py`
- Create: `api/routes/reports.py`
- Modify: `api/main.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `DatasetUploadResponse`, `DatasetPreviewResponse`, `ReportGenerateRequest`, `ReportGenerateResponse`
- Produces: `POST /datasets/upload`, `GET /datasets/{dataset_id}`, `POST /reports/generate`
- Consumes: `读取上传表格(uploaded_file: Any) -> pandas.DataFrame`, `生成数据画像(df: pandas.DataFrame) -> dict[str, Any]`, `生成报表数据(df, 分析需求, 图表类型, x轴, y轴, 分组字段, 聚合方式) -> dict[str, Any]`

- [ ] **Step 1: Add request and response models**

Add these exact models to `api/contracts.py`:

```python
class DatasetUploadResponse(BaseModel):
    数据集ID: str
    文件名: str
    行数: int
    列数: int
    字段列表: list[str]
    数据画像: dict[str, Any]

class DatasetPreviewResponse(BaseModel):
    数据集ID: str
    文件名: str
    预览数据: list[dict[str, Any]]
    数据画像: dict[str, Any]

class ReportGenerateRequest(BaseModel):
    数据集ID: str
    分析需求: str = ""
    图表类型: str = "自动推荐"
    x轴: Optional[str] = None
    y轴: list[str] = Field(default_factory=list)
    分组字段: Optional[str] = None
    聚合方式: str = "求和"

class ReportGenerateResponse(BaseModel):
    报表ID: str
    数据集ID: str
    标题: str
    图表类型: str
    图表配置: Dict[str, Any]
    报表数据: list[dict[str, Any]]
    数据画像: Dict[str, Any]
    结论: str
```

- [ ] **Step 2: Implement dataset upload and preview routes**

Create `api/routes/datasets.py` with a module-level in-memory registry and local upload directory:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from api.contracts import DatasetPreviewResponse, DatasetUploadResponse
from api.dependencies import get_current_user
from 后端_核心.文件数据服务 import 读取上传表格
from 后端_核心.数据画像 import 生成数据画像

router = APIRouter(prefix="/datasets", tags=["datasets"])
_DATASET_DB: Dict[str, Dict[str, Any]] = {}
_UPLOAD_DIR = Path("data/uploads")
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload", response_model=DatasetUploadResponse)
async def upload_dataset(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> DatasetUploadResponse:
    ...

@router.get("/{dataset_id}", response_model=DatasetPreviewResponse)
async def get_dataset(dataset_id: str) -> DatasetPreviewResponse:
    ...
```

Persist uploaded bytes to `data/uploads/{dataset_id}_{filename}` and cache the parsed `DataFrame` in `_DATASET_DB` for the current process.

- [ ] **Step 3: Implement report generation route**

Create `api/routes/reports.py` with a single generation endpoint:

```python
from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.contracts import ReportGenerateRequest, ReportGenerateResponse
from api.dependencies import get_current_user
from api.routes.datasets import _DATASET_DB
from 后端_核心.上传报表生成器 import 生成报表数据

router = APIRouter(prefix="/reports", tags=["reports"])

@router.post("/generate", response_model=ReportGenerateResponse)
async def generate_report(
    payload: ReportGenerateRequest,
    user: dict = Depends(get_current_user),
) -> ReportGenerateResponse:
    ...
```

Convert the returned `报表数据` into `list[dict[str, Any]]` before sending it to the client.

- [ ] **Step 4: Register the new routers**

Modify `api/main.py` so the app includes the new routers:

```python
from api.routes import datasets, reports

app.include_router(datasets.router)
app.include_router(reports.router)
```

Keep `/health` intact.

- [ ] **Step 5: Add backend dependencies**

Modify `requirements.txt` to ensure the backend can read Excel uploads and accept file uploads:

```text
python-multipart
openpyxl
```

- [ ] **Step 6: Verify backend syntax**

Run:

```powershell
python -m py_compile api\main.py api\contracts.py api\routes\datasets.py api\routes\reports.py
```

Expected: exit code 0.

---

### Task 2: Build the HTML page shell and upload workflow

**Files:**
- Create: `前端_html/app.py`
- Create: `前端_html/templates/base.html`
- Create: `前端_html/templates/index.html`
- Create: `前端_html/static/css/app.css`
- Create: `前端_html/static/js/app.js`
- Create: `前端_html/static/js/api.js`

**Interfaces:**
- Consumes: `POST /datasets/upload`, `GET /datasets/{dataset_id}`, `POST /reports/generate`
- Produces: upload form, dataset preview panel, analysis config panel, result container

- [ ] **Step 1: Create the template shell**

Create `前端_html/templates/base.html` with a title slot and a `main` content block, then create `前端_html/templates/index.html` with a three-column layout:

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>数据分析 Agent</title>
    <link rel="stylesheet" href="/static/css/app.css" />
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  </head>
  <body>
    <header class="app-header">
      <h1>数据分析 Agent</h1>
      <p>上传 CSV / Excel，自动生成可视化报表</p>
    </header>
    <main class="layout">
      <aside id="dataset-panel"></aside>
      <section id="config-panel"></section>
      <section id="result-panel"></section>
    </main>
    <script type="module" src="/static/js/app.js"></script>
  </body>
</html>
```

- [ ] **Step 2: Build the FastAPI HTML entrypoint**

Create `前端_html/app.py` that serves the template and static assets:

```python
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="数据分析 Agent")
app.mount("/static", StaticFiles(directory="前端_html/static"), name="static")
templates = Jinja2Templates(directory="前端_html/templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

- [ ] **Step 3: Create the client API wrapper**

Create `前端_html/static/js/api.js` with thin fetch wrappers:

```javascript
export async function uploadDataset(file) { ... }
export async function fetchDataset(datasetId) { ... }
export async function generateReport(payload) { ... }
```

Use `FormData` for upload and JSON for report generation.

- [ ] **Step 4: Implement the upload flow**

Create `前端_html/static/js/app.js` so that:

- file upload submits to `/datasets/upload`
- on success the dataset panel renders file name, row count, column count, and field groups
- the preview table shows the first 20 rows
- the page remembers the returned `数据集ID` in a local variable for subsequent report generation

- [ ] **Step 5: Verify the HTML shell loads**

Run:

```powershell
python -m py_compile 前端_html\app.py
```

Expected: exit code 0.

---

### Task 3: Add report configuration and ECharts rendering

**Files:**
- Modify: `前端_html/templates/index.html`
- Modify: `前端_html/static/css/app.css`
- Modify: `前端_html/static/js/app.js`

**Interfaces:**
- Consumes: uploaded dataset state, analysis config controls, report generation response
- Produces: chart card selection, chart canvas, table view, conclusion view

- [ ] **Step 1: Add chart card controls**

Implement a chart selector with these exact options:

- 自动推荐
- 柱状图
- 折线图
- 饼图
- 散点图
- 表格

Each card should show a short explanation:

```text
柱状图：分类对比
折线图：趋势变化
饼图：占比分析
散点图：相关性观察
表格：明细查看
```

- [ ] **Step 2: Add field selectors**

Render these controls in the config panel:

- 自然语言分析需求 textarea
- X 轴 select
- Y 轴 multi-select
- 分组字段 select
- 聚合方式 select
- 生成报表 button
- 重新生成 button

The X/Y field lists must be populated from the uploaded dataset response.

- [ ] **Step 3: Render the chart with ECharts**

Use `echarts.init(...)` and `setOption(...)` to render the returned chart config. Keep the chart data format JSON-safe and pass axis, series, title, and tooltip data directly from the backend response.

Example client-side structure:

```javascript
const option = {
  title: { text: report.标题 },
  tooltip: {},
  xAxis: { type: 'category', data: xData },
  yAxis: { type: 'value' },
  series: [{ type: report.图表类型, data: yData }]
}
```

- [ ] **Step 4: Render report table and conclusion**

Show `报表数据` in a simple HTML table and render `结论` as markdown-like text blocks or highlighted cards.

- [ ] **Step 5: Verify front-end assets are syntactically valid**

Run a browserless smoke check by opening the HTML entry and confirming the page loads without console syntax errors in the static bundle.

---

### Task 4: Tighten analysis utilities and error handling

**Files:**
- Modify: `后端_核心/文件数据服务.py`
- Modify: `后端_核心/数据画像.py`
- Modify: `后端_核心/上传报表生成器.py`

**Interfaces:**
- Consumes: uploaded file bytes and parsed DataFrame
- Produces: reliable parsing, profiling, aggregation, and report payloads

- [ ] **Step 1: Harden file reading**

Ensure `读取上传表格(uploaded_file)` rejects empty files and unsupported suffixes with explicit `ValueError` messages such as:

```python
raise ValueError("上传文件没有读取到数据")
raise ValueError("不支持的文件格式")
```

- [ ] **Step 2: Harden field profiling**

Ensure `生成数据画像(df)` always returns these keys:

- `行数`
- `列数`
- `字段列表`
- `数值字段`
- `日期字段`
- `分类字段`
- `文本字段`
- `缺失值`
- `总缺失值`

- [ ] **Step 3: Harden report generation**

Ensure `生成报表数据(...)` returns a dict with:

- `标题`
- `分析需求`
- `图表类型`
- `图表配置`
- `报表数据`
- `数据画像`
- `结论`

and that `报表数据` is always JSON-safe.

- [ ] **Step 4: Verify core smoke tests**

Run a local script with a sample DataFrame containing date, category, and numeric columns and verify all chart types return non-empty results.

---

### Task 5: Add documentation and startup instructions

**Files:**
- Create: `前端_html/README.md`
- Modify: `自助式数据分析Agent平台/第一阶段验收交付报告.md`
- Modify: `docs/superpowers/specs/2026-07-22-html-fastapi-echarts-lightweight-agent-design.md` if startup notes need to match implementation

**Interfaces:**
- Consumes: final app startup commands and endpoint list
- Produces: developer run instructions and product positioning notes

- [ ] **Step 1: Write the HTML frontend run guide**

Document exactly these commands:

```powershell
cd D:\python\agent\自助式数据分析Agent平台
python api\main.py
```

and, if the HTML app is run separately:

```powershell
cd D:\python\agent\自助式数据分析Agent平台
python 前端_html\app.py
```

- [ ] **Step 2: Update the delivery note**

Add a short note that the product has been收敛为文件上传数据报表 Agent，主链路不再依赖 MySQL/NL2SQL 和 Streamlit。

- [ ] **Step 3: Verify docs are readable**

Open the updated markdown files and confirm startup commands and architecture notes are present and consistent.

---

### Task 6: End-to-end smoke verification

**Files:**
- No new files.

- [ ] **Step 1: Compile the backend**

Run:

```powershell
python -m compileall api config 后端_核心
```

Expected: all backend Python files compile.

- [ ] **Step 2: Validate the upload/report flow**

Start the backend, open the HTML page, upload a small CSV with date/category/numeric columns, and confirm:

1. upload succeeds,
2. field profile renders,
3. chart type selection changes the output,
4. report table and conclusion render.

- [ ] **Step 3: Validate chart variants**

Repeat the report generation for:

- 自动推荐
- 柱状图
- 折线图
- 饼图
- 散点图
- 表格

Expected: each option returns a valid JSON payload and a visible result.

## Self-Review

- Spec coverage: upload, preview, profiling, chart selection, ECharts rendering, report generation, error handling, docs, and smoke tests are all covered by Tasks 1-6.
- Placeholder scan: no TBD/TODO/fill-in placeholders remain.
- Type consistency: backend response models and frontend payload names use the same Chinese field names across tasks.
- Scope check: this plan stays focused on one product surface — lightweight file-based data analysis and reporting — and avoids unrelated BI platform features.
