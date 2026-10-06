# -*- coding: utf-8 -*-
"""阶段 55 · 报表图表局部精细化编辑服务。

设计定位（见 docs/superpowers/specs/2026-10-06-图表局部精细化编辑-design.md）：
对已生成报表做图表层局部修改，**不重新执行 Agent ReAct、不调用外部工具/LLM**，
仅复用报表关联数据集的 parquet + 已有画像做本地 pandas 重算，另存新报表。
"""
import re
from typing import Dict, List, Optional


# ---- 标识符/编码字段识别（约束 2 基石） ------------------------------------
# 标识符/编码 ID 类字段严禁作 Y 轴/数值度量，仅可作分类 X 轴。
# 识别规则：
#   1. 字段名命中 id/ID/编号/编码/code/序号/单号/号码/uuid/标识/键 等模式；
#   2. 高基数数值字段（唯一值数 ≈ 行数，如 user_id/score 类用户级 ID）。
_ID名称模式 = re.compile(
    r"(id|编号|编码|code|序号|单号|号码|代码|uuid|标识|键)$|^id[_]?",
    re.IGNORECASE,
)


def 标识符字段(画像: Dict) -> List[str]:
    """识别标识符/编码字段。命中的字段禁作 Y 轴/数值度量，仅可作 X 轴。

    规则：
    1. 字段名命中 ``_ID名称模式``；
    2. 画像提供 ``唯一值数`` 时，高基数数值字段（唯一值数 übige 行数，如
       user_id 类 9000/9000）视为标识符。
    """
    行数 = int(画像.get("行数") or 0) or 1
    唯一值数 = 画像.get("唯一值数") or {}
    结果: List[str] = []
    已见 = set()

    def _加(field: str) -> None:
        if field not in 已见:
            已见.add(field)
            结果.append(field)

    for field in 画像.get("字段列表", []) or []:
        if _ID名称模式.search(str(field)):
            _加(field)
            continue
        # 高基数数值标识符：唯一值数 ≈ 行数（≥95% 且绝对数足够大）
        uniq = 唯一值数.get(field)
        if isinstance(uniq, (int, float)) and uniq >= max(10, int(行数 * 0.95)):
            _加(field)
    return 结果


# ---- 编辑动作模型（白名单枚举） --------------------------------------------
# NL 指令与结构化面板归一化为同一编辑模型 dict：
#   {"动作": <动作枚举>, 对应参数...}
# 动作白名单（设计文档 4.1）：
_允许动作 = {
    "改标题", "改子标题", "改图例名称", "改备注",
    "换X轴", "换Y轴", "改X轴别名", "改Y轴别名", "改坐标轴范围",
    "切图表类型",
    "改系列颜色", "切换数据标签", "改图例位置",
    "切占比",         # 样本计数 / 数值加权
    "加筛选",
}

# 可切换的图表类型（柱↔折↔饼↔散点 + 面积/直方）——沿用生成器 图表类型映射 子集
from 后端_核心.report_generator import 图表类型映射

_允许图表类型 = {"柱状图", "折线图", "饼图", "散点图", "面积图", "直方图"}


def _类型中文转plotly(中文: str) -> str:
    """中文图表名 → plotly 类型（chart_config['类型'] 存的是 plotly 值）。"""
    return 图表类型映射.get(中文) or 中文

# 不改数据的纯展示类动作（只改 chart_config 展示字段，不触发重算）
_纯展示动作 = {
    "改标题", "改子标题", "改图例名称", "改备注",
    "改X轴别名", "改Y轴别名", "改坐标轴范围",
    "改系列颜色", "切换数据标签", "改图例位置",
}

# 需要数据重算的动作（回到数据集 parquet，本地 pandas 重算）
_重算动作 = {"换X轴", "换Y轴", "切图表类型", "切占比", "加筛选"}


