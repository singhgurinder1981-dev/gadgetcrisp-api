"""
GadgetCrisp Price Comparison API v2.0
=======================================
- Scrapes Amazon.in, Flipkart, Croma, Reliance Digital, Tata CLiQ, Myntra
- Smart demo fallback when stores block scraping
- Full affiliate ID support: Amazon, Flipkart, Myntra

Environment variables to set in Railway:
  AMAZON_TAG   = gadgetcrisp-21         (your amazon tag)
  FLIPKART_ID  = your_flipkart_id       (from affiliate.flipkart.com)
  MYNTRA_ID    = your_myntra_id         (from myntra.com/affiliates)
"""

import os, re, time, random, logging
from urllib.parse import quote_plus, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # Open CORS for WordPress

AMAZON_TAG  = os.getenv("AMAZON_TAG",  "gadgetcrisp-21")
FLIPKART_ID = os.getenv("FLIPKART_ID", "")
MYNTRA_ID   = os.getenv("MYNTRA_ID",   "")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

def get_headers(ref=None):
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": ref or "https://www.google.co.in/",
        "DNT": "1",
    }

def fetch(url, timeout=15):
    try:
        time.sleep(random.uniform(0.3, 1.0))
        r = requests.get(url, headers=get_headers(url), timeout=timeout, allow_redirects=True)
        return r if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"Fetch {url}: {e}")
        return None

def to_int(text):
    if not text: return None
    d = re.sub(r'[^\d]', '', str(text))
    return int(d) if d else None

# ─── AFFILIATE URL BUILDERS ───────────────────────────────────────

def amazon_url(query, asin=None):
    if asin:
        return f"https://www.amazon.in/dp/{asin}?tag={AMAZON_TAG}"
    return f"https://www.amazon.in/s?k={quote_plus(query)}&tag={AMAZON_TAG}"

def flipkart_url(query, href=None):
    base = href if href else f"https://www.flipkart.com/search?q={quote_plus(query)}"
    if FLIPKART_ID:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}affid={FLIPKART_ID}"
    return base

def myntra_url(query):
    base = f"https://www.myntra.com/search?rawQuery={quote_plus(query)}"
    if MYNTRA_ID:
        return f"{base}&utm_source=affiliate&utm_medium={MYNTRA_ID}"
    return base

# ─── SMART DEMO DATA ─────────────────────────────────────────────
# Returns realistic estimated prices when live scraping fails.
# This ensures users ALWAYS see results, never a blank page.

PRODUCT_DB = {
    'iphone 15 pro max': (134900, 'Apple iPhone 15 Pro Max (256GB, Black Titanium)'),
    'iphone 15 pro':     (119900, 'Apple iPhone 15 Pro (128GB, Natural Titanium)'),
    'iphone 15':         ( 79900, 'Apple iPhone 15 (128GB, Black)'),
    'iphone 14':         ( 64900, 'Apple iPhone 14 (128GB, Midnight)'),
    'iphone 13':         ( 49900, 'Apple iPhone 13 (128GB, Midnight)'),
    'samsung s24 ultra': (129999, 'Samsung Galaxy S24 Ultra (256GB, Titanium Black)'),
    'galaxy s24 ultra':  (129999, 'Samsung Galaxy S24 Ultra (256GB, Titanium Black)'),
    'samsung s24':       ( 74999, 'Samsung Galaxy S24 (128GB, Cobalt Violet)'),
    'galaxy s24':        ( 74999, 'Samsung Galaxy S24 (128GB, Cobalt Violet)'),
    'samsung s23':       ( 54999, 'Samsung Galaxy S23 (128GB, Phantom Black)'),
    'pixel 8 pro':       ( 89999, 'Google Pixel 8 Pro (128GB, Obsidian)'),
    'pixel 8':           ( 59999, 'Google Pixel 8 (128GB, Hazel)'),
    'oneplus 12':        ( 64999, 'OnePlus 12 (256GB, Silky Black)'),
    'oneplus 12r':       ( 29999, 'OnePlus 12R (128GB, Iron Gray)'),
    'macbook air m3':    (114900, 'Apple MacBook Air 13" M3 (8GB RAM, 256GB, Midnight)'),
    'macbook air m2':    ( 94900, 'Apple MacBook Air 13" M2 (8GB RAM, 256GB, Space Gray)'),
    'macbook pro m3':    (169900, 'Apple MacBook Pro 14" M3 (8GB RAM, 512GB SSD)'),
    'sony xm5':          ( 24990, 'Sony WH-1000XM5 Wireless Noise Cancelling Headphones'),
    'wh-1000xm5':        ( 24990, 'Sony WH-1000XM5 Wireless Noise Cancelling Headphones'),
    'sony xm4':          ( 19990, 'Sony WH-1000XM4 Wireless Headphones (Black)'),
    'airpods pro':       ( 24900, 'Apple AirPods Pro (2nd Generation) with MagSafe Case'),
    'airpods':           ( 12900, 'Apple AirPods (3rd Generation) with Lightning Case'),
    'boat airdopes':     (  1299, 'boAt Airdopes 141 TWS Earbuds (Active Black)'),
    'apple watch ultra': ( 89900, 'Apple Watch Ultra 2 (49mm, Natural Titanium)'),
    'apple watch series 9': (41900, 'Apple Watch Series 9 (41mm, Midnight Aluminium)'),
    'galaxy watch':      ( 26999, 'Samsung Galaxy Watch 6 (44mm, Graphite)'),
    'ipad pro':          ( 99900, 'Apple iPad Pro 11" M4 (256GB, Wi-Fi, Space Black)'),
    'ipad air':          ( 59900, 'Apple iPad Air 11" M2 (128GB, Wi-Fi, Blue)'),
    'ipad':              ( 34900, 'Apple iPad 10th Gen (64GB, Wi-Fi, Blue)'),
    'redmi note 13':     ( 16999, 'Redmi Note 13 Pro+ 5G (256GB, Fusion Purple)'),
    'nothing phone':     ( 34999, 'Nothing Phone (2a) (128GB, Black)'),
}

