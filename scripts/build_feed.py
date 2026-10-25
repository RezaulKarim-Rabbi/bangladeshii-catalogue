#!/usr/bin/env python3
"""Generate the Meta product feed (site/feed.csv) from QORIX.

Same source and pricing as build_site.py: website channel, in-stock only,
sell price = cost x 1.75 x 130 BDT rounded to the nearest 10. Feed
semantics: price = regular price, sale_price = discounted price where
QORIX has an old_price above the current price. Link = per-product
Telegram deep link (the order action), image_link = QORIX image URL
(blank for the few products without one — Meta warns, does not reject).

The CSV contains ONLY sell prices, names, descriptions, images and
order links — no QORIX cost prices, no API key, no API URL.

Usage: python3 build_feed.py
Output: site/feed.csv (relative to this script's directory)
Prints: "feed: N products"
"""
import csv
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "site" / "feed.csv"
MARKUP = 1.75
BDT_RATE = 130
CE_RE = re.compile(r"\{ce:\d+:([^}]*)\}")


def sell_bdt(cost):
    return int(round(cost * MARKUP * BDT_RATE / 10.0) * 10)


def clean(t):
    return re.sub(r"\s+", " ", CE_RE.sub(r"\1", t or "")).strip()


def main():
    from qorix_fetch import fetch_products
    data = fetch_products()
    body = data["body"]
    assert body.get("ok"), body
    products = [p for p in body["products"] if p.get("in_stock")]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "description", "link", "image_link",
                    "price", "sale_price", "availability", "condition"])
        for p in products:
            price = sell_bdt(p["price"])
            old = None
            if p.get("old_price") and p["old_price"] > p["price"]:
                old = sell_bdt(p["old_price"])
            desc = clean(p.get("description", ""))
            note = clean(p.get("important_note", ""))
            if note:
                desc = (desc + " " + note)[:500]
            else:
                desc = desc[:500]
            w.writerow([
                p["id"],
                (p.get("name") or "").strip(),
                desc,
                f"https://t.me/bangladeshii_bot?start=p_{str(p['id']).replace('-', '')}",
                p.get("image_url") or "",
                f"{old} BDT" if old else f"{price} BDT",
                f"{price} BDT" if old else "",
                "in stock",
                "new",
            ])
    print(f"feed: {len(products)} products")


if __name__ == "__main__":
    main()
