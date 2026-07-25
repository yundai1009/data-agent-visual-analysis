# React/Vite 前端重做 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Streamlit 数据分析界面重做为 React + Vite 产品级前端，并保持 FastAPI 后端作为统一分析与报表服务。

**Architecture:** 第二阶段以“前后端分离”为目标：React/Vite 负责上传、配置、预览与图表展示；FastAPI 提供数据集上传、字段画像、报表生成和任务查询接口。先用本地文件/内存存储把核心流程跑通，再把页面与导航从 Streamlit 迁移到新前端，最后保留 Streamlit 作为内部调试入口。

**Tech Stack:** Python 3.11, FastAPI, React 18, TypeScript, Vite, Ant Design, React Router, Axios, Plotly.js, pandas.

## Global Constraints

- 保留现有 FastAPI 作为后端唯一业务入口。
- 新前端必须支持 CSV + Excel 上传。
- 不引入用户登录、权限、支付、团队协作、分享链接、PDF/HTML 导出作为第二阶段必需项。
- React 前端优先复用现有中文字段命名风格，避免把后端响应改成纯英文字段。
- 第二阶段目标是“可用的产品级前端骨架”，不是一次性替换掉所有 Streamlit 调试页面。
- 前端图表渲染优先沿用 Plotly 生态，保证与现有报表结果一致。

---

### Task 1: 后端补齐 React 前端所需的数据集与报表接口

**Files:**
- Modify: `api/contracts.py`
- Create: `api/routes/datasets.py`
- Create: `api/routes/reports.py`
- Modify: `api/main.py`

**Interfaces:**
- Produces: `DatasetUploadResponse`, `DatasetPreviewResponse`, `ReportGenerateRequest`, `ReportGenerateResponse`
- Produces: `POST /datasets/upload`, `GET /datasets/{dataset_id}`, `POST /reports/generate`
- Consumes: `读取上传表格(uploaded_file)`, `生成数据画像(df)`, `生成报表数据(df, 分析需求, 图表类型, x轴, y轴, 分组字段, 聚合方式)`

- [ ] **Step 1: Define API models**

Add the request/response models below to `api/contracts.py`:

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

- [ ] **Step 2: Implement dataset storage and upload route**

Create `api/routes/datasets.py` with a small reversible storage layer. Use a module-level dictionary for metadata and a local upload directory for file bytes so the React frontend can refresh and still read a previously uploaded dataset.

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from api.dependencies import get_current_user
from api.contracts import DatasetPreviewResponse, DatasetUploadResponse
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

Store the uploaded bytes as `data/uploads/{dataset_id}_{filename}` and keep the parsed `DataFrame` in `_DATASET_DB` for the current server process.

- [ ] **Step 3: Implement report generation route**

Create `api/routes/reports.py` that loads the dataset from `_DATASET_DB`, delegates to `生成报表数据`, and returns JSON-safe rows instead of raw `DataFrame` objects.

```python
from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_current_user
from api.contracts import ReportGenerateRequest, ReportGenerateResponse
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

Convert `报表数据` to `list[dict[str, Any]]` before returning so the React client does not depend on pandas serialization.

- [ ] **Step 4: Register routers**

Modify `api/main.py` to include the new routers:

```python
from api.routes import admin, feedback, tasks
from api.routes import datasets, reports

app.include_router(tasks.router)
app.include_router(feedback.router)
app.include_router(admin.router)
app.include_router(datasets.router)
app.include_router(reports.router)
```

- [ ] **Step 5: Verify backend syntax**

Run:

```powershell
python -m py_compile api\main.py api\contracts.py api\routes\datasets.py api\routes\reports.py
```

Expected: exit code 0.

---

### Task 2: Scaffold the React/Vite frontend project

**Files:**
- Create: `前端_react/package.json`
- Create: `前端_react/tsconfig.json`
- Create: `前端_react/vite.config.ts`
- Create: `前端_react/index.html`
- Create: `前端_react/src/main.tsx`
- Create: `前端_react/src/App.tsx`
- Create: `前端_react/src/api/http.ts`
- Create: `前端_react/src/api/datasets.ts`
- Create: `前端_react/src/api/reports.ts`
- Create: `前端_react/src/types.ts`
- Create: `前端_react/src/styles/global.css`

**Interfaces:**
- Consumes: backend endpoints from Task 1
- Produces: `createDatasetApi`, `createReportApi`, `fetchDatasetApi`

- [ ] **Step 1: Create package manifest and scripts**

Create `前端_react/package.json` with the following scripts and dependencies:

```json
{
  "name": "data-agent-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "antd": "^5.25.0",
    "axios": "^1.11.0",
    "plotly.js-dist-min": "^2.35.3",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-plotly.js": "^2.6.0",
    "react-router-dom": "^6.30.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.23",
    "@types/react-dom": "^18.3.7",
    "@vitejs/plugin-react": "^4.6.0",
    "typescript": "^5.8.3",
    "vite": "^7.0.4"
  }
}
```

- [ ] **Step 2: Add TypeScript and Vite wiring**

Create `tsconfig.json`, `vite.config.ts`, and `index.html` so the project can build with a single entry point under `src/main.tsx`.

```ts
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
})
```

- [ ] **Step 3: Build API client wrappers**

Create `src/api/http.ts` and keep the base URL configurable via `VITE_API_BASE_URL`.

```ts
import axios from 'axios'

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000',
  timeout: 120000,
})
```

Then add thin wrappers in `src/api/datasets.ts` and `src/api/reports.ts`:

```ts
export async function uploadDataset(file: File) { ... }
export async function fetchDataset(datasetId: string) { ... }
export async function generateReport(payload: ReportGenerateRequest) { ... }
```

- [ ] **Step 4: Add shared frontend types**

Create `src/types.ts` with the exact API-shape types used by the backend response:

```ts
export type DatasetUploadResponse = {
  数据集ID: string
  文件名: string
  行数: number
  列数: number
  字段列表: string[]
  数据画像: Record<string, unknown>
}

