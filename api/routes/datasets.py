from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from pathlib import Path
from uuid import uuid4
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

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