def get_demo_data(query):
    q = query.lower().strip()

    # Find best match in product DB
    base, name = 29999, f'{query.title()}'
    for key, (price, prod_name) in PRODUCT_DB.items():
        if key in q or all(w in q for w in key.split()):
            base, name = price, prod_name
            break

    mrp = int(base * 1.10)

    stores = [
        {"store": "amazon",   "price": base,                         "delivery": "Free delivery",    "fast": True,  "emi": f"₹{base//24:,}/mo" if base>5000 else None, "affiliate": amazon_url(query)},
        {"store": "flipkart", "price": base + random.randint(0,500), "delivery": "Free delivery",    "fast": False, "emi": f"₹{(base+200)//24:,}/mo" if base>5000 else None, "affiliate": flipkart_url(query)},
        {"store": "croma",    "price": base + random.randint(500,1500),"delivery": "₹99 delivery",   "fast": True,  "emi": None, "affiliate": f"https://www.croma.com/searchB?q={quote_plus(query)}"},
        {"store": "reliance", "price": base + random.randint(800,2000),"delivery": "Free delivery",  "fast": False, "emi": None, "affiliate": f"https://www.reliancedigital.in/search?q={quote_plus(query)}"},
        {"store": "tatacliq", "price": base + random.randint(300,1200),"delivery": "₹49 delivery",   "fast": False, "emi": None, "affiliate": f"https://www.tatacliq.com/search/?text={quote_plus(query)}"},
        {"store": "vijay",    "price": base + random.randint(200,1000),"delivery": "Free delivery",  "fast": False, "emi": None, "affiliate": f"https://www.vijaysales.com/search/{quote_plus(query)}", "inStock": random.choice([True,True,False])},
    ]

    # Add Myntra for wearables/audio
    if any(x in q for x in ['watch','band','earphone','headphone','airpods','fitness']):
        stores.append({"store": "myntra", "price": base + random.randint(100,800), "delivery": "Free above ₹499", "fast": False, "emi": None, "affiliate": myntra_url(query)})

    for s in stores:
        s.setdefault("original", mrp)
        s.setdefault("inStock", True)
        s.setdefault("image", "")
        s.setdefault("rating", None)
        s.setdefault("name", name)

    return {
        "name": name, "category": detect_category(q),
        "image": "", "rating": round(random.uniform(4.0, 4.8), 1),
        "reviews": random.randint(5000, 50000), "brand": name.split()[0],
        "specs": {}, "prices": stores, "source": "estimated",
    }

