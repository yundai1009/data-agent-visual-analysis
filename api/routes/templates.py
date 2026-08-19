# ============================================================
# 文件头 · 报表模板路由（阶段 30）
# ------------------------------------------------------------
# 管什么：报表模板的增删改查与"一键执行"——
#   POST   /templates             保存模板（分析配置收藏）
#   GET    /templates             列出我的模板
#   DELETE /templates/{id}        删除模板
#   POST   /templates/{id}/run    立即用模板配置生成报表
# 为什么需要它：业务里"每周销售周报/每月对账"是固定套路，
#   每次重新配置费时费力；模板把分析意图沉淀下来一键复用，
#   也为 定时生成（scheduled_jobs）提供执行底座。
# 删除它会怎样：定时任务失去配置来源，用户每次手动重配。
# ============================================================
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from api.contracts import ReportGenerateRequest, ReportGenerateResponse, 模板请求
from api.dependencies import get_current_user
from api.routes.reports import (
    _STREAM_SEMAPHORE,
    _构建响应,
    _准备上下文,
    _生成报表流式,
)

router = APIRouter(prefix="/templates", tags=["templates"])


# ── 模板 CRUD ────────────────────────────────────────────────────────────────


@router.post("", response_model=Dict[str, Any])
def 保存模板(body: 模板请求, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """保存模板：payload 必须是合法的生成请求结构，字段超限即 422（P0 防超大体）。"""
    from repositories import template_repo

    # 用 Pydantic 校验 payload 字段合法性（过滤掉用户塞进来的多余键/超长值）
    try:
        ReportGenerateRequest(**body.payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"模板配置不合法：{exc.errors()[0]['msg'] if exc.errors() else '字段超限'}",
        )
    # M18：模板 payload 无大小上限此前可无限膨胀（入库 JSON 列/读取时撑爆内存），
    # 加 64KB 硬上限
    import json as _json
    if len(_json.dumps(body.payload, ensure_ascii=False, default=str)) > 64 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="模板配置过大（上限 64KB）")
    tid = template_repo.保存模板(user["user_id"], body.名称.strip(), body.payload)
    return {"模板ID": tid, "message": "模板已保存"}


@router.get("", response_model=Dict[str, Any])
def 列出模板(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    from repositories import template_repo

    return {"模板列表": template_repo.列出模板(user["user_id"])}


@router.delete("/{template_id}", response_model=Dict[str, str])
def 删除模板(template_id: str, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    from repositories import template_repo

    if not template_repo.删除模板(user["user_id"], template_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    return {"message": "已删除"}


# ── 一键执行 ──────────────────────────────────────────────────────────────────


@router.post("/{template_id}/run", response_model=ReportGenerateResponse)
def 执行模板(
    template_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> ReportGenerateResponse:
    """立即用模板配置生成一份新报表（读取数据集最新数据）。

    与 reports.replay 同一套执行链路：_准备上下文 校验数据集存在 + LLM 白名单，
    _生成报表流式 走标准生成（含筛选/TopN），并发受 _STREAM_SEMAPHORE 保护。
    """
    from repositories import template_repo

    item = template_repo.读取模板(user["user_id"], template_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")

    payload = ReportGenerateRequest(**item["payload"])
    if not _STREAM_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="当前分析任务已满（并发上限 4），请稍后重试",
        )
    try:
        df, llm_config = _准备上下文(payload, request, user)
        try:
            new_id, new_report = _生成报表流式(payload, df, llm_config, user)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return _构建响应(payload, new_report, new_id)
    finally:
        _STREAM_SEMAPHORE.release()