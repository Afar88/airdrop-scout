"""Binance announcement fetching.

The catalog list logic (CATALOGS, API, LINK, fetch-with-retry, keyword
classify) is reused from the author's earlier MIT-licensed project
"Airdrop Radar" (radar.py, https://github.com/Afar88/airdrop-radar).
The article-detail fetch and body flattening are new in Airdrop Scout.

Read-only: nothing here touches a wallet, an account, or places a trade.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from typing import Any, Callable

# ---- reused from airdrop-radar/radar.py (MIT) -----------------------------
CATALOGS = {93: "Latest Activities", 128: "Airdrop", 48: "New Listings"}
API = ("https://www.binance.com/bapi/apex/v1/public/apex/cms/article/list/query"
       "?type=1&pageNo=1&pageSize=20&catalogId={}")
LINK = "https://www.binance.com/en/support/announcement/detail/{}"

FREE = ["write", "post", "square", "quiz", "word of the day", "check-in",
        "story", "challenge", "vote", "red packet", "learn", "creator", "pick", "referral"]
CHEAP = ["hold", "holders", "airdrop", "alpha points", "claim"]
PAID = ["trade", "trading", "deposit", "subscribe", "futures", "tournament",
        "competition", "convert", "stake", "launchpool", "volume"]
# ---------------------------------------------------------------------------

DETAIL_API = ("https://www.binance.com/bapi/apex/v1/public/apex/cms/article/detail/query"
              "?articleCode={}")
# Without `clienttype: web` the detail endpoint answers success with data=null.
HEADERS = {"User-Agent": "Mozilla/5.0", "clienttype": "web", "lang": "en"}

Opener = Callable[[str], Any]


def _get_json(url: str, retries: int = 2, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2)


def fetch(cid: int, opener: Opener = _get_json) -> list[dict]:
    """Return the newest articles of one Binance announcement catalog (radar.py)."""
    return opener(API.format(cid))["data"]["catalogs"][0]["articles"]


def classify(title: str) -> str:
    """Keyword pre-tag from radar.py: PAID beats CHEAP beats FREE. A hint only;
    the agent makes the real decision from the full announcement."""
    t = title.lower()
    if any(k in t for k in PAID):
        return "PAID"
    if any(k in t for k in CHEAP):
        return "CHEAP"
    if any(k in t for k in FREE):
        return "FREE"
    return "OTHER"


def scan(days: int, opener: Opener = _get_json, now: float | None = None) -> tuple[list[dict], list[str]]:
    """List campaigns released in the last `days` days across CATALOGS.

    Returns (rows, errors). Rows are de-duplicated by article code.
    """
    now = time.time() if now is None else now
    cutoff = (now - days * 86400) * 1000
    seen: set[str] = set()
    rows: list[dict] = []
    errors: list[str] = []
    for cid, name in CATALOGS.items():
        try:
            for a in fetch(cid, opener):
                if a["releaseDate"] < cutoff or a["code"] in seen:
                    continue
                seen.add(a["code"])
                rows.append({
                    "code": a["code"],
                    "title": a["title"],
                    "catalog": name,
                    "released_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(a["releaseDate"] / 1000)),
                    "keyword_hint": classify(a["title"]),
                    "url": LINK.format(a["code"]),
                })
        except Exception as e:  # one catalog failing must not kill the scan
            errors.append(f"{name}: {e}")
    rows.sort(key=lambda r: r["released_utc"], reverse=True)
    return rows, errors


_CODE_RE = re.compile(r"([0-9a-f]{32})")


def extract_code(url_or_code: str) -> str:
    """Accept a 32-hex article code or any Binance announcement URL containing one."""
    m = _CODE_RE.search((url_or_code or "").strip().lower())
    if not m:
        raise ValueError(f"no Binance article code found in {url_or_code!r}")
    return m.group(1)


_BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "tr", "br", "div", "ul", "ol", "table"}


def flatten_body(body: str | dict | None) -> str:
    """Turn Binance's JSON rich-text tree into plain text (tables as `a | b`)."""
    if not body:
        return ""
    tree = json.loads(body) if isinstance(body, str) else body
    out: list[str] = []

    def walk(n: dict) -> None:
        if n.get("node") == "text":
            out.append(n.get("text", ""))
        for c in n.get("child") or []:
            walk(c)
        tag = n.get("tag")
        if tag in ("td", "th"):
            out.append(" | ")
        elif tag in _BLOCK:
            out.append("\n")

    walk(tree)
    text = html.unescape("".join(out)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def fetch_detail(url_or_code: str, opener: Opener = _get_json) -> dict:
    code = extract_code(url_or_code)
    payload = opener(DETAIL_API.format(code))
    data = (payload or {}).get("data")
    if not data:
        raise LookupError(f"Binance returned no article for code {code}")
    return {
        "code": code,
        "title": data.get("title", ""),
        "url": LINK.format(code),
        "published_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime((data.get("publishDate") or 0) / 1000)),
        "catalog": data.get("firstCatalogName") or "",
        "text": flatten_body(data.get("body")),
    }
