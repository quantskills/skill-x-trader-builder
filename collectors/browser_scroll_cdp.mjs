#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

function parseArgs(argv) {
  const args = {
    cdp: "http://127.0.0.1:9222",
    profile: "crux_capital_",
    output: "x_browser_scroll_posts.csv",
    maxScrolls: 80,
    waitMs: 1600,
    includeReplies: true,
    startUrl: "",
  };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    const val = argv[i + 1];
    if (key === "--cdp") {
      args.cdp = val;
      i += 1;
    } else if (key === "--profile") {
      args.profile = val.replace(/^@/, "");
      i += 1;
    } else if (key === "--output") {
      args.output = val;
      i += 1;
    } else if (key === "--max-scrolls") {
      args.maxScrolls = Number(val);
      i += 1;
    } else if (key === "--wait-ms") {
      args.waitMs = Number(val);
      i += 1;
    } else if (key === "--no-replies") {
      args.includeReplies = false;
    } else if (key === "--start-url") {
      args.startUrl = val;
      i += 1;
    }
  }
  return args;
}

function csvEscape(value) {
  const s = String(value ?? "");
  if (/[",\r\n]/.test(s)) return `"${s.replaceAll('"', '""')}"`;
  return s;
}

function toCsv(rows) {
  const cols = [
    "source_type",
    "author_handle",
    "created_at",
    "text",
    "url",
    "tweet_id",
    "page_kind",
    "captured_at",
  ];
  return [
    cols.join(","),
    ...rows.map((row) => cols.map((col) => csvEscape(row[col])).join(",")),
  ].join("\n");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${url}`);
  return res.json();
}

async function attachToPage(cdpBase, preferredProfile) {
  let pages = await getJson(`${cdpBase}/json`);
  let page = pages.find((p) => p.type === "page" && p.url?.includes(`x.com/${preferredProfile}`));
  if (!page) page = pages.find((p) => p.type === "page");
  if (!page) throw new Error("No debuggable browser page found. Open an X tab in the debug browser first.");
  return page.webSocketDebuggerUrl;
}

function createCdpClient(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    }
  });
  const opened = new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  return {
    async send(method, params = {}) {
      await opened;
      const msgId = ++id;
      const p = new Promise((resolve, reject) => pending.set(msgId, { resolve, reject }));
      ws.send(JSON.stringify({ id: msgId, method, params }));
      return p;
    },
    close() {
      ws.close();
    },
  };
}

async function evalValue(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  return result.result?.value;
}

async function navigate(client, url) {
  await client.send("Page.navigate", { url });
  await sleep(5000);
}

async function revealOriginalPosts(client) {
  await evalValue(
    client,
    `(() => {
      const labels = new Set(['显示原文', 'Show original']);
      let clicked = 0;
      for (const el of Array.from(document.querySelectorAll('button, [role="button"]'))) {
        const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
        if (labels.has(text)) {
          el.click();
          clicked += 1;
        }
      }
      return clicked;
    })()`,
  );
  await sleep(500);
}

async function collectVisibleTweets(client, profile, pageKind) {
  await revealOriginalPosts(client);
  return evalValue(
    client,
    `(() => {
      const profile = ${JSON.stringify(profile)};
      const pageKind = ${JSON.stringify(pageKind)};
      const rows = [];
      const articles = Array.from(document.querySelectorAll('article'));
      for (const article of articles) {
        const text = (article.innerText || '').replace(/\\u0000/g, '').trim();
        const statusLinks = Array.from(article.querySelectorAll('a[href*="/status/"]'))
          .map((a) => a.href)
          .filter(Boolean);
        const url = statusLinks.find((href) => href.includes('/' + profile + '/status/')) || statusLinks[0] || '';
        const match = url.match(/\\/status\\/(\\d+)/);
        const tweetId = match ? match[1] : '';
        const timeEl = article.querySelector('time');
        const createdAt = timeEl ? (timeEl.getAttribute('datetime') || '') : '';
        const authorText = Array.from(article.querySelectorAll('a[role="link"] span'))
          .map((span) => span.innerText || '')
          .find((s) => s.startsWith('@')) || '@' + profile;
        if (tweetId && text) {
          rows.push({
            source_type: 'x_browser_scroll',
            author_handle: authorText.replace(/^@/, ''),
            created_at: createdAt,
            text,
            url,
            tweet_id: tweetId,
            page_kind: pageKind,
            captured_at: new Date().toISOString(),
          });
        }
      }
      return rows;
    })()`,
  );
}

async function collectPage(client, profile, pageKind, maxScrolls, waitMs) {
  const rowsById = new Map();
  let stableRounds = 0;
  let previousCount = 0;
  for (let i = 0; i < maxScrolls; i += 1) {
    const visibleRows = await collectVisibleTweets(client, profile, pageKind);
    for (const row of visibleRows || []) {
      rowsById.set(`${row.tweet_id}:${row.page_kind}`, row);
    }
    const count = rowsById.size;
    stableRounds = count === previousCount ? stableRounds + 1 : 0;
    previousCount = count;
    await evalValue(
      client,
      `(() => {
        const before = window.scrollY;
        window.scrollBy(0, Math.max(900, Math.floor(window.innerHeight * 1.65)));
        if (window.scrollY === before) window.scrollTo(0, document.body.scrollHeight);
        return { before, after: window.scrollY, height: document.body.scrollHeight };
      })()`,
    );
    await sleep(waitMs);
    if (stableRounds >= 12) break;
  }
  return Array.from(rowsById.values());
}

async function main() {
  const args = parseArgs(process.argv);
  const wsUrl = await attachToPage(args.cdp, args.profile);
  const client = createCdpClient(wsUrl);
  await client.send("Runtime.enable");
  await client.send("Page.enable");

  const allRows = [];
  if (args.startUrl) {
    await navigate(client, args.startUrl);
    allRows.push(...await collectPage(client, args.profile, "search", args.maxScrolls, args.waitMs));
  } else {
    await navigate(client, `https://x.com/${args.profile}`);
    allRows.push(...await collectPage(client, args.profile, "posts", args.maxScrolls, args.waitMs));
  }

  if (!args.startUrl && args.includeReplies) {
    await navigate(client, `https://x.com/${args.profile}/with_replies`);
    allRows.push(...await collectPage(client, args.profile, "with_replies", args.maxScrolls, args.waitMs));
  }

  client.close();

  const deduped = Array.from(new Map(allRows.map((row) => [`${row.tweet_id}:${row.page_kind}`, row])).values());
  fs.mkdirSync(path.dirname(path.resolve(args.output)), { recursive: true });
  fs.writeFileSync(args.output, `${toCsv(deduped)}\n`, "utf8");
  console.log(JSON.stringify({ output: args.output, rows: deduped.length }, null, 2));
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
