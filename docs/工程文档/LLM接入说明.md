# LLM 接入说明

> 文档状态：**2026-10-13 · 阶段六十一**（逐条核对到当前代码）
> 配套文档：`docs/工程文档/部署配置说明.md`（部署与环境）、`docs/工程文档/安全设计说明.md`（威胁模型）

本平台的「自然语言 → 图表 / 结论 / 长期记忆」全部由 LLM 驱动。本文回答四件事：**怎么配**、**Key 怎么选**、**安全边界在哪**、**出错了怎么查**。

**读旧文档前先知道的三条演进**

1. **模块改名**：仓库同时存在中文别名与英文名两套文件，**真实 import 路径是英文名**。`llm客户端.py` → `后端_核心/agent/llm_client.py`；`编排器.py` → `后端_核心/agent/orchestrator.py`；`工具集.py` → `后端_核心/agent/tools.py`；`记忆.py` → `后端_核心/agent/memory.py`；`上传报表生成器.py` → `后端_核心/report_generator.py`。
2. **配置从「全局一份 .env」演进到「请求级配置 + 18 家预设供应商 + 用户自带 Key（BYOK）」**：不再有"临时改全局变量"这种并发不安全做法。
3. **阶段六十一新增向量记忆**：embedding 走独立配置项，并在启动时做一致性硬闸（同库不得混用不同 embedding 模型）。

---

## 一、最小可用配置

在 `D:\python\数据分析agent\自助式数据分析Agent平台\.env` 写入：

```dotenv
# 必填：对话模型（任何 OpenAI 兼容端点）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的真实key
LLM_MODEL=deepseek-chat

# 强烈建议：超时与温度写死，避免"抽风"（0 = 不发挥、只做抽取）
LLM_TIMEOUT=60
LLM_TEMPERATURE=0
```

不配 `LLM_API_KEY` 或仍是占位值 → `is_llm_configured()`（`llm_client.py:109`）返回 False，全链路自动降级到关键词规则（响应里 `意图来源` = `规则`），**仍能出图，只是不智能**。

### embedding（向量记忆，可选）

不配这三项时**只有记忆功能关闭**，报表生成、图表推荐不受影响：

```dotenv
LLM_EMBEDDING_BASE_URL=https://api.openai.com/v1
LLM_EMBEDDING_MODEL=text-embedding-3-small
# LLM_EMBEDDING_API_KEY=     # 留空则回落 LLM_API_KEY（同供应商场景不必重复配）
```

> **为什么必须单列这三项**（阶段六十一 D1）：不同供应商的 embedding 模型名与向量维度都不一样，混用会得到"能存不能查"的静默损坏库。`config/settings.py:30-39` 的注释写明了这条坑。
>
> 读取入口：`llm_client.embedding_settings()`（`llm_client.py:379`）与 `llm_client.embed_text()`（`llm_client.py:403`）。

### 其余可调项（`config/settings.py`）

| 变量 | 默认 | 作用 |
|---|---|---|
| `LLM_MAX_TOKENS` | 2048 | 单次响应上限，防止长结论把上下文撑爆 |
| `LLM_DAILY_TOKEN_QUOTA` | 1000000 | 全站每日 token 配额（防刷） |
| `LLM_DAILY_REQUEST_QUOTA` | 200 | 全站每日请求数配额 |
| `LLM_KEY_ENCRYPTION_KEY` | 空 | **BYOK Key 落库加密密钥**，生产必须设置；不设则用户 Key 以明文存 |
| `AUTH_ENABLED` | false | 是否开启登录鉴权；关闭时所有接口走演示账号 |
| `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD` | `admin` / `admin123` | 种子管理员，**生产必须覆盖默认密码** |

---

## 二、18 家预设供应商

配置文件：`config/providers.toml`（153 行）。每个 provider 声明 `name / label / base_url / models / default / api_key_env / note`。

**内置列表**：deepseek、openai、gemini、claude、mistral、groq、xai、glm、qwen、kimi、doubao、ernie、hunyuan、minimax、stepfun、yi、openrouter、siliconflow。

> ⚠️ **全部 `kind = openai`**，即统一走 OpenAI 兼容的 `/chat/completions` 协议。Claude 官方端点只列了模型名，实际接入需走中转服务（否则协议不兼容）。

- 加载入口：`config/settings.py` 的 `_加载LLMProviders()`；文件缺失或 TOML 解析失败 → 回退到内置默认表，**服务照常启动**。
- 类定义完成后统一赋值：`EnvConfig.LLM_PROVIDERS = EnvConfig._加载LLMProviders()`（`config/settings.py:165`）。
- 用户可在前端增删自定义供应商：`frontend/src/components/LLMConfig.jsx`，对应接口 `GET /auth/llm-providers`、`POST /auth/llm-providers/custom`、`DELETE /auth/llm-providers/custom/{name}`、`POST /auth/llm-providers/test`。新增供应商的 base_url 会过 SSRF 校验。

