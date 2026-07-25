# HTML 前端启动说明

这是轻量化数据分析 Agent 的 HTML + ECharts 前端。

## 1. 启动 FastAPI 后端

```powershell
cd D:\python\agent\自助式数据分析Agent平台
python api\main.py
```

后端默认地址：

```text
http://127.0.0.1:8000
```

核心接口：

```text
GET  /health
POST /datasets/upload
GET  /datasets/{dataset_id}
POST /reports/generate
```

`POST /reports/generate` 会返回：

```text
图表配置
报表数据
推荐说明
风险提示
Agent Trace
导出数据
结论
```

## 2. 启动 HTML 前端

```powershell
cd D:\python\agent\自助式数据分析Agent平台
python 前端_html\app.py
```

如果直接用 `uvicorn` 启动：

```powershell
cd D:\python\agent\自助式数据分析Agent平台
uvicorn 前端_html.app:app --host 127.0.0.1 --port 8501
```

然后打开：

```text
http://127.0.0.1:8501
```

## 3. 使用流程

1. 上传 `.csv`、`.xlsx` 或 `.xls` 文件
2. 查看数据概览、字段画像、字段建议和数据质量
3. 从“推荐语句模板”选择受控分析表达，或按模板改写需求
4. 点击“应用推荐字段”，系统会根据语句自动选择字段、图表类型和聚合方式
5. 查看实时配置校验提示
6. 点击“生成报表”
7. 查看 ECharts 图表、数据表、分析结论和 Agent Trace
8. 导出 HTML 报告或 JSON 结果

推荐语句格式：

```text
按【字段】统计数量
按【字段】统计占比
按【时间字段】查看【指标】趋势
查看【字段A】和【字段B】的交叉分布
查看【数值字段】的分布情况
比较【字段】下【指标】差异
按【字段】和【分组字段】生成堆积图
按【时间字段】查看【指标】面积图
按【字段】比较多个指标雷达图
```

当前支持的图表类型：

```text
柱状图、折线图、饼图、散点图、直方图、热力图、
堆积柱状图、面积图、雷达图、表格
```

常见语句与图表映射：

| 语句意图 | 图表 | 默认计算 |
|---|---|---|
| 统计数量 | 柱状图 | 分类字段 + 记录数计数 |
| 统计占比 | 饼图 | 分类字段 + 记录数计数 |
| 查看趋势 | 折线图 | 时间字段 + 指标聚合 |
| 交叉分布 | 热力图 | 两个维度 + 计数/聚合 |
| 数值分布 | 直方图 | 数值字段分桶 + 计数 |
| 生成堆积图 | 堆积柱状图 | X轴 + 分组字段 + 指标 |
| 面积图 | 面积图 | 时间字段 + 指标 |
| 多指标对比 | 雷达图 | 分类字段 + 多个数值指标 |

## 4. 当前边界

- 不依赖 MySQL / NL2SQL
- 不依赖 Streamlit 会话状态
- 上传文件目前保存在 `data/uploads/`
- 数据集 DataFrame 目前缓存在 FastAPI 进程内存中
- Agent Trace 目前基于规则和数据画像生成，后续可替换为 LLM Planner
- HTML 报告导出目前由后端生成静态 HTML 字符串，前端通过 Blob 下载
