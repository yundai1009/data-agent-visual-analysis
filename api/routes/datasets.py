# ============================================================
# 文件头 · 数据集上传/管理接口（面试讲解）
# ------------------------------------------------------------
# 管什么：数据集的增删改查——上传（校验格式与大小、落盘、解析成
#   DataFrame、生成画像、写 SQLite）、预览（head 20 行）、列表、
#   删除、重命名。
# 为什么这样设计：
#   - 上传的原始文件仍落盘（data/uploads/）留副本，同时数据本体
#     进 SQLite 持久化，进程重启不丢（阶段 2 从内存字典升级而来）；
#   - 安全细节：50MB 上限、扩展名白名单、文件名只取末尾组件
#     （防路径穿越）、解析失败即清理已落盘文件（防残留）；
#   - 所有接口都带 get_current_user 依赖——数据集严格按用户隔离，
#     别人看不到、删不掉你的数据。
# ============================================================
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from pathlib import Path
from uuid import uuid4
import io
import threading

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

import logging

logger = logging.getLogger(__name__)

from api.contracts import DatasetPreviewResponse, DatasetUploadResponse
from api.dependencies import get_current_user
from 后端_核心.文件数据服务 import 读取上传表格
from 后端_核心.数据画像 import 生成数据画像
from 后端_核心.存储 import 数据集仓储

router = APIRouter(prefix="/datasets", tags=["datasets"])

# 阶段 2：从进程内字典 _DATASET_DB 升级为本地 SQLite 持久化。
# 仓储实例在模块加载时初始化一次；SQLite 文件路径由 EnvConfig.SQLITE_PATH 决定。
_仓储 = 数据集仓储()

# 上传文件仍落到磁盘（兼容历史行为，留存原始文件副本）。
_UPLOAD_DIR = Path("data/uploads")
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# M21：数据集级操作锁——clean/rename 等"读-改-写"路径共享，防并发覆盖丢数据
_数据集操作锁 = threading.Lock()

# M19：上传文件名长度上限（超长文件名会写盘/入库，需在源头拦截）
_MAX_FILENAME_LEN = 120


# ---- 上传数据集：校验 → 落盘 → 解析 → 画像 → 入库 ------------------
# 支持多文件上传：逐文件校验/解析/入库，返回成功列表 + 失败列表。
@router.post("/upload")
async def upload_dataset(
    file: List[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """批量上传数据集：支持同时传入多个文件（CSV/Excel）。

    每个文件独立校验（空/超大/非法格式/文件名过长）、独立解析入库；
    成功与失败分别返回，前端可展示「成功 N 个，失败 M 个」。
    """
    _MAX_UPLOAD_BYTES = 50 * 1024 * 1024
    成功列表: List[Dict[str, Any]] = []
    失败列表: List[Dict[str, Any]] = []

    if not file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未选择任何文件")

    for f in file:
        try:
            result = await _处理单个上传(f, user["user_id"], _MAX_UPLOAD_BYTES)
            成功列表.append(result)
        except HTTPException as exc:
            失败列表.append({"文件名": f.filename or "未知", "错误": exc.detail})
        except Exception as exc:
            logger.exception("批量上传未知异常：%s", exc)
            失败列表.append({"文件名": f.filename or "未知", "错误": "解析失败，请重试"})

    # 兼容旧契约：全部文件都失败时返回 400（单文件上传失败即是此场景），
    # 部分成功时返回 200 + 成功/失败列表，前端展示「成功 N 个，失败 M 个」。
    if not 成功列表 and 失败列表:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="；".join(f"{f['文件名']}: {f['错误']}" for f in 失败列表) or "全部文件上传失败",
        )

    return {"上传成功": 成功列表, "上传失败": 失败列表, "成功数": len(成功列表), "失败数": len(失败列表)}


async def _处理单个上传(
    f: UploadFile, user_id: str, max_bytes: int
) -> Dict[str, Any]:
    """单文件上传流程：读取 → 校验 → 落盘 → 解析 → 画像 → 入库 → 返回响应字典。"""
    content = await f.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    if len(content) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过 50MB 限制")

    safe_name = (f.filename or "").lower()
    if not safe_name.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 .csv / .xlsx / .xls 格式")
    if len(Path(f.filename or "upload").name) > _MAX_FILENAME_LEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"文件名过长（最多 {_MAX_FILENAME_LEN} 字符）")

    dataset_id = uuid4().hex
    safe_name = Path(f.filename or "upload").name
    stored_name = f"{dataset_id}_{safe_name}"
    stored_path = _UPLOAD_DIR / stored_name
    stored_path.write_bytes(content)

    uploaded_proxy = io.BytesIO(content)
    uploaded_proxy.name = safe_name
    try:
        df = 读取上传表格(uploaded_proxy)
        画像 = 生成数据画像(df)
    except ValueError as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ImportError as exc:
        stored_path.unlink(missing_ok=True)
        logger.error("上传解析依赖缺失: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件解析依赖缺失（.xls 需要 xlrd），请检查服务端依赖",
        ) from exc
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        logger.exception("上传文件解析失败（未知异常），已清理残留")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="文件解析失败，请重试") from exc

    _仓储.保存(
        user_id=user_id,
        dataset_id=dataset_id,
        文件名=safe_name,
        存储路径=str(stored_path),
        df=df,
        画像=画像,
    )
    return {
        "数据集ID": dataset_id,
        "文件名": safe_name,
        "行数": 画像["行数"],
        "列数": 画像["列数"],
        "字段列表": 画像["字段列表"],
        "数据画像": 画像,
    }


