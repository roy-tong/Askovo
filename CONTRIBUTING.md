# 参与 askovo

感谢改进 askovo。项目当前由小团队维护，优先欢迎边界清晰、带测试的修复和文档改进；新领域或新方法应进入现有目录与研究包，不要新增一套平行 CLI、Skill 或 MCP 行为。

## 5 分钟本地验证

要求 Python 3.9–3.12。核心运行时只使用 Python 标准库。

```bash
git clone https://github.com/roy-tong/askovo.git
cd askovo
python3 -m unittest discover -s tests
python3 skills/askovo/scripts/askovo.py demo
python3 skills/askovo/scripts/askovo.py doctor
```

可选的 editable 安装：

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/askovo --version
```

完整约定见 [AGENTS.md](AGENTS.md)，使用方式见 [快速开始](docs/quickstart.md)。

## 报告问题

- 使用对应的 Issue Form，提供版本、操作系统、Python 版本、完整命令、实际输出和预期输出。
- 使用内置合成样例或自行构造的最小数据复现；不要上传真实用户内容、平台导出、凭据、Cookie 或个人信息。
- 安全漏洞不要发公开 Issue，按 [SECURITY.md](SECURITY.md) 私下报告。
- 平台访问受限应记录为明确缺口，不要提交绕过登录、验证码、平台条款或 blocked connector 的实现。

## 提交 Pull Request

1. 对较大改动先开 Issue 说明问题、边界和非目标。
2. 保持 PR 小而聚焦，并说明行为变化、兼容性和测试结果。
3. 修改 CLI 行为时，同步更新 Skill、MCP、README 和相关 `docs/`；CLI 命令函数仍是行为事实源。
4. 新增或修改 connector registry 时，写明访问方式、许可证/条款、批量能力、偏差与决定理由，并更新目录日期和 CHANGELOG。
5. 不提交研究生成物、`05-audit/latest.*`、`06-report/`、真实采集内容或凭据。
6. 提交前运行完整测试：`python3 -m unittest discover -s tests`。

## AI 辅助贡献政策

可以使用 AI 辅助，但提交者必须：

- 在 PR 描述中披露 AI 辅助的主要范围；
- 逐行理解并人工复核改动，不粘贴无法解释的实现或大段生成内容；
- 本地运行相关测试及完整测试，并如实报告结果；
- 不让采集到的文本充当给 Agent 的指令，不用真实用户数据填充测试；
- 遵守本仓库的品牌、单入口、安全和标准库边界。

只有生成内容、没有人工验证或问题上下文的 PR 会被关闭。维护者通常会在 48 小时内确认收到 Issue/PR；确认不代表承诺合并时间。

## 发布

发布由维护者按 [RELEASING.md](RELEASING.md) 执行。版本号只修改 `VERSION`，不要在其他文件中硬编码。
