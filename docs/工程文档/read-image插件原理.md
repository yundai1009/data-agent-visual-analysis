# read-image 插件原理

> 给 Agent 增加"看懂图片"能力的通用原理。核心链路只有三步：
> **图片 → Base64 → 纯视觉模型 → 文本结果 → 主模型继续推理**
>
> 适用场景：把图表截图、表格截图、产品图、验证码等图片内容喂给 LLM 做后续分析。

```
┌────────┐  base64   ┌──────────────────┐  文本/JSON  ┌────────────┐
│ 图片文件 │ ────────→ │ 纯视觉模型（多模态） │ ─────────→ │  主模型 Agent │
└────────┘           └──────────────────┘            └────────────┘
   1.编码                2.推理/描述/抽取               3.消费结果
```

---

## 1. 图片 Base64 编码

### 为什么需要 Base64

- LLM 的 `chat/completions` 接口是**纯文本通道**（JSON），不能直接传二进制图片字节；
- Base64 用 64 个 ASCII 字符表达任意二进制，是"把二进制装进文本"的标准做法；
- 协议层面，OpenAI 兼容接口通过 **Data URL** 传递图片：`data:<mime>;base64,<编码串>`。

### 编码实现（Python）

```python
import base64
from pathlib import Path

def image_to_data_url(path: str, mime: str = "image/png") -> str:
    raw = Path(path).read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")   # bytes → str，避免二进制混入 JSON
    return f"data:{mime};base64,{b64}"
```

- 一句话：`read_bytes()` → `b64encode()` → 拼成 `data:image/png;base64,xxx`；
- `decode("ascii")` 保证结果是纯 ASCII 文本，可以直接放进 JSON 请求体。

### 工程细节（生产必看）

| 细节 | 说明 |
|------|------|
| 压缩 | 原图动辄几 MB，先 `PIL.Image` 缩放（如最长边 1024px）+ 转 JPEG 再编码，省流量、省视觉 token |
| 格式 | PNG 无损适合截图/表格；JPEG 适合照片；统一按目标模型支持的 mime 发送 |
| 大小限制 | 多数端点对单图有上限（如 gpt-4o 常见限制约 20MB/图，且按图块计费）；压缩后一般 <1MB 最稳 |
| 不要打日志 | base64 串很长且可能含敏感信息，日志只记 `image_id`/尺寸，不记编码串 |

---

## 2. 调用纯视觉模型

### 消息结构（OpenAI 兼容协议）

视觉模型的消息里，`content` 从**字符串**变成**数组**，可以混排文本与多张图片：

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "这张图里有什么？请列出图表类型、坐标轴字段和数值。"},
        {
          "type": "image_url",
          "image_url": {"url": "data:image/png;base64,<base64串>", "detail": "high"}
        }
      ]
    }
  ]
}
```

- `text` 指令很重要：直接告诉模型"要输出什么、什么格式"，否则返回质量不稳定；
- `detail`：`low` / `high` / `auto`，控制视觉 token 消耗（`low` 只看低分辨率快照，便宜）；
- 请求本身和普通 `chat_completion` 一致，只是 `content` 数组里多了 `image_url`。

### 本项目接入：扩展现有 `chat_completion`

当前 `后端_核心/agent/llm客户端.py::chat_completion` 只接受 `List[Dict[str, str]]` 的 messages。接入视觉需要：

```python
# messages 允许两种元素：
#   {"role": "user", "content": "普通文本"}                          # 旧
#   {"role": "user", "content": [{"type":"text",...}, {"type":"image_url",...}]}  # 新
```

Payload 组装的 `"messages": messages` 直接透传即可，不需要改请求层——协议兼容。

### 模型选择（注意本项目白名单限制）

| 模型 | 是否支持视觉 | 说明 |
|------|-------------|------|
| GPT-4o / GPT-4o-mini | ✅ | 原生多模态，本项目 openai provider 白名单内 |
| Qwen2.5-VL 系列 | ✅ | siliconflow 上有，需把 `LLM_PROVIDERS` 白名单对应 provider 的 `models` 加入 VL 模型 |
| DeepSeek-chat / reasoner | ❌ | 纯文本模型，无视觉能力，**不能**用于 read-image |

> 关键约束：本项目阶段 5 规定前端只能选白名单内的 provider+model。要支持读图，必须**先在白名单里放一个视觉模型**（如 openai 的 gpt-4o 或 siliconflow 的 Qwen2.5-VL），否则用户无法选到能看图的模型。

### Token 与成本

- 视觉 token 按**图块（tile）**计算：图先被切成 512×512 的块，`high` 精度一块约 170 token，`low` 整体约 85 token；
- 一张 1024×1024 的图 `high` 大约 765 token，`low` 约 85 token——**非必要不开 high**；
- 纯视觉模型调用通常比文本贵，批量处理时先压缩 + 用 `low`。

---

## 3. 结果发回给主模型使用

### 工具调用闭环

本项目是 **ReAct 编排**（`编排器.py` + `工具集.py` + `执行器注册.py`），read-image 作为一个工具注册进 `TOOL_SCHEMAS_FULL`：

```
主模型(LLM) ──tool_call: read_image(path="uploads/xxx.png", question="...")──→ 执行器
执行器：
  1. 读图 → base64
  2. 调视觉模型 → 文本结果
  3. 返回结构化文本
