# 阶段 50：LLM 链路 VCR 录制回放测试 —— 实施计划

> **执行方式**：本会话内联执行（用户已批准方案 B：自研 cassette 层，替代 vcrpy）。
> 步骤用 `- [ ]` 跟踪；每步都有独立验证。

**Goal:** 让「LLM 智能路径」在 CI 上离线可回归——prompt 改动、供应商 API 漂移、模型行为变化会立刻让测试变红，而不是"227 全绿但 LLM 路径从未被真实请求测过"。

**Architecture:** 在测试内 monkeypatch `requests.post`，按 `sha256(url + 请求体 JSON)` 指纹读写 JSON cassette。默认回放（无 key、无网络）；`LLM_VCR_RECORD=1` 录制（真实网络或脚本响应）。cassette 只存 url/请求体/响应体，**headers 永不落盘**（Authorization 零泄露面）。

**Tech Stack:** Python pytest（无新依赖）、unittest.mock、`后端_核心/agent/orchestrator.py` 既有 ReAct 编排。

## Global Constraints

- 不新增任何锁版本依赖（沿用项目"依赖轻、好讲解"原则）；
- 现有 227 个测试一个不碰；
- 新测试在 CI（windows-latest）离线可跑：conftest 占位 key 下也必须全绿；
- 命名沿用项目中文标识符风格；新文件均 UTF-8；
- 结束必须双写开发日志（md + docx）并 commit 后 push。

---

## Task 1: cassette 核心模块（tests/llm_cassette.py）

**Files:**
- Create: `tests/llm_cassette.py`
- Test: `tests/backend/test_llm_cassette.py`

**Interfaces:**
- Produces: `LLMCassette(scenario, script=None)`；`cassette.wrap(real_post) -> Callable`；`CassetteMiss`；`FakeResponse`；`_请求指纹(url, payload) -> str`。

- [ ] **Step 1: 写失败单测**（fingerprint 稳定性 / 回放命中 / 回放未命中抛 CassetteMiss / 录制落盘且不含 headers）
- [ ] **Step 2: 跑单测确认红**（`python -m pytest tests/backend/test_llm_cassette.py -q` → ModuleNotFoundError）
- [ ] **Step 3: 实现模块**（约 90 行，见下）
- [ ] **Step 4: 跑单测确认绿**
- [ ] **Step 5: 提交** `feat(test): 阶段50 自研LLM VCR cassette层`

核心实现：

```python
class LLMCassette:
    def __init__(self, scenario, script=None):
        self.scenario = scenario
        self.script = script                      # 录制时可用脚本响应替代真实网络
        self._real_post = None
        self._calls = 0
        self.recording = os.getenv("LLM_VCR_RECORD") == "1"

    def wrap(self, real_post):
        self._real_post = real_post
        def _post(url, *args, **kwargs):
            payload = kwargs.get("json") or {}
            fp = _请求指纹(url, payload)
            path = _cassette_path(self.scenario, fp)
            if not self.recording and path.exists():
                entry = json.loads(path.read_text(encoding="utf-8"))
                return FakeResponse(entry["status_code"], entry["json"])
            if not self.recording:
                raise CassetteMiss("cassette 缺失：... 请用 LLM_VCR_RECORD=1 录制或运行 generate_llm_goldens.py")
            resp = (FakeResponse(200, self.script(url, payload, self._calls))
                    if self.script is not None else real_post(url, *args, **kwargs))
            if self.script is not None:
                self._calls += 1
            entry = {"request": {"url": url, "json": payload},
                     "status_code": int(resp.status_code), "json": resp.json()}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
            return resp
        return _post
```

## Task 2: 端到端 VCR 测试（tests/backend/test_llm_vcr.py）

**Files:**
- Create: `tests/backend/test_llm_vcr.py`
- Create: `tests/backend/test_llm_cassette.py`（Task 1 单测）

