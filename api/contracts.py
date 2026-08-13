# ============================================================
# 文件头 · API 数据契约（面试讲解）
# ------------------------------------------------------------
# 这个文件管什么：全项目"前后端之间的数据契约"——每个接口的
#   请求体 / 响应体长什么样，都在这用 Pydantic 模型定义死。
# 为什么需要它：后端把模型类挂在 FastAPI 路由上后，框架会自动
#   ① 校验请求（字段缺失/类型错/超长直接 422）② 生成 OpenAPI 文档
#   ③ 序列化响应。前端和联调工具看到的字段结构完全以此为准。
# 设计要点：
#   - 字段用中文命名，与业务概念（数据集ID/报表ID）一一对应；
#   - 可复用结构（数据集×数据画像）抽成独立模型，避免重复定义；
#   - P0 加固：所有用户可控字段带 max_length / ge / le 上限，
#     防止超大请求体拖垮服务（详见 ReportGenerateRequest 注释）。
# 删除它会怎样：所有接口失去类型校验与文档，前后端会因字段对不上
#   而连环报错。
# ============================================================
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


# 任务状态枚举：异步分析任务的"生命周期"。PENDING→RUNNING→
# COMPLETED/FAILED/CANCELLED，前端轮询任务接口靠它判断进度。
class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 执行模式枚举：AUTO 由 Agent 自行决定深度；FAST 走轻量路径；
# DEEP 强制多智能体/深度推理。注意：本文件是历史契约，实际
# 生成报表流程已改由 agent_mode（single/multi）控制。
class ExecutionMode(str, Enum):
    AUTO = "auto"
    FAST = "fast"
    DEEP = "deep"


# 创建分析任务请求体：任务中心的入参。字段带边界约束
# （问题 1~2000 字、重试 0~5 次），防止脏数据进入任务队列。
class CreateTaskRequest(BaseModel):
    问题: str = Field(..., min_length=1, max_length=2000)
    执行模式: ExecutionMode = Field(default=ExecutionMode.AUTO)
    最大重试次数: int = Field(default=2, ge=0, le=5)
    启用缓存: bool = Field(default=True)
    异步执行: bool = Field(default=True)


# 上传数据集响应：上传成功后一次性返回文件元信息 + 数据画像，
# 前端拿它直接展示"这个数据集长什么样"，不必再发一次预览请求。
class DatasetUploadResponse(BaseModel):
    数据集ID: str
    文件名: str
    行数: int
    列数: int
    字段列表: list[str]
    数据画像: Dict[str, Any]


# 预览响应：返回前 N 行原始数据（list），配合画像供
# 数据管理页表格 + 字段推荐展示。
class DatasetPreviewResponse(BaseModel):
    数据集ID: str
    文件名: str
    预览数据: list[dict[str, Any]]
    数据画像: Dict[str, Any]


class ReportGenerateRequest(BaseModel):
    """生成报表请求（P0 加固：全部字段设长度上限，防超大请求体 DoS）。"""

    数据集ID: str = Field(..., max_length=64)
    分析需求: str = Field("", max_length=2000)
    图表类型: str = Field("自动推荐", max_length=32)
    x轴: Optional[str] = Field(None, max_length=64)
    y轴: list[str] = Field(default_factory=list, max_length=8)
    分组字段: Optional[str] = Field(None, max_length=64)
    聚合方式: str = Field("求和", max_length=16)
    agent_mode: str = Field("single", max_length=16)  # "single" | "multi"
    model: Optional[str] = Field(None, max_length=64)  # 临时覆盖 LLM 模型名，None=使用 .env 默认
    上一报表ID: Optional[str] = Field(None, max_length=64)  # 追问上下文：延续上一份报表继续分析
    原始分析需求: Optional[str] = Field(None, max_length=2000)  # 内部：追问注入上下文前的原话（用于报表标题）


# 生成报表响应：全项目最核心的契约——一次分析产出的全部内容：
# 图表配置/数据、数据画像、结论、风险提示与 Agent 决策轨迹。
# 注意 ChartConfig 用 echarts 原生结构（前端直接渲染，后端零转换）；
# Agent_Trace 带 alias 兼容外部字段名 "Agent Trace"。
class ReportGenerateResponse(BaseModel):
    报表ID: str
    数据集ID: str
    标题: str
    图表类型: str
    图表配置: Dict[str, Any]
    报表数据: list[dict[str, Any]]
    数据画像: Dict[str, Any]
    推荐说明: Dict[str, Any]
    风险提示: list[str]
    Agent_Trace: list[dict[str, Any]] = Field(alias="Agent Trace")
    导出数据: Dict[str, Any]
    结论: str
    # 阶段 1 已在 生成报表数据 返回中存在；阶段 2 透传到 API 响应，便于前端展示 LLM/规则 兜底来源
    意图来源: str = "无"
    # LLM 失败原因：降级到规则时透传，前端明示"为什么是规则匹配"
    LLM失败原因: str = ""
    agent_mode: str = "single"

    model_config = ConfigDict(populate_by_name=True)


# 看板请求体（新建/更新）：名称 + 归属用户的报表ID列表。
class DashboardRequest(BaseModel):
    """新建 / 更新看板：名称 + 归属用户的报表ID列表。"""

    名称: str = Field(..., min_length=1, max_length=50)
    报表ID列表: list[str] = Field(default_factory=list, max_length=50)


# 任务响应：任务中心列表/查询用的结构；结果可为空（任务未完成时）。
class TaskResponse(BaseModel):
    任务ID: str
    状态: TaskStatus
    当前步骤: int = 0
    结果: Optional[Dict[str, Any]] = None
    创建时间: datetime
    更新时间: datetime
    问题: Optional[str] = None


# 意见反馈请求体：评分 1~5 + 可选纠错文本，纠正过的内容
# 可一键同步进知识库（金标集），实现"用反馈喂模型"。
class FeedbackRequest(BaseModel):
    任务ID: str
    评分: int = Field(..., ge=1, le=5)
    纠错内容: Optional[str] = Field(default=None, max_length=4000)
    同步知识库: bool = Field(default=False)


# 金标集条目：由人工/反馈沉淀的"标准问答"，用于评测与
# 少样本提示词注入，是 Agent 效果持续提升的素材库。
class GoldenSetItem(BaseModel):
    id: Optional[str] = None
    问题: str
    预期SQL: str
    标签: List[str] = Field(default_factory=list)
    难度: str = Field(default="medium")
    创建时间: Optional[datetime] = None


# 清洗数据集响应：记录清洗前后的行列数变化 + 操作摘要
# （去重多少行、填充多少缺失等），前端据此提示用户清洗效果。
class CleanDatasetResponse(BaseModel):
    数据集ID: str
    原行数: int
    清洗后行数: int
    清洗前列数: int = 0
    清洗后列数: int = 0
    操作摘要: Dict[str, Any] = Field(default_factory=dict)
    数据画像: Dict[str, Any]


# 加载示例数据集响应：与上传响应同构，方便前端复用同一套渲染逻辑。
class LoadExampleResponse(BaseModel):
    数据集ID: str
    文件名: str
    行数: int
    列数: int
    字段列表: list[str]
    数据画像: Dict[str, Any]


# 健康检查响应：status/version/timestamp，供部署探活
# （K8s/负载均衡的 liveness probe）判断服务是否存活。
class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
