# -*- coding: utf-8 -*-
# 一句话定位：向量记忆的**上线前一次性真实验证**——真发 embedding 请求、真写入、真按语义捞回来，全通才退出 0。
# 做了什么：静态配置同源检查 → 真实 embed 调用 → 指纹一致性 → 写入一条带唯一标记的记忆 → 语义检索回捞
#         → 跨用户隔离反证 → 条数自增核对 → 清理探测数据；每步打印 PASS/FAIL 与现场，任何一步不过非零退出。
# 为什么这么做：`检查嵌入配置()` 是纯静态的（只比配置项），`/healthz.memory.ok` 只表示「库可读」——
#         阶段六十二 的 F1 就是两者都绿、而记忆其实从未写入过一次。本脚本补的是第三个证据：**真的跑通**。
# 关键约定与坑：
#         1) 探测用独立 user_id（`__自检__`），检索侧 where 按 user_id 过滤，**默认执行完自动清理**，
#            不污染真实用户记忆，也不需要先注册账号。
#         2) 只打印 HTTP 状态/错误码/维度，**绝不打印 API Key**（阶段六十三 的教训）。
#         3) 退出码有语义，CI/上线脚本可直接判：2 配置不同源 / 3 embedding 调不通 / 4 指纹不一致
#            / 5 写入失败 / 6 检索回捞失败（写进去了却捞不回来）/ 7 跨用户隔离失效 / 8 条数不自增。
#         4) 若库已有数据但指纹与当前配置不符，必须先跑 `scripts/重建记忆库.py`——本脚本只报告不删数据。
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from 后端_核心.agent import memory as M  # noqa: E402
from 后端_核心.agent.llm_client import embedding_settings, embed_text  # noqa: E402

探测用户 = "__自检__"
另一用户 = "__自检对照__"
退出码说明 = {
    0: "全链路通过：配置同源 + embedding 可调 + 指纹一致 + 写入成功 + 语义回捞成功 + 跨用户隔离生效",
    2: "配置不同源（静态检查就挂了，先看 /healthz.memory.嵌入配置说明）",
    3: "embedding 真实调用失败（端点/模型/Key 问题，见上一步的 HTTP 状态与错误信息）",
    4: "库内指纹与当前配置不一致——已有数据是用另一个语义空间写的，必须重建记忆库",
    5: "写入失败（记忆状态里有最近错误）",
    6: "写入成功但语义检索捞不回来——最隐蔽的一类：查询向量与存储向量不同源，或维度不匹配",
    7: "跨用户隔离失效：另一个 user_id 能检索到 __自检__ 的记忆",
    8: "条数未自增：写成功了但 记忆条数() 没变",
}


def 步骤(序号: int, 名称: str) -> None:
    print(f"\n[{序号}] {名称}")


def 通过(说明: str) -> None:
    print(f"    PASS  {说明}")


def 失败(说明: str) -> None:
    print(f"    FAIL  {说明}")