def detect_category(q):
    if any(x in q for x in ['phone','iphone','samsung','pixel','oneplus','redmi','realme','vivo','oppo','nothing']): return 'Smartphones'
    if any(x in q for x in ['macbook','laptop','notebook']): return 'Laptops'
    if any(x in q for x in ['headphone','earphone','airpods','earbud','xm5','xm4','boat']): return 'Audio'
    if any(x in q for x in ['watch','band']): return 'Wearables'
    if any(x in q for x in ['ipad','tablet']): return 'Tablets'
    if any(x in q for x in ['tv','television']): return 'TVs'
    return 'Electronics'

# ─── LIVE SCRAPERS ────────────────────────────────────────────────

def scrape_amazon(query):
    r = fetch(f"https://www.amazon.in/s?k={quote_plus(query)}")
    if not r: return []
    soup  = BeautifulSoup(r.text, "html.parser")
    items = soup.select('[data-component-type="s-search-result"]')[:5]
    for item in items:
        try:
            name_el  = item.select_one("h2 a span")
            price_el = item.select_one(".a-price-whole")
            if not name_el or not price_el: continue
            price = to_int(price_el.get_text())
            if not price or price < 100: continue
            link_el = item.select_one("h2 a")
            href    = link_el["href"] if link_el else ""
            asin_m  = re.search(r'/dp/([A-Z0-9]{10})', href)
            img_el  = item.select_one("img.s-image")
            orig_el = item.select_one(".a-price.a-text-price .a-offscreen")
            rat_el  = item.select_one(".a-icon-star-small .a-icon-alt")
            rating  = None
            if rat_el:
                try: rating = float(rat_el.get_text(strip=True).split()[0])
                except: pass
            return [{"store":"amazon","name":name_el.get_text(strip=True),"price":price,
                "original": to_int(orig_el.get_text()) if orig_el else price,
                "delivery":"Free delivery","fast":True,"inStock":True,
                "emi":f"₹{price//24:,}/mo" if price>5000 else None,
                "affiliate":amazon_url(query, asin_m.group(1) if asin_m else None),
                "image":img_el.get("src","") if img_el else "","rating":rating}]
        except Exception as e:
            log.warning(f"Amazon: {e}")
    return []

def scrape_flipkart(query):
    r = fetch(f"https://www.flipkart.com/search?q={quote_plus(query)}")
    if not r: return []
    soup = BeautifulSoup(r.text, "html.parser")
    for price_sel, name_sel, link_sel, orig_sel in [
        ("div._30jeq3","div._4rR01T,a.s1Q9rs","a._1fQZEK,a.s1Q9rs","div._3I9_wc"),
        ("div.Nx9bqj", "div.WKTcLC,div.KzDlHZ","a","div.yRaY8j"),
    ]:
        for card in soup.select("div._1AtVbE,div._2kHMtA,div.tUxRFH")[:8]:
            try:
                pe = card.select_one(price_sel)
                if not pe: continue
                price = to_int(pe.get_text())
                if not price or price < 100: continue
                ne = card.select_one(name_sel)
                le = card.select_one(link_sel)
                oe = card.select_one(orig_sel)
                ie = card.select_one("img._396cs4,img._2r_T1I,img")
                href = "https://www.flipkart.com" + le["href"] if le and le.get("href","").startswith("/") else ""
                return [{"store":"flipkart","name":ne.get_text(strip=True) if ne else query,
                    "price":price,"original":to_int(oe.get_text()) if oe else price,
                    "delivery":"Free delivery","fast":False,"inStock":True,
                    "emi":f"₹{price//24:,}/mo" if price>5000 else None,
                    "affiliate":flipkart_url(query, href),"image":ie.get("src","") if ie else "","rating":None}]
            except Exception as e:
                log.warning(f"Flipkart: {e}")
    return []

def scrape_croma(query):
    r = fetch(f"https://www.croma.com/searchB?q={quote_plus(query)}%3Arelevance")
    if not r: return []
    soup = BeautifulSoup(r.text, "html.parser")
    for card in soup.select("li.product-item,div.product-item")[:3]:
        try:
            pe = card.select_one("span.pdp-selling-price,.new-price")
            if not pe: continue
            price = to_int(pe.get_text())
            if not price or price < 100: continue
            ne = card.select_one("h3.product-title,a.product-title")
            le = card.select_one("a[href*='/p/'],a.product-title")
            href = "https://www.croma.com" + le["href"] if le and le.get("href","").startswith("/") else f"https://www.croma.com/searchB?q={quote_plus(query)}"
            return [{"store":"croma","name":ne.get_text(strip=True) if ne else query,
                "price":price,"original":price,"delivery":"₹99 delivery",
                "fast":True,"inStock":True,"emi":None,"affiliate":href,"image":"","rating":None}]
        except Exception as e:
            log.warning(f"Croma: {e}")
    return []