@router.post("/merge")
async def merge_datasets(payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """优化③：合并多个数据集为一份（列对齐 union + 行追加），返回新数据集。

    body: {"数据集ID列表": [...], "文件名": "可选新名称"}
    列对齐：各数据集列取并集，缺失列填 NaN；行上限 50 万（防画像/存储膨胀）。
    """
    import pandas as pd
    ids = payload.get("数据集ID列表") or []
    新文件名 = (payload.get("文件名") or "").strip()
    if not isinstance(ids, list) or len(ids) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少选择 2 个数据集进行合并")
    if len(ids) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="一次最多合并 20 个数据集")
    if len(新文件名) > 120:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名过长（最多 120 字符）")

    dfs: List[pd.DataFrame] = []
    for _id in ids:
        item = _仓储.读取(user["user_id"], str(_id))
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"数据集不存在或无权访问")
        dfs.append(item["数据"])

    merged = pd.concat(dfs, ignore_index=True, sort=False)
    _MAX_MERGE_ROWS = 500_000
    if len(merged) > _MAX_MERGE_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"合并后共 {len(merged)} 行，超过上限 {_MAX_MERGE_ROWS} 行",
        )
    if merged.empty or len(merged.columns) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="合并结果为空，请检查所选数据集")

    新文件名 = 新文件名 or f"合并数据集（{len(ids)} 个）"
    画像 = 生成数据画像(merged)
    dataset_id = uuid4().hex
    _仓储.保存(
        user_id=user["user_id"],
        dataset_id=dataset_id,
        文件名=新文件名,
        存储路径="",
        df=merged,
        画像=画像,
    )
    return {
        "数据集ID": dataset_id,
        "文件名": 新文件名,
        "行数": 画像["行数"],
        "列数": 画像["列数"],
        "字段列表": 画像["字段列表"],
        "数据画像": 画像,
    }


@router.get("/{dataset_id}", response_model=DatasetPreviewResponse)
async def get_dataset(dataset_id: str, user: dict = Depends(get_current_user)) -> DatasetPreviewResponse:
    item = _仓储.读取(user["user_id"], dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")

    # SQLite 存的是 JSON 反序列化后的 DataFrame；预览仍取 head(20)
    df = item["数据"]
    画像 = item["数据画像"]
    return DatasetPreviewResponse(
        数据集ID=dataset_id,
        文件名=item["文件名"],
        预览数据=df.head(20).to_dict(orient="records"),
        数据画像=画像,
    )


@router.get("/{dataset_id}/rows")
async def get_dataset_rows(
    dataset_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """优化⑨：数据集原始数据分页预览（避免一次返回全量撑爆前端）。"""
    item = _仓储.读取(user["user_id"], dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")
    df = item["数据"]
    total = int(len(df))
    rows = df.iloc[offset:offset + limit]
    return {
        "数据集ID": dataset_id,
        "文件名": item["文件名"],
        "总行数": total,
        "偏移": offset,
        "返回行数": int(len(rows)),
        "数据": rows.to_dict(orient="records"),
    }


@router.get("/", response_model=Dict[str, Any])
async def list_datasets(
    limit: int = Query(200, ge=1, le=500),
    q: str = Query("", max_length=100, description="文件名搜索"),
    sort: str = Query("created_at_desc", pattern="^(created_at_desc|rows_desc|file_name_asc)$"),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出数据集（阶段 31 增强：文件名搜索 + 排序 + 概览统计）。"""
    items = _仓储.列表(user["user_id"], limit=limit, q=q, sort=sort)
    统计 = _仓储.统计(user["user_id"])
    return {"数据集列表": items, "统计": 统计}


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """删除一个数据集（仅限归属用户）。"""
    if not _仓储.删除(user["user_id"], dataset_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "删除数据集", target_type="dataset", target_id=dataset_id)
    return {"message": "已删除"}


@router.patch("/{dataset_id}")
async def rename_dataset(dataset_id: str, payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """重命名一个数据集（仅限归属用户）。"""
    新名 = str(payload.get("文件名") or "").strip()
    if not 新名 or len(新名) > 120:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名需 1-120 字符")
    # M21：与 clean 共用数据集级锁，防读-改-写并发交错
    with _数据集操作锁:
        if not _仓储.重命名(user["user_id"], dataset_id, 新名):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")
    return {"message": "已重命名", "文件名": 新名}
