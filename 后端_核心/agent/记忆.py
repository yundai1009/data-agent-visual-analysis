"""Agent 长期记忆模块（chromadb + API embedding）。

设计决策
========
- 使用 chromadb（纯 Python 嵌入式向量数据库，零运维）
- 使用 LLM API 的 /embeddings 接口生成向量（中文效果好，零额外依赖）
- 每次分析完成自动保存，下次推理前检索相似历史作为 few-shot
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

from 后端_核心.agent.llm客户端 import embed_text

logger = logging.getLogger(__name__)

# chromadb 持久化目录
_CHROMA_DIR = "data/chroma_db"
_COLLECTION_NAME = "agent_memories"

# 客户端单例
_client: Optional[chromadb.Client] = None
_collection: Optional[chromadb.Collection] = None


def _get_collection() -> chromadb.Collection:
    """获取或创建 chromadb collection（惰性初始化）。"""
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
) -> bool:
    """把一次分析结果存入向量记忆（P0 加固：记忆按 user_id 隔离）。

    Args:
        user_id: 归属用户（为空则不保存——无主记忆会被他人检索，跨用户泄漏）
        需求: 用户原始输入
        意图: 标准化意图 dict（含图表类型、x轴、y轴等）
        画像摘要: 数据画像的文本摘要
        用户反馈: 用户评分/纠错（可选）
    """
    if not user_id:
        return False
    try:
        text = f"需求：{需求}\n意图：{json.dumps(意图, ensure_ascii=False)}\n画像：{画像摘要}"
        vector = embed_text(text)
        if vector is None:
            logger.warning("embedding 失败，跳过记忆保存")
            return False

        metadata = {
            "user_id": user_id,
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


def 检索相似记忆(user_id: str, 需求: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """检索与当前需求最相似的 k 条当前用户的记忆（P0 加固：where 按 user_id 过滤）。

    Returns:
        list of {"需求": str, "图表类型": str, "x轴": str, ...}
    """
    if not user_id:
        return []
    try:
        vector = embed_text(需求)
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
