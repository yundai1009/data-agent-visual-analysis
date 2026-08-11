# LLM 接入说明（阶段 1 起，现已演进为多轮 ReAct 编排）

本项目从"自然语言 → 报表意图"的关键词匹配，先后演进为：

> **阶段 1**：单次 Function Calling（结构化意图 JSON）
> **阶段 9 起**：多轮 ReAct 编排（画像 → 聚合分析 → 推荐图表 + 生成结论）

核心安全姿态始终不变：

> **LLM 不生成可执行代码、不被 exec、不被 eval**——只能通过受控工具 schema 填参数，执行路径完全由后端 Python 决定。

---

## 一、配 `.env` 启用 LLM

复制 `.env` 改成你的真实 key：

```dotenv
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的真实 key
LLM_MODEL=deepseek-chat
LLM_TIMEOUT=60
LLM_TEMPERATURE=0
```

不配 / 占位 `your_llm_api_key` → 项目自动按关键词匹配兜底，仍能跑，只是不"智能"。

---

## 二、安全姿态（面试可讲）

| 项 | 规则 |
|---|---|
| LLM 输出形态 | 仅接受 chat/completions 的 `tool_calls` JSON；不解析 Python 字面量；多轮 ReAct 中每轮调用一个受控工具 |
| 字段白名单 | `X轴 / 分组字段 / Y轴` 必须在数据画像 `字段列表` 内；越界即视为失败 |
| 图表类型/聚合方式 | 必须在白名单 set 内 |
| 字段决策优先级 | **用户显式选择（非空）优先，LLM 只填空缺**；图表类型仅在用户选"自动推荐"时由 LLM 决策（`上传报表生成器.py` 生成报表数据内合并逻辑） |
| LLM 代码执行 | **任何情况下都不 exec LLM 输出**。Tool 是后端 Python 函数，参数由 LLM 提供、由后端校验后再调用 |
| 凭据 | 仅从 `config.settings.EnvConfig` 读，源码中无 key |
| 超时 | 单次 LLM 调用 ≤ `LLM_TIMEOUT` 秒 |
| 失败回退 | 未配置 / 网络异常 / HTTP 非 200 / 无 tool_call / 字段越界 → 全部静默回退到关键词匹配 `_意图驱动配置`，主链路不报错 |
| 可观测性 | `后端_核心/agent/llm客户端.py` 与 `编排器.py` 在每个失败节点打 `logger.warning`；响应中保留 `意图来源` 字段，取值 `LLM / 规则 / 无` |

---

## 三、为什么不让 LLM 生成可执行代码

「Agent 自动数据分析」常见但危险的写法是：让 LLM 生成一段 pandas 代码，后端 `exec` 执行。
这种路线的问题：

1. **`exec` 没有强制力**：LLM 输出 `__import__("os").system("rm -rf ...")` 或 `open("/etc/passwd").read()` 没有任何 guard 能拦。
2. **AST 白名单 + 子进程隔离** 是工程上能做的加固，但成本高、易绕过、不在阶段 1 范围。
3. **结构化意图 JSON + 后端受控 Tool** 是更现代的路线（OpenAI Function Calling / Anthropic Tool Use 都是这条路）。

本项目选第三条路：LLM 只能在受控 schema 内填参数，**执行路径完全由后端 Python 决定**，LLM 没有写代码的权限。

---

## 四、模块结构

```
后端_核心/
├── agent/
│   ├── __init__.py        # 对外暴露 解析自然语言需求
│   ├── llm客户端.py        # OpenAI 兼容 chat/completions 调用 + JSON 容错解析 + tool_call 抽取
│   ├── 工具集.py           # 5 个 Tool schema（解析为报表意图/获取数据画像/聚合分析/推荐图表/生成结论）；
│   │                       #   运行时 TOOL_SCHEMAS_FULL 去掉旧"解析为报表意图"后暴露 4 个 ReAct 工具
│   └── 编排器.py           # 多轮 ReAct 编排：轮1 获取数据画像 → 轮2 聚合分析 → 轮3 推荐图表+生成结论；
│                           #   _从消息提取意图 做字段白名单校验；词云等特殊图兜底修正
└── 上传报表生成器.py        # 调用 agent 编排；失败回退 _意图驱动配置（关键词兜底）；合并 LLM 决策与用户显式字段
```

---

## 五、测试

不依赖网络、不依赖真实 key：

```powershell
cd D:\python\agent\自助式数据分析Agent平台
python -m pytest tests/test_agent_意图.py -v
```

覆盖：
- JSON 解析层（含 markdown fence / 括号不配平 / 非 dict / 空输入）
- tool_call 抽取层（含 dict / string / 非法 JSON / 空响应）
- 字段白名单校验层（含字段越界 / 图表类型越界 / 聚合方式越界 / Y 轴字符串转 list）
- 编排器降级路径（未配 key / 空需求 / LLM 返回 None / 无 tool_call / tool 名错 / 字段越界 / 正常成功）

---

## 六、用户侧验证（配了 key 后）

启动后端：

```powershell
cd D:\python\agent\自助式数据分析Agent平台
python api\main.py
```

上传一个 CSV：

```powershell
curl -F "file=@data/http_verification_sales.csv" -H "Authorization: Bearer demo-token" http://127.0.0.1:8000/datasets/upload
```

拿到 `数据集ID` 后让 LLM 自动出图：

```powershell
curl -X POST http://127.0.0.1:8000/reports/generate `
  -H "Authorization: Bearer demo-token" `
  -H "Content-Type: application/json" `
  -d '{\"数据集ID\":\"<你的 ID>\",\"分析需求\":\"按地区看销售额占比\",\"图表类型\":\"自动推荐\"}'
```

响应里的 `意图来源` 字段应为 `"LLM"`，且 `图表类型` 应为 `饼图`。

把 `LLM_API_KEY` 改回占位再跑一次，`意图来源` 应变为 `"规则"`（关键词匹配兜底），仍可出图。

---

## 七、DeepSeek 接入注意点

- DeepSeek 与 OpenAI 协议兼容，`LLM_BASE_URL=https://api.deepseek.com/v1`，`LLM_MODEL=deepseek-chat`；
- DeepSeek 支持 Function Calling（`tools` + `tool_choice`）；
- 在中文 prompt + 复杂 schema 场景下，DeepSeek 输出稳定性约 90-95%，本项目靠字段白名单 + 关键词兜底保证主链路 100% 可用；
- 切换到 OpenAI gpt-4o-mini 只需改 `.env` 三行，**零代码改动**：
  ```dotenv
  LLM_BASE_URL=https://api.openai.com/v1
  LLM_API_KEY=sk-...
  LLM_MODEL=gpt-4o-mini
  ```
