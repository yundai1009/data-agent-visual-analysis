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
from typing import Any, Dict
from pathlib import Path
from uuid import uuid4
import io

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


# ---- 上传数据集：校验 → 落盘 → 解析 → 画像 → 入库 ------------------
# 为什么流程是这个顺序：先挡掉非法输入（空文件/超 50MB/非白名单格式），
# 再写磁盘，最后才解析入库——解析失败时 unlink 清理，不留半成品。
# 注意 file.filename 在 UploadFile 里是客户端可控字段，取 base name
# 防止 "../" 之类路径穿越。
@router.post("/upload", response_model=DatasetUploadResponse)
async def upload_dataset(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> DatasetUploadResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过 50MB 限制")

    # MIME 类型校验
    safe_name = (file.filename or "").lower()
    if not safe_name.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 .csv / .xlsx / .xls 格式")

    dataset_id = uuid4().hex
    # 只使用文件名末尾组件，防止路径穿越
    safe_name = Path(file.filename or "upload").name
    stored_name = f"{dataset_id}_{safe_name}"
    stored_path = _UPLOAD_DIR / stored_name
    stored_path.write_bytes(content)

    uploaded_proxy = io.BytesIO(content)
    uploaded_proxy.name = safe_name
    try:
        df = 读取上传表格(uploaded_proxy)
        画像 = 生成数据画像(df)
    except ValueError as exc:
        # 解析失败：清理已写入的文件，避免残留
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ImportError as exc:
        # B2 修复：.xls 依赖 xlrd 缺失等导入错误 → 400 并清理残留，而非 500
        stored_path.unlink(missing_ok=True)
        logger.error("上传解析依赖缺失: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件解析依赖缺失（.xls 需要 xlrd），请检查服务端依赖",
        ) from exc

    # 持久化到 SQLite。进程重启后仍可凭 dataset_id 取回数据。
    _仓储.保存(
        user_id=user["user_id"],
        dataset_id=dataset_id,
        文件名=safe_name,
        存储路径=str(stored_path),
        df=df,
        画像=画像,
    )

    return DatasetUploadResponse(
        数据集ID=dataset_id,
        文件名=safe_name,
        行数=画像["行数"],
        列数=画像["列数"],
        字段列表=画像["字段列表"],
        数据画像=画像,
    )


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


@router.get("/", response_model=Dict[str, Any])
async def list_datasets(
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出最近的数据集（阶段 2 新增；前端不依赖此接口）。"""
    return {"数据集列表": _仓储.列表(user["user_id"], limit=limit)}


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
    if not _仓储.重命名(user["user_id"], dataset_id, 新名):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")
    return {"message": "已重命名", "文件名": 新名}