---

## 三、Key 的四级优先级与隔离

同一次请求可能涉及四种 Key 来源，优先级从高到低：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 请求头 `X-LLM-API-Key` | 仅供脚本/自动化调用显式指定 |
| 2 | 账号 BYOK Key | 用户在 `LLMConfig.jsx` 里填自己的 Key，加密后存库 |
| 3 | provider 的 `api_key_env` | 如 deepseek → `DEEPSEEK_API_KEY`，按供应商各配各的 |
| 4 | 服务端 `LLM_API_KEY` | 兜底：谁的都没有就用平台自己的 |

**隔离原则：请求级配置，不碰全局。**

`config/settings.py:168` 的 `@dataclass(frozen=True) class LLMRequestConfig` 字段为 `provider / base_url / model / api_key / llm_fail_reason`，每次生成报表时按用户选择构造，沿调用链显式传递。

> **为什么不选"临时改 `EnvConfig.LLM_BASE_URL` 再 try/finally 还原"**：两个用户同时发请求必然互相污染，还依赖 try/finally 万无一失。frozen dataclass 让每个请求的配置在整条链路上"看得见"，并发请求互不干扰（这是阶段 12 收尾时的改造点）。

---

## 四、安全姿态（面试可讲）

| 项 | 规则 | 位置 |
|---|---|---|
| LLM 不执行代码 | 任何情况下都不 `exec` / `eval` LLM 输出；工具是后端 Python 函数，参数由 LLM 给、后端校验后再调 | `tools.py` |
| 工具数量 | 5 个受控 schema（`解析为报表意图` / `获取数据画像` / `聚合分析` / `推荐图表` / `生成结论`），ReAct 循环只暴露后 4 个 | `tools.py:52,108,117,155,178` |
| 字段白名单 | `X轴 / Y轴 / 分组字段` 必须命中数据画像的字段列表，否则视为失败 | `tools.py` 的 `_validate_field` / `_validate_y_axis` |
| 枚举白名单 | 图表类型 `_validate_chart_type`、聚合方式 `_validate_aggregation` | `tools.py:344/366` |
| 用户优先 | 用户显式选的字段/图表类型优先，LLM 只填空缺 | `report_generator.py` |
| SSRF 防护 | base_url 出站前做地址校验；**且禁用重定向**（`allow_redirects=False`），防"校验通过后再 302 到内网"绕过 | `llm_client.py:264`、`:296-299` |
| 重试与退避 | 最多尝试 3 次（首发 + 2 次重试），指数退避 0.5s / 1s，仅对 429 / 5xx / 408 / 网络异常重试 | `llm_client.py:286-320` |
| 超时 | 单次调用 ≤ `LLM_TIMEOUT` 秒（默认 60） | `llm_client.py` |
| 配额 | 每日 token 与请求数双配额 | `config/settings.py:88-89` |
| 凭据落库 | BYOK Key 用 `LLM_KEY_ENCRYPTION_KEY` 加密；管理端读用户列表时该字段被查询层剔除，而非事后过滤 | `config/settings.py:101`、`repositories/admin_repo.py` |
| 失败回退 | 未配置 / 超时 / 非 200 / 无 tool_call / 字段越界 → 全部降级为关键词规则，主链路不报错 | `orchestrator.py` |
| 可观测性 | 每个失败节点 `logger.warning`；响应带 `意图来源`（`LLM` / `规则` / `无`）与 `llm_fail_reason` | `llm_client.py:73,91` |
| 启动硬闸 | 记忆库 embedding 指纹与当前配置不一致 → 拒绝启动（宁可停服也不产出静默损坏的向量库） | `api/main.py` 第 6 道防线 |

---

## 五、为什么不生成可执行代码

「让 LLM 写一段 pandas，然后后端 `exec`」是行业里常见但危险的做法：

1. **`exec` 没有强制力**：模型输出 `__import__("os").system(...)` 或 `open("/etc/passwd").read()`，任何 guard 都拦不住。
2. **AST 白名单 + 子进程隔离**能加固，但成本高、易绕过。
3. **结构化意图 + 受控 Tool**（OpenAI Function Calling / Anthropic Tool Use 的路线）把"写代码"降级成"填参数"，执行路径完全由后端 Python 决定。

本项目选第三条。LLM **没有任何写代码的权限**，它只能在受控 schema 里填参数，越界字段一律丢弃并降级。

---

## 六、模块结构

