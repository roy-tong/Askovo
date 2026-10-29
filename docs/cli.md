# CLI 参考

`sure` 的设计原则：**一个命令做一件事，JSON 可管道，退出码有语义。**

```bash
sure --version
sure --help
```

## 命令总览

| 命令 | 用途 | 退出码 |
| --- | --- | --- |
| `audit` | 全量审计 + 每条判断的结论（推荐入口） | 0/1/2 |
| `demo` | 在临时目录跑内置样例 | 0/1/2 |
| `plan` | 从目标生成研究工作区、配额、可行性、任务 | 0/2/3 |
| `init` | 从模板创建工作区（`plan` 的旧入口） | 0/2 |
| `check` | 只跑某一阶段的门禁 | 0/1/2 |
| `signals` | 计算确定性语料信号 | 0/2 |
| `lexicon` | 命名前研究的词表产出与充分性 | 0/1/2 |
| `report` | 组装研究状态报告 | 0/2 |
| `connectors` | 查看连接器审查结论 | 0/2 |
| `stage` | 转发到数据集工具箱脚本 | 透传 |

退出码含义：

| 码 | 含义 |
| --- | --- |
| 0 | 成功 / 门禁通过 |
| 1 | 门禁未过，或存在超出证据的判断（合法的研究状态） |
| 2 | 用法或环境错误 |
| 3 | 没有任何可行平台（`plan`；也是合法的研究状态） |

## demo

```bash
sure demo
```

把 `examples/sample-study` 复制到临时目录，跑一次完整审计并打印结论。不联网、不写仓库、可反复运行。

## audit

```bash
sure audit <study_dir> [--claim TEXT] [--json]
```

- 跑全量门禁（design + evidence + decision）
- 计算信号
- 对每条 demand judgment 给出 `supported` / `exceeds_evidence` / `open` / `rejected` / `deprioritized`
- 写 `05-audit/audit.json` 与 `05-audit/audit.md`

`--claim` 按 id、标题或状态做不区分大小写的过滤；不匹配返回 2。

`--json` 打印完整 JSON，适合管道。

## plan

```bash
sure plan <study_dir> \
  --goal "..." \
  --region cn|overseas|global \
  --sample-size 100000 \
  --platform-types forum,social,video \
  [--mode standard|unnamed-experience] \
  [--market us] [--languages en,zh] \
  [--time-window 2025-01-01:2026-08-31] \
  [--decision "..."] [--study-id ...] [--title ...]
```

- 目标目录必须不存在或为空，否则返回 2
- 无可行平台时仍会写出工作区与缺口，但返回 3
- `--mode unnamed-experience` 先做 grounding，再设计关键词路线

## init

```bash
sure init <study_dir> --study-id ... --title ... --decision ... [--platform reddit ...]
```

`plan` 已覆盖其能力，保留用于兼容和最小模板场景。

## check

```bash
sure check <study_dir> [--stage design|evidence|decision|full] [--write-report]
```

只跑门禁，不计算信号、不生成结论。`--write-report` 写 `05-audit/latest.json` 与 `latest.md`。

适合 CI：失败返回 1，输出 JSON 便于解析。

## signals

```bash
sure signals <study_dir>
```

计算并写 `04-findings/signals.json`：

- 记录数、去重率
- 证据等级分布
- 五类证据角色分布
- 角色 × 等级矩阵
- 来源族占比、主导来源
- 时间跨度与集中度
- 链条就绪度（problem/solution/commercial/counter）
- 门槛对照

## lexicon

```bash
sure lexicon <study_dir> [--min-per-term 20]
```

只用于 `--mode unnamed-experience` 的 study：计算词表产出、需求化石、充分性。存量不足返回 1。

## report

```bash
sure report <study_dir> [--output path.md]
```

组装 `06-report/report.md`。未通过全量检查时，报告顶部保留失败横幅，结论只停留在研究状态。

## connectors

```bash
sure connectors [--platform reddit] [--include-blocked]
```

列出连接器审查结论。默认隐藏 `blocked`；`--include-blocked` 可看到被拒绝的项目与原因。

## stage

```bash
sure stage <stage-name> [args...]
```

转发到 `skills/user-demand-research/scripts/stages/` 下的脚本，退出码原样透传。可用名称见 `scripts/stages/README.md`。

## 机器可读

所有命令都向 stdout 输出 JSON（`audit --json` 也是），错误写 stderr。适合：

```bash
sure audit ./study --json | jq '.claims[] | select(.verdict=="exceeds_evidence")'
```

## 环境变量

当前没有必需的环境变量。数据目录通过位置参数传入；不要依赖仓库相对路径，安装后 `sure` 会自己找到运行时。
