# X Trader Skill Builder

> Turn a public X/Twitter trader history into a reusable research-model skill for agent platforms.

> 将公开的 X/Twitter 交易员历史内容，转化为可复用的“交易员研究模型 Skill”，可迁移到 Claude Code、OpenClaw 等 Agent 平台。

Language / 语言： [English](#english) | [中文](#中文)

## English

### What This Is

`x-trader-skill-builder` is a portable agent skill for reverse-engineering public trader research behavior from X/Twitter post datasets.

It is designed as a platform-agnostic workflow that can be imported or adapted into agent environments such as Claude Code, OpenClaw, Codex-style skill systems, or other local AI agent runtimes.

It helps separate real forward-looking research from noisy public-post artifacts such as:

- quoted posts from other accounts
- retrospective performance claims
- broad watchlists
- crowdsourced idea lists
- link-only posts
- post-event explanations
- marketing-style track-record posts

The goal is not to prove a trader's private P&L. The goal is to extract a reusable research model:

- What does this trader look for?
- What counts as a high-quality thesis?
- What evidence do they rely on?
- What risks do they acknowledge?
- Which posts should be ignored or deweighted?
- Can their style be turned into a trader-specific agent skill?

### Why It Matters

Popular X traders often mix several types of content:

- original research
- replies
- quotes
- jokes
- retrospective victory laps
- public watchlists
- real thesis posts

If all mentions are treated equally, the resulting model is polluted.

This skill creates a cleaner pipeline:

1. Review and label public post signals.
2. Remove quote-only and retrospective noise.
3. Split forward-looking signals from background context.
4. Extract high-quality thesis patterns.
5. Produce a template for building a trader-specific agent skill.

### Main Workflow

Initialize a real-data run:

```powershell
python .\scripts\x_trader_builder.py init-run `
  --trader "Trader Name" `
  --trader-slug trader_slug_yyyymmdd `
  --out .\real_runs
```

Normalize stable collection outputs before extraction:

```powershell
python .\collectors\stable_collectors.py normalize-export `
  --input .\sources\apify_export.json `
  --out .\sources\x_posts.csv `
  --source "apify run id or X API query" `
  --source-type apify_x_profile `
  --author "Trader Name"

python .\collectors\stable_collectors.py substack-rss `
  --feed https://example.substack.com/feed `
  --out .\sources\substack_posts.csv `
  --author "Trader Name"
```

See `DATA_COLLECTION_STABLE_zh.md` at the repository root for the recommended collection stack.

If you have a public post export, extract first-pass signals:

```powershell
python .\scripts\x_trader_builder.py extract `
  --posts .\posts.csv `
  --trader "Trader Name" `
  --trader-slug trader_slug_yyyymmdd `
  --out .\real_runs\trader_slug_yyyymmdd\outputs\raw_extract
```

```powershell
python .\scripts\x_trader_builder.py auto-review `
  --signals .\signals.csv `
  --out .\outputs
```

This generates semantic labels such as:

- `keep`
- `keep_deweighted`
- `deweight`
- `delete_from_this_signal`
- `remove_from_forward_signal_keep_as_track_record_context`
- `keep_as_explainer_deweight`
- `delete`

Then split the reviewed dataset:

```powershell
python .\scripts\x_trader_builder.py split `
  --reviewed .\outputs\signals_auto_reviewed.csv `
  --out .\outputs
```

Then derive a high-quality thesis template:

```powershell
python .\scripts\x_trader_builder.py template `
  --signals .\outputs\signals_high_quality_thesis.csv `
  --trader "Trader Name" `
  --out .\outputs
```

When price data is relevant, evaluate public forward returns:

```powershell
python .\scripts\x_trader_builder.py download-prices `
  --signals .\outputs\signals_forward_clean.csv `
  --out .\outputs\prices_yahoo_top40 `
  --limit 40

python .\scripts\x_trader_builder.py evaluate `
  --signals .\outputs\signals_forward_clean.csv `
  --prices .\outputs\prices_yahoo_top40 `
  --out .\outputs\forward_clean_eval
```

Write the MVP report:

```powershell
python .\scripts\x_trader_builder.py report `
  --signals .\outputs\signals_auto_reviewed.csv `
  --evaluation .\outputs\forward_clean_eval\signal_evaluation.csv `
  --trader "Trader Name" `
  --out .\outputs
```

### Quick Smoke Test

This repository includes a tiny sample file:

```powershell
python .\scripts\x_trader_builder.py auto-review `
  --signals .\scripts\sample_signals.csv `
  --out .\sample_outputs
```

The sample is only for verifying the pipeline shape. It is not a real trader dataset.

### Outputs

Typical outputs include:

- `extract_summary.md`
- `signals_auto_reviewed.csv`
- `signals_forward_clean.csv`
- `signals_high_quality_thesis.csv`
- `signals_removed_or_context.csv`
- `semantic_filter_summary.md`
- `high_quality_thesis_template.md`
- `signal_evaluation.csv`
- `signal_evaluation_summary.md`
- `real_data_mvp_report.md`

### Input Data

Preferred input columns:

- `created_at`
- `author`
- `url`
- `ticker`
- `text`
- `quoted_author`
- `quoted_text`
- `theme`
- `evidence_types`
- `supply_chain_role`
- `risk_markers`
- `conviction_score`
- `engagement_score`

Minimum usable input:

- post text
- ticker column or `$CASHTAG` mentions in the text

### What This Does Not Do

This skill does not:

- verify private trading profits
- scrape private or restricted X data
- provide financial advice
- automatically recommend trades
- treat public claims as audited performance

### Repository Hygiene

Do not commit large raw datasets, cloned source repositories, or price-history files into the skill folder.

Recommended to commit:

- `SKILL.md`
- `scripts/`
- `references/`
- `agents/openai.yaml`
- this `README.md`

Recommended to keep out of Git:

- raw X exports
- large CSV outputs
- downloaded price data
- cloned third-party repositories

---

## 中文

### 这是什么

`x-trader-skill-builder` 是一个通用 Agent 平台 Skill，用来从公开的 X/Twitter 交易员历史内容中，反推出这个交易员的研究模型。

它不是某一个平台的专属能力，而是一套可迁移的工作流，可以导入或改造到 Claude Code、OpenClaw、Codex 风格 Skill 系统，以及其他本地 AI Agent 运行环境。

它解决的核心问题是：公开推文里噪声很多，不能把所有 ticker 提及都当成有效信号。

常见噪声包括：

- 引用别人推文里的 ticker
- 事后收益复盘
- 历史命中宣传
- 宽泛股票清单
- 众包候选名单
- 纯链接
- 事件发生后的解释
- 调侃、免责声明、弱观点

这个 skill 的目标不是证明某个交易员真实赚了多少钱，而是提取他的研究方法：

- 他真正关注什么？
- 什么样的帖子算高质量 thesis？
- 他依赖哪些证据？
- 他怎么判断风险？
- 哪些内容应该删除或降权？
- 能否把他的风格做成一个专属 Agent Skill？

### 为什么有意义

很多 X 交易员的内容混在一起：

- 真正的原创研究
- 回复
- 引用
- 玩笑
- 复盘
- watchlist
- 业绩宣传
- 强 thesis

如果把所有内容都当成信号，模型会被污染。

这个 skill 提供了一条更干净的流程：

1. 给公开推文信号打语义标签。
2. 剔除 quote-only 和事后复盘污染。
3. 分离前瞻信号和背景材料。
4. 提取高质量 thesis。
5. 生成这个交易员的研究模板。
6. 为后续生成交易员专属 Agent Skill 做准备。

### 主要流程

第一步，自动语义复核：

```powershell
python .\scripts\x_trader_builder.py auto-review `
  --signals .\signals.csv `
  --out .\outputs
```

它会生成这些标签：

- `keep`：高质量主动 thesis
- `keep_deweighted`：保留但降权，通常是宽泛清单或普通正文提及
- `deweight`：候选池、watchlist、未完成 DD
- `delete_from_this_signal`：ticker 只出现在引用文本里
- `remove_from_forward_signal_keep_as_track_record_context`：事后收益复盘，只作背景
- `keep_as_explainer_deweight`：事件解释，低权重保留
- `delete`：纯链接或无效内容

第二步，切分数据集：

```powershell
python .\scripts\x_trader_builder.py split `
  --reviewed .\outputs\signals_auto_reviewed.csv `
  --out .\outputs
```

第三步，反推高质量 thesis 模板：

```powershell
python .\scripts\x_trader_builder.py template `
  --signals .\outputs\signals_high_quality_thesis.csv `
  --trader "交易员名称" `
  --out .\outputs
```

### 快速试运行

仓库里带了一个很小的样例文件：

```powershell
python .\scripts\x_trader_builder.py auto-review `
  --signals .\scripts\sample_signals.csv `
  --out .\sample_outputs
```

这个样例只用来验证流程，不是真实交易员数据。

### 输出文件

常见输出包括：

- `signals_auto_reviewed.csv`：全量语义复核版
- `signals_forward_clean.csv`：剔除引用和复盘后的前瞻信号
- `signals_high_quality_thesis.csv`：只保留高质量 thesis
- `signals_removed_or_context.csv`：删除或仅作背景的内容
- `semantic_filter_summary.md`：切分统计
- `high_quality_thesis_template.md`：交易员研究模板

### 输入数据格式

推荐字段：

- `created_at`
- `author`
- `url`
- `ticker`
- `text`
- `quoted_author`
- `quoted_text`
- `theme`
- `evidence_types`
- `supply_chain_role`
- `risk_markers`
- `conviction_score`
- `engagement_score`

最低可用字段：

- 推文正文 `text`
- `ticker` 字段，或者正文里的 `$CASHTAG`

### 它不做什么

这个 skill 不做：

- 不验证交易员真实收益
- 不抓取私有或受限 X 数据
- 不提供投资建议
- 不自动推荐买卖
- 不把公开收益声明当成审计业绩

### GitHub 上传建议

建议上传：

- `SKILL.md`
- `scripts/`
- `references/`
- `agents/openai.yaml`
- `README.md`

不建议上传：

- 原始 X 导出大文件
- 大型 CSV 输出
- 下载的价格数据
- 克隆下来的第三方仓库

### 一句话总结

`x-trader-skill-builder` 不是“跟单工具”，而是一个“交易员研究方法逆向工程工具”。

它把一个交易员公开历史内容中的噪声剔除掉，留下真正可复用的研究结构，再把这个结构变成后续 Agent Skill 生成的基础。