def 编辑校验(编辑: Dict, 画像: Dict):
    """校验一个编辑动作。

    返回 (ok: bool, 拒绝原因: Optional[str])。
    - Y 轴禁区：标识符/编码字段禁作数值度量，仅可作分类 X 轴（约束 2）。
    - 不存在的字段 → 拒绝并说明。
    """
    动作 = 编辑.get("动作")
    if not 动作 or 动作 not in _允许动作:
        return False, f"不支持的编辑动作「{动作}」"

    if 动作 == "换Y轴":
        y = 编辑.get("Y轴", []) or []
        唯一约束字段 = _ID名称模式
        禁区 = set(标识符字段(画像))
        for f in y:
            if f in 禁区:
                return False, f"字段「{f}」是标识符/编码，禁止作为数值度量 Y 轴，仅能作分类 X 轴"
    elif 动作 == "换X轴":
        x = 编辑.get("X轴")
        if x is not None and x not in (画像.get("字段列表") or []):
            return False, f"字段「{x}」不存在于数据集中"
    elif 动作 == "切图表类型":
        t = 编辑.get("图表类型")
        if t not in _允许图表类型:
            return False, f"不支持的图表类型「{t}」，支持：{'、'.join(sorted(_允许图表类型))}"
    elif 动作 == "加筛选":
        cond = 编辑.get("筛选") or {}
        字段 = cond.get("字段")
        if 字段 not in (画像.get("字段列表") or []):
            return False, f"筛选字段「{字段}」不存在于数据集中"
    return True, None


def 应用编辑(chart_config: Dict, 编辑: Dict) -> Dict:
    """在既有 chart_config 上做纯 spec 层面的修改（不改 数据，仅改展示字段）。

    仅接受 ``_展示动作``；重算类动作由 :func:`重算图表数据` 处理。
    """
    new = dict(chart_config)
    动作 = 编辑.get("动作")
    if 动作 == "改标题":
        new["标题"] = 编辑.get("标题")
    elif 动作 == "改子标题":
        new["子标题"] = 编辑.get("子标题")
    elif 动作 == "改图例名称":
        new["图例名称"] = 编辑.get("图例名称")
    elif 动作 == "改备注":
        new["备注"] = 编辑.get("备注")
    elif 动作 == "改X轴别名":
        new["X轴别名"] = 编辑.get("别名")
    elif 动作 == "改Y轴别名":
        new["Y轴别名"] = 编辑.get("别名")
    elif 动作 == "改坐标轴范围":
        new["坐标范围"] = 编辑.get("范围")
    elif 动作 == "改系列颜色":
        new["系列颜色"] = 编辑.get("颜色")
    elif 动作 == "切换数据标签":
        new["显示数据标签"] = bool(编辑.get("显示", True))
    elif 动作 == "改图例位置":
        new["图例位置"] = 编辑.get("位置")
    elif 动作 == "切图表类型":
        new["类型"] = _类型中文转plotly(编辑.get("图表类型") or new.get("类型"))
    return new


# ---- NL 指令解析（轻量正则 + 画像字段名匹配） -----------------------------
# 编辑指令（如"把X轴换成行业 / 用标题改为… / 切换成饼图"）→ 结构化编辑模型。
# 识别不到动作 / 字段名不唯一 → 返回需确认（约束 3）。
# 不引入新 NLU 依赖；字段名用 field_selector._匹配意图字段。
_图表词 = {"直方图", "柱状图", "折线图", "饼图", "散点图", "面积图"}
_X模式 = re.compile(r"[Xx]\s*轴(?:换|改为|改成|设成)?[：:]?\s*([^\s,，。；、]+)")
_Y模式 = re.compile(r"[Yy]\s*轴(?:换|改为|改成|设成|为)?[：:]?\s*([^\s,，。；、]+)")
_类型模式 = re.compile(r"(?:切|换成|切换成|改成|变成|转为)(?:成|为)?\s*(柱状图|折线图|饼图|散点图|面积图|直方图)")
_标题模式 = re.compile(r"标题(?:改|给)?(?:为|成|成)?[：:]\s*(.+?)(?:[。；;]|$)")
_标题模式2 = re.compile(r"标题(?:改为|改成|叫|是)?[：:【\[]?\s*(\S+?)(?:】|\]|[。；;]|$)")

