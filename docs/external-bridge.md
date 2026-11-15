# 外部研究桥安全边界（External Bridge）

> 运行宿主提供的适配器是 Askovo 权限最高的一步。A-06 把它收成一条**可审计的子进程边界**：白名单环境、签名命令、有界输出流、独立运行 ID、输出路径不可逃逸、URL 只是候选。

`askovo external-research` 不导入外部框架、不联网。它执行一个经过人工 `--authorize` 的本地命令，把命令输出的 JSON 存成**候选来源**。边界实现在 `skills/askovo/scripts/external_bridge.py`，`sure_engine.cli_external_research` 只是 CLI 薄壳。

## 1. 边界一览

| 维度 | 规则 | 实现 |
| --- | --- | --- |
| 环境变量（A29） | 只传 `DEFAULT_ENV_ALLOWLIST` + 条目 `extra_env` + 4 个 `ASKOVO_*` 上下文；**从白名单构建**，不是继承全部再删 | `_build_env` |
| 命令（A30） | 只跑 `01-sources/external-research.json` 里登记的命令；条目必须有 `adapter`、`argv`、`sha256`、`access_basis`、`reviewed_at`、`reviewed_by` | `_entry_by_id` / `_validate_entry` |
| 适配器完整性（A30） | 适配器文件 SHA-256 必须与注册表一致，改一个字节就拒绝 | `_validate_entry` |
| 输出流（A31） | stdout 默认上限 256 KiB、stderr 64 KiB；超界 `RATE_LIMITED` **失败**，不截断成成功；调用方只能调低，不能调高 | `_effective_cap` |
| 运行 ID（A32） | `ext-<UTC 微秒>-<8 位随机>`，独占创建 `04-findings/external-research/<run_id>.json`，同秒两次运行都保留 | `run` |
| 输出路径（A30） | 解析后的绝对路径（含符号链接）必须落在 study 目录内；`..`、绝对路径越界、多级链接全拒 | `_resolve_output` |
| 来源（A33） | `url` 只接受 `http(s)`；记录 `evidence_level: null`、`status: candidate`、`url_verification: not_attempted`、`review_required: true`；**不抓取、不解析、不验证链接** | `_validate_payload` |

## 2. 命令

```bash
# 1) 登记一个经过评审的适配器（写进 study 的 01-sources/external-research.json）
cat > ./study/01-sources/external-research.json <<'JSON'
{
  "schema_version": "1.0",
  "updated_at": "2026-11-15",
  "commands": [
    {
      "id": "my-adapter",
      "label": "内部研究适配器",
      "adapter": "/abs/path/my_adapter.py",
      "argv": ["/usr/bin/python3", "/abs/path/my_adapter.py"],
      "sha256": "sha256:<适配器文件的 SHA-256>",
      "access_basis": "自建适配器；只读本地语料，无网络",
      "reviewed_at": "2026-11-15",
      "reviewed_by": "research-lead",
      "timeout_seconds": 120
    }
  ]
}
JSON

# 2) 运行（--authorize 是人工动作）
askovo external-research ./study --command my-adapter --authorize --json

# 3) 降低输出上限（只能调低）
askovo external-research ./study --command my-adapter --authorize \
  --max-stdout-bytes 65536 --max-stderr-bytes 16384
```

**`--trusted-local`（A-06 迁移开关）**：显式绕过注册表，运行任意 `--command`；仍必须同时给 `--authorize`。它的使用会写进运行记录（`trusted_local: true`、`command_sha256`、`notes` 首条警告），便于审计。**不要**把它写进脚本或 MCP 工具里。

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 运行完成，候选已保存 |
| 2 | 拒绝或输入错误：`AUTH_REQUIRED`（缺 `--authorize`）、`POLICY_DENIED`（未登记命令/哈希不符/路径逃逸）、`RATE_LIMITED`（输出超界）、`INPUT_REQUIRED`（输出不是合法 JSON 或 URL 非 http(s)）、`INTERNAL_ERROR`（命令非零退出/无法启动）、`INDETERMINATE_EXTERNAL_ACTION`（超时，外部效果未知，禁止自动重放） |

