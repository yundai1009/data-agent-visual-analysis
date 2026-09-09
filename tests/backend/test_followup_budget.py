"""追问链 token 预算管理测试（阶段 27）。

覆盖三个回归点：
1. 预算生效：长结论链中较早轮次降级为一行摘要，最新轮保留结论+样例；
2. 防指数膨胀：注入上下文使用报表「标题」（用户原话）而非注入后的
   「分析需求」字段——第 N 轮上下文绝不再包含前 N-1 轮的上下文文本；
3. 短链兼容：预算内不截断，各轮结论都保留。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"


@pytest.fixture(scope="module")
def tmp_repo(tmp_path_factory):
    """临时 SQLite：repositories 直接写库（不经 HTTP）。"""
    tmp_dir = tmp_path_factory.mktemp("followup_budget")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    from repositories import report_repo
    初始化数据库()
    report_repo.初始化报表表()
    return report_repo


def _造报表(report_repo, user_id, title, 结论, prev_id=None):
    """构造一条报表记录并返回 report_id。"""
    report = {
        "标题": title,
        "分析需求": f"【上一轮分析上下文】……{title}（模拟注入后的污染文本）",
        "图表类型": "柱状图",
        "图表配置": {"X轴": "地区", "Y轴": ["销售额"], "颜色": None},
        "报表数据": [{"地区": "华东", "销售额": 100}],
        "结论": 结论,
        "上一报表ID": prev_id,
    }
    return report_repo.保存报表(
        user_id=user_id, dataset_id="ds1", title=title, chart_type="柱状图", report=report
    )


def _注入(report_repo, user_id, rid):
    """调用生产代码 _注入追问上下文，返回注入后的分析需求文本。"""
    from api.contracts import ReportGenerateRequest
    from api.routes.reports import _注入追问上下文
    payload = ReportGenerateRequest(数据集ID="ds1", 分析需求="继续追问", 上一报表ID=rid)
    injected = _注入追问上下文(payload, {"user_id": user_id})
    return injected.分析需求


def test_长链超预算_较早轮降级摘要(tmp_repo):
    """三条 500 字结论（合计远超预算）→ 前两轮降级为一行摘要，最新轮保留结论。"""
    uid = "budget-user-1"
    长结论 = "结" * 500
    rid1 = _造报表(tmp_repo, uid, "第一轮", 长结论)
    rid2 = _造报表(tmp_repo, uid, "第二轮", 长结论, prev_id=rid1)
    rid3 = _造报表(tmp_repo, uid, "第三轮", 长结论, prev_id=rid2)

    text = _注入(tmp_repo, uid, rid3)
    # 三轮都在（链头不丢）
    assert "第 1 轮" in text and "第 2 轮" in text and "第 3 轮" in text
    # 预算上限：1500 + 最新轮完整 + 头尾，总量应可控
    assert len(text) < 2600, f"注入上下文超预算: {len(text)} 字符"
    # 前两轮降级为摘要行（不再携带结论全文）
    assert "结论：" in text  # 最新轮保留
    # 第 1/2 轮不应带结论全文（降级）
    第1轮块 = text.split("第 2 轮")[0]
    assert "结" * 300 not in 第1轮块, "较早轮次应降级为摘要"


def test_防指数膨胀_标题替代注入文本(tmp_repo):
    """注入上下文不得包含嵌套的『上一轮分析上下文』（标题=原话，阻断递归）。"""
    uid = "budget-user-2"
    rid1 = _造报表(tmp_repo, uid, "第一轮", "结论一", prev_id=None)
    rid2 = _造报表(tmp_repo, uid, "第二轮", "结论二", prev_id=rid1)
    rid3 = _造报表(tmp_repo, uid, "第三轮", "结论三", prev_id=rid2)

    text = _注入(tmp_repo, uid, rid3)
    # 每轮需求原文应是用户原话（标题），而非注入后的「分析需求」
    assert "第一轮" in text and "第二轮" in text and "第三轮" in text
    # 防递归：上下文内绝不再出现上下文标记（旧实现会因取「分析需求」字段而嵌套）
    assert text.count("【上一轮分析上下文】") == 1, "注入文本中不得嵌套上一轮上下文"
    assert "模拟注入后的污染文本" not in text, "不得把注入后的分析需求当需求原文"


def test_短链预算内_不截断(tmp_repo):
    """预算内短结论：三轮结论全部保留（行为与改造前一致）。"""
    uid = "budget-user-3"
    rid1 = _造报表(tmp_repo, uid, "第一轮", "结论甲", prev_id=None)
    rid2 = _造报表(tmp_repo, uid, "第二轮", "结论乙", prev_id=rid1)
    rid3 = _造报表(tmp_repo, uid, "第三轮", "结论丙", prev_id=rid2)

    text = _注入(tmp_repo, uid, rid3)
    assert "结论甲" in text and "结论乙" in text and "结论丙" in text
