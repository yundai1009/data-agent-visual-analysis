#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重建向量记忆库（阶段 61）。

什么时候必须跑：改了 ``LLM_EMBEDDING_MODEL`` / ``LLM_EMBEDDING_BASE_URL`` 之后。
旧向量与新查询向量不在同一语义空间，记忆检索结果不可信；启动自检会直接拒绝启动，
直到本脚本跑完——这正是为了消灭「悄悄变差」这种最难查的故障。

为什么必须显式二选一（--dry-run / --yes）
==========================================
本脚本删的是**用户的长期记忆**，且不可恢复。默认动作必须是「什么都不做」：
一个只敲了脚本名就回车的人，不该因此丢掉整库历史。所以两个开关都不给时直接报错退出，
而不是「替你选一个默认值」——默认 --dry-run 会让以为已经重建的人白等，
默认 --yes 更危险。

为什么 Key 为空时直接返回 2（不删库）
=====================================
删库之后仍然存不进新记忆，是比「指纹不一致」更糟的状态：库没了、闸门也不响了
（空库会被自动回填指纹），但记忆链路依然 100% 不工作，而且看起来一切正常。
所以宁可**什么都不删**，把原因打出来让人先配 Key。

用法：
    python scripts/重建记忆库.py --dry-run   # 只看将删除多少条
    python scripts/重建记忆库.py --yes        # 确认删除并按当前配置重建
"""
from __future__ import annotations

import argparse
import os
import sys

# 脚本是直接 `python scripts/重建记忆库.py` 跑的，不在包里：必须先把仓库根塞进
# sys.path，否则 `from 后端_核心.agent import memory` 直接 ImportError。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 后端_核心.agent import memory  # noqa: E402
from 后端_核心.agent.llm_client import embedding_settings, is_llm_configured  # noqa: E402


def main() -> int:
    解析 = argparse.ArgumentParser(description="重建向量记忆库")
    解析.add_argument("--dry-run", action="store_true", help="只打印，不删除")
    解析.add_argument("--yes", action="store_true", help="确认删除（历史记忆不可恢复）")
    参数 = 解析.parse_args()
    if not 参数.dry_run and not 参数.yes:
        解析.error("必须显式指定 --dry-run 或 --yes")

    base, model, key = embedding_settings()
    # 只判空不够："your_llm_api_key" 这种非空占位符照样调不通 embedding，
    # 保存记忆会全线存不进。直接复用 llm_client 的占位符判定（与编排器降级开关同源）。
    有真实Key = is_llm_configured(key)
    print(f"记忆目录：{memory._CHROMA_DIR}")
    print(f"当前 embedding：模型={model} 端点={base} Key={'已配置' if 有真实Key else '未配置/占位符'}")
    if not 有真实Key:
        print("[X] embedding Key 未配置或仍是占位符，重建后依然存不进去。")
        print("    先配 LLM_API_KEY 或 LLM_EMBEDDING_API_KEY 再重跑。")
        return 2

    client = memory._get_client()
    try:
        col = client.get_collection(memory._COLLECTION_NAME)
        条数 = col.count()
        旧模型 = (col.metadata or {}).get("embedding模型")
    except Exception:
        # 库还没建 / 目录被清过 / collection 名字对不上——都等价于「没有可删的东西」，
        # 属于正常状态，不该让上面那句「Key 没配」之外的第二个红色错误吓到人。
        条数, 旧模型 = 0, None
    print(f"现有记忆：{条数} 条（库内 embedding 模型 {旧模型!r}）")
    if 条数 == 0:
        print("[OK] 记忆库为空，无需重建。")
        return 0
    if 参数.dry_run:
        print("[dry-run] 确认无误后加 --yes 执行删除并重建。")
        return 0

    client.delete_collection(memory._COLLECTION_NAME)
    memory._collection = None  # 清掉进程内单例（脚本一般用不到，保险）
    memory._get_collection()  # 按当前配置重建，metadata 写入新指纹
    print(f"[OK] 已重建：{条数} 条历史记忆已删除，新记忆将用 {model!r} 重新积累。")
    print("    记忆是可再生的 few-shot 参考积累，几小时内即可恢复到可用水平。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
