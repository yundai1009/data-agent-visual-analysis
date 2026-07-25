# Frontend Navigation Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Streamlit frontend understandable for first-time users by turning the UI from feature-menu navigation into workflow navigation.

**Architecture:** Keep existing Streamlit pages and components, but rename/reorder navigation, reduce sidebar noise, add environment readiness signals, simplify the task submission page into a three-step “start analysis” flow, and add clear empty-state guidance to secondary pages.

**Tech Stack:** Python 3.11, Streamlit, existing custom CSS/components.

## Global Constraints

- Preserve existing page function names exported from `前端_streamlit/页面/__init__.py` to minimize routing changes.
- User-facing navigation labels become: `开始分析`, `分析记录`, `数据看板`, `知识配置`, `运行状态`.
- Keep advanced/unfinished features visually secondary.
- Do not change backend APIs in this pass.

---

## Tasks

1. Rewrite `前端_streamlit/组件/侧边栏导航.py` as a clean workflow sidebar with config readiness signals.
2. Update `前端_streamlit/主入口.py` page mapping from new labels to existing page functions.
3. Simplify `前端_streamlit/页面/任务提交.py` into a three-step guided “开始分析” flow and clearer failed/config-missing messaging.
4. Add concise page intro/empty state guidance to `历史记录`, `可视化看板`, `知识库管理`, and `系统监控` without deep feature rewrites.
5. Run `python -m compileall config api 前端_streamlit 后端_核心` and fix syntax/import failures.
