#!/usr/bin/env python3
"""Build review datasets and thesis templates from public trader signals."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Z][A-Z0-9]{0,6}(?:\.[A-Z]{1,4})?)(?![A-Za-z0-9_])")

THEME_KEYWORDS = {
    "ai_infrastructure": ["ai", "datacenter", "data center", "gpu", "accelerator", "capex", "cpo", "optical", "photonics", "hbm"],
    "semiconductor_supply_chain": ["semi", "semiconductor", "foundry", "packaging", "wafer", "substrate", "memory", "fab", "tsmc"],
    "growth_momentum": ["breakout", "base", "relative strength", "rs", "earnings", "sales growth", "leader", "leadership"],
    "technical_trading": ["vwap", "moving average", "ma", "trendline", "volume", "support", "resistance", "stop", "setup"],
    "macro_rates_liquidity": ["fed", "rates", "inflation", "liquidity", "dollar", "yield", "recession"],
    "crypto_market_structure": ["bitcoin", "btc", "eth", "onchain", "on-chain", "wallet", "miner"],
    "business_quality": ["revenue", "margin", "fcf", "retention", "unit economics", "guidance", "earnings call"],
}

EVIDENCE_KEYWORDS = {
    "customer_demand": ["customer", "demand", "order", "backlog", "design win", "qualification"],
    "capex": ["capex", "spending", "buildout", "capacity", "ramp"],
    "financial_inflection": ["revenue", "margin", "eps", "fcf", "guidance", "beat", "raise"],
    "technical_constraint": ["bottleneck", "chokepoint", "constraint", "scarce", "capacity", "yield", "qualified"],
    "price_volume": ["breakout", "volume", "rs", "relative strength", "squeeze", "base", "flag"],
    "policy": ["policy", "tariff", "export control", "subsidy", "regulation"],
}

RISK_KEYWORDS = ["risk", "downside", "wrong", "invalid", "stop", "dilution", "expensive", "competition", "customer concentration"]
CONVICTION_KEYWORDS = ["conviction", "favorite", "best", "mispriced", "undervalued", "asymmetric", "massive"]
FORWARD_HORIZONS = [1, 5, 20, 60, 120]


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_records(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv(path)
    if suffix == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ["tweets", "posts", "data", "items", "results"]:
                if isinstance(data.get(key), list):
                    return [x for x in data[key] if isinstance(x, dict)]
            return [data]
    if suffix in {".txt", ".md"}:
        rows = []
        chunks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig"))
        for i, chunk in enumerate(chunks, 1):
            text = chunk.strip()
            if text:
                rows.append({"post_id": str(i), "text": text})
        return rows
    raise ValueError(f"Unsupported input file: {path}")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def has_cashtag(text: str, ticker: str) -> bool:
    if not ticker:
        return False
    normalized = re.sub(r"\$\s+([A-Z])", r"$\1", text or "")
    return re.search(r"(?<![A-Za-z0-9_])\$" + re.escape(ticker) + r"(?![A-Za-z0-9_])", normalized) is not None


def get_first(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    value = value.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(value[:10], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return value[:10] if re.match(r"\d{4}-\d{2}-\d{2}", value) else ""


def safe_float(value: str) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def extract_cashtags(text: str) -> list[str]:
    text = re.sub(r"\$\s+([A-Z])", r"$\1", text or "")
    seen = set()
    out = []
    for match in CASHTAG_RE.finditer(text or ""):
        ticker = match.group(1).upper()
        if ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def infer_bucket(text: str, mapping: dict[str, list[str]], default: str = "other") -> str:
    lower = (text or "").lower()
    scores = Counter()
    for bucket, words in mapping.items():
        for word in words:
            if word in lower:
                scores[bucket] += 1
    return scores.most_common(1)[0][0] if scores else default


def infer_multi(text: str, mapping: dict[str, list[str]]) -> str:
    lower = (text or "").lower()
    found = []
    for bucket, words in mapping.items():
        if any(word in lower for word in words):
            found.append(bucket)
    return ";".join(found)


def calc_engagement(row: dict) -> str:
    fields = ["like_count", "likes", "favorite_count", "retweet_count", "retweets", "reply_count", "replies", "quote_count", "quotes"]
    return str(int(sum(safe_float(row.get(field, "")) for field in fields)))


def infer_ticker(row: dict) -> str:
    ticker = (row.get("ticker") or "").strip().upper()
    if ticker:
        return ticker
    text = f"{row.get('text', '')} {row.get('quoted_text', '')}"
    match = CASHTAG_RE.search(text)
    return match.group(1).upper() if match else ""


def extract(args: argparse.Namespace) -> None:
    posts = read_records(Path(args.posts))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    signals = []
    no_ticker_rows = []
    for idx, post in enumerate(posts, 1):
        text = get_first(post, ["text", "full_text", "tweet", "content", "body", "message"])
        quoted_text = get_first(post, ["quoted_text", "quote_text", "retweeted_text", "repost_text"])
        if not text and not quoted_text:
            continue
        created_at = parse_date(get_first(post, ["created_at", "date", "time", "timestamp", "published_at"]))
        post_id = get_first(post, ["post_id", "tweet_id", "id", "conversation_id"]) or str(idx)
        url = get_first(post, ["url", "tweet_url", "link", "permalink"])
        author = get_first(post, ["author", "username", "screen_name", "handle"]) or args.trader
        tickers = extract_cashtags(text)
        quote_tickers = [t for t in extract_cashtags(quoted_text) if t not in tickers]
        row_base = {
            "post_id": post_id,
            "created_at": created_at,
            "author": author,
            "url": url,
            "text": text,
            "quoted_author": get_first(post, ["quoted_author", "quote_author", "retweeted_author"]),
            "quoted_text": quoted_text,
            "theme": infer_bucket(f"{text} {quoted_text}", THEME_KEYWORDS),
            "evidence_types": infer_multi(f"{text} {quoted_text}", EVIDENCE_KEYWORDS),
            "supply_chain_role": "",
            "risk_markers": "risk_or_stop" if any(x in (text or "").lower() for x in RISK_KEYWORDS) else "",
            "conviction_score": "0.80" if any(x in (text or "").lower() for x in CONVICTION_KEYWORDS) else "0.50",
            "engagement_score": calc_engagement(post),
        }
        if not tickers and not quote_tickers:
            no_ticker_rows.append(dict(row_base, signal_id=f"{args.trader_slug}_{idx:06d}_theme", ticker=""))
            continue
        for ticker in tickers:
            signals.append(dict(row_base, signal_id=f"{args.trader_slug}_{idx:06d}_{ticker}", ticker=ticker))
        for ticker in quote_tickers:
            signals.append(dict(row_base, signal_id=f"{args.trader_slug}_{idx:06d}_QUOTE_{ticker}", ticker=ticker))
    write_csv(out_dir / "signals.csv", signals)
    write_csv(out_dir / "no_ticker_theme_posts.csv", no_ticker_rows)
    lines = [
        f"# Extract Summary",
        "",
        f"- trader: {args.trader}",
        f"- input posts: {len(posts)}",
        f"- signal rows: {len(signals)}",
        f"- no-ticker theme rows: {len(no_ticker_rows)}",
        f"- unique tickers: {len(set(r['ticker'] for r in signals if r.get('ticker')))}",
    ]
    (out_dir / "extract_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Extracted {len(signals)} signal rows into {out_dir / 'signals.csv'}")


def semantic_review(row: dict) -> dict:
    ticker = infer_ticker(row)
    text = row.get("text", "") or ""
    quoted = row.get("quoted_text", "") or ""
    lower = text.lower()
    in_main = has_cashtag(text, ticker)
    in_quote = has_cashtag(quoted, ticker)
    result = {
        "ticker": ticker,
        "ticker_in_main_text": "yes" if in_main else "no",
        "ticker_in_quoted_text": "yes" if in_quote else "no",
        "view_owner": "trader" if in_main else ("quoted_context" if in_quote else "none"),
        "timing_type": "unknown",
        "signal_type": "unknown",
        "review_decision": "deweight",
        "signal_weight": "0.50",
        "review_reason": "",
        "needs_followup": "no",
    }
    if not ticker and re.fullmatch(r"https?://\S+", text.strip()):
        result.update(view_owner="none", timing_type="link_only", signal_type="insufficient_text", review_decision="delete", signal_weight="0.00", review_reason="Only a link is present; no usable thesis text or ticker.")
        return result
    if in_quote and not in_main:
        result.update(view_owner="quoted_context", timing_type="quote_context", signal_type="quote_only_context", review_decision="delete_from_this_signal", signal_weight="0.00", review_reason="Ticker appears only in quoted text.")
        return result
    if any(token in lower for token in ["ytd:", " ytd", "called out", "do you remember", "100-1000%", "10x", "return %", "track record"]):
        result.update(view_owner="trader", timing_type="retrospective_performance_claim", signal_type="track_record_or_thesis_validation", review_decision="remove_from_forward_signal_keep_as_track_record_context", signal_weight="0.00", review_reason="Retrospective performance or thesis-validation post, not a new forward signal.")
    elif any(token in lower for token in ["crowdsourced", "will start doing dd", "need some more ideas", "watchlist", "radar"]):
        result.update(view_owner="trader_or_crowd", timing_type="pre_research_idea_sourcing", signal_type="watchlist_candidate", review_decision="deweight", signal_weight="0.25", review_reason="Candidate list or pre-DD idea; useful for attention mapping but not a strong thesis.", needs_followup="yes")
    elif any(token in lower for token in ["basket", "random", "stocks i like", "names i like", "ratings"]):
        result.update(view_owner="trader", timing_type="current_broad_list", signal_type="broad_basket_with_short_rationale", review_decision="keep_deweighted", signal_weight="0.55", review_reason="Broad list or basket with uneven single-name thesis quality.")
    elif any(token in lower for token in ["crashed today", "ended the day down", "flash crash", "here's why", "squeeze", "liquidation"]):
        result.update(view_owner="trader", timing_type="post_event_explainer", signal_type="market_structure_explanation", review_decision="keep_as_explainer_deweight", signal_weight="0.20", review_reason="Post-event explanation rather than an explicit forward thesis.")
    elif (
        any(token in lower for token in ["thesis:", "key proof", "proof point", "key idea", "framework", "deep dive"])
        and any(token in lower for token in ["risk", "constraint", "capacity", "execution", "margin", "adoption", "conversion", "revenue", "guidance", "ramp"])
    ):
        result.update(view_owner="trader", timing_type="active_thesis_or_update", signal_type="active_research_thesis", review_decision="keep", signal_weight="0.85", review_reason="Active research thesis with explicit mechanism, proof point, risk, or tracking variable.")
    elif any(token in lower for token in ["chokepoint", "bottleneck", "tam", "risk/reward", "supply chain", "qualified", "backlog", "barrier", "mispriced", "undervalued", "under appreciated", "dislocation"]):
        result.update(view_owner="trader", timing_type="active_thesis_or_update", signal_type="active_research_thesis", review_decision="keep", signal_weight="0.85", review_reason="Active thesis with mechanism, evidence, valuation gap, risk/reward, or chokepoint logic.")
    elif in_main:
        result.update(view_owner="trader", timing_type="current_or_event_context", signal_type="main_text_signal", review_decision="keep_deweighted", signal_weight="0.50", review_reason="Ticker appears in trader's own text, but the thesis is incomplete or generic.")
    return result


def auto_review(args: argparse.Namespace) -> None:
    rows = read_csv(Path(args.signals))
    reviewed = []
    for row in rows:
        out = dict(row)
        out.update(semantic_review(row))
        reviewed.append(out)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (Path(args.signals).stem + "_auto_reviewed.csv")
    write_csv(out_path, reviewed)
    write_review_summary(out_dir / (Path(args.signals).stem + "_review_summary.md"), reviewed, out_path.name)
    print(f"Reviewed {len(reviewed)} rows into {out_path}")


def write_review_summary(path: Path, rows: list[dict], output_name: str) -> None:
    counts = Counter(row.get("review_decision", "") for row in rows)
    lines = ["# Semantic Review Summary", "", f"- Input rows: {len(rows)}", f"- Output: `{output_name}`", "", "## Decision Counts"]
    lines += [f"- {decision}: {count}" for decision, count in counts.most_common()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def split(args: argparse.Namespace) -> None:
    rows = read_csv(Path(args.reviewed))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    forward = [r for r in rows if r.get("review_decision") in {"keep", "keep_deweighted", "deweight"}]
    high_quality = [r for r in rows if r.get("review_decision") == "keep"]
    removed = [r for r in rows if r.get("review_decision") in {"delete_from_this_signal", "remove_from_forward_signal_keep_as_track_record_context", "delete"}]
    explainer = [r for r in rows if r.get("review_decision") == "keep_as_explainer_deweight"]
    write_csv(out_dir / "signals_forward_clean.csv", forward)
    write_csv(out_dir / "signals_high_quality_thesis.csv", high_quality)
    write_csv(out_dir / "signals_removed_or_context.csv", removed)
    write_csv(out_dir / "signals_explainer_context.csv", explainer)
    lines = ["# Semantic Filter Summary", "", f"- all rows: {len(rows)}", f"- forward clean rows: {len(forward)}", f"- high-quality thesis rows: {len(high_quality)}", f"- removed/context rows: {len(removed)}", f"- explainer rows: {len(explainer)}", ""]
    for title, data in [("Forward Clean", forward), ("High Quality Thesis", high_quality), ("Removed Or Context", removed)]:
        lines += dataset_summary(title, data) + [""]
    (out_dir / "semantic_filter_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Split {len(rows)} rows into {out_dir}")


def dataset_summary(title: str, rows: list[dict]) -> list[str]:
    themes = Counter(r.get("theme", "") for r in rows)
    tickers = Counter(r.get("ticker", "") for r in rows if r.get("ticker"))
    lines = [f"## {title}", "", f"- rows: {len(rows)}", f"- unique tickers: {len(tickers)}", "", "### Top Themes"]
    lines += [f"- {k}: {v}" for k, v in themes.most_common(15)]
    lines += ["", "### Top Tickers"]
    lines += [f"- {k}: {v}" for k, v in tickers.most_common(25)]
    return lines


def template(args: argparse.Namespace) -> None:
    rows = read_csv(Path(args.signals))
    trader = args.trader
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_post = defaultdict(list)
    for row in rows:
        by_post[row.get("url") or row.get("text", "")[:160]].append(row)
    themes = Counter(r.get("theme", "") for r in rows)
    tickers = Counter(r.get("ticker", "") for r in rows if r.get("ticker"))
    evidence = Counter()
    roles = Counter()
    for row in rows:
        evidence.update([x for x in row.get("evidence_types", "").split(";") if x])
        roles.update([x for x in row.get("supply_chain_role", "").split(";") if x])
    lines = [
        f"# {trader} High-Quality Thesis Template",
        "",
        f"- thesis rows: {len(rows)}",
        f"- unique posts: {len(by_post)}",
        f"- unique tickers: {len(tickers)}",
        "",
        "## Dominant Themes",
    ]
    lines += [f"- {k}: {v}" for k, v in themes.most_common(12)]
    lines += ["", "## Dominant Tickers"]
    lines += [f"- {k}: {v}" for k, v in tickers.most_common(20)]
    lines += ["", "## Evidence Preferences"]
    lines += [f"- {k}: {v}" for k, v in evidence.most_common()]
    lines += ["", "## Role Preferences"]
    lines += [f"- {k}: {v}" for k, v in roles.most_common()]
    lines += [
        "",
        "## Reusable Thesis Template",
        "",
        "1. Start from the large demand wave or market regime.",
        "2. Map where the asset/company sits in the chain or structure.",
        "3. Explain why this position is a bottleneck, chokepoint, or mispriced constraint.",
        "4. Explain why the market has not priced it correctly yet.",
        "5. Attach evidence: customer demand, capex, technical constraints, financial inflection, policy, flows, or price/volume.",
        "6. Identify catalysts that could force repricing.",
        "7. State risks and falsifiers.",
        "8. Define tracking metrics for follow-up.",
        "",
        "## Prompt Template",
        "",
        f"Analyze [asset/company/theme] using {trader}'s high-quality thesis structure. Start from the demand wave, map the chain position, identify chokepoints or mispricing, cite evidence, list catalysts, risks, and follow-up metrics. Do not treat retrospective performance claims or quote-only mentions as new signals.",
    ]
    (out_dir / "high_quality_thesis_template.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_dir / 'high_quality_thesis_template.md'}")


def load_prices(path: Path) -> list[tuple[dt.date, float]]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            date = parse_date(get_first(row, ["date", "Date", "datetime", "time"]))
            close = get_first(row, ["close", "Close", "adj_close", "Adj Close", "adjclose"])
            if date and close:
                rows.append((dt.date.fromisoformat(date), float(close)))
    rows.sort()
    return rows


def max_drawdown(values: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return worst


def evaluate(args: argparse.Namespace) -> None:
    signals = read_csv(Path(args.signals))
    price_dir = Path(args.prices)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    price_cache: dict[str, list[tuple[dt.date, float]]] = {}
    rows = []
    for sig in signals:
        ticker = (sig.get("ticker") or "").strip().upper()
        date = parse_date(sig.get("created_at", ""))
        if not ticker or not date:
            continue
        price_path = price_dir / f"{ticker}.csv"
        if not price_path.exists():
            continue
        if ticker not in price_cache:
            price_cache[ticker] = load_prices(price_path)
        prices = price_cache[ticker]
        if not prices:
            continue
        post_date = dt.date.fromisoformat(date)
        idx = next((i for i, (d, _) in enumerate(prices) if d >= post_date), None)
        if idx is None:
            continue
        base_date, base_close = prices[idx]
        out = {
            "signal_id": sig.get("signal_id", ""),
            "ticker": ticker,
            "post_date": date,
            "base_date": base_date.isoformat(),
            "base_close": f"{base_close:.4f}",
            "review_decision": sig.get("review_decision", ""),
            "signal_weight": sig.get("signal_weight", ""),
        }
        for horizon in FORWARD_HORIZONS:
            if idx + horizon < len(prices):
                close = prices[idx + horizon][1]
                out[f"ret_{horizon}d"] = f"{close / base_close - 1:.4f}"
            else:
                out[f"ret_{horizon}d"] = ""
        window = [p for _, p in prices[idx:min(len(prices), idx + 121)]]
        out["max_drawdown_120d"] = f"{max_drawdown(window):.4f}" if window else ""
        rows.append(out)
    write_csv(out_dir / "signal_evaluation.csv", rows)
    write_evaluation_summary(out_dir / "signal_evaluation_summary.md", rows)
    print(f"Evaluated {len(rows)} signal rows into {out_dir / 'signal_evaluation.csv'}")


def write_evaluation_summary(path: Path, rows: list[dict]) -> None:
    lines = ["# Signal Evaluation Summary", "", f"- evaluated rows: {len(rows)}", ""]
    for horizon in FORWARD_HORIZONS:
        vals = [safe_float(r.get(f"ret_{horizon}d", "")) for r in rows if r.get(f"ret_{horizon}d", "") != ""]
        if not vals:
            lines.append(f"- {horizon}d: no data")
            continue
        vals_sorted = sorted(vals)
        median = vals_sorted[len(vals_sorted) // 2]
        win_rate = sum(1 for v in vals if v > 0) / len(vals)
        avg = sum(vals) / len(vals)
        lines.append(f"- {horizon}d: n={len(vals)}, avg={avg:.2%}, median={median:.2%}, win_rate={win_rate:.2%}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def download_prices(args: argparse.Namespace) -> None:
    import yfinance as yf

    rows = read_csv(Path(args.signals))
    counts = Counter((r.get("ticker") or "").strip().upper() for r in rows if r.get("ticker"))
    tickers = [ticker for ticker, _ in counts.most_common(args.limit)]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    for ticker in tickers:
        try:
            data = yf.download(ticker, start=args.start, end=args.end, progress=False, auto_adjust=False, threads=False)
            if data.empty:
                failures.append({"ticker": ticker, "reason": "empty"})
                continue
            out_path = out_dir / f"{ticker}.csv"
            data.reset_index().rename(columns={"Date": "date", "Close": "close"}).to_csv(out_path, index=False)
        except Exception as exc:  # noqa: BLE001
            failures.append({"ticker": ticker, "reason": str(exc)})
    write_csv(out_dir / "download_failures.csv", failures)
    print(f"Downloaded {len(tickers) - len(failures)} of {len(tickers)} tickers into {out_dir}")


def report(args: argparse.Namespace) -> None:
    signals = read_csv(Path(args.signals))
    evaluation = read_csv(Path(args.evaluation)) if args.evaluation and Path(args.evaluation).exists() else []
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    themes = Counter(r.get("theme", "") for r in signals)
    tickers = Counter(r.get("ticker", "") for r in signals if r.get("ticker"))
    decisions = Counter(r.get("review_decision", "") for r in signals)
    lines = [
        f"# {args.trader} Real-Data MVP Report",
        "",
        "## Boundary",
        "",
        "- This report analyzes public-post signals, not private P&L.",
        "- Quote-only, retrospective, paid-only, and private-context rows must be removed or deweighted before model conclusions.",
        "",
        "## Data Scale",
        "",
        f"- signal rows: {len(signals)}",
        f"- unique tickers: {len(tickers)}",
        f"- evaluated rows: {len(evaluation)}",
        "",
        "## Semantic Review",
        "",
    ]
    lines += [f"- {k or 'blank'}: {v}" for k, v in decisions.most_common()]
    lines += ["", "## Top Themes", ""]
    lines += [f"- {k or 'blank'}: {v}" for k, v in themes.most_common(15)]
    lines += ["", "## Top Tickers", ""]
    lines += [f"- {k}: {v}" for k, v in tickers.most_common(25)]
    if evaluation:
        lines += ["", "## Forward Return Summary", ""]
        for horizon in FORWARD_HORIZONS:
            vals = [safe_float(r.get(f"ret_{horizon}d", "")) for r in evaluation if r.get(f"ret_{horizon}d", "") != ""]
            if vals:
                vals_sorted = sorted(vals)
                lines.append(f"- {horizon}d: n={len(vals)}, avg={sum(vals)/len(vals):.2%}, median={vals_sorted[len(vals_sorted)//2]:.2%}, win_rate={sum(1 for v in vals if v > 0)/len(vals):.2%}")
    lines += [
        "",
        "## Serenity-Grade Gaps",
        "",
        "- Confirm whether the dataset includes replies and quote context.",
        "- Manually review the top 200 ambiguous or high-engagement rows.",
        "- Verify fake tickers, sarcasm, retrospective language, and quote ownership.",
        "- Re-run split, template, and evaluation after manual corrections.",
    ]
    (out_dir / "real_data_mvp_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_dir / 'real_data_mvp_report.md'}")


def init_run(args: argparse.Namespace) -> None:
    root = Path(args.out) / args.trader_slug
    for rel in ["sources", "outputs/raw_extract", "outputs/cleaned", "outputs/prices_yahoo_top40", "outputs/forward_clean_eval", "outputs/high_quality_eval"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {args.trader} Real-Data MVP Run",
        "",
        f"- trader: {args.trader}",
        f"- slug: {args.trader_slug}",
        f"- created_at: {dt.datetime.utcnow().replace(microsecond=0).isoformat()}Z",
        "",
        "## Serenity-Grade Acceptance Checklist",
        "",
        "- [ ] Public historical post dataset collected.",
        "- [ ] Source boundary documented.",
        "- [ ] `signals.csv` generated from real posts.",
        "- [ ] Quote/reply/retrospective semantic review completed.",
        "- [ ] Top 200 priority rows manually reviewed.",
        "- [ ] `signals_forward_clean.csv` generated.",
        "- [ ] `signals_high_quality_thesis.csv` generated.",
        "- [ ] Forward returns evaluated when price data is applicable.",
        "- [ ] High-quality thesis template generated.",
        "- [ ] Final MVP report written.",
    ]
    (root / "run_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Initialized {root}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init-run", help="Create a Serenity-grade real-run folder")
    p.add_argument("--trader", required=True)
    p.add_argument("--trader-slug", required=True)
    p.add_argument("--out", default="real_runs")
    p.set_defaults(func=init_run)
    p = sub.add_parser("extract", help="Extract signal rows from public post exports")
    p.add_argument("--posts", required=True)
    p.add_argument("--trader", required=True)
    p.add_argument("--trader-slug", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=extract)
    p = sub.add_parser("auto-review")
    p.add_argument("--signals", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=auto_review)
    p = sub.add_parser("split")
    p.add_argument("--reviewed", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=split)
    p = sub.add_parser("template")
    p.add_argument("--signals", required=True)
    p.add_argument("--trader", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=template)
    p = sub.add_parser("download-prices", help="Download Yahoo price files for top signal tickers")
    p.add_argument("--signals", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=download_prices)
    p = sub.add_parser("evaluate", help="Evaluate signal rows with local price CSVs")
    p.add_argument("--signals", required=True)
    p.add_argument("--prices", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=evaluate)
    p = sub.add_parser("report", help="Write a real-data MVP report")
    p.add_argument("--signals", required=True)
    p.add_argument("--trader", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--evaluation", default="")
    p.set_defaults(func=report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