export type ReportGenerateResponse = {
  报表ID: string
  数据集ID: string
  标题: string
  图表类型: string
  图表配置: Record<string, unknown>
  报表数据: Record<string, unknown>[]
  数据画像: Record<string, unknown>
  结论: string
}
```

- [ ] **Step 5: Verify the frontend builds**

Run:

```powershell
cd 前端_react
npm install
npm run build
```

Expected: build completes successfully and emits production assets under `dist/`.

---

### Task 3: Build the React upload/report experience

**Files:**
- Create: `前端_react/src/pages/UploadReportPage.tsx`
- Create: `前端_react/src/components/DataProfileCard.tsx`
- Create: `前端_react/src/components/ReportToolbar.tsx`
- Create: `前端_react/src/components/ChartPreview.tsx`
- Modify: `前端_react/src/App.tsx`
- Modify: `前端_react/src/main.tsx`

**Interfaces:**
- Consumes: `uploadDataset(file)`, `fetchDataset(datasetId)`, `generateReport(payload)`
- Produces: upload flow, report form, chart preview, data table, summary panel

- [ ] **Step 1: Build the upload page shell**

Create a page that contains three sections:

```tsx
// 1. 上传区
// 2. 字段画像与预览区
// 3. 报表配置与结果区
```

Use `Upload.Dragger` from Ant Design for the upload area and keep the page state local in React.

- [ ] **Step 2: Add the profiling panel**

Implement a card that renders row count, column count, missing value count, and field groups from `数据画像`.

```tsx
export function DataProfileCard({ profile }: { profile: DatasetUploadResponse['数据画像'] }) {
  ...
}
```

- [ ] **Step 3: Add report configuration controls**

Implement a toolbar with the exact controls below:

- 自然语言需求 `Input.TextArea`
- 图表类型 `Select` with `自动推荐 / 柱状图 / 折线图 / 饼图 / 散点图 / 表格`
- X轴字段 `Select`
- Y轴字段 `Select` with multi-select behavior
- 分组字段 `Select`
- 聚合方式 `Select` with `求和 / 平均值 / 计数 / 最大值 / 最小值`

- [ ] **Step 4: Render the chart and table**

Use `react-plotly.js` to render the chart and Ant Design `Table` to render `报表数据`.

```tsx
import Plot from 'react-plotly.js'

export function ChartPreview({ config }: { config: ReportGenerateResponse['图表配置'] }) {
  ...
}
```

- [ ] **Step 5: Wire the page into the app**

Set `App.tsx` to mount `UploadReportPage` directly for the first iteration, so the front door is obvious and easy to validate.

```tsx
export default function App() {
  return <UploadReportPage />
}
```

- [ ] **Step 6: Verify the page compiles**

Run:

```powershell
cd 前端_react
npm run build
```

Expected: no TypeScript or bundling errors.

---

### Task 4: Add product navigation and startup docs

**Files:**
- Create: `前端_react/README.md`
- Modify: `自助式数据分析Agent平台/第一阶段验收交付报告.md`
- Modify: `自助式数据分析Agent平台/docs/superpowers/plans/2026-07-22-upload-data-report-mvp.md` if it needs a cross-reference note

**Interfaces:**
- Consumes: React app startup commands and backend startup commands
- Produces: clear run instructions for developers

- [ ] **Step 1: Write the React startup guide**

Document these commands exactly:

```powershell
cd D:\python\agent\自助式数据分析Agent平台\前端_react
npm install
npm run dev
```

and backend startup:

```powershell
cd D:\python\agent\自助式数据分析Agent平台
python api\main.py
```

- [ ] **Step 2: Update the project delivery note**

Add a short note that the product now has both the original Streamlit MVP and the new React/Vite frontend track, and explain which one is the default user-facing path.

- [ ] **Step 3: Verify docs are readable**

Open the updated markdown files and confirm the new startup commands and architecture note are present.

---

### Task 5: End-to-end smoke verification

**Files:**
- No new files.

- [ ] **Step 1: Compile the backend**

Run:

```powershell
python -m compileall api config 后端_核心
```

Expected: all Python files compile.

- [ ] **Step 2: Build the frontend**

Run:

```powershell
cd 前端_react
npm run build
```

Expected: Vite emits production assets without TypeScript errors.

- [ ] **Step 3: Exercise the dataset/report flow manually**

Start backend and frontend, upload a small CSV with date/category/numeric columns, then confirm:

1. dataset upload succeeds,
2. field profile renders,
3. chart selection changes the output,
4. report table and conclusion render.

Expected: the full web flow works without Streamlit.

## Self-Review

- Spec coverage: React/Vite replacement, backend API support, upload/report flow, chart preview, and startup docs are covered by Tasks 1-5.
- Placeholder scan: no "TBD", "TODO", or vague test steps remain; every task has exact files and commands.
- Type consistency: backend and frontend share the same Chinese field names for dataset/report payloads, and the task interfaces reference only symbols defined earlier in the plan.
