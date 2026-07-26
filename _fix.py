import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open('后端_核心/上传报表生成器.py', 'r', encoding='utf-8') as f:
    s = f.read()
old = 'agent_result["意图来源"], agent\n'
new = 'agent_result["意图来源"], agent_result["Agent_Trace"]\n'
count = s.count(old)
s = s.replace(old, new)
with open('后端_核心/上传报表生成器.py', 'w', encoding='utf-8') as f:
    f.write(s)
print(f'fixed {count} occurrence(s)')