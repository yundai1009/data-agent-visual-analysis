"""Agent 长期记忆模块（chromadb + API embedding）。

设计决策
========
- 使用 chromadb（纯 Python 嵌入式向量数据库，零运维）
- 使用 LLM API 的 /embeddings 接口生成向量（中文效果好，零额外依赖）
- 每次分析完成自动保存，下次推理前检索相似历史作为 few-shot

═══════════════════════════════════════════════════════════════
【文件总览】项目层级与调用关系
═══════════════════════════════════════════════════════════════
- 所在目录：后端_核心/agent/
- 被谁调用：
  · 编排器.py → 检索相似记忆 / 保存记忆 / 生成_few_shot_prompt / 清理记忆
- 调用了谁：
  · llm客户端.py → embed_text（用 /embeddings 接口把文本转成向量）
  · chromadb      → 向量库（持久化到 data/chroma_db 目录）
  · config/settings.py → EnvConfig（embedding 三要素 LLM_EMBEDDING_*，平台级同源配置）
- 本文件负责：
  1. 保存记忆：分析完成后把「需求」向量化后存入 chromadb（全量文本另存 documents）
  2. 检索记忆：新需求到来时按 user_id 过滤 + 向量相似度取 top-k
  3. 容量治理：清理记忆（超上限删最旧）/ 删除用户记忆（注销时清空）
  4. few-shot 格式化：把历史记忆拼成 prompt 文本给 LLM 参考
  5. 阶段 61：embedding 指纹（建库时写入，换模型可检出）+ 只读一致性校验（启动硬闸）
- 面试要点：这是典型的 RAG（检索增强生成）+ 长期记忆设计；
  记忆按 user_id 隔离是 P0 加固点——跨用户检索会泄漏他人分析记录。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
# 阶段 61 修复 B4：区分「库还没建」（正常状态）与「库打不开」（真故障）必须按类型判，
#   不能靠字符串匹配消息——chromadb 换版本就会改文案。
from chromadb.errors import NotFoundError

from 后端_核心.agent.llm_client import embed_text, embedding_settings
from config.settings import EnvConfig

logger = logging.getLogger(__name__)

# chromadb 持久化目录
# 阶段 61：默认仍是 cwd 相对路径——Electron 桌面版靠 cwd=%APPDATA% 把整份数据重定向
#   到用户目录（见 docs/superpowers/specs/2026-10-06-PC端桌面应用-design.md），
#   改成绝对路径会破坏桌面版的数据隔离。新增 DAA_CHROMA_PATH 仅为测试/多实例重定向。
_CHROMA_DIR = os.getenv("DAA_CHROMA_PATH") or "data/chroma_db"
_COLLECTION_NAME = "agent_memories"

# 客户端单例（阶段 61：client 与 collection 拆成两级——只读探活不需要建库）
_client: Optional[chromadb.Client] = None
_collection: Optional[chromadb.Collection] = None
# P0 修复（Bug23）：加锁防并发初始化——多线程同时进入创建分支
#   会导致 chromadb 文件锁冲突（AlreadyExists），记忆写入丢失。
# 阶段 61 修正[预检1·P0]：必须是 **RLock**——_get_collection 持锁内再调 _get_client，
#   普通 Lock 不可重入，会永久死锁（且死锁发生在无 IO 的临界区里，栈上看不出原因）。
_记忆锁 = threading.RLock()
# 阶段 61 Task 2 的占位：容量治理摊销水位。
#   【死代码说明】Task 2 的 清理记忆 会读它来做分批摊销；在 Task 2 落地之前
#   全仓没有任何读取点（grep `_清理水位` 只有这一行赋值）。刻意保留而不是删除，
#   免得 Task 2 重新发明一个同名字段时漏掉命名/语义约定。
_清理水位 = 0
# 阶段 61（决策 D8）：最近一次失败原因——把「静默降级」变成 /healthz.memory 可见
_记忆状态: Dict[str, Any] = {"最近错误": ""}

# [预检修正4] 指纹的第四个字段：向量化文本模板。D3 决策把存储侧向量化输入从
#   「需求+意图+画像」改成「需求」，老库里存的是**旧模板**算出来的向量——
#   维度可能相同（所以不报错）但语义空间不同，属于最难自查的劣化。
#   模型/端点指纹对这次改动毫无感觉，所以模板必须单独进指纹。
#   改动这里的字符串 = 声明「老向量全部作废」，启动闸门会据此拒绝旧库。
_向量化文本模板 = "需求"

# 指纹字段 → 人话标签（错误文案用；指纹 dict 的键保持无空格的机器可读形态）
_指纹标签 = {
    "embedding模型": "embedding 模型",
    "embedding端点": "embedding 端点",
    "向量化文本模板": "向量化文本模板",
}


def 当前指纹() -> Dict[str, str]:
    """当前 embedding 配置指纹——建库时写进 collection metadata，换模型时可检出。"""
    base, model, _ = embedding_settings()
    return {
        "embedding模型": model,
        "embedding端点": base,
        "向量化文本模板": _向量化文本模板,
    }


def 校验指纹(记录指纹: Optional[dict], 当前: Dict[str, str]) -> None:
    """纯函数：已有库的 embedding 指纹与当前配置不一致 → 抛 RuntimeError。

    为什么必须硬失败（决策 D4）：向量要在**同一语义空间**里才能算相似度。换模型后——
      · 维度不同 → chroma 查询抛异常 → 被调用方 except 吞掉 → 记忆检索恒空；
      · 维度相同但换了供应商 → **不报错**，只是结果全是噪声（最难发现的一类劣化）。
    为什么端点与模板也要比（预检修正 4/5）：同模型不同供应商、不同模板（见
      _向量化文本模板）都可能落在「维度相同」的静默劣化区。
    库内没有某个指纹字段（老库）时视为**未知**，放行启动，交给重建/清理流程处理——
    老部署不该因为新增字段就被拒绝启动。
    """
    记录 = 记录指纹 or {}
    for 字段, 当前值 in 当前.items():
        记录值 = 记录.get(字段)
        if not 记录值:
            # 老库没有这个字段：无法证明不一致，放行（不拿「缺字段」当「不一致」）
            continue
        # 端点归一化尾部斜杠：运维在 .env 里多打一个 '/' 不该被当成换了语义空间
        if str(记录值).strip().rstrip("/") != str(当前值).strip().rstrip("/"):
            标签 = _指纹标签.get(字段, 字段)
            # 阶段 61 修复 B3：只给**真实可执行**的自救路径。
            # 原文案指向 `python scripts/重建记忆库.py --yes`——那个脚本属于 Task 3，
            # 现在并不存在，于是「指纹不一致」＝拒绝启动 + 无修复路径 ＝ 不可恢复停服。
            # 等重建脚本真正落地，由 Task 3 自己把这条更省事的提示加回来。
            raise RuntimeError(
                f"向量记忆库的{标签}与当前配置不一致：库内 {记录值!r}，当前 {当前值!r}。"
                "旧向量与新查询向量不在同一语义空间，检索结果不可信。"
                f"修复：停服后删除 {os.path.abspath(_CHROMA_DIR)} 目录再启动"
                "（会丢失全部长期记忆，不可逆）；或把 embedding 配置改回原值。"
            )


def _指纹一致判定(库内: Optional[dict], 当前: Dict[str, str]) -> tuple:
    """/healthz 用的指纹判定：返回 ``(显示值, 原因)``，不抛异常。

    显示值三种：``True``（逐字段一致）/ ``False``（不一致，带原因）/
    ``"未知（老库无指纹，缺字段按未知放行）"``。

    阶段 61 修复 M4：老库缺指纹字段时**不能**输出 ``True``。字段缺失时
    校验指纹 是按「未知放行」处理的，一个字段都没比过，报 True 等于告诉运维
    「闸门在工作」——这是主动误导，不是「无保护」。加字符串这一态就是为了
    把「没比过」如实显示出来。
    """
    记录 = 库内 or {}
    缺字段 = [字段 for 字段 in 当前 if not 记录.get(字段)]
    try:
        校验指纹(记录, 当前)
    except RuntimeError as exc:
        return False, str(exc)
    if 缺字段:
        return "未知（老库无指纹，缺字段按未知放行）", "库内缺少指纹字段：" + "、".join(缺字段)
    return True, ""


def _get_client() -> "chromadb.Client":
    """取（并惰性创建）PersistentClient——只建 client，不碰 collection。"""
    global _client
    if _client is not None:
        return _client
    with _记忆锁:
        if _client is None:
            _client = chromadb.PersistentClient(
                path=_CHROMA_DIR,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("向量记忆库客户端已初始化（%s）", _CHROMA_DIR)
    return _client


def _get_collection() -> "chromadb.Collection":
    """取（并惰性创建）collection——首次创建写入指纹；已有库校验指纹。

    阶段 61 修复 B1：全程用**局部变量** col，只有校验通过之后才回填全局 `_collection`。
    为什么（原缺陷）：旧写法第一步就把 `client.get_collection(...)` 的返回值赋给了
    全局 `_collection`，校验指纹在后面才执行——校验抛错时全局已经被污染成「不一致的
    collection」，此后每次调用都走函数开头的 fast-path 直接返回它：硬闸只响一次就被
    绕过，同一进程后续所有读写都落在不一致的语义空间里（且 保存记忆/检索相似记忆 的
    except 会把那次 RuntimeError 吞成 warning，调用方毫无感知）。
    改法语义不变：新建库仍 `create_collection(metadata=指纹)`；已有库仍
    `校验指纹(col.metadata, 指纹)` + `count()==0` 时 `modify(metadata=指纹)`。
    """
    global _collection
    if _collection is not None:
        return _collection
    with _记忆锁:
        if _collection is not None:
            return _collection
        client = _get_client()  # 阶段 61：锁可重入，这里与外层是同一把 RLock
        指纹 = 当前指纹()
        try:
            col = client.get_collection(_COLLECTION_NAME)
        except Exception:
            # 阶段 61 修正[预检6·P1]：不能再只捕 ValueError——chromadb 1.5.9 抛的是
            #   chromadb.errors.NotFoundError，旧写法下首次运行永远建不了库，
            #   异常还被 保存记忆 的 except 吞掉，表现就是「记忆库莫名其妙是空的」。
            # 放宽到 Exception：真的建不起来时 create_collection 自己会抛，
            #   交给调用方降级，不在这里假装成功。
            col = client.create_collection(_COLLECTION_NAME, metadata=指纹)
        else:
            校验指纹(col.metadata, 指纹)  # 抛错时 _collection 仍是 None，下次调用照样校验
            if col.count() == 0:
                # 空库：指纹直接改写，无数据可损失，不需要人工介入
                col.modify(metadata=指纹)
        # 【关键行】只有走完「校验通过」或「新建成功」才回填全局。
        # 为什么：异常路径下全局必须保持 None——否则 fast-path 会把不一致的库
        #         当成已验证结果返回，硬闸退化成「只响一次」。
        _collection = col
        return col


def 校验记忆库一致性() -> Dict[str, Any]:
    """启动期**只读**校验：不建库、**不写盘**；库目录不存在时直接返回「未创建」。

    阶段 61 修复 B2：原 docstring 自称「只读不写盘」是失实的——`chromadb.PersistentClient`
    在 rust 层就会创建数据目录（实测：空目录上调用一次就多出 data/chroma_db；
    桌面版 cwd=%APPDATA%，等于把启动探活写进用户目录）。所以这里**先判目录是否存在**：
    目录不存在就在 `_get_client()` 之前返回，一个字节都不写盘。
    只读是刻意的：探活/启动自检不应该在磁盘上留副作用。
    「指纹不一致」抛 RuntimeError（拒绝启动）；「库打不开」返回 ok=False
    （可降级故障，见 api/main.py 第 6 道防线的 except 分支）。
    `ok` 语义与 记忆状态 一致 = **「记忆库可读」**（还没建库也算可读）；
    所有返回分支的键集合一致（含 `指纹一致`），消费者不必写防御式取值。
    """
    指纹 = 当前指纹()
    结果: Dict[str, Any] = {
        "ok": True,
        "库": "未创建",
        "模型": 指纹["embedding模型"],
        "条数": 0,
        "指纹一致": "未知（库未创建，无指纹可比）",
        "原因": "",
    }
    # 【关键行】目录不存在 → 直接返回，绝不碰 _get_client()（它会创建目录）。
    # 为什么：启动自检在全新部署上每跑一次就写一次磁盘，桌面版写的是用户目录；
    #       「探活不该有副作用」是这里唯一要守住的不变量。
    if not os.path.isdir(_CHROMA_DIR):
        结果["原因"] = "记忆库尚未创建（本次启动不创建）"
        return 结果
    try:
        client = _get_client()
    except Exception as exc:
        logger.warning("向量记忆库不可用（不影响分析主流程）: %s", exc)
        结果.update(ok=False, 库="未知", 指纹一致="未知（记忆库打不开）", 原因=str(exc))
        return 结果
    try:
        col = client.get_collection(_COLLECTION_NAME)
    except NotFoundError:
        # 目录在但 collection 还没建：老数据目录残留 / 只建过 client——仍算「未创建」
        结果["原因"] = "记忆库尚未创建（本次启动不创建）"
        return 结果
    except Exception as exc:
        logger.warning("读取向量记忆库 collection 失败（不影响分析主流程）: %s", exc)
        结果.update(ok=False, 库="未知", 指纹一致="未知（记忆库打不开）", 原因=str(exc))
        return 结果
    校验指纹(col.metadata, 指纹)  # 不一致 → RuntimeError，由调用方拒绝启动
    结果["库"] = "已存在"
    结果["指纹一致"], 一致性原因 = _指纹一致判定(col.metadata, 指纹)
    if 一致性原因:
        结果["原因"] = 一致性原因
    try:
        条数 = col.count()
    except Exception:
        条数 = -1
    结果["条数"] = 条数
    return 结果


def 记忆状态() -> Dict[str, Any]:
    """/healthz.memory 用：库可读性 + 指纹 + 条数 + 最近一次失败原因（只读）。

    阶段 61 修复 B4/M4，`ok` 的含义在这里**定死**为「**记忆库可读**」，
    不是「记忆健康」——记忆是可降级依赖，坏掉时分析主流程照跑：
      · collection 还没建（全新部署最常见的状态）算**健康**。原来这里
        ok=False + 原因「记忆库不可用：Collection [agent_memories] does not exist」，
        与 校验记忆库一致性 的 ok=True/未创建 自相矛盾；按 memory.ok 配的告警会永久误报。
      · 指纹是否同源看独立的 `指纹一致` 键（ok=True 时它也可能是 False 或「未知」）。
    所有返回分支的键集合一致（未创建/失败分支同样带 `指纹一致`）。
    """
    指纹 = 当前指纹()
    状态: Dict[str, Any] = {
        "ok": True,  # 语义 = 记忆库可读（未创建也算可读）
        "库": "未知",
        "模型": 指纹["embedding模型"],
        "端点": 指纹["embedding端点"],
        "向量化文本模板": 指纹["向量化文本模板"],
        "条数": 0,
        "指纹一致": "未知（未读到库指纹）",
        "原因": "",
        "最近错误": _记忆状态["最近错误"],
    }
    # 【关键行】目录不存在 → 直接返回「未创建」，绝不碰 _get_client()（它会建目录）。
    # 为什么：与 校验记忆库一致性 同一条不变量——`PersistentClient` 会在 rust 层
    #   创建数据目录，而 /healthz 会被启动器反复轮询（启动.ps1），探活不该在磁盘
    #   上留副作用（桌面版 cwd=%APPDATA%，等于每次探活都往用户目录写）。
    #   语义上也对：目录不存在 = 还没建过库 = 未创建。
    if not os.path.isdir(_CHROMA_DIR):
        状态["库"] = "未创建"
        状态["指纹一致"] = "未知（库未创建，无指纹可比）"
        状态["原因"] = "记忆库尚未创建，记忆链路将首次写入时创建"
        return 状态
    try:
        col = _get_client().get_collection(_COLLECTION_NAME)
    except NotFoundError:
        # 阶段 61 修复 B4：还没建库是全新部署的**正常状态**，不是「记忆库不可用」
        状态["库"] = "未创建"
        状态["指纹一致"] = "未知（库未创建，无指纹可比）"
        状态["原因"] = "记忆库尚未创建，记忆链路将首次写入时创建"
        return 状态
    except Exception as exc:
        # 这里才是不该忽略的真故障：磁盘满 / 权限 / 锁文件 / 索引损坏
        状态["ok"] = False
        状态["原因"] = f"记忆库不可用：{exc}"
        return 状态
    try:
        状态["库"] = "已存在"
        状态["条数"] = col.count()
        库内 = col.metadata or {}
        状态["库内模型"] = 库内.get("embedding模型")
        状态["库内模板"] = 库内.get("向量化文本模板")
        状态["指纹一致"], 一致性原因 = _指纹一致判定(库内, 指纹)
        if 一致性原因:
            状态["原因"] = 一致性原因
    except Exception as exc:
        状态["ok"] = False
        状态["原因"] = f"读取失败：{exc}"
    return 状态


def 保存记忆(
    user_id: str,
    需求: str,
    意图: Dict[str, Any],
    画像摘要: str,
    用户反馈: Optional[str] = None,
) -> bool:
    """把一次分析结果存入向量记忆（P0 加固：记忆按 user_id 隔离）。

    Args:
        user_id: 归属用户（为空则不保存——无主记忆会被他人检索，跨用户泄漏）
        需求: 用户原始输入
        意图: 标准化意图 dict（含图表类型、x轴、y轴等）
        画像摘要: 数据画像的文本摘要
        用户反馈: 用户评分/纠错（可选）

    阶段 61 决策 D2：**不再接收 llm_config**。embedding 是平台级能力（一个向量库
    只能有一个语义空间），跟用户选的 chat provider 走必然出现混库/错配。
    """
    if not user_id:
        return False
    try:
        # 【关键行】只向量化「需求」，不把意图/画像拼进来。
        # 为什么：检索侧（下方 检索相似记忆）用的也是「需求」。若存储侧向量化的是
        #       「需求+意图+画像」而查询侧只有需求，就变成短查询 vs 长文档的非对称
        #       比较——相似度分数被额外内容稀释，top-3 排名失真，表现就是
        #       「记忆好像没起作用」。
        # 删除后果：召回质量下降但不报错，属于最难自查的一类劣化。
        # 替代方案：分别用「查询：」/「文档：」前缀做非对称检索（需实测效果再定）。
        text = f"需求：{需求}\n意图：{json.dumps(意图, ensure_ascii=False)}\n画像：{画像摘要}"
        vector = embed_text(需求)
        if vector is None:
            # 阶段 61（决策 D8）：静默降级 → 可见。原来只有一条 warning，
            # /healthz 上看不出「记忆其实一直没在写」，所以把原因挂到模块状态里。
            _记忆状态["最近错误"] = "embedding 返回空（Key / 端点 / 模型配置问题）"
            logger.warning("embedding 失败，跳过记忆保存")
            return False

        from datetime import datetime, timezone
        metadata = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),  # 批次4：供容量清理排序
            "需求": 需求[:200],
            "图表类型": str(意图.get("图表类型", "")),
            "x轴": str(意图.get("x轴", "")),
            "聚合方式": str(意图.get("聚合方式", "")),
            "画像摘要": 画像摘要[:100],
        }
        if 用户反馈:
            metadata["用户反馈"] = 用户反馈[:100]

        col = _get_collection()
        col.add(
            embeddings=[vector],
            documents=[text],
            metadatas=[metadata],
            ids=[uuid.uuid4().hex],
        )
        _记忆状态["最近错误"] = ""  # 写成功即认为链路健康（D8）
        return True
    except Exception as exc:
        _记忆状态["最近错误"] = f"保存失败：{exc}"
        logger.warning("保存记忆失败: %s", exc)
        return False


def 检索相似记忆(
    user_id: str,
    需求: str,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """检索与当前需求最相似的 k 条当前用户的记忆（P0 加固：where 按 user_id 过滤）。

    作用：ReAct 循环开始前，从向量库取出历史中"最像的 3 条分析"作为 few-shot，
    让 LLM 参考"上次类似需求怎么做的"来决策图表类型和字段。

    入参：
      - user_id：当前用户 ID（严格隔离，不返回他人的记忆）
      - 需求：用户当前输入的自然语言分析需求（用它做查询向量）
      - top_k：最多返回几条（默认 3，硬上限 10）
    返回：
      list of {"需求": str, "图表类型": str, "x轴": str, "聚合方式": str, "得分": float}
      无匹配/检索失败时返回空列表（不中断主流程）

    业务定位：记忆增强的"检索入口"——是 few-shot prompt 的数据源。
    阶段 61 决策 D2：去掉 llm_config；决策 D3：查询向量与存储向量同为「需求」。
    """
    if not user_id:
        return []
    try:
        vector = embed_text(需求)
        if vector is None:
            _记忆状态["最近错误"] = "embedding 返回空（Key / 端点 / 模型配置问题）"
            return []
        col = _get_collection()
        results = col.query(
            query_embeddings=[vector],
            n_results=min(top_k, 10),
            where={"user_id": user_id},
        )
        memories: List[Dict[str, Any]] = []
        if not results or not results.get("metadatas") or not results["metadatas"][0]:
            return memories
        for i, meta in enumerate(results["metadatas"][0]):
            if meta:
                memories.append({
                    "需求": meta.get("需求", ""),
                    "图表类型": meta.get("图表类型", ""),
                    "x轴": meta.get("x轴", ""),
                    "聚合方式": meta.get("聚合方式", ""),
                    "得分": float(results["distances"][0][i]) if results.get("distances") else 0.0,
                })
        _记忆状态["最近错误"] = ""
        return memories
    except Exception as exc:
        _记忆状态["最近错误"] = f"检索失败：{exc}"
        logger.warning("检索记忆失败: %s", exc)
        return []


def 清理记忆(keep: int = 5000) -> int:
    """批次4：记忆容量上限——超过 keep 条时删除最旧的（按 created_at 排序）。返回删除条数。"""
    try:
        col = _get_collection()
        total = col.count()
        if total <= keep:
            return 0
        data = col.get(include=["metadatas"])
        ids = data.get("ids") or []
        metas = data.get("metadatas") or []
        pairs = []
        for i, m in enumerate(metas):
            pairs.append((str(m.get("created_at", "") if m else ""), ids[i]))
        pairs.sort()  # 旧 → 新
        drop_ids = [pid for _, pid in pairs[: total - keep]]
        if drop_ids:
            col.delete(ids=drop_ids)
        return len(drop_ids)
    except Exception as exc:
        logger.warning("清理记忆失败: %s", exc)
        return 0


def 删除用户记忆(user_id: str) -> int:
    """D：注销时删除该用户的全部记忆（按 metadata user_id 过滤）。"""
    try:
        col = _get_collection()
        data = col.get(where={"user_id": user_id}, include=["metadatas"])
        ids = data.get("ids") or []
        if ids:
            col.delete(ids=ids)
        return len(ids)
    except Exception as exc:
        logger.warning("删除用户记忆失败: %s", exc)
        return 0


def 记忆条数() -> int:
    """返回当前记忆库中的记录数。"""
    try:
        col = _get_collection()
        return col.count()
    except Exception:
        return 0


def 生成_few_shot_prompt(memories: List[Dict[str, Any]]) -> str:
    """把相似历史记忆格式化为 few-shot 示例文本。"""
    if not memories:
        return ""
    lines = ["\n参考历史分析模式："]
    for i, m in enumerate(memories[:3], 1):
        lines.append(f"{i}. 历史需求「{m['需求']}」→ 图表={m['图表类型']}, X轴={m['x轴']}, 聚合={m['聚合方式']}")
    return "\n".join(lines)
