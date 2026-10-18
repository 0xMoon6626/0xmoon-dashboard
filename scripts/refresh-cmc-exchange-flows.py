#!/usr/bin/env python3
"""Refresh the CoinMarketCap exchange inflow/outflow snapshot.

The chart page
https://coinmarketcap.com/charts/exchange-inflows-outflows/
(Chinese: https://coinmarketcap.com/zh/charts/exchange-inflows-outflows/)
loads this public, unofficial JSON (no CoinMarketCap Pro API key):

  GET https://api.coinmarketcap.com/data-api/v3/exchange-asset/flow/list
      ?convertId=2781&start=1&limit=100&sortBy=exchangeRank&sortType=asc

convertId 2781 is USD. sortBy=exchangeRank&sortType=asc matches the table
order on that page. Response rows use totalAsset, netFlow24hUsd,
netFlow7dUsd, netFlow30dUsd, openInterestUsd. The Source column on the
site is not a number; it links to /exchanges/{slug}/#reserve.

Browser fetches from GitHub Pages are blocked by CORS. The API returns
Access-Control-Allow-Origin: https://coinmarketcap.com only. This script
runs outside the browser, writes cmc-exchange-flows-snapshot.json, and
updates the embedded CMC_FLOWS_SNAPSHOT fallback in data.html.

Usage (from the repo root):

  python3 scripts/refresh-cmc-exchange-flows.py

Then commit both files. data.html tries the live URL first, then the
snapshot file, then the embedded copy. Do not hand-edit the numbers.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "cmc-exchange-flows-snapshot.json"
DATA_HTML = ROOT / "data.html"
BEGIN = "/*CMC_FLOWS_SNAPSHOT_BEGIN*/"
END = "/*CMC_FLOWS_SNAPSHOT_END*/"

API = (
    "https://api.coinmarketcap.com/data-api/v3/exchange-asset/flow/list"
    "?convertId=2781&start=1&limit=100&sortBy=exchangeRank&sortType=asc"
)
CHART_ZH = "https://coinmarketcap.com/zh/charts/exchange-inflows-outflows/"
CHART_EN = "https://coinmarketcap.com/charts/exchange-inflows-outflows/"

FIELDS = (
    "id",
    "name",
    "slug",
    "exchangeRank",
    "totalAsset",
    "openInterestUsd",
    "netFlow24hUsd",
    "netFlow7dUsd",
    "netFlow30dUsd",
)


def fetch_payload() -> dict:
    req = urllib.request.Request(
        API,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (compatible; 0xmoon-dashboard-refresh/1.0; "
                "+https://github.com/0xMoon6626/0xmoon-dashboard)"
            ),
            "Origin": "https://coinmarketcap.com",
            "Referer": "https://coinmarketcap.com/charts/exchange-inflows-outflows/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"CMC flow API HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"CMC flow API request failed: {exc.reason}") from exc

    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"CMC flow API did not return JSON: {exc}") from exc

    status = raw.get("status") or {}
    if str(status.get("error_code")) not in ("0", "0.0"):
        raise SystemExit(f"CMC flow API error: {status}")

    data = raw.get("data") or {}
    rows = data.get("flowList")
    if not isinstance(rows, list) or len(rows) < 10:
        raise SystemExit("CMC flow API returned too few exchanges; refusing to overwrite snapshot")

    exchanges = []
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit("CMC flow API row was not an object")
        item = {}
        for key in FIELDS:
            item[key] = normalize_value(key, row.get(key))
        if not item["name"] or not item["slug"]:
            raise SystemExit(f"CMC flow API row missing name/slug: {row!r}")
        exchanges.append(item)

    binance = next((x for x in exchanges if x["slug"] == "binance"), None)
    if binance is None:
        raise SystemExit("CMC flow API response has no Binance row; refusing to overwrite snapshot")
    asset = binance.get("totalAsset")
    if not isinstance(asset, (int, float)) or not math.isfinite(asset) or asset <= 0:
        raise SystemExit("Binance totalAsset missing or not a positive number; refusing to overwrite snapshot")

    updated = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S%z")
    return {
        "updatedAt": updated,
        "source": CHART_ZH,
        "sourceEn": CHART_EN,
        "api": API,
        "convert": "USD",
        "convertId": 2781,
        "count": data.get("count") if isinstance(data.get("count"), int) else len(exchanges),
        "exchanges": exchanges,
        "refresh": "python3 scripts/refresh-cmc-exchange-flows.py",
    }


def normalize_value(key: str, value):
    if key in ("name", "slug"):
        return value if isinstance(value, str) else None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"Unexpected type for {key}: {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise SystemExit(f"Non-finite number for {key}")
    return value


def write_snapshot(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")


def write_embedded(payload: dict) -> None:
    html = DATA_HTML.read_text(encoding="utf-8")
    if BEGIN not in html or END not in html:
        raise SystemExit(f"Markers {BEGIN} / {END} not found in data.html")
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    block = (
        f"{BEGIN}\n"
        f"    var CMC_FLOWS_SNAPSHOT = {compact};\n"
        f"    {END}"
    )
    start = html.find(BEGIN)
    finish = html.find(END, start)
    if finish < 0:
        raise SystemExit("CMC snapshot end marker missing")
    finish += len(END)
    DATA_HTML.write_text(html[:start] + block + html[finish:], encoding="utf-8")


def main() -> None:
    payload = fetch_payload()
    write_snapshot(payload)
    write_embedded(payload)
    binance = next(x for x in payload["exchanges"] if x["slug"] == "binance")
    print(
        f"Wrote {payload['count']} exchanges at {payload['updatedAt']}. "
        f"Binance totalAsset={binance['totalAsset']} "
        f"netFlow24hUsd={binance['netFlow24hUsd']} "
        f"netFlow7dUsd={binance['netFlow7dUsd']} "
        f"netFlow30dUsd={binance['netFlow30dUsd']} "
        f"openInterestUsd={binance['openInterestUsd']}"
    )


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
