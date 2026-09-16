# AGENTS.md — 项目上下文（从 Reasonix 迁移）

## 项目信息
- **项目名称**：自助式数据分析 Agent 平台
- **路径**：`D:\python\数据分析agent\自助式数据分析Agent平台`
- **Git 仓库**：remote 走 SSH-443（ssh://git@ssh.github.com:443/yundai1009/data-agent-visual-analysis.git）
- **当前状态**：批1+2+3 全部完成 push、测试 178 全绿，批4 待做
- **技能**：Python 3.11.9 + Node.js + npm

## 开发日志规范
在 `自助式数据分析Agent平台` 里做功能、架构、前端、后端、测试或文档改动后，同步更新项目日志，记录日期、背景、改动内容、技术取舍、验证命令、面试可讲点和后续计划。优先维护 `docs/项目开发日志.md`。
**双写规则**：每次在 `docs/开发日志/项目开发日志.md` 补写新阶段后，必须同步把相同内容追加到 `D:\python\数据分析agent\求职学习资料\项目开发日志.docx`（用 python-docx 写入），且 commit 后必须 `git push` 到 GitHub（SSH-443 通道）。

## 常用命令
```bash
# Python 测试
python -m pytest tests/ -v

# 前端测试
npm --prefix frontend test

# 前端 lint（注意限定 src，dist 有噪音）
npx oxlint src

# Git 状态
git status --short
git log --oneline -5
```

## 环境注意
- 无 docker；测试用 `python -m pytest` 与 `npm --prefix frontend test`
- 前端 lint 必须限定 `npx oxlint src`（dist 产物有噪音）
- 中文文件名/路径 + PowerShell：行内 python -c 引号转义易错，复杂逻辑写临时脚本
- 沙箱：write_file 仅限 workspace 内

## 项目权限（从 reasonix.toml 迁移）
- `Bash(dir)` — 允许目录列出
- `Bash(dir C:\\Users\\26805\\Desktop\\简历\\自助式数据分析Agent平台\\后端_核心:*)` — 允许后端核心目录列出
