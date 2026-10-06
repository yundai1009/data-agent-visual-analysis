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