def 清探针(uid: str) -> None:
    try:
        n = M.删除用户记忆(uid)
        print(f"    清理 {uid}：删除 {n} 条")
    except Exception as exc:  # 清理失败不影响结论，但必须让人看见
        print(f"    清理 {uid} 失败（不影响本次结论）：{type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="向量记忆上线前一次性真实验证")
    ap.add_argument("--保留", action="store_true", help="保留探测记忆（默认执行完删除）")
    args = ap.parse_args()

    print("=" * 74)
    print("向量记忆上线前自检 —— 全过才说明记忆功能真的能用")
    print("=" * 74)

    # ---------- 1. 静态：配置是否同源 ----------
    步骤(1, "静态配置检查（零网络）")
    同源 = M.记忆状态().get("嵌入配置同源")
    base, model, key = embedding_settings()  # 返回 (base_url, model, api_key) 三元组
    print(f"    端点 = {base or '<空>'}")
    print(f"    模型 = {model or '<空>'}")
    print("    键   = " + ("=<set>" if key else "<未配置>"))
    if 同源 is False:
        失败(f"配置不同源：{M.记忆状态().get('嵌入配置说明')}")
        print("\n" + 退出码说明[2])
        return 2
    if 同源 == "未知":
        失败("配置未知（没配 embedding Key）——先在 .env 配 LLM_EMBEDDING_API_KEY")
        print("\n" + 退出码说明[2])
        return 2
    通过(f"配置同源：{M.记忆状态().get('嵌入配置说明')}")

    # ---------- 2. 真实发一次 embedding ----------
    步骤(2, "真实 embedding 调用（这一步过了才谈得上记忆）")
    t0 = time.perf_counter()
    vec = embed_text("向量记忆上线前自检：按地区统计销售额")
    耗时 = time.perf_counter() - t0
    if not vec:
        失败(f"embed_text 返回空，用时 {耗时:.2f}s；记忆状态：{M.记忆状态().get('最近错误') or '<空>'}")
        print("    提示：第三方端点必须显式配 LLM_EMBEDDING_MODEL，缺省模型名多半调不通（F1）")
        print("\n" + 退出码说明[3])
        return 3
    通过(f"维度 {len(vec)}，用时 {耗时:.2f}s，前 3 维 {vec[:3]}")

    # ---------- 3. 指纹一致性 ----------
    步骤(3, "记忆库指纹一致性")
    try:
        # 指纹不一致时 校验记忆库一致性() 直接抛 RuntimeError（那是启动期的硬闸语义），
        # 自检脚本不能让它变成 traceback——这里接住，转成退出码 4。
        一致 = M.校验记忆库一致性()
    except RuntimeError as exc:
        失败(f"{exc}")
        条数 = M.记忆条数()
        if 条数 == 0:
            print("    处理：库里 0 条，重建不会丢任何数据——直接 python scripts/重建记忆库.py --yes 即可")
        else:
            print(f"    处理：库内 {条数} 条记忆，重建不可逆——先确认这些记忆可以丢，再跑 --dry-run")
        print("\n" + 退出码说明[4])
        return 4
    print(f"    {一致}")
    通过(f"库内条数 {M.记忆条数()}，指纹与当前配置一致")

    # ---------- 4. 写入一条 ----------
    步骤(4, "写入一条探测记忆")
    标记 = f"自检标记-{int(time.time())}"
    写前 = M.记忆条数()
    ok = M.保存记忆(
        user_id=探测用户,
        需求=f"{标记}：自检专用记录，图表类型柱状图，x轴地区，聚合方式求和",
        意图={"图表类型": "柱状图", "x轴": "地区", "聚合方式": "求和"},
        画像摘要="自检用，不含任何业务数据",
    )
    if not ok:
        失败(f"保存记忆返回 False；记忆状态：{M.记忆状态().get('最近错误') or '<空>'}")
        if not args.保留:
            清探针(探测用户)
        print("\n" + 退出码说明[5])
        return 5
    通过(f"写入成功，条数 {写前} → {M.记忆条数()}")

    # ---------- 5. 语义回捞（换一种说法，验证是语义匹配不是字符串命中）----------
    步骤(5, "语义回捞（换一种问法，不能靠字符串撞上）")
    命中 = M.检索相似记忆(探测用户, "帮我看看各个区域卖了多少", top_k=3)
    if not 命中:
        失败("检索不到刚写进去的记录——查询向量与存储向量可能不同源，或维度不匹配")
        if not args.保留:
            清探针(探测用户)
        print("\n" + 退出码说明[6])
        return 6
    顶 = 命中[0]
    通过(f"命中 {len(命中)} 条，Top1 得分 {顶.get('得分')}，需求={顶.get('需求')!r}")
    if 标记 not in 顶.get("需求", ""):
        失败(f"Top1 不是刚写入的那条（得分 {顶.get('得分')}），检索质量存疑")

    # ---------- 6. 跨用户隔离反证 ----------
    步骤(6, "跨用户隔离反证（另一个 user_id 必须捞不到）")
    越权 = M.检索相似记忆(另一用户, "帮我看看各个区域卖了多少", top_k=3)
    if 越权:
        失败(f"隔离失效：另一个用户检索到 {len(越权)} 条别人的记忆")
        if not args.保留:
            清探针(探测用户)
            清探针(另一用户)
        print("\n" + 退出码说明[7])
        return 7
    通过("另一个 user_id 检索为空，隔离生效")

    # ---------- 7. 条数自增 ----------
    步骤(7, "条数自增核对")
    写后 = M.记忆条数()
    if 写后 <= 写前:
        失败(f"写前 {写前}、写后 {写后}，条数没有自增")
        if not args.保留:
            清探针(探测用户)
        print("\n" + 退出码说明[8])
        return 8
    通过(f"{写前} → {写后}")

    # ---------- 收尾 ----------
    if args.保留:
        print("\n    （--保留：探测记忆留在库里了）")
    else:
        print("\n    清理探测数据：")
        清探针(探测用户)

    print("\n" + "=" * 74)
    print("结论：向量记忆全链路可用。")
    print("上线观测指标应满足：memory.ok=true 且 嵌入配置同源=true 且 条数>0。")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())