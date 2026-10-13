# ============================================================
# 文件头 · 示例数据集接口（面试讲解）
# ------------------------------------------------------------
# 管什么：POST /datasets/load-example —— 把内置示例 CSV
#   （data/examples/sales_2024.csv）加载为当前用户的数据集。
# 为什么需要它：新用户没数据也能"一键体验"完整分析流程；
#   复用上传链路（读取表格 → 画像 → 入库），只是数据源换成内置文件。
# 路径怎么找（阶段 59 修 404）：
#   数据目录约定 = 当前工作目录（desktop electron/main.js spawn 时把 cwd 设为
#   %APPDATA%\数据分析Agent，故 data/uploads、data/parquet 都落在数据目录下）。
#   源码用 cwd 相对路径就够，但安装包启动时 cwd 由用户/快捷方式决定，靠猜 cwd 会 404；
#   故「可写目录（数据目录）+ 只读副本（随包分发）」两级解析，见 解析示例文件()。
# ============================================================
from __future__ import annotations

import io
import logging
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.contracts import LoadExampleResponse
from api.dependencies import get_current_user
from api.routes.datasets import _仓储
from 后端_核心.file_services import 读取上传表格
from 后端_核心.profile import 生成数据画像

router = APIRouter(prefix="/datasets", tags=["datasets"])

_log = logging.getLogger(__name__)

# 内置示例数据文件名（随代码/安装包分发，见 electron/build-backend/daa-backend.spec）
_示例文件名 = "sales_2024.csv"


def _可写示例目录() -> Path:
    """可写示例目录：与 data/uploads 同一约定（相对当前工作目录 = 数据目录）。"""
    return Path("data/examples")


def _只读示例候选() -> list[Path]:
    """随代码/安装包分发的只读副本候选。

    与 config/settings.py 读 providers.toml 同策略：以 __file__ 锚定（打包后
    __file__ 落在解包目录内，无需 _MEIPASS 也能定位）；再补 sys._MEIPASS 兜底
    （onefile 模式 __file__ 落在临时目录外层）。
    """
    候选: list[Path] = []
    解包根 = getattr(sys, "_MEIPASS", "")
    if 解包根:
        候选.append(Path(解包根) / "data" / "examples" / _示例文件名)
    候选.append(Path(__file__).resolve().parents[2] / "data" / "examples" / _示例文件名)
    return 候选


def 解析示例文件() -> Path | None:
    """返回可长期使用的示例文件路径；两者都没有时返回 None（路由转 404）。

    优先级：
    1. 可写目录已有（用户自带/替换过的示例，或上次复制过来的副本）→ 直接用；
    2. 只有只读副本（仓库源码 / 安装包）→ 复制到可写目录再用。必须落副本是因为
       入库的 溯源路径 若指向 PyInstaller 解包目录，应用退出即失效（clean 的
       溯源元数据、导出文件名会指向一个不存在的文件）；
    3. 都没有 → None。
    """
    目标 = _可写示例目录() / _示例文件名
    if 目标.exists():
        return 目标
    for 源 in _只读示例候选():
        # 同一文件（源码运行且 cwd=仓库根）已在第 1 步返回，这里跳过以免 self-copy
        if not 源.exists() or 源.resolve() == 目标.resolve():
            continue
        try:
            目标.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(源, 目标)
            return 目标
        except OSError as exc:
            # 数据目录不可写（只读部署等）：功能仍可用，只是溯源路径指向只读副本
            _log.warning("示例数据复制到 %s 失败（%s），改用只读副本 %s", 目标, exc, 源)
            return 源
    return None


@router.post("/load-example", response_model=LoadExampleResponse)
def load_example_dataset(
    user: dict = Depends(get_current_user),
) -> LoadExampleResponse:
    """加载内置示例数据集，方便新用户快速体验。"""
    example_path = 解析示例文件()
    if example_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="示例数据文件不存在（内置示例文件缺失，请检查安装包完整性）",
        )
    content = example_path.read_bytes()
    dataset_id = uuid4().hex

    uploaded_proxy = io.BytesIO(content)
    uploaded_proxy.name = _示例文件名
    try:
        df = 读取上传表格(uploaded_proxy)
        画像 = 生成数据画像(df)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _仓储.保存(
        user_id=user["user_id"],
        dataset_id=dataset_id,
        文件名=_示例文件名,
        存储路径=str(example_path),
        df=df,
        画像=画像,
    )

    return LoadExampleResponse(
        数据集ID=dataset_id,
        文件名=_示例文件名,
        行数=画像["行数"],
        列数=画像["列数"],
        字段列表=画像["字段列表"],
        数据画像=画像,
    )