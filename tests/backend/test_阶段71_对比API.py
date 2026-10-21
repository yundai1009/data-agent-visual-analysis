"""阶段 71 · 多数据集对比 API 测试：preview / compare / 落库 / 重放 / 精细化拒绝。

覆盖目标
========
- ``POST /reports/compare/preview``：共同字段、主体轴候选、来源轴候选、推荐口径
- ``POST /reports/compare``：跨 3 个月文件生成对比报表、图表配置按来源分系列、落库
- 参数边界：1 个 / 11 个 / 空列表 / 重复 ID / 别人的数据集 / 无共同指标
- 对比报表专属行为：refine 拒绝（400）、replay 重算（新报表）、LLM 未配置降级规则

全部走确定性规则（conftest 把 LLM_API_KEY 设成占位值 → is_llm_configured() 为 False）。
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("compare_api_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    初始化数据库()

    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT_CODES[email] = code
        return True

    _orig_send = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig_send


def _register(client, username: str) -> str:
    email = f"{username}@test.com"
    assert client.post("/auth/send-code", json={"email": email}).status_code == 200
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _上传(client, token: str, 文件名: str, 内容: str) -> str:
    r = client.post(
        "/datasets/upload",
        files={"file": (文件名, 内容.encode(), "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    if "上传成功" in j:
        return j["上传成功"][0]["数据集ID"]
    return j["数据集ID"]


def _月度数据(月份: str, 倍数: float = 1.0) -> str:
    """同一批地区、不同月份的数据：华东/华南/华北 三行。"""
    行 = ["地区,销售额"]
    for 地区, 基数 in (("华东", 100), ("华南", 200), ("华北", 300)):
        行.append(f"{地区},{基数 * 倍数:.1f}")
    return "\n".join(行)


def _准备三个数据集(client, token: str):
    return [
        _上传(client, token, "1月.csv", _月度数据("1月", 1.0)),
        _上传(client, token, "2月.csv", _月度数据("2月", 1.5)),
        _上传(client, token, "10月.csv", _月度数据("10月", 2.0)),
    ]


_认证 = lambda token: {"Authorization": f"Bearer {token}"}  # noqa: E731


# ============================================================================
# 1. 预览
# ============================================================================

class Test对比预览:
    def test_推荐来源轴取文件名_主体轴取地区(self, client):
        token = _register(client, "cmpv1")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare/preview", json={"数据集ID列表": ids},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "地区" in body["共同字段"]
        assert "销售额" in body["指标候选"]
        主体 = {c["列"]: c["基数"] for c in body["主体轴候选"]}
        assert 主体.get("地区") == 3
        推荐 = body["推荐"]
        assert 推荐["来源标签"] == ["1月", "2月", "10月"]   # 文件名兜底 + 自然排序
        assert 推荐["主体轴"] == "地区"
        assert 推荐["指标"] == "销售额"

    def test_手动标签覆盖文件名(self, client):
        token = _register(client, "cmpv2")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare/preview",
                        json={"数据集ID列表": ids, "对比标签": ["一期", "二期", "三期"]},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        assert r.json()["推荐"]["来源标签"] == ["一期", "二期", "三期"]

    def test_只有一个数据集_422(self, client):
        token = _register(client, "cmpv3")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare/preview", json={"数据集ID列表": ids[:1]},
                        headers=_认证(token))
        assert r.status_code == 422

    def test_数据集不存在_404(self, client):
        token = _register(client, "cmpv4")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare/preview",
                        json={"数据集ID列表": [ids[0], "不存在的ID"]},
                        headers=_认证(token))
        assert r.status_code == 404


# ============================================================================
# 2. 生成对比报表
# ============================================================================

class Test对比生成:
    def test_三个月对比_按来源分系列(self, client):
        token = _register(client, "cmpg1")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare", json={"数据集ID列表": ids},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        body = r.json()
        # 3 主体 × 3 来源 = 9 行长表
        assert len(body["报表数据"]) == 9
        assert body["图表配置"]["颜色"] == "来源"
        assert body["图表配置"]["类型"] == "stacked_bar"
        assert body["数据集ID列表"] == ids
        assert body["数据集ID"] == ids[0]
        assert body["agent_mode"] == "compare"
        # 对比元信息经 response_model 透出（否则前端拿不到明细）
        assert body["对比配置"]["轴类型"] == "时间型"
        assert len(body["对比配置"]["明细"]) == 3
        # 时间型 1月→10月，华东 100 → 200，变化率 +100%
        assert body["对比配置"]["明细"][0]["变化率"] == 1.0
        # LLM 未配置 → 结论走规则模板，如实标记来源
        assert body["意图来源"] == "规则"
        # 时间型结论：点名主体轴 + 变化率（三地同比增幅相同，取排序首项，不断言具体地区）
        assert "地区" in body["结论"]
        assert "%" in body["结论"]

    def test_类别型轴出倍数不出变化率(self, client):
        token = _register(client, "cmpg2")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare",
                        json={"数据集ID列表": ids, "对比标签": ["华东区", "华南区", "华北区"]},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["对比配置"]["轴类型"] == "类别型"
        assert "倍" in body["结论"]
        assert "%" not in body["结论"]

    def test_落库后可读且可列出(self, client):
        token = _register(client, "cmpg3")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare", json={"数据集ID列表": ids},
                        headers=_认证(token))
        rid = r.json()["报表ID"]
        r2 = client.get(f"/reports/{rid}", headers=_认证(token))
        assert r2.status_code == 200, r2.text
        # 该端点返回仓储原始结构：报表正文在嵌套的 "报表" 里
        报表 = r2.json()["报表"]
        assert 报表["agent_mode"] == "compare"
        assert 报表["数据集ID列表"] == ids

    def test_指定主体轴与指标(self, client):
        token = _register(client, "cmpg4")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare",
                        json={"数据集ID列表": ids, "维度": "地区", "指标": "销售额",
                              "聚合方式": "平均值"},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        assert r.json()["对比配置"]["聚合方式"] == "平均值"
        assert r.json()["对比配置"]["主体轴"] == "地区"

    def test_筛选条件生效(self, client):
        token = _register(client, "cmpg5")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare", json={
            "数据集ID列表": ids,
            "筛选条件": [{"字段": "地区", "操作": "等于", "值": "华东"}],
        }, headers=_认证(token))
        assert r.status_code == 200, r.text
        assert {行["主体"] for 行 in r.json()["报表数据"]} == {"华东"}

    def test_别人的数据集_404(self, client):
        token = _register(client, "cmpg6")
        other = _register(client, "cmpg7")
        my_ids = _准备三个数据集(client, token)
        other_ids = _准备三个数据集(client, other)
        r = client.post("/reports/compare",
                        json={"数据集ID列表": [my_ids[0], other_ids[0]]},
                        headers=_认证(token))
        assert r.status_code == 404

    def test_重复数据集_400(self, client):
        token = _register(client, "cmpg8")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare",
                        json={"数据集ID列表": [ids[0], ids[0]]},
                        headers=_认证(token))
        assert r.status_code == 400
        assert "重复" in r.json()["message"]

    def test_超过十个数据集_422(self, client):
        token = _register(client, "cmpg9")
        r = client.post("/reports/compare",
                        json={"数据集ID列表": [f"d{i}" for i in range(11)]},
                        headers=_认证(token))
        assert r.status_code == 422

    def test_空列表_422(self, client):
        token = _register(client, "cmpg10")
        r = client.post("/reports/compare", json={"数据集ID列表": []}, headers=_认证(token))
        assert r.status_code == 422

    def test_没有共同指标_400(self, client):
        token = _register(client, "cmpg11")
        a = _上传(client, token, "a.csv", "地区,销售额\n华东,100\n华南,200")
        b = _上传(client, token, "b.csv", "地区,库存量\n华东,10\n华南,20")
        r = client.post("/reports/compare",
                        json={"数据集ID列表": [a, b], "指标": "不存在的列"},
                        headers=_认证(token))
        assert r.status_code == 400


# ============================================================================
# 3. 对比报表的专属约束：refine 拒绝 / replay 重算
# ============================================================================

class Test对比报表约束:
    def _建一份(self, client, token) -> str:
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare", json={"数据集ID列表": ids}, headers=_认证(token))
        assert r.status_code == 200, r.text
        return r.json()["报表ID"]

    def test_精细化编辑被拒绝_400(self, client):
        token = _register(client, "cmpc1")
        rid = self._建一份(client, token)
        r = client.post(f"/reports/{rid}/refine", json={"指令": "把X轴换成地区"},
                        headers=_认证(token))
        assert r.status_code == 400
        assert "精细化编辑" in r.json()["message"]

    def test_重放走对比重算并落新报表(self, client):
        token = _register(client, "cmpc2")
        rid = self._建一份(client, token)
        r = client.post(f"/reports/{rid}/replay", headers=_认证(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["报表ID"] != rid
        assert body["agent_mode"] == "compare"
        assert len(body["报表数据"]) == 9
        assert body["对比配置"]["轴类型"] == "时间型"

    def test_重放时数据集被删_404(self, client):
        token = _register(client, "cmpc3")
        ids = _准备三个数据集(client, token)
        r = client.post("/reports/compare", json={"数据集ID列表": ids}, headers=_认证(token))
        rid = r.json()["报表ID"]
        # 删掉一个来源数据集 → 重放必须明确 404，而不是静默少一列
        assert client.delete(f"/datasets/{ids[2]}", headers=_认证(token)).status_code == 200
        r2 = client.post(f"/reports/{rid}/replay", headers=_认证(token))
        assert r2.status_code == 404


# ============================================================================
# 4. 合并时打血缘：/datasets/merge 新增可选 来源标识
# ============================================================================

class Test合并来源标识:
    def test_默认不加来源列(self, client):
        token = _register(client, "cmpm1")
        a = _上传(client, token, "甲.csv", "地区,销售额\n华东,100\n华南,200")
        b = _上传(client, token, "乙.csv", "地区,销售额\n华东,150\n华南,250")
        r = client.post("/datasets/merge", json={"数据集ID列表": [a, b]},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        # 未开启 → 字段集合与旧行为完全一致
        assert set(r.json()["字段列表"]) == {"地区", "销售额"}

    def test_开启后写入来源列(self, client):
        token = _register(client, "cmpm2")
        a = _上传(client, token, "1月.csv", "地区,销售额\n华东,100\n华南,200")
        b = _上传(client, token, "2月.csv", "地区,销售额\n华东,150\n华南,250")
        r = client.post("/datasets/merge",
                        json={"数据集ID列表": [a, b], "来源标识": True},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "来源" in body["字段列表"]
        assert body["行数"] == 4
        item = client.get(f"/datasets/{body['数据集ID']}", headers=_认证(token))
        assert item.status_code == 200, item.text
        取值 = {行.get("来源") for 行 in item.json()["预览数据"]}
        assert 取值 == {"1月", "2月"}

    def test_来源列被占用时改名(self, client):
        token = _register(client, "cmpm3")
        a = _上传(client, token, "x.csv", "来源,销售额\n甲,100\n乙,200")
        b = _上传(client, token, "y.csv", "来源,销售额\n甲,150\n乙,250")
        r = client.post("/datasets/merge",
                        json={"数据集ID列表": [a, b], "来源标识": True},
                        headers=_认证(token))
        assert r.status_code == 200, r.text
        字段 = r.json()["字段列表"]
        assert "数据来源" in 字段
        assert "来源" in 字段
