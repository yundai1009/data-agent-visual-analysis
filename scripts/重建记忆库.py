#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重建向量记忆库（阶段 61）。

什么时候必须跑：改了 ``LLM_EMBEDDING_MODEL`` / ``LLM_EMBEDDING_BASE_URL`` 之后。
旧向量与新查询向量不在同一语义空间，记忆检索结果不可信；启动自检会直接拒绝启动，
直到本脚本跑完——这正是为了消灭「悄悄变差」这种最难查的故障。

判据是**指纹**不是条数
==================
阶段 65 自检时撞上的死局：库是在旧配置（比如阶段 63 的 F1 缺省模型名）下建空的，
0 条但指纹是旧的。此时启动硬闸按指纹拒启动，运维照报错跑本脚本——如果脚本按
``条数 == 0`` 回一句「无需重建」，闸门照旧、服务照旧起不来，闸门与工具互相指着对方。
所以指纹已是当前配置才返回「无需重建」；0 条 + 指纹旧属于「无数据可丢」，同样走重建，
只是如实说成 0 条。

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
    库内元数据 = None
    库存在 = False
    try:
        col = client.get_collection(memory._COLLECTION_NAME)
        条数 = col.count()
        旧模型 = (col.metadata or {}).get("embedding模型")
        库内元数据 = col.metadata
        库存在 = True
    except Exception:
        # 库还没建 / 目录被清过 / collection 名字对不上——都等价于「没有可删的东西」，
        # 属于正常状态，不该让上面那句「Key 没配」之外的第二个红色错误吓到人。
        条数, 旧模型 = 0, None
    print(f"现有记忆：{条数} 条（库内 embedding 模型 {旧模型!r}）")

    # 【关键行】指纹已经是当前配置 → 什么都不用做。原来这里只判 `条数 == 0` 就返回
    # 「无需重建」，于是留下一个死局：库是在旧配置（比如 F1 的缺省模型名）下建空的，
    # 0 条但指纹是旧的；启动硬闸按指纹拒启动，运维照着报错跑本脚本，脚本说「无需重建」，
    # 服务依旧起不来——闸门与工具互相指着对方。判据必须是**指纹**，不是条数。
    指纹一致, 一致性原因 = memory._指纹一致判定(库内元数据, memory.当前指纹())
    print(f"指纹一致：{指纹一致}")
    if 指纹一致 is True:
        print("[OK] 指纹与当前配置一致，无需重建。")
        return 0
    if 一致性原因:
        print(f"    原因：{一致性原因}")

    if 条数 == 0:
        # 没有用户数据可丢：这是「空壳库」，重新盖章即可。
        # 保留 --dry-run / --yes 双开关不放水——只是把「将丢多少条」如实说成 0。
        # 两种「0 条」要分开说：指纹**不一致**是「上一份配置留下的」，指纹**未知**是
        # 「压根没盖过章」（全新库、或阶段 61 之前的老库）。后者同样要重建——否则这个
        # collection 会永远没有指纹，校验指纹 对它永远「未知放行」，下次换模型照样检不出来。
        if isinstance(指纹一致, bool):
            print("[!] 库内 0 条，但指纹与当前配置不一致：没有用户数据可丢，只需按当前配置重新盖章。")
        else:
            # 说明白「重建」在这里到底做了什么：memory._get_collection 对 0 条空库本来就会
            # 自动 modify(metadata=指纹)，所以重建并不是「不盖章就没法写入」——它只是让状态
            # 在写入第一条记忆**之前**就归正，运维跑一次脚本就能确认当前配置已经落到库上。
            print("[!] 库内 0 条，且库内一个指纹字段都没有（全新库，或阶段 61 之前的老库）："
                  "没有数据可丢，重建只是把当前指纹盖上去，让状态在第一条记忆写入前就归正。")
    if 参数.dry_run:
        print(f"[dry-run] 将按当前配置重建：删除 {条数} 条历史记忆后新建 collection，metadata 写入新指纹。")
        print("          确认无误后加 --yes 执行。")
        return 0

    # 阶段 65 F6：collection 压根不存在时不能无条件 delete_collection——chromadb 会抛
    # NotFoundError 直接把脚本打崩（全新装机跑一次就撞上）。要删的前提是有东西可删。
    if 库存在:
        client.delete_collection(memory._COLLECTION_NAME)
        memory._collection = None  # 清掉进程内单例（脚本一般用不到，保险）
    memory._get_collection()  # 按当前配置重建，metadata 写入新指纹
    if 条数 == 0:
        print(f"[OK] 已重新盖章：0 条数据未受影响，新指纹={model!r}。")
    else:
        print(f"[OK] 已重建：{条数} 条历史记忆已删除，新记忆将用 {model!r} 重新积累。")
        print("    记忆是可再生的 few-shot 参考积累，几小时内即可恢复到可用水平。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
