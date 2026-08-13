# ============================================================
# 文件头 · 定时任务路由（阶段 30）
# ------------------------------------------------------------
# 管什么：定时生成的增删查——
#   POST   /schedules            创建定时任务（模板 + cron 表达式）
#   GET    /schedules            列出我的定时任务
#   DELETE /schedules/{id}       删除定时任务
# 执行引擎：services/scheduler.py 的后台线程每 30s tick 一次，
#   命中 cron 的任务自动用模板配置 + 数据集最新数据生成报表入库。
# 删除它会怎样：定时生成停摆，只剩手动/模板一键执行。
# ============================================================
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from api.contracts import 定时任务请求
from api.dependencies import get_current_user
from services.scheduler import cron合法, 下次执行时间

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.post("", response_model=Dict[str, Any])
def 创建定时任务(body: 定时任务请求, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """创建定时任务：校验 cron 表达式合法 + 模板归属。"""
    from repositories import schedule_repo, template_repo

    if not cron合法(body.cron):  # 5 字段语法校验（不依赖当前时间命中）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cron 表达式不合法（应为 5 字段：分 时 日 月 周）")
    if not template_repo.读取模板(user["user_id"], body.模板ID):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    job_id = schedule_repo.创建任务(user["user_id"], body.模板ID, body.cron.strip())
    return {"任务ID": job_id, "message": "定时任务已创建"}


@router.get("", response_model=Dict[str, Any])
def 列出定时任务(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    from repositories import schedule_repo

    任务列表 = schedule_repo.列出任务(user["user_id"])
    # 附上"下次执行时间"（未来 7 天内首次命中），前端直接展示
    for 任务 in 任务列表:
        任务["下次执行"] = 下次执行时间(任务["cron"])
    return {"任务列表": 任务列表}


@router.delete("/{job_id}", response_model=Dict[str, str])
def 删除定时任务(job_id: str, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    from repositories import schedule_repo

    if not schedule_repo.删除任务(user["user_id"], job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="定时任务不存在")
    return {"message": "已删除"}