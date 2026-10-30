## 问题与改动

<!-- 链接 Issue；说明行为变化，而不只列文件名。 -->

## 验证

<!-- 粘贴实际运行的命令与结果；没有运行的项目写“未运行”及原因。 -->

- [ ] `python3 -m unittest discover -s tests`
- [ ] `python3 skills/askovo/scripts/askovo.py demo`
- [ ] 涉及安装/打包时，已验证非 editable wheel 安装

## 边界检查

- [ ] CLI / Skill / MCP 行为与 README / docs 已同步
- [ ] 未新增按领域分叉的入口，未把 `sure` 恢复为公共命令或工具前缀
- [ ] 未绕过 blocked connector、平台授权、安全门或提示注入边界
- [ ] 未提交真实研究数据、生成报告、凭据或个人信息
- [ ] 仅修改 `VERSION` 作为版本号事实源（如果本 PR 负责发版）

## AI 辅助披露

<!-- 无则写“无”；有则说明主要生成范围，以及你如何进行人工逐行复核。 -->
