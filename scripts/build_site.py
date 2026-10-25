#!/usr/bin/env python3
"""Generate the Bangladeshii Reseller catalogue site (v2) from QORIX.

Reads the website channel via qorix_fetch.py: the vault-backed qorix.py
CLI on local runs, or the public API with QORIX_API_KEY from the
environment on GitHub Action runs. The key is never written to disk or
to the HTML. The HTML contains ONLY sell prices in BDT, product
names/descriptions/images and stock counts -- no QORIX cost prices
and no API key. Discounts, where shown, are sell price vs. the sell price
computed from QORIX's old_price field, never vs. cost.

Usage: python3 build_site.py
Output: site/index.html (relative to this script's directory)
"""
import html
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "site" / "index.html"
MARKUP = 1.75
BDT_RATE = 130
BOT_URL = "https://t.me/bangladeshii_bot"
GENERIC = {"ai", "pro", "plus", "premium", "app", "the", "and", "for"}
CE_RE = re.compile(r"\{ce:\d+:([^}]*)\}")


META_CATALOG = "1511158037629428"
WA_PHONE = "8801771023368"
WA_MAP_CACHE = BASE / "wa_product_map.json"
META_CLI = "/opt/hatch/bin/meta-ads-cli"


def load_wa_map():
    """Map QORIX product id (hyphens stripped) -> Meta catalog product id.

    Powers the WhatsApp catalog buttons: wa.me/p/<meta_product_id>/<phone>
    opens that product's card inside WhatsApp. On any Meta failure, fall
    back to the last cached map, and if there is none, to an empty map —
    the caller then uses a prefilled-text WhatsApp link instead, so a
    Meta outage never produces a broken catalog button.
    """
    try:
        mapping = {}
        cursor = None
        while True:
            args = {"advertiser_job": "other",
                    "advertiser_request": "site build WhatsApp catalog map",
                    "entity_id": META_CATALOG, "limit": 100}
            if cursor:
                args["cursor"] = cursor
            res = subprocess.run(
                [META_CLI, "call-tool", "--name", "ads_catalog_list_products",
                 "--agent-output", "--arguments-json", json.dumps(args)],
                capture_output=True, text=True, timeout=60)
            data = json.loads(res.stdout)["data"]
            for p in data["products"]:
                mapping[str(p["retailer_id"]).replace("-", "").lower()] = p["product_id"]
            if not data["page_info"]["has_next_page"]:
                break
            cursor = data["page_info"]["after_cursor"]
        if mapping:
            WA_MAP_CACHE.write_text(json.dumps(mapping), encoding="utf-8")
        return mapping
    except Exception:
        try:
            return json.loads(WA_MAP_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}


def sell_bdt(cost):
    return int(round(cost * MARKUP * BDT_RATE / 10.0) * 10)


def norm_tokens(t):
    return [w for w in re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split()
            if len(w) > 2 and w not in GENERIC]


def assign_categories(products, categories):
    cat_ids = {c.get("id") for c in categories}
    cat_toks = [(c.get("id"), norm_tokens(c.get("name"))) for c in categories]
    assign = {}
    for p in products:
        cid = p.get("category_id")
        if cid in cat_ids:
            assign[p["id"]] = cid
            continue
        pn = re.sub(r"[^a-z0-9]+", " ", (p.get("name") or "").lower())
        hit = next((ccid for ccid, toks in cat_toks if any(t in pn for t in toks)), None)
        assign[p["id"]] = hit or "other"
    return assign


def clean_desc(t):
    return CE_RE.sub(r"\1", t or "").strip()