from 后端_核心.field_selector import _匹配意图字段


def _命中字段(关键词: str, 画像: Dict) -> Optional[str]:
    """把指令里的字段名映射到数据集中真实列名；命中才返回。"""
    # 直接命中
    for f in 画像.get("字段列表", []) or []:
        if str(f) == 关键词: 关键词 = f
        if 关键词 in str(f) or str(f) in 关键词:
            return f
    # 语义匹配兜底
    try:
        return _匹配意图字段(画像, [关键词], 关键词)
    except Exception:
        return None


def 解析编辑指令(文本: str, 画像: Dict):
    """NL 编辑指令 → (编辑模型, 需确认, 错误提示)。

    返回:
      - (dict, False, None)：解析成功
      - (None, True, 说明)：需向用户确认目标图表/参数（约束 3）
    """
    文本 = (文本 or "").strip()
    if not 文本:
        return None, True, "编辑指令为空，请描述要修改的内容"

    # 标题
    m = _标题模式2.search(文本)
    if m:
        return {"动作": "改标题", "标题": m.group(1).strip()}, False, None

    # 切图表类型
    m = _类型模式.search(文本)
    if m:
        t = m.group(1)
        if t.replace("图", "") in {"柱状", "折线", "饼", "散点", "面积", "直方"}:
            中文 = {"柱状": "柱状图", "折线": "折线图", "饼": "饼图", "散点": "散点图",
                 "面积": "面积图", "直方": "直方图"}[t.replace("图", "")]
            return {"动作": "切图表类型", "图表类型": 中文}, False, None

    # X 轴
    m = _X模式.search(文本)
    if m:
        f = _命中字段(m.group(1), 画像)
        if f:
            return {"动作": "换X轴", "X轴": f}, False, None
        return None, True, f"未能识别字段「{m.group(1)}」，请从数据集中选择或确认"

    # Y 轴
    m = _Y模式.search(文本)
    if m:
        f = _命中字段(m.group(1), 画像)
        if f:
            return {"动作": "换Y轴", "Y轴": [f]}, False, None
        return None, True, f"未能识别字段「{m.group(1)}」，请从数据集中选择或确认"

    return None, True, "未能理解编辑指令，请描述具体要修改的内容（如：把X轴换成地区 / 标题改为… / 切换成饼图），或使用编辑面板"


# ---- 本地重算（换轴 / 切占比 / 加筛选） ------------------------------------
# 回到报表关联数据集的原始 df，用既有画像 + 本地 pandas 重算新 数据。
# 不触发 Agent ReAct、不调外部工具/LLM（约束 1）。复用 report_generator._聚合数据。
from 后端_核心.report_generator import _聚合数据, _可_json行

_占比模式 = {"计数": "count", "数值": "sum"}
# chart_config["类型"] 存 plotly 值；饼类图表补 名称/值
_饼类 = {"pie", "donut"}


def _类型转换值(series, 值):
    """把筛选值转成与列类型匹配的类型（日期/数值/文本）。"""
    try:
        import pandas as pd
        if pd.api.types.is_numeric_dtype(series):
            return pd.to_numeric(值)
        return str(值)
    except Exception:
        return str(值)


def 求和聚合(y_valid: List[str]) -> str:
    return "求和" if y_valid else "计数"


