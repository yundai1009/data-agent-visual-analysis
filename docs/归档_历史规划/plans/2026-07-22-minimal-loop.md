# Minimal Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project run as a minimal closed loop: Streamlit submits a task to FastAPI, FastAPI returns a completed mock result, and Streamlit displays SQL, data, chart config, and conclusions.

**Architecture:** Keep existing FastAPI and Streamlit structure. Implement only mock task completion and real HTTP calls from the frontend service layer; do not add database, LLM, Redis, Chroma, or LangGraph execution.

**Tech Stack:** Python 3.11, FastAPI, Streamlit, requests, pandas.

## Global Constraints

- Keep changes minimal and reversible.
- Do not integrate real NL2SQL, database, LLM, Redis, Chroma, or LangGraph in this iteration.
- Preserve existing Chinese function names and public page names.
- Make status handling compatible with backend enum values: `pending`, `running`, `completed`, `failed`, `cancelled`.

---

### Task 1: Backend Mock Task Completion

**Files:**
- Modify: `api/routes/tasks.py`

**Interfaces:**
- Consumes: `CreateTaskRequest`, `TaskResponse`, `TaskStatus` from `api.contracts`.
- Produces: `POST /tasks` response with `状态=completed`, `当前步骤=10`, and `结果` containing `SQL`, `数据`, `图表`, `结论`, `执行耗时秒`, `返回行数`, `Token消耗`, `成本_元`.

Steps:
- Update `create_task()` to create a deterministic mock result from `payload.问题`.
- Keep `get_task()`, `cancel_task()`, and `list_tasks()` working with `_TASK_DB`.
- Run Python compile check on `api/routes/tasks.py`.

### Task 2: Frontend API Client

**Files:**
- Modify: `前端_streamlit/服务/api客户端.py`

**Interfaces:**
- Produces: `创建任务(问题: str, 执行模式: str = "auto", 最大重试次数: int = 2, 启用缓存: bool = True, 异步执行: bool = True) -> str | None`.
- Produces: `获取任务状态(任务ID: str) -> dict | None`.
- Produces: `取消任务(任务ID: str) -> dict | None`.
- Produces: `获取任务列表() -> list[dict]`.

Steps:
- Add `requests` calls to `http://127.0.0.1:8000` by default.
- Add a demo Bearer token header because backend currently requires HTTPBearer.
- Map Streamlit selectbox labels to backend execution modes `auto`, `fast`, `deep`.
- Return safe `None` or empty lists on network/API errors and show Streamlit errors when available.
- Run Python compile check.

### Task 3: Streamlit Entry and Status Compatibility

**Files:**
- Modify: `前端_streamlit/主入口.py`
- Modify: `前端_streamlit/页面/任务提交.py`

**Interfaces:**
- `主入口.py` should call the selected page function.
- `任务提交.py` should treat backend `completed`, `failed`, `cancelled` as terminal states and display completed mock results.

Steps:
- Implement Streamlit sidebar navigation with existing page functions.
- Normalize `任务提交.py` status checks to backend English enum values.
- Because backend completes immediately in this minimal loop, display results after the first successful status read.
- Run Python compile check.

### Task 4: Basic Verification

Steps:
- Run `python -m compileall api config 前端_streamlit 后端_核心` from project directory.
- Run a small FastAPI TestClient script that posts `/tasks`, reads `/tasks/{task_id}`, and verifies `状态 == "completed"` and `结果.SQL` exists.
- Summarize changed files and how to run manually.
