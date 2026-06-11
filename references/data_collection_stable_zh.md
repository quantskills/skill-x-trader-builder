# 稳定数据采集指南（Stable Data Collection Guide）

本指南配合 `collectors/stable_collectors.py` 与 `collectors/browser_scroll_cdp.mjs` 使用，目标是把不同来源的公开帖子数据，归一化为 `scripts/x_trader_builder.py` 可直接消费的 `posts.csv` 契约（统一字段：`post_id, created_at, author, url, text, quoted_author, quoted_text, like_count, retweet_count, reply_count, quote_count, source, source_type, retrieved_at`）。

## 采集优先级

按稳定性与合规性从高到低，**能用上面的就不要用下面的**：

1. 官方 X API 导出 / 用户自有数据导出
2. Apify 等托管抓取服务的导出
3. Substack / 博客 RSS
4. 登出状态的公开首屏种子数据
5. 本地已登录浏览器的 CDP 滚动采集（兜底，按「不完整采集」对待）

依赖：Python 3.9+；`x-api-user-timeline` / `apify-x-profile` / 在线 `substack-rss` 需要 `requests`；`x-public-seed` 需要 `beautifulsoup4`。

## 子命令速查

### 1. normalize-export — 归一化现成导出

把 X API、Apify、twscrape 或归档工具的 CSV/JSON/JSONL 导出统一成 posts.csv（字段别名自动映射，如 `tweet_id`→`post_id`、`full_text`→`text`）：

```bash
python collectors/stable_collectors.py normalize-export \
  --input raw_export.json --out sources/posts_export.csv \
  --source "apify run 2026-06-11" --source-type managed_export --author crux_capital_
```

### 2. substack-rss — 抓取/解析 Substack RSS

```bash
python collectors/stable_collectors.py substack-rss \
  --feed https://cruxcapitalgroup.substack.com --out sources/posts_substack.csv \
  --author crux_capital_ --limit 100
# 本地 XML 文件也可作为 --feed 输入；TLS 证书异常时可加 --allow-insecure（仅限本地证书损坏场景）
```

### 3. x-api-user-timeline — 官方 X API v2 时间线

```bash
export X_BEARER_TOKEN=...   # 或用 --bearer-token 传入
python collectors/stable_collectors.py x-api-user-timeline \
  --username crux_capital_ --out sources/posts_api.csv --limit 100
```

### 4. apify-x-profile — 托管抓取（Apify actor）

```bash
export APIFY_TOKEN=...      # 或用 --token 传入
python collectors/stable_collectors.py apify-x-profile \
  --username crux_capital_ --out sources/posts_apify.csv \
  --actor apidojo/twitter-scraper --limit 1000 \
  --include-replies --include-quotes
```

### 5. x-public-seed — 登出公开首屏种子

只采集未登录状态可见的公开首屏内容，适合做小样本验证：

```bash
python collectors/stable_collectors.py x-public-seed \
  --username crux_capital_ --out sources/posts_seed.csv
```

### 6. merge — 合并去重

多来源合并，按 URL / post_id 去重：

```bash
python collectors/stable_collectors.py merge \
  --inputs sources/posts_api.csv sources/posts_apify.csv sources/posts_substack.csv \
  --out sources/posts.csv
```

## 兜底：浏览器 CDP 滚动采集

仅当用户本地浏览器已登录 X 时使用。先以调试端口启动 Edge/Chrome，再运行采集脚本：

```bash
# 1. 启动浏览器（示例：Edge）
msedge --remote-debugging-port=9222

# 2. 滚动采集（默认 CDP 端点 http://127.0.0.1:9222）
node collectors/browser_scroll_cdp.mjs \
  --profile crux_capital_ \
  --output sources/posts_browser.csv \
  --max-scrolls 80 --wait-ms 1600
# 可用 --start-url 指定已登录的搜索/个人页；--cdp 指定其他端点
```

注意：CDP 采集结果**默认视为不完整**，除非做了日期窗口限定并经过人工复核；合并进 `posts.csv` 时务必在 `source_type` 中保留 `browser_cdp` 标记。

## 采集记录要求

每次采集都要记录：数据来源、抓取日期（`retrieved_at` 字段自动写入）、覆盖缺口（缺哪些日期段、是否含回复/引用/转发）。这些信息将进入 `init-run` 生成的检查清单和最终 MVP 报告的「数据边界」章节。
