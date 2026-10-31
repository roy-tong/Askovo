# website/ — GitHub Pages 站点（产品官网）

结构参照 verovo 的打法：**repo README 是落地页，本目录是接单页与 claims 信任页**，两者互相链接。纯静态、零依赖（不用 Google Fonts，国内可达）、无 JS、无表单后端（接单用 mailto 草稿模板）。

- `index.html` — 落地页：痛点句、七节点链、**今天可用什么（能力边界表）**、30 秒本地验证
- `first-look.html` — 接单页：五字段任务模板（mailto 草稿）、**逐案口径**（不公布标准价目）
- `claims.html` — 主张纪律：六类结论、测试证明什么、永远不做的推断、star 请求句（canonical，仅限三处：免费交付收尾 / 接单页 / 本页）
- `styles.css` / `assets/favicon.svg` / `robots.txt` / `sitemap.xml` / `llms.txt`

## 部署（一次性开通）

1. GitHub 仓库 → Settings → Pages → Source 选 **GitHub Actions**（`.github/workflows/pages.yml` 已就位，`website/**` 变更即部署）
2. 部署后地址：`https://roy-tong.github.io/Askovo/`
3. README 顶部已链接官网地址；部署前该链接 404 属预期

## 维护纪律

- **不公布价格**：任何价格数字不进本站；口径统一为"范围与费用按任务商定"（逐案报价，见 `marketing/commercialization-plan.md`）
- 每页页脚带"复核日期"，更新页面时同步改
- 新增页面时更新 `sitemap.xml` 与各页 nav
- 站内主张必须能在仓库 README/docs 找到对应表述，不造第二事实源
