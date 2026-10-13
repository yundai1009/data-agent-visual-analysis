# -*- coding: utf-8 -*-
"""示例数据集接口路径解析（阶段 59：修「导入示例数据」404）。

背景：`data/examples/sales_2024.csv` 在阶段 39「代码清理」被误删，网页版与桌面版的
「导入示例数据」都 404；且旧实现是「模块导入时就 mkdir + 纯 cwd 相对路径」，桌面版
打包后 cwd = %APPDATA%\\数据分析Agent，只会凭空造出一个空目录继续 404。

覆盖：
1. 可写目录已有示例 → 直接用，不再拷贝
2. 只有只读副本（源码 / 安装包解包目录）→ 复制到可写目录，溯源路径指向可写副本
3. 两者都没有 → 仍 404（对外语义不变）
4. 数据目录不可写 → 降级用只读副本（功能可用，不因复制失败而 404）
5. 仓库守卫：内置示例文件必须在库（防再次被「代码清理」删掉）
6. 端到端：load-example 真正落库，且 datasets.stored_path 是长期有效的可写副本
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.routes import examples as ex

示例表头 = "月份,地区,销售额,订单数,工作经验要求,岗位类型"
样例内容 = "月份,地区,销售额\n2024-01,北京,12450\n"


def _放示例(目录: Path, 内容: str = 样例内容) -> Path:
    """在指定目录下放一个示例文件，返回该目录。"""
    目录.mkdir(parents=True, exist_ok=True)
    (目录 / ex._示例文件名).write_text(内容, encoding="utf-8")
    return 目录


# ═══ 1. 可写目录优先 ═══


def test_可写目录已有示例_直接用不拷贝(tmp_path, monkeypatch):
    可写目录 = _放示例(tmp_path / "数据目录" / "data" / "examples")
    只读目录 = _放示例(tmp_path / "包内" / "data" / "examples", "月份\n1999-01\n")
    monkeypatch.setattr(ex, "_可写示例目录", lambda: 可写目录)
    monkeypatch.setattr(ex, "_只读示例候选", lambda: [只读目录 / ex._示例文件名])

    结果 = ex.解析示例文件()

    assert 结果 == 可写目录 / ex._示例文件名
    # 未被只读副本覆盖（用户自带的/上次复制的示例优先）
    assert 结果.read_text(encoding="utf-8") == 样例内容


# ═══ 2. 只读副本 → 复制到可写目录 ═══


def test_只有只读副本_复制到可写目录并返回可写副本(tmp_path, monkeypatch):
    可写目录 = tmp_path / "数据目录" / "data" / "examples"  # 首次运行并不存在
    只读目录 = _放示例(tmp_path / "包内" / "data" / "examples")
    monkeypatch.setattr(ex, "_可写示例目录", lambda: 可写目录)
    monkeypatch.setattr(ex, "_只读示例候选", lambda: [只读目录 / ex._示例文件名])

    结果 = ex.解析示例文件()

    assert 结果 == 可写目录 / ex._示例文件名
    assert 结果.parent.is_dir(), "写时可惰性建目录（不再在模块导入时 mkdir）"
    assert 结果.exists(), "必须复制到可写目录：解包目录退出即删，溯源路径会失效"
    assert 结果.read_text(encoding="utf-8") == 样例内容
    assert (只读目录 / ex._示例文件名).exists(), "只读副本应保留（下次安装仍要用）"


# ═══ 3. 缺失仍 404 ═══


def test_两者都没有_返回None且路由404(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "_可写示例目录", lambda: tmp_path / "空" / "examples")
    monkeypatch.setattr(ex, "_只读示例候选", lambda: [tmp_path / "缺" / ex._示例文件名])

    assert ex.解析示例文件() is None

    with pytest.raises(HTTPException) as 异常:
        ex.load_example_dataset(user={"user_id": "u-1"})
    assert 异常.value.status_code == 404
    assert "示例数据文件不存在" in 异常.value.detail
    assert not (tmp_path / "空" / "examples").exists(), "找不到时不应留下空目录"


# ═══ 4. 数据目录不可写 → 降级只读副本 ═══


def test_数据目录不可写_降级用只读副本(tmp_path, monkeypatch):
    可写目录 = tmp_path / "只读挂载" / "examples"
    只读目录 = _放示例(tmp_path / "包内" / "examples")
    monkeypatch.setattr(ex, "_可写示例目录", lambda: 可写目录)
    monkeypatch.setattr(ex, "_只读示例候选", lambda: [只读目录 / ex._示例文件名])

    def _拒绝拷贝(*_args, **_kwargs):
        raise OSError("只读文件系统")

    monkeypatch.setattr(ex.shutil, "copyfile", _拒绝拷贝)

    结果 = ex.解析示例文件()

    assert 结果 == 只读目录 / ex._示例文件名, "复制失败应降级，不能把功能变成 404"


# ═══ 5. 仓库守卫：示例文件必须在库 ═══


def test_仓库内置示例文件必须在库():
    """阶段 39「代码清理」把它当临时数据删过一次 → 加守卫防复发。

    它同时是「导入示例数据」按钮与安装包 datas（daa-backend.spec）的依赖，
    缺了网页版和桌面版都会 404。
    """
    候选 = [p for p in ex._只读示例候选() if p.exists()]

    assert 候选, f"内置示例文件缺失：{ex._只读示例候选()}"

    行 = [r for r in 候选[0].read_text(encoding="utf-8").splitlines() if r.strip()]
    assert 行[0] == 示例表头
    assert len(行) == 31, f"示例数据应为 1 行表头 + 30 行数据，实际 {len(行)} 行"


# ═══ 6. 端到端：真正落库，且溯源路径长期有效 ═══


def test_导入示例数据_端到端落库且溯源指向可写副本(tmp_path, monkeypatch):
    from config import settings
    from 后端_核心.存储 import sqlite_repo as sr

    库 = tmp_path / "ex.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(库))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(库), raising=False)
    monkeypatch.setattr(sr, "_PARQUET_DIR", tmp_path / "parquet")
    sr.初始化数据库()

    可写目录 = tmp_path / "数据目录" / "data" / "examples"
    monkeypatch.setattr(ex, "_可写示例目录", lambda: 可写目录)

    结果 = ex.load_example_dataset(user={"user_id": "u-1"})

    assert 结果.文件名 == "sales_2024.csv"
    assert 结果.行数 == 30
    assert 结果.列数 == 6
    assert (可写目录 / ex._示例文件名).exists(), "首次调用应把内置副本落到数据目录"

    conn = sqlite3.connect(str(库))
    try:
        行 = conn.execute(
            "SELECT stored_path, file_name FROM datasets WHERE dataset_id=?",
            (结果.数据集ID,),
        ).fetchone()
    finally:
        conn.close()

    assert 行 is not None, "示例数据集应写入 datasets 表"
    assert Path(行[0]) == 可写目录 / ex._示例文件名, (
        f"溯源路径必须指向可写副本，实际 {行[0]}"
    )
