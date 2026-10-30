# 发布 askovo

本文件描述正式发布流程。代码通过测试不等于已经发布；GitHub 仓库元数据、Release、PyPI 和私密漏洞报告都需要在对应平台核验。

## 1. 先完成 canonical 仓库迁移

当前目标地址为 <https://github.com/roy-tong/askovo>。

1. 在 GitHub 将 `roy-tong/user-demand-research` 重命名为 `roy-tong/askovo`，不要新建一个没有历史的空仓库替代。
2. 确认旧 URL 会重定向，且以下地址全部可用：仓库页、raw logo、CI badge、Issues、Security Advisories。
3. 将 About 改为 askovo 的产品描述；SURE 只描述为底层研究引擎。更新 Topics、Homepage 和个人官网 `llms.txt` 中的旧链接。
4. 启用 Private Vulnerability Reporting，并实际确认 `security/advisories/new` 可用。
5. 迁移后更新本地 remote；使用仓库实际采用的 SSH alias 或 HTTPS，不要盲目覆盖其他机器的认证配置。

```bash
git remote set-url origin git@github.com:roy-tong/askovo.git
git ls-remote --symref origin HEAD
```

## 2. 准备候选版本

- 不移动已经公开的 tag。当前后续修复应发布为 **v2.0.1**，除非维护者另行决定语义化版本。
- 只修改 `VERSION` 作为版本事实源；同步合成样例中的 `method_version`。
- 将 `CHANGELOG.md` 的 `Unreleased` 内容整理到该版本，保持 1.x 历史中的旧 SURE 名称和命令不变。
- 确认工作树干净，所有评审、CI 和文档链接检查通过。

```bash
git status --short --branch
python3 -m unittest discover -s tests -v
python3 skills/askovo/scripts/askovo.py check examples/sample-study --stage full
python3 skills/askovo/scripts/askovo.py demo
python3 skills/askovo/scripts/askovo.py doctor
```

GitHub Actions 必须通过 Python 3.9、3.10、3.11、3.12 和 packaging job。不能只以本机单一 Python 版本代替矩阵。

## 3. 重跑文档中的首条成功路径

在干净临时目录执行 README/quickstart 的源码安装、`--dry-run`、`demo` 和 fixture 示例。fixture 使用合成数据；真实采集前必须先完成 design gate、scope、adapter 和平台权利审查。文档不得声称尚未发生的 PyPI 发布、文档站或托管能力已经存在。

## 4. 构建并检查最终产物

```bash
rm -rf build dist *.egg-info
python3 -m pip install build twine
python3 -m build
python3 -m twine check dist/*
python3 -m venv /tmp/askovo-release-venv
/tmp/askovo-release-venv/bin/pip install dist/*.whl
cd /tmp
/tmp/askovo-release-venv/bin/askovo --version
/tmp/askovo-release-venv/bin/askovo doctor
/tmp/askovo-release-venv/bin/askovo demo
/tmp/askovo-release-venv/bin/askovo-mcp --tools > /tmp/askovo-tools.json
```

检查 wheel/sdist：包含 runtime、VERSION、合成 sample、CHANGELOG、llms.txt 和社区/安全文档；不包含 `__pycache__`、`.pyc`、真实研究数据、凭据、queue.db 或已删除的 legacy `mcp_server.py`。核心 wheel 不需要 openpyxl/datasets；它们是可选工具依赖。

```bash
cd /path/to/askovo
shasum -a 256 dist/*
```

## 5. 发布 GitHub Release 与分发物

1. 在候选提交上创建一次 annotated tag：`git tag -a vX.Y.Z -m 'askovo vX.Y.Z'`。
2. 推送提交和 tag，等待对应 CI 全绿。
3. 创建 GitHub Release，使用人类可读的 CHANGELOG 摘要，上传已验证的 wheel/sdist 和 SHA-256 校验值。
4. 实测 Release 页面和产物下载，不以“tag 存在”代替 Release 核验。

PyPI 是可延后但不得虚假宣传的分发渠道。若发布 PyPI，使用 Trusted Publishing 或维护者凭据，先核对项目名归属，再上传同一批已验证产物；随后从干净的源码树外环境执行 `pipx install askovo` 和 `askovo demo`，此时才能把安装文档改成 PyPI 命令。

## 6. 发布后复核与回滚

- 复核 GitHub About、Topics、Release、Community Profile、Security 入口和旧 URL 重定向。
- 记录 wheel/sdist 安装与采用指标，不只用 star 判断发布效果。
- 文档或 CI 失败：停止推广，发布新的补丁版本；不要移动公开 tag。
- PyPI 严重问题：优先 yank 受影响版本并说明原因，再发补丁；不要假装旧版本从未存在。
- 安全漏洞：按 SECURITY.md 私下协调修复和披露，不在公开 Issue 泄露细节。