```
自助式数据分析Agent平台/
├── config/
│   ├── settings.py            # EnvConfig 全部环境变量 + LLMRequestConfig 请求级配置
│   └── providers.toml         # 18 家预设供应商
├── 后端_核心/
│   ├── agent/
│   │   ├── llm_client.py      # 唯一出网调用点：SSRF 校验/重试退避/JSON 容错解析/tool_call 抽取/embedding
│   │   ├── tools.py           # 5 个受控工具 schema + 字段白名单校验
│   │   ├── orchestrator.py    # 多轮 ReAct 编排（画像 → 聚合 → 推荐图表+结论）
│   │   ├── memory.py          # 阶段六十一：向量记忆（指纹校验、容量治理）
│   │   └── multi_agent.py     # 多智能体模式
│   └── report_generator.py    # 调编排器；失败回退关键词规则；合并用户显式字段
└── api/routes/reports.py      # /reports/generate、/reports/generate-stream
```

---

## 七、测试（不联网、不烧 Key）

```powershell
cd D:\python\数据分析agent\自助式数据分析Agent平台
python -m pytest tests\backend\test_agent_意图.py -v
python -m pytest tests\backend -q            # 全量，约 520+ 用例
```

**VCR 录放**：`tests/backend/llm_cassette.py` 提供"假网关"，把真实 LLM 响应录成 JSON 磁带放在 `tests/cassettes/`（5 个场景目录：`react_multi_round`、`react_llm_api_ok`、`react_llm_api_midmiss`、`degrade_round1`、`tool_call_direct`，共 11 个磁带）。测试时按请求指纹命中磁带，**不产生任何真实调用与费用**。

覆盖重点：JSON 容错解析（markdown 围栏 / 括号不配平 / 非 dict）、tool_call 抽取（dict / string / 非法 JSON / 空响应）、字段白名单越界、编排器降级路径（未配 key / 空需求 / LLM 返 None / tool 名错）、embedding 三要素同源与指纹校验。

---

## 八、手动验证

```powershell
cd D:\python\数据分析agent\自助式数据分析Agent平台
python api\main.py
```

1. 上传 CSV（示例文件：`data/示例数据_销售数据.csv`）：

```powershell
curl -F "file=@data/示例数据_销售数据.csv" http://127.0.0.1:8000/datasets/upload
```

> 鉴权说明：`AUTH_ENABLED=false` 时接口走演示账号，无需 `Authorization` 头；开启后请带登录拿到的真实 token（旧的 `demo-token` 机制已废弃）。

2. 用返回的 `数据集ID` 生成报表：

```powershell
curl -X POST http://127.0.0.1:8000/reports/generate `
  -H "Content-Type: application/json" `
  -d '{\"数据集ID\":\"<你的ID>\",\"分析需求\":\"按地区看销售额占比\",\"图表类型\":\"自动推荐\"}'
```

响应里 `意图来源` 应为 `"LLM"`；把 `LLM_API_KEY` 改回占位再跑一次，`意图来源` 应变为 `"规则"`，仍能出图。

---

## 九、故障排查

| 现象 | 真实原因与处理 |
|---|---|
| HTTP 401 | Key 与 `LLM_BASE_URL` 不属于同一家。最典型的是拿 DeepSeek 的 chat key 去打别人的 embedding 端点 —— 阶段六十一的三要素同源就是为消灭这个 |
| HTTP 400 + 模型名 | `LLM_MODEL` / `LLM_EMBEDDING_MODEL` 在该端点不存在，或该模型不支持 function calling |
| HTTP 429 | 触发限流或额度。系统会自动重试 2 次并指数退避；持续 429 就是真限流了，查供应商账户 |
| HTTP 5xx | 供应商侧故障，自动重试后仍失败则降级为规则，`llm_fail_reason` 里有原文 |
| 响应里 `意图来源: 规则` | LLM 没配、调用失败或输出被白名单判负。看后端日志的 `LLM 调用失败` 警告行 |
| 启动被拒："记忆库 embedding 指纹不一致" | 改了 `LLM_EMBEDDING_*` 但旧向量库还在。删除向量库目录后重启（旧记忆会丢）或用重建脚本迁移 |
| 记忆功能静默失效 | `LLM_EMBEDDING_*` 没配，或 embedding 端点返回 401/400 被吞掉。查 `/healthz` 的 `memory` 段 |

> `/healthz` 会同时返回数据库与记忆库状态（`api/main.py`）。记忆块**不会**把整体状态降级为失败——它只做观测，不拖垮可用性。

---

## 十、相关文件

- 配置定义：`config/settings.py`、`config/providers.toml`
- 出网唯一入口：`后端_核心/agent/llm_client.py`
- 编排与工具：`后端_核心/agent/orchestrator.py`、`后端_核心/agent/tools.py`
- 向量记忆：`后端_核心/agent/memory.py`
- 前端配置界面：`frontend/src/components/LLMConfig.jsx`
- 历史演进（阶段 50/51）：`docs/工程文档/阶段50-LLM-VCR实施计划.md`、`docs/工程文档/阶段51-实施计划.md`