# AI 新闻聚合 · 自动 RSS

一个跑在 GitHub 上的自动新闻聚合器：GitHub Actions 每小时自动抓取 22 个 AI 信息源
（RSS 解析 + 网页抓取），把最新文章汇总成一个标准 RSS 文件 `feed.xml`，
通过 GitHub Pages 对外提供固定订阅地址。不需要服务器，不需要付费。

订阅地址（部署完成后）：
    https://<你的GitHub用户名>.github.io/ai-news-feed/feed.xml

## 部署步骤（约 5 分钟，只需做一次）

1. 在 GitHub 新建一个**公开**仓库，名字填 `ai-news-feed`，
   不要勾选 Add a README 等任何初始化选项，点 Create repository。
2. 在仓库页面点 Add file → Upload files，把本包里的全部内容拖进去：
   `aggregator.py`、`feed.xml`、`state.json`、`README.md` 和 `.github` 文件夹，
   然后点 Commit changes。
   （如果 `.github` 文件夹拖不上去：点 Add file → Create new file，
   文件名输入 `.github/workflows/feed.yml`，把包里 feed.yml 的内容粘贴进去提交。）
3. 开启 Pages：仓库 Settings → Pages → Build and deployment →
   Source 选「Deploy from a branch」，Branch 选 `main`、文件夹选 `/ (root)`，点 Save。
   等 1–2 分钟，订阅地址就生效了（见上方地址格式）。
4. 手动验证一次：仓库 Actions 标签 → 左侧「Update AI news feed」→ Run workflow。
   跑完后仓库里 feed.xml 的提交时间会更新，订阅地址打开能看到 RSS 内容即成功。
   之后每小时（第 17 分钟）自动更新，无需再管。

## 日常维护

- **改订阅源**：直接编辑 `aggregator.py` 里的 `SOURCES` 列表，一行一个源；
  行首加 `#` 即停用。掘金、千问、豆包、机器之心、新智元 5 个源是前端渲染/公众号，
  静态抓取拿不到，已在列表里注释保留，找到可用 RSS/镜像后去掉 `#` 即可启用。
- **立即更新**：Actions 页 Run workflow 手动触发，不必等整点。
- **原理**：`state.json` 记住了每篇文章的首次出现时间，所以老文章不会重复顶上来，
  新文章按时间排在最前；feed.xml 保留最新 100 条。

## 说明

- GitHub 免费账户的公开仓库 Actions 额度足够用（本任务每次约 1 分钟）。
- GitHub 定时任务偶尔会延迟几分钟到几十分钟，属平台惯例，不影响订阅使用。
