from __future__ import annotations

import io
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.contracts import LoadExampleResponse
from api.dependencies import get_current_user
from api.routes.datasets import _仓储
from 后端_核心.文件数据服务 import 读取上传表格
from 后端_核心.数据画像 import 生成数据画像

router = APIRouter(prefix="/datasets", tags=["datasets"])

# 内置示例数据目录
_EXAMPLES_DIR = Path("data/examples")
_EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/load-example", response_model=LoadExampleResponse)
async def load_example_dataset(
    user: dict = Depends(get_current_user),
) -> LoadExampleResponse:
    """加载内置示例数据集，方便新用户快速体验。"""
    example_path = _EXAMPLES_DIR / "sales_2024.csv"
    if not example_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="示例数据文件不存在",
        )
    content = example_path.read_bytes()
    dataset_id = uuid4().hex

    uploaded_proxy = io.BytesIO(content)
    uploaded_proxy.name = "sales_2024.csv"
    try:
        df = 读取上传表格(uploaded_proxy)
        画像 = 生成数据画像(df)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _仓储.保存(
        dataset_id=dataset_id,
        文件名="sales_2024.csv",
        存储路径=str(example_path),
        df=df,
        画像=画像,
    )

    return LoadExampleResponse(
        数据集ID=dataset_id,
        文件名="sales_2024.csv",
        行数=画像["行数"],
        列数=画像["列数"],
        字段列表=画像["字段列表"],
        数据画像=画像,
    )
