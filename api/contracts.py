from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionMode(str, Enum):
    AUTO = "auto"
    FAST = "fast"
    DEEP = "deep"


class CreateTaskRequest(BaseModel):
    问题: str = Field(..., min_length=1, max_length=2000)
    执行模式: ExecutionMode = Field(default=ExecutionMode.AUTO)
    最大重试次数: int = Field(default=2, ge=0, le=5)
    启用缓存: bool = Field(default=True)
    异步执行: bool = Field(default=True)


class DatasetUploadResponse(BaseModel):
    数据集ID: str
    文件名: str
    行数: int
    列数: int
    字段列表: list[str]
    数据画像: Dict[str, Any]


class DatasetPreviewResponse(BaseModel):
    数据集ID: str
    文件名: str
    预览数据: list[dict[str, Any]]
    数据画像: Dict[str, Any]


class ReportGenerateRequest(BaseModel):
    数据集ID: str
    分析需求: str = ""
    图表类型: str = "自动推荐"
    x轴: Optional[str] = None
    y轴: list[str] = Field(default_factory=list)
    分组字段: Optional[str] = None
    聚合方式: str = "求和"
    agent_mode: str = "single"  # "single" | "multi"
    model: Optional[str] = None  # 临时覆盖 LLM 模型名，None=使用 .env 默认
    上一报表ID: Optional[str] = None  # 追问上下文：延续上一份报表继续分析
    原始分析需求: Optional[str] = None  # 内部：追问注入上下文前的原话（用于报表标题）


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


class DashboardRequest(BaseModel):
    """新建 / 更新看板：名称 + 归属用户的报表ID列表。"""

    名称: str = Field(..., min_length=1, max_length=50)
    报表ID列表: list[str] = Field(default_factory=list, max_length=50)


class TaskResponse(BaseModel):
    任务ID: str
    状态: TaskStatus
    当前步骤: int = 0
    结果: Optional[Dict[str, Any]] = None
    创建时间: datetime
    更新时间: datetime
    问题: Optional[str] = None


class FeedbackRequest(BaseModel):
    任务ID: str
    评分: int = Field(..., ge=1, le=5)
    纠错内容: Optional[str] = Field(default=None, max_length=4000)
    同步知识库: bool = Field(default=False)


class GoldenSetItem(BaseModel):
    id: Optional[str] = None
    问题: str
    预期SQL: str
    标签: List[str] = Field(default_factory=list)
    难度: str = Field(default="medium")
    创建时间: Optional[datetime] = None


class CleanDatasetResponse(BaseModel):
    数据集ID: str
    原行数: int
    清洗后行数: int
    清洗前列数: int = 0
    清洗后列数: int = 0
    操作摘要: Dict[str, Any] = Field(default_factory=dict)
    数据画像: Dict[str, Any]


class LoadExampleResponse(BaseModel):
    数据集ID: str
    文件名: str
    行数: int
    列数: int
    字段列表: list[str]
    数据画像: Dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
