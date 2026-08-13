# ============================================================
# 文件头 · 文件数据服务（面试讲解）
# ------------------------------------------------------------
# 管什么：把用户上传的原始文件（.csv/.xlsx/.xls）解析成 DataFrame，
#   是"上传 → 分析"的第一道关卡（全项目唯一入口）。
# 关键细节：
#   - 按扩展名分派：CSV 用 utf-8 读取并做 GBK 兜底（国内 Excel
#     另存的 CSV 常见 GBK 编码），xlsx/xls 用 pandas 引擎；
#   - 解析失败抛 ValueError（带人话原因），由路由层转 400 给前端。
# 删除它会怎样：所有上传功能瘫痪。
# ============================================================
from __future__ import annotations

from typing import Any

import pandas as pd


支持的上传后缀 = {".csv", ".xlsx", ".xls"}


def _文件后缀(file_name: str) -> str:
    dot_index = file_name.rfind(".")
    if dot_index == -1:
        return ""
    return file_name[dot_index:].lower()


def 读取上传表格(uploaded_file: Any) -> pd.DataFrame:
    """读取上传的 CSV/Excel 文件为 DataFrame。"""
    if uploaded_file is None:
        raise ValueError("请先上传 CSV 或 Excel 文件")

    file_name = getattr(uploaded_file, "name", "") or ""
    suffix = _文件后缀(file_name)
    if suffix not in 支持的上传后缀:
        raise ValueError("不支持的文件格式")

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    if suffix == ".csv":
        try:
            df = pd.read_csv(uploaded_file)
        except UnicodeDecodeError:
            if hasattr(uploaded_file, "seek"):
                uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, encoding="gbk")
    else:
        df = pd.read_excel(uploaded_file)

    df = df.dropna(how="all")
    df.columns = [str(column).strip() for column in df.columns]
    if df.empty or len(df.columns) == 0:
        raise ValueError("上传文件没有读取到数据")
    return df