主模型 ←─tool 消息: "图表类型：柱状图；X轴=地区；数值=[华东100, 华南200, ...]"──
主模型（拿到结果继续推理）→ 最终输出结论/报表
```

- 工具 schema 注册在 `后端_核心/agent/工具集.py`，执行函数注册在 `执行器注册.py`，主模型看到 schema 后自行决定何时调用；
- 图片路径来自**服务端**（用户上传的 dataset 附件），不走用户传 URL，避免 SSRF 与任意地址读取。

### 返回什么给主模型

视觉模型的原生输出通常是自由文本，**不能直接丢给主模型当结论**，执行器要做一次"翻译"：

```python
# 视觉模型输出（自由文本）
"这是一张柱状图，X轴是地区，有华东、华南、华北，数值分别约100、200、150……"

# 执行器整理后返回（结构化，主模型好消费）
{
  "图表类型": "柱状图",
  "x轴字段": "地区",
  "数值": {"华东": 100, "华南": 200, "华北": 150},
  "置信度": "中",
  "说明": "数值为视觉近似读取，如需精确请以源数据为准"
}
```

- **结构化优于原文**：主模型直接拿字段，避免二次幻觉；
- **必须标注"视觉近似"**：模型读图数值不可靠，让主模型在结论里提示不确定性；
- 结果通过 `role: "tool"` 消息追加回 messages，主模型在下一轮 ReAct 里消费它并产出最终答案。

### 失败降级

视觉调用随时可能失败（模型不支持、图损坏、超时），沿用本项目 LLM 失败模式：

```python
try:
    result = 调用视觉模型(data_url, prompt)
    return {"成功": True, "内容": 整理后的结构化结果}
except Exception as exc:
    logger.warning("read-image 失败: %s", exc)
    return {"成功": False, "错误": "图片无法解析，请上传清晰的图表截图"}
```

失败时返回**可读的降级消息**而不是抛异常——主模型据此告知用户"图片无法识别"，流程不中断。

---

## 接入本项目的落地清单

1. `config/settings.py`：白名单 `LLM_PROVIDERS` 的 openai models 确认含 `gpt-4o`，或 siliconflow 加 `Qwen/Qwen2.5-VL-7B-Instruct`；
2. `后端_核心/agent/llm客户端.py`：`chat_completion` 的 messages 类型注解放宽（允许 content 数组），payload 无需改动；
3. 新增 `后端_核心/agent/图像工具.py`：`read_image(path, question)` 执行器（读图→压缩→base64→视觉调用→结构化返回）；
4. `后端_核心/agent/工具集.py` + `执行器注册.py`：注册 `read_image` 的 schema 与执行器；
5. 上传接口（`api/routes/datasets.py`）支持图片附件，存到服务端可读路径；
6. 前端无需改：Agent 自行决定是否调用该工具。

---

## 面试可讲点

**"read-image 怎么让纯文本模型看懂图？"**
> "分三步：先把图片 Base64 编码成 Data URL 塞进文本通道；再调用原生多模态模型（如 gpt-4o）解析图片——这一步是**纯视觉模型**，它只负责把图翻译成文本；最后把翻译结果结构化后通过 tool 消息发回给主模型。主模型从头到尾只处理文本，视觉能力是'外包'给子模型的，这就是插件解耦。"
**"为什么不直接把图片丢给主模型？"**
> "主模型不一定有视觉能力（如 DeepSeek），即使有也会消耗大量视觉 token。用一个专门的视觉模型做'看图→文本'这一步，主模型保持纯文本推理，职责清晰、成本可控、还能在视觉模型不可用时降级。"
