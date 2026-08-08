from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.contracts import CleanDatasetResponse
from api.dependencies import get_current_user
from api.routes.datasets import _仓储
from 后端_核心.数据清洗 import 清洗数据集

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/{dataset_id}/clean", response_model=CleanDatasetResponse)
async def clean_dataset(
    dataset_id: str,
    deduplicate: bool = Query(False, description="是否去重"),
    fill_missing: bool = Query(False, description="是否填充缺失值"),
    fill_strategy: str = Query("auto", description="填充策略: auto/mean/median/mode/zero"),
    drop_empty_rows: bool = Query(False, description="是否删除全空行"),
    drop_empty_columns: bool = Query(False, description="是否删除全空列"),
    user: dict = Depends(get_current_user),
) -> CleanDatasetResponse:
    """对数据集执行清洗操作，保存清洗后版本并返回摘要。"""
    item = _仓储.读取(user["user_id"], dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")

    df = item["数据"]
    result = 清洗数据集(
        df,
        deduplicate=deduplicate,
        fill_missing=fill_missing,
        fill_strategy=fill_strategy,
        drop_empty_rows=drop_empty_rows,
        drop_empty_columns=drop_empty_columns,
    )
    cleaned_df = result["清洗后数据"]
    摘要 = result["操作摘要"]

    # 保存清洗版本（用同一 dataset_id 覆盖；如需保留原始数据可换新 id）
    from 后端_核心.数据画像 import 生成数据画像
    from 后端_核心.文件数据服务 import 读取上传表格
    import io

    new_profile = 生成数据画像(cleaned_df)
    _仓储.保存(
        user_id=user["user_id"],
        dataset_id=dataset_id,
        文件名=item["文件名"] + "（已清洗）",
        存储路径=item.get("路径", ""),  # B11 修复：仓储返回键为"路径"（原"存储路径"取不到 → 溯源元数据被清空）
        df=cleaned_df,
        画像=new_profile,
    )

    return CleanDatasetResponse(
        数据集ID=dataset_id,
        原行数=len(df),
        清洗后行数=len(cleaned_df),
        清洗前列数=len(df.columns),
        清洗后列数=len(cleaned_df.columns),
        操作摘要=摘要,
        数据画像=new_profile,
    )