def main():
    from qorix_fetch import fetch_products
    data = fetch_products()
    body = data["body"]
    assert body.get("ok"), body
    products = [p for p in body["products"] if p.get("in_stock")]
    categories = body["categories"]
    cat_name = {c["id"]: (c.get("name") or "").strip() for c in categories}
    cat_emoji = {c["id"]: (c.get("emoji") or "").strip() for c in categories}
    assign = assign_categories(products, categories)
    products.sort(key=lambda p: (-(p.get("featured_rank") or 0),
                                 (p.get("sort_order") or 0),
                                 (p.get("name") or "")))

    cats_in_use = []
    seen = set()
    for c in categories:
        if any(assign.get(p["id"]) == c["id"] for p in products) and c["id"] not in seen:
            cats_in_use.append(c)
            seen.add(c["id"])
    chips = []
    seen_names = set()
    for c in cats_in_use:
        n = cat_name[c["id"]]
        if n in seen_names:
            continue
        seen_names.add(n)
        chips.append((c["id"], n, cat_emoji[c["id"]]))
    other_count = sum(1 for p in products if assign.get(p["id"]) == "other")

    def cat_label(p):
        cid = assign.get(p["id"])
        return "Everything else" if cid == "other" else cat_name.get(cid, "Everything else")

    wa_map = load_wa_map()
    cards = []
    n_deals = 0
    for p in products:
        name = (p.get("name") or "").strip()
        price = sell_bdt(p["price"])
        old = None
        if p.get("old_price") and p["old_price"] > p["price"]:
            old = sell_bdt(p["old_price"])
        discount = 0
        if old and old > price:
            discount = round((old - price) * 100 / old)
            n_deals += 1
        stock = p.get("stock")
        badge = f"Only {stock} left!" if isinstance(stock, int) and stock <= 5 else f"{stock} in stock"
        badge_class = "low" if isinstance(stock, int) and stock <= 5 else ""
        instant = "Instant delivery" if p.get("instant") else "Delivery after confirmation"
        desc = clean_desc(p.get("description", ""))
        note = clean_desc(p.get("important_note", ""))
        img = p.get("image_url") or ""
        pem = (p.get("emoji") or "🛒").strip()
        fallback = (f'<div class="noimg"{" style=\"display:none\"" if img else ""}>'
                    f'<span class="noimg-emoji">{html.escape(pem)}</span>'
                    f'<span class="noimg-name">{html.escape(name)}</span></div>')
        img_tag = ""
        if img:
            img_tag = (f'<img src="{html.escape(img, quote=True)}" alt="" loading="lazy" '
                       f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">')
        img_tag += fallback
        featured = "1" if p.get("featured_rank") else "0"
        search_text = html.escape(f"{name} {cat_label(p)} {desc}", quote=True)
        badges = ""
        if discount:
            badges += f'<span class="deal-badge">-{discount}%</span>'
        if p.get("featured_rank"):
            badges += '<span class="pop-badge">🔥 Popular</span>'
        old_html = f'<span class="old">৳{old:,}</span>' if old else ""
        pid = str(p['id']).replace('-', '')
        wa_mid = wa_map.get(str(p['id']).replace('-', '').lower())
        if wa_mid:
            wa_url = f"https://wa.me/p/{wa_mid}/{WA_PHONE}"
            wa_hint = ("Opens this product in the WhatsApp catalog — "
                       "add to cart and message to order.")
        else:
            wa_text = urllib.parse.quote(
                f"Hi, I want to order {name} — ৳{price:,} — from Bangladeshii Reseller.",
                safe="")
            wa_url = f"https://wa.me/{WA_PHONE}?text={wa_text}"
            wa_hint = ("Opens WhatsApp with this product ready — pay bKash, "
                       "Nagad or Upay, send your TrxID there.")
        cards.append(f"""<article class="card" data-cat="{html.escape(cat_label(p), quote=True)}" data-pid="{pid}" data-featured="{featured}" data-discount="{1 if discount else 0}" data-price="{price}" data-name="{html.escape(name.lower(), quote=True)}" data-search="{search_text}">
  <div class="imgwrap">{badges}{img_tag}</div>
  <div class="card-body">
    <div class="cat">{html.escape(pem)} {html.escape(cat_label(p))}</div>
    <h3>{html.escape(name)}</h3>
    <div class="price-row"><span class="price">৳{price:,}</span>{old_html}</div>
    <div class="meta"><span class="badge {badge_class}">{html.escape(badge)}</span> <span>{html.escape(instant)}</span></div>
    <p class="desc">{html.escape(desc)}</p>
    <button class="details-btn" type="button">Show details</button>
    {f'<p class="note">{html.escape(note)}</p>' if note else ''}
    <button class="fav-btn" type="button" data-fav="{pid}">♡ Save</button>
    <a class="buy" href="{BOT_URL}?start=p_{pid}" target="_blank" rel="noopener">Buy on Telegram</a>
    <p class="buyhint">Opens @bangladeshii_bot directly on this product — pay bKash, Nagad or Upay, send your TrxID.</p>
    <a class="buy wa" href="{wa_url}" target="_blank" rel="noopener">Order on WhatsApp</a>
    <p class="buyhint">{html.escape(wa_hint)}</p>
  </div>
</article>""")

    chip_html = ['<button class="chip active" data-filter="all">All products</button>',
                 '<button class="chip" data-filter="popular">🔥 Popular</button>',
                 '<button class="chip" data-filter="deals">💸 Deals</button>',
                 '<button class="chip" data-filter="favs">♥ Favorites</button>']
    for _cid, n, em in chips:
        chip_html.append(f'<button class="chip" data-filter="{html.escape(n, quote=True)}">{html.escape((em + " " + n).strip())}</button>')
    if other_count:
        chip_html.append('<button class="chip" data-filter="Everything else">📦 Everything else</button>')

    dhaka = timezone(timedelta(hours=6))
    stamp = datetime.now(dhaka).strftime("%d %b %Y, %I:%M %p Asia/Dhaka")
    n_pop = sum(1 for p in products if p.get("featured_rank"))

    page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bangladeshii Reseller — Catalogue</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%9B%92%3C/text%3E%3C/svg%3E">
<style>
:root{--green:#0f5132;--green2:#1a7a4a;--bg:#f4f6f3;--ink:#1c1c1c;--muted:#666;--line:#e3ddd0;--red:#b42318}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
a{color:var(--green)}
.topbar{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 20px}
.brand{font-weight:800;font-size:18px}
.brand small{display:block;font-weight:600;font-size:12px;color:var(--muted)}
.tgbtn{background:var(--green);color:#fff!important;text-decoration:none;padding:9px 14px;border-radius:999px;font-weight:700;white-space:nowrap}
.hero{background:linear-gradient(135deg,#0f5132,#1a7a4a 60%,#2a9d5f);color:#fff;padding:36px 20px 30px}
.hero-inner{max-width:1100px;margin:0 auto}
.hero h1{margin:8px 0;font-size:clamp(28px,5vw,44px);line-height:1.1}
.hero p{max-width:720px;line-height:1.6;color:#e6f4ea}
.pill{display:inline-block;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.35);padding:5px 10px;border-radius:999px;font-size:13px;margin:2px}
.hero-cta{margin-top:16px;display:flex;flex-wrap:wrap;gap:10px}
.btn{display:inline-block;padding:12px 18px;border-radius:12px;font-weight:700;text-decoration:none}
.btn-white{background:#fff;color:var(--green)}
.btn-outline{border:2px solid #fff;color:#fff}
.trust{max-width:1100px;margin:-14px auto 0;padding:0 20px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.trust div{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}
.trust b{display:block;margin-bottom:4px}.trust span{color:var(--muted);font-size:13px;line-height:1.4;display:block}
.steps{max-width:1100px;margin:20px auto 0;padding:0 20px}
.steps h2,.catalogue h2{font-size:20px;margin:0 0 10px}
.steps ol{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;list-style:none;padding:0;margin:0}
.steps li{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}
.steps li b{font-size:22px;color:var(--green2);display:block}
.steps li span{color:var(--muted);font-size:13px;line-height:1.4;display:block;margin-top:4px}
.catalogue{max-width:1100px;margin:24px auto;padding:0 20px}
.controls{position:sticky;top:57px;z-index:10;background:var(--bg);padding:10px 0;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
#search{flex:1;min-width:220px;padding:11px 12px;border:1px solid #ccc;border-radius:10px;font-size:16px;background:#fff}
#sort{padding:11px;border:1px solid #ccc;border-radius:10px;font-size:15px;background:#fff}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 18px}
.chip{border:1px solid var(--green);background:#fff;color:var(--green);padding:8px 12px;border-radius:999px;cursor:pointer}
.chip.active{background:var(--green);color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.imgwrap{position:relative}
.card img{width:100%;height:190px;object-fit:cover;background:#eee;display:block}
.noimg{height:190px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;background:#e6efe8;color:var(--green)}
.noimg-emoji{font-size:56px}.noimg-name{font-size:13px;padding:0 16px;text-align:center}
.deal-badge{position:absolute;top:10px;left:10px;background:var(--red);color:#fff;font-weight:800;font-size:13px;padding:5px 9px;border-radius:999px;z-index:2}
.pop-badge{position:absolute;top:10px;right:10px;background:#fff;color:#1c1c1c;font-weight:700;font-size:12px;padding:5px 9px;border-radius:999px;z-index:2}
.card-body{padding:14px;display:flex;flex-direction:column;gap:8px;flex:1}
.cat{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.card h3{margin:0;font-size:17px;line-height:1.3}
.price-row{display:flex;align-items:baseline;gap:10px}
.price{font-size:24px;font-weight:800;color:var(--green)}
.old{color:#999;text-decoration:line-through}
.meta{font-size:13px;color:#444}.badge{background:#eef6ee;padding:3px 8px;border-radius:999px}
.badge.low{background:#fde8e8;color:#9b1c1c}
.desc{font-size:14px;line-height:1.55;color:#333;margin:0;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;white-space:pre-line}
.desc.expanded{display:block;-webkit-line-clamp:unset}
.details-btn{align-self:flex-start;background:none;border:0;color:var(--green);font-weight:700;cursor:pointer;padding:0}
.note{font-size:13px;color:var(--muted);margin:0}
.fav-btn{align-self:flex-start;background:#fff;border:1px solid var(--green);color:var(--green);padding:6px 12px;border-radius:999px;cursor:pointer;font-weight:700}
.fav-btn.on{background:var(--green);color:#fff}
.buy{display:block;text-align:center;background:var(--green);color:#fff!important;text-decoration:none;padding:12px;border-radius:10px;margin-top:auto;font-weight:700}
.buy.wa{background:#25a85a;margin-top:0}
.buyhint{font-size:12px;color:var(--muted);margin:0}
footer{max-width:1100px;margin:0 auto;padding:20px;color:#555;line-height:1.6}
#count{font-weight:600}
@media(max-width:700px){.trust,.steps ol{grid-template-columns:1fr 1fr}.controls{top:57px}}
</style>
</head>
<body>
<div class="topbar"><div class="brand">🇧🇩 Bangladeshii Reseller<small>Digital products • BDT prices</small></div><a class="tgbtn" href="__BOT_URL__" target="_blank" rel="noopener">Order on Telegram</a></div>
<section class="hero"><div class="hero-inner">
<span class="pill">Made for Bangladesh</span> <span class="pill">Pay with bKash / Nagad / Upay</span> <span class="pill">Seller-confirmed orders</span>
<h1>Premium subscriptions,<br>in BDT, delivered fast.</h1>
<p>AI tools, streaming, VPNs and software — browse the full catalogue here, then finish your order in the Telegram bot or on WhatsApp. No payment is taken on this website itself.</p>
<div class="hero-cta"><a class="btn btn-white" href="#catalogue">Browse products ↓</a><a class="btn btn-outline" href="__BOT_URL__" target="_blank" rel="noopener">Open @bangladeshii_bot</a><a class="btn btn-outline" href="https://wa.me/c/8801771023368" target="_blank" rel="noopener">Order on WhatsApp</a></div>
</div></section>
<section class="trust">
<div><b>⚡ Instant delivery</b><span>For auto-delivery products, once your order is confirmed.</span></div>
<div><b>✅ Seller-confirmed</b><span>Every order is checked before anything is bought from the supplier.</span></div>
<div><b>💳 bKash, Nagad &amp; Upay</b><span>Pay to 01771023368 via any of the three, then send your TrxID in the bot.</span></div>
<div><b>💬 Telegram &amp; WhatsApp support</b><span>Questions, warranty and refunds — in the bot, or on WhatsApp 01771023368.</span></div>
</section>
<section class="steps"><h2>How to order</h2><ol>
<li><b>1</b>Pick a product<span>Search or filter by category, Popular or Deals.</span></li>
<li><b>2</b>Tap Buy on Telegram or WhatsApp<span>That opens the bot, or a WhatsApp chat, for that product.</span></li>
<li><b>3</b>Pay &amp; send TrxID<span>bKash, Nagad or Upay to 01771023368, then send the TrxID in the bot.</span></li>
<li><b>4</b>Seller confirms<span>Once confirmed, delivery follows in the bot.</span></li>
</ol></section>
<main class="catalogue" id="catalogue">
<h2>All products</h2>
<div class="controls"><input id="search" type="search" placeholder="Search products… e.g. Netflix, Gemini, Spotify"><select id="sort"><option value="popular">Sort: Popular first</option><option value="price-asc">Price: low to high</option><option value="price-desc">Price: high to low</option><option value="name">Name: A to Z</option></select><span id="count"></span></div>
<div class="chips">__CHIPS__</div>
<div class="grid" id="grid">__CARDS__</div>
<p id="empty" style="display:none">No products match that search. Try another name, or open the bot and use /search there.</p>
</main>
<footer>
<p>Catalogue refreshed __STAMP__ — __N__ products in stock, __NPOP__ marked Popular, __NDEALS__ on deal. Prices and stock can change; the bot shows live stock at order time.</p>
<p>Orders are completed in @bangladeshii_bot or on WhatsApp. This website takes no payment and stores no card or payment details.</p>
</footer>
<script>
const q=document.getElementById('search'), grid=document.getElementById('grid'), sortSel=document.getElementById('sort'),
count=document.getElementById('count'), empty=document.getElementById('empty');
let filter='all';
const cards=[...grid.children];
// Favorites live only in this browser (localStorage) — the static site has
// no accounts and no server, so nothing about a visitor is sent anywhere.
const favKey='bangladeshii_favs';
let favs=new Set(JSON.parse(localStorage.getItem(favKey)||'[]'));
function paintFavs(){document.querySelectorAll('.fav-btn').forEach(b=>{const on=favs.has(b.dataset.fav); b.textContent=on?'♥ Saved':'♡ Save'; b.classList.toggle('on',on);});}
paintFavs();
function apply(){
  const term=q.value.trim().toLowerCase();
  let visible=cards.filter(c=>{
    const okCat = filter==='all' || (filter==='popular' ? c.dataset.featured==='1' : filter==='deals' ? c.dataset.discount==='1' : filter==='favs' ? favs.has(c.dataset.pid) : c.dataset.cat===filter);
    const okTerm = !term || c.dataset.search.toLowerCase().includes(term);
    return okCat && okTerm;
  });
  const mode=sortSel.value;
  visible.sort((a,b)=>{
    if(mode==='price-asc') return +a.dataset.price - +b.dataset.price;
    if(mode==='price-desc') return +b.dataset.price - +a.dataset.price;
    if(mode==='name') return a.dataset.name.localeCompare(b.dataset.name);
    return (+b.dataset.featured - +a.dataset.featured) || (+a.dataset.price - +b.dataset.price);
  });
  cards.forEach(c=>c.style.display='none');
  visible.forEach(c=>{c.style.display=''; grid.appendChild(c);});
  count.textContent = visible.length + ' products shown';
  empty.textContent = filter==='favs' ? 'No favorites yet — tap ♡ Save on any product.' : 'No products match that search. Try another name, or open the bot and use /search there.';
  empty.style.display = visible.length ? 'none' : '';
}
document.querySelectorAll('.chip').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); filter=b.dataset.filter; apply();
}));
q.addEventListener('input', apply); sortSel.addEventListener('change', apply);
grid.addEventListener('click', e=>{
  const fav=e.target.closest('.fav-btn');
  if(fav){ const id=fav.dataset.fav; favs.has(id)?favs.delete(id):favs.add(id); localStorage.setItem(favKey, JSON.stringify([...favs])); paintFavs(); if(filter==='favs') apply(); return; }
  const btn=e.target.closest('.details-btn'); if(!btn) return;
  const desc=btn.parentElement.querySelector('.desc');
  const open=desc.classList.toggle('expanded');
  btn.textContent = open ? 'Hide details' : 'Show details';
});
apply();
</script>
<!-- Cloudflare Web Analytics --><script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "aed05cda823649f884281c45c9e8d87f"}'></script><!-- End Cloudflare Web Analytics -->
</body>
</html>
"""
    page = (page.replace("__BOT_URL__", BOT_URL)
                .replace("__CHIPS__", "".join(chip_html))
                .replace("__CARDS__", "".join(cards))
                .replace("__STAMP__", html.escape(stamp))
                .replace("__N__", str(len(products)))
                .replace("__NPOP__", str(n_pop))
                .replace("__NDEALS__", str(n_deals)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} : {len(products)} products, {len(chips)} categories + other={other_count}, deals={n_deals}, popular={n_pop}")


if __name__ == "__main__":
    main()
