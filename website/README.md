# website/ — GitHub Pages 站点（产品官网）

**产品首页已迁入 OVO 统一官网**（`https://roy-tong.github.io/ovo/`），本目录保留接单页、深度指南与 claims 信任页。统一官网集中维护产品、案例、Journal 与开始使用入口；本目录不再维护独立视觉首页。跳转页仅负责兼容旧链接，深度内容继续按原 URL 工作。

- `index.html` — 跳转至 OVO 统一官网；本目录的深度文档继续独立可用
- `first-look.html` — 接单页：五字段任务模板（mailto 草稿）、**逐案口径**（不公布标准价目）
- `claims.html` — 主张纪律：六类结论、测试证明什么、永远不做的推断、star 请求句（canonical，仅限三处：免费交付收尾 / 接单页 / 本页）
- `en/` — 英文镜像：六个页面同名同层级（`index.html`、`first-look.html`、`claims.html`、`faq.html`、`glossary.html`、`guides/need-validation.html`），`lang="en"`、独立 canonical；中英页面双向 `hreflang`（`zh-CN` / `en` / `x-default`→中文页），导航各有 `EN` / `中文` 切换
- `styles.css` / `assets/favicon.svg` / `robots.txt` / `sitemap.xml` / `llms.txt`

## 部署（一次性开通）

1. GitHub 仓库 → Settings → Pages → Source 选 **GitHub Actions**（`.github/workflows/pages.yml` 已就位，`website/**` 变更即部署）
2. 部署后地址：`https://roy-tong.github.io/Askovo/`
3. README 顶部已链接官网地址；部署前该链接 404 属预期

## 维护纪律

- **不公布价格**：任何价格数字不进本站；口径统一为"范围与费用按任务商定"（逐案报价，见 `marketing/commercialization-plan.md`）
- 每页页脚带"复核日期"，更新页面时同步改
- 新增页面时更新 `sitemap.xml` 与各页 nav
- 中英页面成对维护：改中文页的主张、数字或边界，必须同步改 `en/` 对应页；新增/改名页面时连同 `hreflang`、`EN`/`中文` 切换与 sitemap 一起改
- 站内主张必须能在仓库 README/docs 找到对应表述，不造第二事实源