**Interfaces:**
- Consumes: `LLMCassette`（Task 1）
- Produces: `录制黄金样本(scenarios)` 供 Task 3 生成器调用；`样本画像()` / `样本df()` / `测试llm配置()` / 三个脚本响应函数

- [ ] **Step 1: 写测试**（4 个场景）：
  1. `react_multi_round` 回放 → `编排Agent` 返回 `意图来源 == "LLM"`、图表类型在白名单、字段在画像内、trace 非空；
  2. `degrade_round1` 回放（第 1 轮 LLM 只回文字）→ `意图来源 == "规则"`（真实 HTTP 层触发降级）；
  3. `tool_call_direct` 回放 → 直接调 `chat_completion` + `extract_tool_call`，arguments 字符串被正确解析；
  4. 未命中场景 → 抛 `CassetteMiss`（证明 CI 只红不假绿）。
- [ ] **Step 2: 跑测试确认红**（无 cassettes → 全部 CassetteMiss / ModuleNotFoundError）
- [ ] **Step 3: 跑 Task 3 生成器生成黄金样本**
- [ ] **Step 4: 跑测试确认绿**（回放命中）
- [ ] **Step 5: 提交** `feat(test): 阶段50 LLM链路VCR端到端回归`

要点：
- 记忆链路全部打桩：`检索相似记忆 → []`、`保存记忆 → no-op`、`生成_few_shot_prompt → ""`、`清理记忆 → no-op`（否则 chromadb/embedding 会把 cassette 范围污染）；
- `测试llm配置()` 用固定 `base_url="https://api.deepseek.com/v1"` + `model="deepseek-chat"`（SSRF 校验在离线环境 DNS 失败时放行，已验证 `llm_security.py:58-63`）；
- 脚本响应按调用序返回 OpenAI 格式 dict：轮 1 `获取数据画像`、轮 2 `聚合分析`、轮 3 `推荐图表`（arguments 各为 `"{}"` / JSON 字符串 / JSON 字符串）。

## Task 3: 黄金样本生成器（scripts/generate_llm_goldens.py）

**Files:**
- Create: `scripts/generate_llm_goldens.py`

**Interfaces:**
- Consumes: `tests/backend/test_llm_vcr.py` 的 `录制黄金样本`

- [ ] **Step 1: 写生成器**（importlib 从文件路径加载测试模块，避免包导入歧义；`os.environ["LLM_VCR_RECORD"]="1"`；跑 3 个场景）
- [ ] **Step 2: 运行** `python scripts/generate_llm_goldens.py` → 生成 `tests/cassettes/<scenario>/<fp>.json`
- [ ] **Step 3: 跑 Task 2 测试确认回放全绿**
- [ ] **Step 4: 提交** `chore(test): 阶段50 黄金样本生成器 + 首批cassette`

## Task 4: 验收清单更新（docs/工程文档/生产级验收清单.md）

- [ ] 更新 `阶段 28 → 阶段 50`；`171/113/29 → 227+新增/33`；
- [ ] 自动化验证节加入：`python -m pytest tests/backend/test_llm_vcr.py -q`（离线回放，无 key）与 `python scripts/generate_llm_goldens.py`（有 key 时重录）；
- [ ] 已知限制表新增一行：LLM 智能路径通过 VCR 回放离线回归；真实响应由用户 `LLM_VCR_RECORD=1` 录制。
- [ ] 提交 `docs: 生产级验收清单同步阶段50（VCR 回归项）`

## Task 5: 回归 + 开发日志双写 + push

- [ ] `python -m pytest tests/ -q` 全量（含新测试）全绿
- [ ] `node node_modules/vitest/vitest.mjs run` 33 绿；`npx oxlint src` 0 error
- [ ] 开发日志 `docs/开发日志/项目开发日志.md` 补写阶段 50（六段式 + 导航表一行）
- [ ] docx 双写：`求职学习资料\项目开发日志.docx`（python-docx，插到旧日志锚点前）
- [ ] 提交（`feat(test)` 已在各 Task 提交；此处 `docs:` 单独提交）→ `git push`（SSH-443）