## 3. 注册表契约

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-11-15",
  "commands": [{
    "id": "my-adapter",
    "label": "内部研究适配器",
    "adapter": "/abs/path/my_adapter.py",
    "argv": ["/usr/bin/python3", "/abs/path/my_adapter.py"],
    "sha256": "sha256:…",
    "access_basis": "自建适配器；只读本地语料，无网络",
    "reviewed_at": "2026-11-15",
    "reviewed_by": "research-lead",
    "timeout_seconds": 120,
    "extra_env": ["MY_ADAPTER_TOKEN"]
  }]
}
```

- 六个必填字段（`id` / `adapter` / `argv` / `sha256` / `access_basis` / `reviewed_at` / `reviewed_by`）缺一即 `POLICY_DENIED`。
- `adapter` 必须是真实文件；`sha256` 与文件内容不一致即拒绝（防篡改）。
- `extra_env` 是**显式**放行的变量名；只有名字进入白名单，值来自父进程环境。运行记录只写键名，不写值。
- 注册表本身放在 study 里（随仓库评审、可 diff、可审计）。

## 4. 运行记录

`04-findings/external-research/<run_id>.json`：

| 字段 | 含义 |
| --- | --- |
| `schema` | 恒为 `askovo.external-research/1` |
| `run_id` / `started_at` / `finished_at` | 独立运行身份与时间 |
| `command_id` / `command_argv` / `command_sha256` / `trusted_local` | 跑了什么、是否绕过注册表 |
| `registry` | 使用的注册表路径（可回溯到评审记录） |
| `env_allowlist` / `env_keys` | 放行的变量名（**不含值**） |
| `limits` | 本次生效的 stdout/stderr/timeout 上限 |
| `exit_code` | 命令退出码（0） |
| `sources[]` | `{id, url, title, excerpt, claim, retrieved_at, evidence_level: null, status: "candidate", url_verification: "not_attempted"}` |
| `notes[]` | 适配器备注 + `--trusted-local` 警告 |
| `review_required` | 恒为 `true` |
| `evidence_grade_assigned` | 恒为 `false` |
| `network_attempted` | 恒为 `false` |
| `boundary` | 全局边界声明 |

## 5. 验收对照（AC A29–A33）

| AC | 落实 | 反例测试（真跑子进程） |
| --- | --- | --- |
| A29 | 子进程环境从白名单构建；父进程的 `ASKOVO_TEST_SECRET_*` 读不到；`extra_env` 需显式登记；运行记录只写键名 | `test_child_cannot_read_unauthorized_env_secret` / `test_env_is_built_from_the_allowlist_not_inherited` / `test_registry_can_allow_one_extra_variable_explicitly` |
| A30 | 未登记命令、哈希不符、缺 `access_basis` 全部 `POLICY_DENIED`；`..`、绝对路径越界、符号链接逃逸全部拒绝 | `test_unregistered_command_is_refused` / `test_tampered_adapter_hash_is_refused` / `test_parent_traversal_output_is_refused` / `test_absolute_output_outside_study_is_refused` / `test_symlink_escape_is_refused` |
| A31 | stdout 超 400 KB、stderr 超 200 KB 都 `RATE_LIMITED` 且**不留记录**；上限只能调低 | `test_oversized_stdout_fails_clearly` / `test_oversized_stderr_fails_clearly` / `test_cap_can_only_be_lowered` |
| A32 | 同一秒两次运行 → 两个不同 `run_id`、两个文件、都可读 | `test_two_runs_in_the_same_second_do_not_overwrite` / `test_run_record_carries_the_run_identity` |
| A33 | `evidence_level: null` + `candidate` + `url_verification: not_attempted`；`socket` 与 `urllib.request.urlopen` 被替换为抛错时仍成功 | `test_urls_stay_candidates` / `test_no_network_is_attempted` / `test_non_http_url_is_refused` |

## 6. 破坏性变更与迁移（v1.1 / A-06）

**变更**：`askovo external-research --command "<任意命令>"` 不再默认可用；默认只接受注册表里的命令 id。

**原因**：PRD §3 A-06 要求"允许命令白名单/明确签署路径"，任意 `--command` 就是没有边界。

**迁移**（三选一）：

1. **推荐**：把适配器登记进 `01-sources/external-research.json`（六个必填字段），然后用 `--command <id>` 运行。
2. **一次性本机工作流**：加 `--trusted-local`（同时仍需 `--authorize`）。运行记录会标 `trusted_local: true` 并带警告。
3. **不确定**：先跑 `askovo external-research ./study --command <id> --authorize`，被拒绝时 JSON 里的 `suggestion` 会给出注册表路径与字段要求。

已有调用方（含测试）需要在命令后补 `--trusted-local` 才能保持旧的任意命令行为；仓库内 `tests/test_askovo_modes.py::test_external_research_stores_candidates_only` 已按此迁移，断言语义未变。

## 7. 边界

- 桥只保证"子进程边界"，不保证适配器本身可信：`--authorize` 是人对适配器的背书，注册表 hash 只保证评审后没被改过。
- `--trusted-local` 是**逃生舱**，不是默认路径；它让任意命令以当前用户权限运行，必须由人逐次确认。
- URL 只是指向：不抓取、不解析、不验证可达性，也不证明源内容真实（A33）。
- 候选仍未定级、未与需求判断相连；只有人工把来源映射到研究问题后才可能成为证据。
- 超时视为 `INDETERMINATE_EXTERNAL_ACTION`：外部效果未知，禁止自动重放。
- 没有沙箱/容器隔离：子进程继承当前用户权限。真正不可信的适配器应放进容器或独立账号运行，本工单不提供该能力。

## 8. 与其他文档的关系

- [CLI 参考](cli.md)：`external-research` 的参数与退出码。
- [SURE 引擎](sure-engine.md)：引擎与外部适配器的关系边界。
- [数据契约](data-contract.md)：候选来源的写入位置与证据等级归属。
- [平台与连接器](connectors.md)：被阻断的来源路线与合规要求。