def 重算图表数据(画像: Dict, df, 编辑: Dict, 原_chart: Dict):
    """对原始 df 本地重算，产出新 chart_config 的 数据（及轴/名称/值/占比）。

    返回 (新_chart_config, 说明)。
    仅处理重算类动作（换X轴/换Y轴/切图表类型/切占比/加筛选）。
    """
    动作 = 编辑.get("动作")
    新 = dict(原_chart)

    # ---- 1. 确定交换后的 x / y ----
    x = 新.get("X轴")
    y_list = list(新.get("Y轴", []) or [])
    if 动作 == "换X轴":
        x = 编辑.get("X轴")
    elif 动作 == "换Y轴":
        y_list = list(编辑.get("Y轴", []) or [])

    # ---- 2. 加筛选：对原始 df 行过滤（重算前，约束 6 确认：作用于原始 df） ----
    if 动作 == "加筛选":
        cond = 编辑.get("筛选") or {}
        字段, 值 = cond.get("字段"), cond.get("值")
        if 字段 and 字段 in df.columns:
            目标值 = _类型转换值(df[字段], 值)
            df = df[df[字段] == 目标值]

    # ---- 3. 占比模式（样本计数 / 数值加权） ----
    占比 = "数值"
    if 动作 == "切占比":
        占比 = 编辑.get("占比") or "计数"
    聚合方式 = _占比模式.get(占比, "count")

    # ---- 4. 聚合 ----
    y_valid = [y for y in y_list if y in df.columns]
    分组 = 新.get("颜色") or 新.get("分组字段")
    有效聚合方式 = "count" if 聚合方式 == "count" else 求和聚合(y_valid)
    report_df = _聚合数据(df, x, y_valid or ["记录数"], 分组, 有效聚合方式)
    report_rows = _可_json行(report_df)

    # ---- 5. 组装新 chart_config ----
    新["数据"] = report_rows
    新["X轴"] = x if x in df.columns else (df.columns[0] if len(df.columns) else None)
    if 聚合方式 == "count":
        新["Y轴"] = ["记录数"] if "记录数" in report_df.columns else (y_valid or ["记录数"])
        新["占比模式"] = "计数"
    else:
        新["Y轴"] = y_valid or ["记录数"]
        新["占比模式"] = "数值"

    # 图表类型：切类型动作用目标中文转 plotly；否则保留原类型
    if 动作 == "切图表类型":
        target = _类型中文转plotly(编辑.get("图表类型"))
    else:
        target = _类型中文转plotly(新.get("类型"))
    新["类型"] = target
    # 饼类：补 名称/值
    if target in _饼类:
        if 新.get("X轴"):
            新["名称"] = 新["X轴"]
        if 新.get("Y轴"):
            新["值"] = 新["Y轴"][0]

    说明 = f"已按 {新.get('X轴')} + {'、'.join(str(j) for j in 新.get('Y轴', []))} 本地重算（{新.get('占比模式')}）"
    return 新, 说明


# ---- 变更对比清单（旧配置 → 新配置） ----------------------------------------
_对比字段顺序 = ["标题", "子标题", "图表类型", "X轴", "Y轴", "分组字段", "颜色",
               "占比模式", "图例位置", "显示数据标签", "系列颜色", "数据"]


def 生成变更对比(旧配置: Dict, 新配置: Dict) -> List[Dict]:
    """输出「旧 → 新」变更清单（约束 4）。

    逐项对比展示字段：值有变化才列入；数据列只报行数变化（内容不具可比性）。
    """
    变更: List[Dict] = []
    # 展示字段 + 轴 + 类型
    for key in _对比字段顺序:
        if key == "数据":
            continue
        旧值 = 旧配置.get(key)
        新值 = 新配置.get(key)
        if 旧值 != 新值:
            变更.append({"字段": key, "旧": 旧值, "新": 新值})
    # 数据行数
    旧行 = len(旧配置.get("数据") or [])
    新行 = len(新配置.get("数据") or [])
    if 旧行 != 新行:
        变更.append({"字段": "数据", "旧": f"{旧行} 行", "新": f"{新行} 行"})
    # 类型中文可读化（plotly → 中文）
    for it in 变更:
        if it["字段"] == "图表类型":
            it["旧"] = _类型plotly转中文(it["旧"])
            it["新"] = _类型plotly转中文(it["新"])
    return 变更


def _类型plotly转中文(t) -> str:
    """plotly 值 → 中文图表名（变更清单人读友好）。"""
    for 中文, plotly in 图表类型映射.items():
        if plotly == t:
            return 中文
    return t if isinstance(t, str) else ""