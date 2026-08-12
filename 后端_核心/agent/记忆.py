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
  · config/settings.py → LLMRequestConfig（请求级配置透传，保证 embedding 与调用同供应商）
- 本文件负责：
  1. 保存记忆：分析完成后把（需求+意图+画像摘要）向量化后存入 chromadb
  2. 检索记忆：新需求到来时按 user_id 过滤 + 向量相似度取 top-k
  3. 容量治理：清理记忆（超上限删最旧）/ 删除用户记忆（注销时清空）
  4. few-shot 格式化：把历史记忆拼成 prompt 文本给 LLM 参考
- 面试要点：这是典型的 RAG（检索增强生成）+ 长期记忆设计；
  记忆按 user_id 隔离是 P0 加固点——跨用户检索会泄漏他人分析记录。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

from 后端_核心.agent.llm客户端 import embed_text
from config.settings import LLMRequestConfig

logger = logging.getLogger(__name__)

# chromadb 持久化目录
_CHROMA_DIR = "data/chroma_db"
_COLLECTION_NAME = "agent_memories"

# 客户端单例
_client: Optional[chromadb.Client] = None
_collection: Optional[chromadb.Collection] = None


def _get_collection() -> chromadb.Collection:
    """获取或创建 chromadb collection（惰性初始化）。

    作用：首次调用时创建持久化客户端并建立 collection，之后直接复用单例。

    入参：无
    返回：chromadb.Collection 对象（agent_memories 集合）
    业务定位：记忆模块的"数据库连接"——所有读写都经由这个集合对象。
    """
    global _client, _collection
    if _collection is not None:
        return _collection
    _client = chromadb.PersistentClient(
        path=_CHROMA_DIR,
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        _collection = _client.get_collection(_COLLECTION_NAME)
    except ValueError:
        _collection = _client.create_collection(_COLLECTION_NAME)
    logger.info("记忆模块已初始化（%s）", _CHROMA_DIR)
    return _collection


def 保存记忆(
    user_id: str,
    需求: str,
    意图: Dict[str, Any],
    画像摘要: str,
    用户反馈: Optional[str] = None,
    llm_config: Optional[LLMRequestConfig] = None,
) -> bool:
    """把一次分析结果存入向量记忆（P0 加固：记忆按 user_id 隔离）。

    Args:
        user_id: 归属用户（为空则不保存——无主记忆会被他人检索，跨用户泄漏）
        需求: 用户原始输入
        意图: 标准化意图 dict（含图表类型、x轴、y轴等）
        画像摘要: 数据画像的文本摘要
        用户反馈: 用户评分/纠错（可选）
        llm_config: 请求级 LLM 配置（embedding 与调用同供应商，避免跨请求串配置）
    """
    if not user_id:
        return False
    try:
        # 【关键行】把记忆文本（需求+意图+画像摘要）通过 /embeddings 转成向量。
        # 为什么：向量库靠"语义相似度"检索，必须先有向量才能存进去；
        # 中文场景用 LLM 官方 embedding 接口效果远好于本地词袋/BOW 方案。
        # 删除后果：记忆无法落库，few-shot 增强功能整体失效（但分析主流程不受影响）。
        # 替代方案：本地 sentence-transformers 模型（零 API 成本但多 ~100MB 依赖）；
        # 用现有 LLM 的 /embeddings 接口零额外依赖，是性价比最高的选择。
        text = f"需求：{需求}\n意图：{json.dumps(意图, ensure_ascii=False)}\n画像：{画像摘要}"
        vector = embed_text(text, llm_config=llm_config)
        if vector is None:
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
        return True
    except Exception as exc:
        logger.warning("保存记忆失败: %s", exc)
        return False


def 检索相似记忆(
    user_id: str,
    需求: str,
    top_k: int = 3,
    llm_config: Optional[LLMRequestConfig] = None,
) -> List[Dict[str, Any]]:
    """检索与当前需求最相似的 k 条当前用户的记忆（P0 加固：where 按 user_id 过滤）。

    作用：ReAct 循环开始前，从向量库取出历史中"最像的 3 条分析"作为 few-shot，
    让 LLM 参考"上次类似需求怎么做的"来决策图表类型和字段。

    入参：
      - user_id：当前用户 ID（严格隔离，不返回他人的记忆）
      - 需求：用户当前输入的自然语言分析需求（用它做查询向量）
      - top_k：最多返回几条（默认 3，硬上限 10）
      - llm_config：请求级 LLM 配置（embedding 与调用同供应商，避免跨配置串）
    返回：
      list of {"需求": str, "图表类型": str, "x轴": str, "聚合方式": str, "得分": float}
      无匹配/检索失败时返回空列表（不中断主流程）

    业务定位：记忆增强的"检索入口"——是 few-shot prompt 的数据源。
    """
    if not user_id:
        return []
    try:
        vector = embed_text(需求, llm_config=llm_config)
        if vector is None:
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
        return memories
    except Exception as exc:
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
