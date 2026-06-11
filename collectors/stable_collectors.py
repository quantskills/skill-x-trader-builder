#!/usr/bin/env python3
"""Stable-ish data collection normalizers for trader skill MVP runs.

This module intentionally avoids brittle X.com page scraping. Prefer official
exports, X API exports, Apify/managed scraper exports, RSS feeds, and user-owned
archives, then normalize them into the post CSV contract used by
scripts/x_trader_builder.py.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


FIELD_ALIASES = {
    "post_id": ["post_id", "tweet_id", "id", "id_str", "conversation_id", "status_id"],
    "created_at": ["created_at", "date", "time", "timestamp", "published_at", "createdAt"],
    "author": ["author", "username", "screen_name", "handle", "userName", "user_name"],
    "url": ["url", "tweet_url", "link", "permalink", "postUrl", "twitterUrl"],
    "text": ["text", "full_text", "tweet", "content", "body", "message", "fullText"],
    "quoted_author": ["quoted_author", "quote_author", "quotedUser", "quoted_user"],
    "quoted_text": ["quoted_text", "quote_text", "quotedText", "quoted_status_text"],
    "like_count": ["like_count", "likes", "favorite_count", "favoriteCount", "likeCount"],
    "retweet_count": ["retweet_count", "retweets", "retweetCount"],
    "reply_count": ["reply_count", "replies", "replyCount"],
    "quote_count": ["quote_count", "quotes", "quoteCount"],
}

OUTPUT_FIELDS = [
    "post_id",
    "created_at",
    "author",
    "url",
    "text",
    "quoted_author",
    "quoted_text",
    "like_count",
    "retweet_count",
    "reply_count",
    "quote_count",
    "source",
    "source_type",
    "retrieved_at",
]


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_jsonish(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["data", "items", "tweets", "posts", "results", "records"]:
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
        return [data]
    return []


def first(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def parse_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    value = value.replace("Z", "+00:00")
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(value[:31], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}", value)
        return match.group(0) if match else ""


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    if BeautifulSoup is not None:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    else:
        text = re.sub(r"<[^>]+>", " ", text).strip()
    return re.sub(r"\$\s+([A-Z])", r"$\1", text)


def normalize_rows(rows: list[dict], source: str, source_type: str, default_author: str = "") -> list[dict]:
    retrieved_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    out = []
    for idx, row in enumerate(rows, 1):
        normalized = {field: "" for field in OUTPUT_FIELDS}
        for field, aliases in FIELD_ALIASES.items():
            normalized[field] = first(row, aliases)
        normalized["post_id"] = normalized["post_id"] or str(idx)
        normalized["created_at"] = parse_date(normalized["created_at"])
        normalized["author"] = normalized["author"] or default_author
        normalized["text"] = strip_html(normalized["text"])
        normalized["quoted_text"] = strip_html(normalized["quoted_text"])
        normalized["source"] = source
        normalized["source_type"] = source_type
        normalized["retrieved_at"] = retrieved_at
        if normalized["text"] or normalized["quoted_text"]:
            out.append(normalized)
    return out


def normalize_export(args: argparse.Namespace) -> None:
    in_path = Path(args.input)
    suffix = in_path.suffix.lower()
    if suffix == ".csv":
        rows = read_csv(in_path)
    elif suffix in {".json", ".jsonl"}:
        rows = read_jsonish(in_path)
    else:
        raise SystemExit(f"Unsupported export format: {in_path}")
    normalized = normalize_rows(rows, args.source or str(in_path), args.source_type, args.author)
    write_csv(Path(args.out), normalized)
    print(f"Normalized {len(normalized)} rows into {args.out}")


def fetch_text(url_or_file: str, allow_insecure: bool = False) -> str:
    path = Path(url_or_file)
    if path.exists():
        return path.read_text(encoding="utf-8-sig")
    if requests is None:
        raise SystemExit("requests is required for URL fetching")
    headers = {"User-Agent": "Mozilla/5.0 trader-skill-builder/1.0"}
    response = requests.get(url_or_file, headers=headers, timeout=30, verify=not allow_insecure)
    response.raise_for_status()
    return response.text


def xml_text(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    return found.text.strip() if found is not None and found.text else ""


def substack_rss(args: argparse.Namespace) -> None:
    feed = args.feed
    if not feed.endswith("/feed") and urlparse(feed).scheme in {"http", "https"}:
        feed = feed.rstrip("/") + "/feed"
    raw = fetch_text(feed, allow_insecure=args.allow_insecure)
    root = ET.fromstring(raw)
    rows = []
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall(".//item")
    for idx, item in enumerate(items[: args.limit], 1):
        content = ""
        for child in item:
            if child.tag.endswith("encoded") and child.text:
                content = child.text
                break
        description = xml_text(item, "description")
        title = xml_text(item, "title")
        link = xml_text(item, "link")
        pub_date = xml_text(item, "pubDate")
        text = "\n\n".join(x for x in [title, content or description] if x)
        rows.append(
            {
                "post_id": xml_text(item, "guid") or link or str(idx),
                "created_at": parse_date(pub_date),
                "author": args.author,
                "url": link,
                "text": strip_html(text),
                "quoted_author": "",
                "quoted_text": "",
                "like_count": "",
                "retweet_count": "",
                "reply_count": "",
                "quote_count": "",
                "source": feed,
                "source_type": "substack_rss",
                "retrieved_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            }
        )
    write_csv(Path(args.out), rows)
    print(f"Wrote {len(rows)} RSS rows into {args.out}")


def merge(args: argparse.Namespace) -> None:
    seen = set()
    merged = []
    for item in args.inputs:
        for row in read_csv(Path(item)):
            key = row.get("url") or row.get("post_id") or row.get("text", "")[:120]
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    write_csv(Path(args.out), merged)
    print(f"Merged {len(merged)} rows into {args.out}")


def fetch_json(url: str, headers: dict, params: dict | None = None) -> dict:
    if requests is None:
        raise SystemExit("requests is required for API fetching")
    response = requests.get(url, headers=headers, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def x_api_user_timeline(args: argparse.Namespace) -> None:
    token = args.bearer_token or ""
    if not token:
        raise SystemExit("Missing X bearer token. Pass --bearer-token or set X_BEARER_TOKEN.")
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "trader-skill-builder/1.0"}
    user_lookup = fetch_json(
        f"https://api.x.com/2/users/by/username/{args.username}",
        headers,
        params={"user.fields": "created_at,description,public_metrics,verified"},
    )
    user_id = user_lookup.get("data", {}).get("id")
    if not user_id:
        raise SystemExit(f"Could not resolve username {args.username}: {user_lookup}")
    rows = []
    pagination_token = None
    while len(rows) < args.limit:
        params = {
            "max_results": min(100, args.limit - len(rows)),
            "tweet.fields": "created_at,public_metrics,referenced_tweets,conversation_id,entities,lang",
            "expansions": "referenced_tweets.id,referenced_tweets.id.author_id,author_id",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token
        data = fetch_json(f"https://api.x.com/2/users/{user_id}/tweets", headers, params=params)
        includes_tweets = {item.get("id"): item for item in data.get("includes", {}).get("tweets", [])}
        for item in data.get("data", []):
            quoted_text = ""
            quoted_author = ""
            for ref in item.get("referenced_tweets", []) or []:
                ref_item = includes_tweets.get(ref.get("id"))
                if ref_item and ref.get("type") in {"quoted", "replied_to"}:
                    quoted_text = ref_item.get("text", "")
                    quoted_author = ref_item.get("author_id", "")
            metrics = item.get("public_metrics", {}) or {}
            rows.append(
                {
                    "post_id": item.get("id", ""),
                    "created_at": parse_date(item.get("created_at", "")),
                    "author": args.username,
                    "url": f"https://x.com/{args.username}/status/{item.get('id', '')}",
                    "text": item.get("text", ""),
                    "quoted_author": quoted_author,
                    "quoted_text": quoted_text,
                    "like_count": str(metrics.get("like_count", "")),
                    "retweet_count": str(metrics.get("retweet_count", "")),
                    "reply_count": str(metrics.get("reply_count", "")),
                    "quote_count": str(metrics.get("quote_count", "")),
                    "source": f"x_api_user_timeline:{args.username}",
                    "source_type": "x_api_user_timeline",
                    "retrieved_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                }
            )
        pagination_token = data.get("meta", {}).get("next_token")
        if not pagination_token:
            break
    write_csv(Path(args.out), rows)
    print(f"Wrote {len(rows)} X API rows into {args.out}")


def apify_x_profile(args: argparse.Namespace) -> None:
    token = args.token or ""
    if not token:
        raise SystemExit("Missing Apify token. Pass --token or set APIFY_TOKEN.")
    if requests is None:
        raise SystemExit("requests is required for Apify fetching")
    actor = quote(args.actor, safe="")
    payload = {
        "handles": [args.username],
        "maxItems": args.limit,
        "includeReplies": args.include_replies,
        "includeRetweets": args.include_reposts,
        "includeQuotes": args.include_quotes,
    }
    run_url = f"https://api.apify.com/v2/acts/{actor}/runs?token={token}"
    run_response = requests.post(run_url, json=payload, timeout=60)
    run_response.raise_for_status()
    run_data = run_response.json().get("data", {})
    run_id = run_data.get("id")
    dataset_id = run_data.get("defaultDatasetId")
    if not run_id or not dataset_id:
        raise SystemExit(f"Apify run did not return ids: {run_response.text[:500]}")
    status = run_data.get("status", "")
    while status in {"READY", "RUNNING"}:
        import time

        time.sleep(args.poll_seconds)
        status_response = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={token}", timeout=60)
        status_response.raise_for_status()
        status = status_response.json().get("data", {}).get("status", "")
    if status != "SUCCEEDED":
        raise SystemExit(f"Apify run {run_id} ended with status {status}")
    items_response = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": token, "format": "json", "clean": "true"},
        timeout=120,
    )
    items_response.raise_for_status()
    raw_rows = items_response.json()
    normalized = normalize_rows(raw_rows, f"apify:{args.actor}:{run_id}", "apify_x_profile", args.username)
    write_csv(Path(args.out), normalized)
    meta_path = Path(args.out).with_suffix(".apify_run.json")
    meta_path.write_text(json.dumps({"run_id": run_id, "dataset_id": dataset_id, "status": status, "actor": args.actor}, indent=2), encoding="utf-8")
    print(f"Wrote {len(normalized)} Apify rows into {args.out}")


def extract_x_public_articles(raw_html: str, username: str, source_url: str, mode: str) -> list[dict]:
    if BeautifulSoup is None:
        raise SystemExit("beautifulsoup4 is required for x-public-seed")
    soup = BeautifulSoup(raw_html, "html.parser")
    rows = []
    retrieved_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    for article in soup.select("article[data-tweet-id]"):
        tweet_id = article.get("data-tweet-id", "").strip()
        if not tweet_id:
            continue
        text = article.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\$\s+([A-Z])", r"$\1", text)
        # Trim obvious shell UI fragments while preserving post text.
        text = re.sub(r"^(Pinned|Gaetano @crux_capital_ · [A-Za-z]{3} \\d{1,2})\\s*", "", text)
        rows.append(
            {
                "post_id": tweet_id,
                "created_at": "",
                "author": username,
                "url": f"https://x.com/{username}/status/{tweet_id}",
                "text": text,
                "quoted_author": "",
                "quoted_text": "",
                "like_count": "",
                "retweet_count": "",
                "reply_count": "",
                "quote_count": "",
                "source": source_url,
                "source_type": f"x_public_seed_{mode}",
                "retrieved_at": retrieved_at,
            }
        )
    return rows


def x_public_seed(args: argparse.Namespace) -> None:
    if requests is None:
        raise SystemExit("requests is required for x-public-seed")
    headers = {"User-Agent": "Mozilla/5.0"}
    all_rows = []
    modes = ["posts"]
    if args.include_replies:
        modes.append("with_replies")
    for mode in modes:
        suffix = "" if mode == "posts" else "/with_replies"
        url = f"https://x.com/{args.username}{suffix}"
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        raw_path = Path(args.out).with_suffix(f".{mode}.html")
        raw_path.write_text(response.text, encoding="utf-8")
        all_rows.extend(extract_x_public_articles(response.text, args.username, url, mode))
    seen = set()
    deduped = []
    for row in all_rows:
        if row["post_id"] in seen:
            continue
        seen.add(row["post_id"])
        deduped.append(row)
    write_csv(Path(args.out), deduped)
    print(f"Wrote {len(deduped)} public X seed rows into {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("normalize-export", help="Normalize CSV/JSON/JSONL exports from X API, Apify, twscrape, or archives")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--source", default="")
    p.add_argument("--source-type", default="managed_export")
    p.add_argument("--author", default="")
    p.set_defaults(func=normalize_export)

    p = sub.add_parser("substack-rss", help="Fetch or parse a Substack RSS feed into posts.csv")
    p.add_argument("--feed", required=True, help="https://example.substack.com or https://example.substack.com/feed or local XML file")
    p.add_argument("--out", required=True)
    p.add_argument("--author", default="")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--allow-insecure", action="store_true", help="Disable TLS verification only when local certificates are broken")
    p.set_defaults(func=substack_rss)

    p = sub.add_parser("merge", help="Merge normalized post CSVs and de-duplicate by URL/post_id")
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=merge)

    p = sub.add_parser("x-api-user-timeline", help="Collect user timeline through official X API v2")
    p.add_argument("--username", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--bearer-token", default="")
    p.set_defaults(func=x_api_user_timeline)

    p = sub.add_parser("apify-x-profile", help="Run an Apify X profile actor and normalize its dataset")
    p.add_argument("--username", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--actor", default="apidojo/twitter-scraper")
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--token", default="")
    p.add_argument("--include-replies", action="store_true")
    p.add_argument("--include-quotes", action="store_true")
    p.add_argument("--include-reposts", action="store_true")
    p.add_argument("--poll-seconds", type=int, default=10)
    p.set_defaults(func=apify_x_profile)

    p = sub.add_parser("x-public-seed", help="Collect logged-out public X first-screen seed rows")
    p.add_argument("--username", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--include-replies", action="store_true")
    p.set_defaults(func=x_public_seed)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    if sys.version_info < (3, 9):
        raise SystemExit("Python 3.9+ is required")
    main()