def scrape_tatacliq(query):
    r = fetch(f"https://www.tatacliq.com/api/b2c/page/search?searchKey={quote_plus(query)}&pageSize=5")
    if not r: return []
    try:
        data = r.json()
        hits = (data.get("searchresult") or {}).get("products", {}).get("result", [])
        if hits:
            p = hits[0]
            price = p.get("price",{}).get("sellingPrice")
            mrp   = p.get("price",{}).get("mrp")
            if price:
                return [{"store":"tatacliq","name":p.get("productName",query),
                    "price":int(price),"original":int(mrp) if mrp else int(price),
                    "delivery":"₹49 delivery","fast":False,"inStock":True,"emi":None,
                    "affiliate":"https://www.tatacliq.com"+p.get("productURL","/search/?text="+quote_plus(query)),
                    "image":p.get("imageURL",""),"rating":None}]
    except Exception as e:
        log.warning(f"TataCliq: {e}")
    return []

def run_scrapers(query):
    results, best_name, best_img, best_rating = [], query, "", None
    scrapers = {"amazon":scrape_amazon,"flipkart":scrape_flipkart,"croma":scrape_croma,"tatacliq":scrape_tatacliq}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fn, query): store for store, fn in scrapers.items()}
        for future in as_completed(futures, timeout=25):
            try:
                items = future.result() or []
                for item in items:
                    if not best_img and item.get("image"): best_img = item["image"]
                    if item.get("name") and len(item["name"]) > len(best_name): best_name = item["name"]
                    if item.get("rating") and not best_rating: best_rating = item["rating"]
                    results.append(item)
            except Exception as e:
                log.error(f"Scraper error: {e}")
    return results, best_name, best_img, best_rating

def extract_name_from_url(url):
    if not url.startswith("http"): return url
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    try:
        r = fetch(url)
        if r:
            soup = BeautifulSoup(r.text, "html.parser")
            if "amazon" in domain:
                el = soup.find("span", id="productTitle")
                if el: return el.get_text(strip=True)[:200]
            elif "flipkart" in domain:
                for sel in ["span.B_NuCI","h1.yhB1nd","span.VU-ZEz"]:
                    el = soup.select_one(sel)
                    if el: return el.get_text(strip=True)[:200]
    except: pass
    path = re.sub(r'[/_-]', ' ', parsed.path).strip()
    return path[:100] if path else url

# ─── ROUTES ──────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status":"ok","message":"GadgetCrisp API v2.0 is live! 🚀",
        "affiliates":{"amazon":AMAZON_TAG or "not set","flipkart":FLIPKART_ID or "not set","myntra":MYNTRA_ID or "not set"}})

@app.route("/compare", methods=["POST","GET"])
def compare():
    if request.method == "GET":
        query = request.args.get("q","").strip()
    else:
        query = (request.get_json(silent=True) or {}).get("query","").strip()

    if not query:
        return jsonify({"error":"Provide a product name or URL"}), 400

    log.info(f"Compare: {query!r}")
    clean = extract_name_from_url(query) if query.startswith("http") else query
    log.info(f"Searching: {clean!r}")

    prices, name, image, rating = run_scrapers(clean)
    valid = [p for p in prices if p.get("price",0) > 100]

    if not valid:
        log.info(f"Live scraping returned nothing — using demo data")
        return jsonify(get_demo_data(clean))

    by_store = {}
    for p in valid:
        s = p["store"]
        if s not in by_store or p["price"] < by_store[s]["price"]:
            by_store[s] = p

    return jsonify({
        "name": name or clean, "category": detect_category(clean.lower()),
        "image": image, "rating": rating or round(random.uniform(4.0,4.6),1),
        "reviews": random.randint(5000,30000), "brand": (name or clean).split()[0],
        "specs": {}, "prices": sorted(by_store.values(), key=lambda x: x["price"]),
        "source": "live"
    })

@app.route("/test", methods=["GET"])
def test():
    q = request.args.get("q","iphone 15")
    return jsonify(get_demo_data(q))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
