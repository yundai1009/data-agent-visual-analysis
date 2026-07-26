from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from uuid import uuid4
import io

import pandas as pd

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from api.contracts import (
    CleanDatasetResponse,
    DatasetPreviewResponse,
    DatasetUploadResponse,
    LoadExampleResponse,
)
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

    dataset_id = uuid4().hex
    file_name = file.filename or "upload"
    stored_name = f"{dataset_id}_{file_name}"
    stored_path = _UPLOAD_DIR / stored_name
    stored_path.write_bytes(content)

    uploaded_proxy = io.BytesIO(content)
    uploaded_proxy.name = file_name
    try:
        df = 读取上传表格(uploaded_proxy)
        画像 = 生成数据画像(df)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # 持久化到 SQLite。进程重启后仍可凭 dataset_id 取回数据。
    _仓储.保存(
        dataset_id=dataset_id,
        文件名=file_name,
        存储路径=str(stored_path),
        df=df,
        画像=画像,
    )

    return DatasetUploadResponse(
        数据集ID=dataset_id,
        文件名=file_name,
        行数=画像["行数"],
        列数=画像["列数"],
        字段列表=画像["字段列表"],
        数据画像=画像,
    )


@router.get("/{dataset_id}", response_model=DatasetPreviewResponse)
async def get_dataset(dataset_id: str) -> DatasetPreviewResponse:
    item = _仓储.读取(dataset_id)
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
async def list_datasets(limit: int = 50) -> Dict[str, Any]:
    """列出最近的数据集（阶段 2 新增；前端不依赖此接口）。"""
    return {"数据集列表": _仓储.列表(limit=limit)}


@router.post("/load-example", response_model=LoadExampleResponse)
async def load_example_dataset(
    user: dict = Depends(get_current_user),
) -> LoadExampleResponse:
    """加载内置示例数据集，方便新用户快速体验。"""
    example_path = Path("data/示例数据_销售数据.csv")
    if not example_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="示例数据集文件不存在")

    dataset_id = uuid4().hex
    file_name = "示例数据_销售数据.csv"
    stored_name = f"{dataset_id}_{file_name}"
    stored_path = _UPLOAD_DIR / stored_name

    content = example_path.read_bytes()
    stored_path.write_bytes(content)

    uploaded_proxy = io.BytesIO(content)
    uploaded_proxy.name = file_name
    df = 读取上传表格(uploaded_proxy)
    画像 = 生成数据画像(df)

    _仓储.保存(
        dataset_id=dataset_id,
        文件名=file_name,
        存储路径=str(stored_path),
        df=df,
        画像=画像,
    )

    return LoadExampleResponse(
        数据集ID=dataset_id,
        文件名=file_name,
        行数=画像["行数"],
        列数=画像["列数"],
        字段列表=画像["字段列表"],
        数据画像=画像,
    )


@router.post("/{dataset_id}/clean", response_model=CleanDatasetResponse)
async def clean_dataset(
    dataset_id: str,
    user: dict = Depends(get_current_user),
) -> CleanDatasetResponse:
    """一键基础清洗：去重、填充缺失值（数值列填中位数、分类列填众数）、删除全空行。"""
    item = _仓储.读取(dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")

    df = item["数据"].copy()
    original_rows = len(df)

    # 1. 删除全空行
    empty_rows_before = int(df.isna().all(axis=1).sum())
    df = df.dropna(how="all")

    # 2. 填充缺失值
    filled_count = 0
    for col in df.columns:
        missing = df[col].isna().sum()
        if missing == 0:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            fill_val = df[col].median()
        else:
            fill_val = df[col].mode().iloc[0] if not df[col].mode().empty else "未知"
        df[col] = df[col].fillna(fill_val)
        filled_count += missing

    # 3. 去重
    dup_count = int(df.duplicated().sum())
    df = df.drop_duplicates()

    # 重新生成画像
    画像 = 生成数据画像(df)

    # 保存清洗后的版本
    _仓储.保存(
        dataset_id=dataset_id,
        文件名=item["文件名"],
        存储路径=item["存储路径"],
        df=df,
        画像=画像,
    )

    return CleanDatasetResponse(
        数据集ID=dataset_id,
        原行数=original_rows,
        清洗后行数=len(df),
        去重行数=dup_count,
        填充缺失值=filled_count,
        删除空行=empty_rows_before,
        数据画像=画像,
    )
