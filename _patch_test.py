import pathlib
f = pathlib.Path(r'D:\python\agent\自助式数据分析Agent平台\tests\test_agent_意图.py')
src = f.read_text(encoding='utf-8')

# 替换 old: 编排器_mod.解析自然语言需求 → 编排Agent
# 还要确保保留的调用传入 enable_llm=False

rep = {
    '编排器_mod.解析自然语言需求': '编排器_mod.编排Agent',
    'assert 编排器_mod.解析自然语言需求("按地区看占比", ': 'assert 编排器_mod.编排Agent(',
    'assert 编排器_mod.解析自然语言需求("", ': 'assert 编排器_mod.编排Agent(',
    'assert 编排器_mod.解析自然语言需求("   ", ': 'assert 编排器_mod.编排Agent(',
    'assert 编排器_mod.解析自然语言需求("按地区看占比，换个折线图", ': 'assert 编排器_mod.编排Agent(',
    'assert 编排器_mod.解析自然语言需求(画像) is None)': 'assert 编排器_mod.编排Agent(画像) is None)'
}

for old, new in rep.items():
    src = src.replace(old, new)

# 对于未配置 key 那个，要传入 enable_llm=False 严格限定
src = src.replace(
    'assert 编排器_mod.编排Agent("按地区看占比", add_image_side) is None',
    'assert 编排器_mod.编排Agent("按地区看占比", 画像, enable_llm=False) is None'
)

f.write_text(src, encoding='utf-8')
print('patched test')