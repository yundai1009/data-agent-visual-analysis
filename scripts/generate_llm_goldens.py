# -*- coding: utf-8 -*-
# 一句话定位：测试基建脚本（阶段 50，非运行时路径）——用"脚本响应"冒充合规的 LLM 供应商，生成 VCR 黄金样本。
#
# 做了什么：先把 `LLM_VCR_RECORD` 置 1，再用 `importlib.util.spec_from_file_location` 从文件路径加载
# `tests/backend/test_llm_vcr.py`（模块名 `_vcr_test_source`），最后调 `模块.录制黄金样本(_SCENARIOS)`
# 跑 `react_multi_round`/`degrade_round1`/`tool_call_direct` 三个场景，把 cassette 落盘。
#
# 为什么这么做：
#   - 用脚本响应而非真实 LLM：CI 无 key 无网络，黄金样本必须离线确定、可复现；真实响应留给有 key 的机器另行录制覆盖。
#   - 按文件路径加载测试模块而不是 `import tests.backend.test_llm_vcr`：站点包里也有个 `tests`，且 pytest 侧导入名与本脚本导入名不一致，按路径加载才避得开命名冲突。
#   - 任一场景 0 条 cassette 就返回 1：宁可失败，也不产出"假绿"的空样本集。
#
# 关键约定与坑：
#   - `LLM_VCR_RECORD=1` 必须在加载测试模块之前设置（`LLMCassette` 在 `__init__` 时读取它）。
#   - 本脚本会覆盖 `tests/cassettes/` 下的黄金样本，跑完先看 `git diff tests/cassettes/` 再提交。
#   - 生成后应跑 `python -m pytest tests/backend/test_llm_vcr.py -q` 回放验证。
"""生成 LLM VCR 黄金样本（阶段 50）：用脚本响应替代真实 LLM，落盘 cassette。

背景
====
测试 tests/backend/test_llm_vcr.py 在回放模式下需要 tests/cassettes/<场景>/*.json；
本脚本用「脚本响应」模拟一个合规的 LLM 供应商，按真实请求指纹落盘，
让 CI（无 key、无网络）能离线回归 LLM 智能路径。

用法
====
    python scripts/generate_llm_goldens.py          # 生成/覆盖黄金样本
    python -m pytest tests/backend/test_llm_vcr.py  # 回放验证（应全绿）

真实录制（有 Key 的机器，覆盖黄金样本为真实模型响应）：
    LLM_VCR_RECORD=1 LLM_VCR_API_KEY=sk-xxx \
    python -m pytest tests/backend/test_llm_vcr.py
    # 录制后 git diff tests/cassettes/ 审查真实模型行为，再全量回归
"""

import importlib.util
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 录制模式开关（LLMCassette 在 __init__ 时读取）
os.environ["LLM_VCR_RECORD"] = "1"

# 从文件路径加载测试模块（避免站点包的 tests.* 命名冲突，
# 也避免 pytest 的 backend.* 导入名与脚本导入名不一致）
_测试模块路径 = PROJECT_ROOT / "tests" / "backend" / "test_llm_vcr.py"
_spec = importlib.util.spec_from_file_location("_vcr_test_source", _测试模块路径)
assert _spec and _spec.loader, f"无法加载测试模块：{_测试模块路径}"
模块 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(模块)

_SCENARIOS = ["react_multi_round", "degrade_round1", "tool_call_direct"]


def main() -> int:
    print(f"生成黄金样本（场景：{', '.join(_SCENARIOS)}）...")
    recorded = 模块.录制黄金样本(_SCENARIOS)
    ok = True
    for scenario, count in recorded.items():
        status = "[OK]" if count >= 1 else "[FAIL] 无 cassette"
        if count < 1:
            ok = False
        print(f"  {status} {scenario}: {count} 条 cassette")
    if not ok:
        print("失败：有场景未生成 cassette，请检查脚本响应是否被编排器消费。")
        return 1
    print("全部生成完毕。接着跑：python -m pytest tests/backend/test_llm_vcr.py -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())