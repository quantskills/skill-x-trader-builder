---
name: x-trader-skill-builder
description: Build trader-specific research-model agent skills from public X/Twitter post datasets, exported timelines, saved threads, signal CSVs, and quote-aware review files. Use when an agent needs to reverse-engineer an X trader's investment logic, separate forward-looking thesis posts from quote-only or retrospective performance posts, generate clean signal datasets, derive a high-quality thesis template, or prepare a reusable trader-specific agent skill for platforms such as Claude Code, OpenClaw, Codex-style skill systems, or other local AI agent runtimes.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-x-trader-builder
  repository_url: https://github.com/quantskills/skill-x-trader-builder
  project_type: skill
  collection: trader-research-models
  license: GPL-3.0
---

# X Trader Skill Builder

Use this skill to turn a public trader post history into a reusable research model. It generalizes the Serenity MVP workflow: clean noisy public posts, label semantic intent, isolate forward-looking signals, extract high-quality thesis patterns, and prepare the ingredients for a trader-specific agent skill.

## Workflow

1. Initialize a real-data run folder.
   - Use `scripts/x_trader_builder.py init-run --trader "<name>" --trader-slug <slug> --out real_runs`.
   - This creates a Serenity-grade checklist and standard `sources/` and `outputs/` folders.

2. Collect public data.
   - Accept CSV, JSON, JSONL, TXT, or Markdown exports.
   - Prefer columns: `created_at`, `text`, `url`, `ticker`, `quoted_text`, `theme`, `evidence_types`, `supply_chain_role`, `engagement_score`.
   - Record data source, retrieval date, and missing coverage.
   - For stable collection and normalization, use `collectors/stable_collectors.py` and the guide `../DATA_COLLECTION_STABLE_zh.md`.
   - Prefer official API exports, user-owned exports, Apify/managed scraper exports, RSS feeds, and public article archives over DIY X page scraping.
   - If the user has already logged into X in a local browser, a browser-assisted fallback can be used with `collectors/browser_scroll_cdp.mjs`. Launch Edge/Chrome with a local CDP port, navigate logged-in X search/profile pages, and export visible posts into the same `posts.csv` contract. Treat this as a partial capture unless it is date-windowed and reviewed.

3. Extract raw public signals when only post exports are available.
   - Use `scripts/x_trader_builder.py extract --posts <posts.csv|json|jsonl|txt|md> --trader "<name>" --trader-slug <slug> --out <run>/outputs/raw_extract`.
   - This creates `signals.csv`, `no_ticker_theme_posts.csv`, and `extract_summary.md`.

4. Run semantic review.
   - Use `scripts/x_trader_builder.py auto-review --signals <signals.csv> --out <dir>`.
   - This labels rows as `keep`, `keep_deweighted`, `deweight`, `delete_from_this_signal`, `remove_from_forward_signal_keep_as_track_record_context`, `keep_as_explainer_deweight`, or `delete`.

5. Split the dataset.
   - Use `scripts/x_trader_builder.py split --reviewed <signals_auto_reviewed.csv> --out <dir>`.
   - Outputs:
     - `signals_forward_clean.csv`
     - `signals_high_quality_thesis.csv`
     - `signals_removed_or_context.csv`
     - `semantic_filter_summary.md`

6. Evaluate forward returns when price data is applicable.
   - Use `scripts/x_trader_builder.py download-prices --signals <signals_forward_clean.csv> --out <price_dir> --limit 40`.
   - Use `scripts/x_trader_builder.py evaluate --signals <signals_forward_clean.csv> --prices <price_dir> --out <run>/outputs/forward_clean_eval`.
   - Repeat with `signals_high_quality_thesis.csv` for high-quality thesis evaluation.

7. Derive the trader thesis template.
   - Use `scripts/x_trader_builder.py template --signals <signals_high_quality_thesis.csv> --trader "<name>" --out <dir>`.
   - The template should explain the trader's recurring thesis structure: starting trend, asset/supply-chain position, why mispriced, evidence, catalyst, risk, and tracking metrics.

8. Write the real-data MVP report.
   - Use `scripts/x_trader_builder.py report --signals <signals_auto_reviewed.csv> --evaluation <signal_evaluation.csv> --trader "<name>" --out <dir>`.
   - The report must state data scale, semantic-review counts, forward-return coverage, and remaining Serenity-grade gaps.

9. Build or upgrade the trader-specific agent skill only after review quality is acceptable.
   - Use the generated template and summaries as references.
   - Keep the trader-specific agent skill concise; do not bundle raw large datasets.
   - Follow `references/skill_output_contract.md` for generated skill structure.

## Interpretation Rules

- Treat public posts as research artifacts, not audited P&L.
- Separate a trader's own words from quoted text.
- Do not treat retrospective return claims as forward signals.
- Keep watchlists and crowdsourced lists, but deweight them.
- Keep broad baskets, but deweight single-ticker signal strength.
- Give highest weight to posts with mechanism, evidence, risk, and tracking logic.

## Git Hygiene

Generated CSVs, source checkouts, and price files are not skill dependencies. Keep large run artifacts out of the skill folder and usually out of Git. Upload concise Markdown reports, schemas, and scripts; store large data separately if needed.
